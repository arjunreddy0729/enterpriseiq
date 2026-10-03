# Deploying the public demo

The demo runs on one free service: a **Hugging Face Gradio Space**, with
Postgres running **inside** it. The only paid part is Claude, capped by
`LLM_DAILY_BUDGET_USD`.

Docker Spaces are now a paid Hugging Face feature, so the free deployment is a
Gradio Space (on a free account it runs on ZeroGPU hardware; the app never
uses the GPU). Its [`app.py`](../deploy/huggingface/app.py) starts Postgres,
prepares the database, then serves the same FastAPI app (API and `/docs`) with
a small Gradio page mounted at `/demo`, which `/` redirects to. Visitors pick
a persona, ask, and see the answer, its sources, and what happened under the
hood. The page's logic is in
[`app/web/demo_ui.py`](../backend/app/web/demo_ui.py), tested in CI; it calls
the services directly and applies the same permission checks, rate limits,
relevance gate and spend cap as the HTTP API. A Docker image for any other
host is in [`deploy/docker/`](../deploy/docker/Dockerfile).

After the one-time setup below, deploying is just `git push`. CI runs the full
test suite, including the leak suite. If it passes,
[`deploy.yml`](../.github/workflows/deploy.yml) pushes the tested commit to the
Space, which rebuilds. Never edit the Space directly: each deploy overwrites it.

> Free-tier limits change. At the time of writing, a free Space sleeps after a
> period without visitors and takes a minute or two to wake. Check before
> relying on it.

## Why the database runs inside the Space

The first deploys pointed the Space at a hosted Postgres (Supabase, session
pooler on port 5432). Every connection attempt from the Space timed out, on
each of six retries, while the same database was healthy. A free Space could
not reach it, consistent with long-standing reports of outbound database
ports being unreliable from Spaces.

So the Space runs Postgres itself, from the
[`pgserver`](https://pypi.org/project/pgserver/) wheel (Postgres 16 with
pgvector, no system install, no account, no network). What that costs:

- **The data is rebuilt on every start.** The Space's disk is wiped on
  restart, so each start runs the migrations, seeds the demo users and
  ingests the corpus again. The audit trail and the spend counter start empty
  after a restart. For a demo with a fictional corpus this is acceptable.
- **pgvector is 0.6, not 0.8.** The `hnsw.iterative_scan` option arrived in
  0.8, so it is used only where available (`vector._supports_iterative_scan`).
  Without it, a very selective permission filter can return fewer than the
  requested number of vector candidates. With 264 chunks and
  `ef_search = 100`, the whole test suite (including the 300-case leak suite
  and the relevance-gate test) passes on both versions.
- **No `pg_trgm`.** Nothing uses it yet, so migration 0001 now creates it only
  where it exists.

To use an external database instead, for example on a host that can reach
one, set `EMBEDDED_POSTGRES=false` and the `POSTGRES_*` settings (or
`DATABASE_URL`).

## What demo mode does

`DEMO_MODE=true` (set by the Space's `app.py`) turns on:

| Protection | Why |
|---|---|
| Daily spend cap (`LLM_DAILY_BUDGET_USD`) | Spend is summed from `query_logs`. When it runs out, `/query` returns 503 and `/search` keeps working. Questions the relevance gate declines are free and never count. |
| Per-visitor rate limits | Login 10/min (also blocks password guessing), search 30/min, query 15/hour. The client IP is read from the proxy's entry in `X-Forwarded-For`, never one the client wrote. |
| Read-only admin | Everyone shares the admin login, so one visitor revoking HR's access would break the demo for everyone. Reading ACLs and the audit trail still works. |
| Hidden queries in the audit | With a shared admin login, the audit would otherwise show every visitor what others typed. |
| Front page at `/` | Redirects to the Gradio page on the Space (`DEMO_UI_PATH=/demo`); elsewhere, a static page with demo logins and a walkthrough. |

The Space's `app.py` also sets `ENVIRONMENT=production`, which refuses to
start if the password-less `X-Dev-User` header is enabled or `JWT_SECRET` is
short. Demo mode refuses to start without a budget, or with a model whose
price it does not know, because an unpriced model would make the cap read $0.

## One-time setup

### 1. Hugging Face Space

1. Create a Space at huggingface.co/new-space: **Gradio**, **Blank** template,
   the free hardware option, and Public. Ignore the sample code the empty
   Space shows; the deploy workflow pushes this repo's `app.py`.
2. Under **Settings → Variables and secrets**, add these as **secrets**:

   | Name | Value |
   |---|---|
   | `ANTHROPIC_API_KEY` | your key |
   | `JWT_SECRET` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
   | `DEMO_USER_PASSWORD` | `northwind-demo` (shown on the demo page) |
   | `LLM_DAILY_BUDGET_USD` | e.g. `1.00` |
   | `ANTHROPIC_MODEL` | optional: `claude-haiku-4-5`, about 5x cheaper per answer than the default |

   Values are stripped of surrounding whitespace, so a pasted trailing space
   is harmless. No database secrets are needed.
3. As a second safety net, set a monthly spend limit for the key in the
   Anthropic Console. The app's cap is an estimate; the Console limit is billing.

### 2. Connect GitHub to the Space

1. Create a Hugging Face token with **write** access (Settings → Access Tokens).
2. In the GitHub repo, go to **Settings → Secrets and variables → Actions**:
   - **Secret** `HF_TOKEN`: the token.
   - **Variable** `HF_SPACE`: `your-hf-username/your-space-name`.
3. Push to `main`, or run **Actions → Deploy demo → Run workflow**.

Until `HF_TOKEN` and `HF_SPACE` exist, the deploy workflow skips instead of
failing.

## Rehearsing a deploy locally

This assembles exactly what the workflow pushes and runs it as the Space
does, embedded Postgres included. `pgserver` ships wheels for Python
3.9 to 3.12, so use one of those, with the Space's requirements installed:

```bash
python3.12 -m venv /tmp/space-venv
/tmp/space-venv/bin/pip install -r deploy/huggingface/requirements.txt gradio==6.29.0

site=$(mktemp -d)
rsync -a --exclude tests --exclude .venv --exclude __pycache__ backend/ "$site/backend/"
cp -r corpus "$site/corpus"
cp deploy/huggingface/app.py deploy/huggingface/requirements.txt deploy/huggingface/README.md "$site/"

cd "$site" && EMBEDDED_POSTGRES_DIR=/tmp/space-pg \
  JWT_SECRET=local-rehearsal-secret-at-least-32-characters \
  DEMO_USER_PASSWORD=northwind-demo LLM_DAILY_BUDGET_USD=0.50 \
  ANTHROPIC_MODEL=claude-haiku-4-5 FORWARDED_PROXY_HOPS=0 PORT=7863 \
  ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  /tmp/space-venv/bin/python app.py
# then open http://localhost:7863
```

Measured on this rehearsal: the first start loads 22 documents (264 chunks)
in about 25s; restarting over the same data directory takes about 8s. On the
Space, add the embedding-model download on every cold start, and expect
slower CPUs.

To run the test suite against the embedded database, point `DATABASE_URL` at a
`pgserver` instance, run the migrations, seed and ingest, then `pytest`; the
result should match a run against the Docker database.

## Known limits

- **Data does not survive a restart** (see above).
- **Rate limits live in process memory.** Correct for one container. With
  several replicas each would count separately; move the counters to
  Postgres or Redis first.
- **The spend cap can overshoot slightly.** Concurrent requests that pass the
  check together each get one answer, which is cents at `max_tokens`.
- **Visitor questions are stored** in `query_logs`, because that is how the
  audit works, until the next restart. The demo page says so.
