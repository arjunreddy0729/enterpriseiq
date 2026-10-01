# Deploying the public demo

The demo runs on two free services: a **Hugging Face Docker Space** for the
app, and **Neon** for Postgres with pgvector. The only paid part is Claude,
capped by `LLM_DAILY_BUDGET_USD`.

After the one-time setup below, deploying is just `git push`. CI runs the full
test suite, including the leak suite. If it passes,
[`deploy.yml`](../.github/workflows/deploy.yml) pushes the tested commit to the
Space, which rebuilds. Never edit the Space directly: each deploy overwrites it.

> Free-tier limits change. At the time of writing, a free Space sleeps after a
> period without visitors and takes about a minute to wake, and Neon's free
> compute suspends when idle. Check both before relying on them.

## What demo mode does

`DEMO_MODE=true` (set in the deploy image) turns on:

| Protection | Why |
|---|---|
| Daily spend cap (`LLM_DAILY_BUDGET_USD`) | Spend is summed from `query_logs`, so it survives restarts. When it runs out, `/query` returns 503 and `/search` keeps working. Questions the relevance gate declines are free and never count. |
| Per-visitor rate limits | Login 10/min (also blocks password guessing), search 30/min, query 15/hour. The client IP is read from the proxy's entry in `X-Forwarded-For`, never one the client wrote. |
| Read-only admin | Everyone shares the admin login, so one visitor revoking HR's access would break the demo for everyone. Reading ACLs and the audit trail still works. |
| Hidden queries in the audit | With a shared admin login, the audit would otherwise show every visitor what others typed. |
| Landing page at `/` | Demo logins and a four-step walkthrough. |

The image also sets `ENVIRONMENT=production`, which refuses to start if the
password-less `X-Dev-User` header is enabled or `JWT_SECRET` is short. Demo
mode refuses to start without a budget, or with a model whose price it does
not know, because an unpriced model would make the cap read $0 forever.

## One-time setup

### 1. Database: Neon

1. Create a project at neon.tech.
2. On the dashboard, open **Connect**, turn **Connection pooling off**, and
   copy the host, database, user and password. Use the direct connection: the
   app sets per-session pgvector options that a transaction pooler drops.
3. Nothing else. The first boot runs the migrations, which create the
   `vector` extension, and loads the corpus. That takes about a minute.

### 2. App: Hugging Face Space

1. Create a Space at huggingface.co/new-space: **Docker**, blank template, the
   free CPU hardware, and Public.
2. Under **Settings → Variables and secrets**, add these as **secrets**:

   | Name | Value |
   |---|---|
   | `ANTHROPIC_API_KEY` | your key |
   | `JWT_SECRET` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
   | `DEMO_USER_PASSWORD` | `northwind-demo` (shown on the landing page) |
   | `LLM_DAILY_BUDGET_USD` | e.g. `1.00` |
   | `POSTGRES_HOST` | from Neon |
   | `POSTGRES_PORT` | `5432` |
   | `POSTGRES_USER` | from Neon |
   | `POSTGRES_PASSWORD` | from Neon |
   | `POSTGRES_DB` | from Neon |
   | `POSTGRES_SSLMODE` | `require` |

   Optional: `ANTHROPIC_MODEL=claude-haiku-4-5` makes each answer roughly 5x
   cheaper than the default.
3. As a second safety net, set a monthly spend limit for the key in the
   Anthropic Console. The app's cap is an estimate; the Console limit is billing.

### 3. Connect GitHub to the Space

1. Create a Hugging Face token with **write** access (Settings → Access Tokens).
2. In the GitHub repo, go to **Settings → Secrets and variables → Actions**:
   - **Secret** `HF_TOKEN`: the token.
   - **Variable** `HF_SPACE`: `your-hf-username/your-space-name`.
3. Push to `main`, or run **Actions → Deploy demo → Run workflow**.

Until `HF_TOKEN` and `HF_SPACE` exist, the deploy workflow skips instead of
failing.

## Rehearsing a deploy locally

This builds exactly what the workflow pushes and boots it against an empty
database, as a first deploy would:

```bash
site=$(mktemp -d)
rsync -a --exclude tests --exclude .venv --exclude __pycache__ backend/ "$site/backend/"
cp -r corpus "$site/corpus"
cp deploy/huggingface/Dockerfile "$site/Dockerfile"
docker build -t enterpriseiq-demo "$site"

docker compose exec db psql -U enterpriseiq -c "CREATE DATABASE enterpriseiq_demo"
docker run --rm -p 7861:7860 --network enterpriseiq_default \
  -e POSTGRES_HOST=db -e POSTGRES_PORT=5432 -e POSTGRES_USER=enterpriseiq \
  -e POSTGRES_PASSWORD=enterpriseiq -e POSTGRES_DB=enterpriseiq_demo \
  -e JWT_SECRET=local-rehearsal-secret-at-least-32-characters \
  -e DEMO_USER_PASSWORD=northwind-demo -e LLM_DAILY_BUDGET_USD=0.50 \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  enterpriseiq-demo
# then open http://localhost:7861
```

Measured on this rehearsal: the first boot loads 22 documents (264 chunks) in
about 63s. A restart skips all 22 by content hash and is ready in about 4s.

## Known limits

- **Rate limits live in process memory.** Correct for one container. With
  several replicas each would count separately; move the counters to
  Postgres or Redis first.
- **The spend cap can overshoot slightly.** Concurrent requests that pass the
  check together each get one answer, which is cents at `max_tokens`.
- **Visitor questions are stored** in `query_logs`, because that is how the
  audit works. The landing page says so. There is no automatic retention
  purge yet.
