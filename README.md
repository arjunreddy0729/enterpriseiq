# EnterpriseIQ

A permission-aware enterprise RAG platform. Employees ask questions in natural
language; the system retrieves evidence from company documents **that the
asking user is actually allowed to read**, and answers with citations pointing
at the exact supporting text — or says it cannot answer.

> **Status: Step 1 of the build — foundation.**
> Schema, configuration, health probes, identity seeding and the synthetic
> corpus are in place. Ingestion, retrieval and generation land next.
> Nothing in this README claims a benchmark number that has not been measured.

---

## The problem

Company knowledge is scattered across wikis, repos, PDFs and policy documents.
Two things go wrong when you point a naive RAG pipeline at it:

1. **Semantic search alone misses exact matches.** Ask for the OAuth
   configuration of a specific service and an embedding model will happily
   return five documents about authentication in general and miss the one
   containing `client_id`.
2. **Retrieval ignores who is asking.** An engineer asking "what is our
   compensation policy?" should not have the restricted HR document pulled
   into the model's context — and once it is in context, it has already
   leaked, because the model will paraphrase it.

EnterpriseIQ addresses both directly: hybrid retrieval for (1), and an ACL
predicate inside the retrieval query for (2).

---

## Architecture

```
                       ┌──────────────────────────┐
                       │  Demo UI (static HTML)   │
                       └────────────┬─────────────┘
                                    │ HTTP + X-Dev-User
                       ┌────────────▼─────────────┐
                       │   FastAPI (api/routes)   │  thin: validate, delegate
                       └────────────┬─────────────┘
                                    │
                       ┌────────────▼─────────────┐
                       │        services/         │  orchestration + timing
                       └──┬────────────────────┬──┘
                          │                    │
          ┌───────────────▼──────┐   ┌─────────▼──────────────────────────┐
          │  INGESTION PIPELINE  │   │        QUERY PIPELINE              │
          │                      │   │  1. normalise query                │
          │  parsers/ ─► Block[] │   │  2. resolve identity → group ids   │
          │       │              │   │  3. build the ACL predicate        │
          │  chunking.py         │   │  4. ┌─ vector search   (top 50) ─┐ │
          │       │              │   │     └─ keyword search   (top 50)─┘ │
          │  metadata.py         │   │        both filter in SQL ▲        │
          │       │              │   │  5. RRF fuse           → top 30    │
          │  embedder            │   │  6. rerank (V2)        → top 6     │
          └───────┼──────────────┘   │  7. context builder (budget+dedup) │
                  │                  │  8. grounded generation            │
                  ▼                  │  9. citation resolution + validate │
       ┌──────────────────────┐      │ 10. grounding check → confidence   │
       │ PostgreSQL 16        │◄─────┤ 11. query_logs write               │
       │  + pgvector (HNSW)   │      └────────────────────────────────────┘
       │  + tsvector (GIN)    │
       │  + int[] ACL (GIN)   │      ┌────────────────────────────────────┐
       └──────────────────────┘      │ evaluation/ (offline CLI)          │
                                     │  dataset.json → runner → metrics   │
                                     └────────────────────────────────────┘
```

Four interfaces are the seams that let this grow without a rewrite:
`Retriever`, `Embedder`, `Reranker`, `LLMClient`. Moving to OpenSearch means
writing one new `Retriever`; nothing above the interface knows what is behind
it.

---

## Quick start

**Prerequisites:** Docker Desktop. Nothing else — no Python install, no
Postgres, no model downloads for this step.

```bash
git clone <your-fork> enterpriseiq && cd enterpriseiq
cp .env.example .env
docker compose up --build
```

That will:

1. start PostgreSQL 16 with `pgvector`,
2. wait for it to accept connections,
3. apply migration `0001` (schema, extensions, HNSW + GIN indexes),
4. seed the five access groups and seven demo users,
5. start the API on <http://localhost:8000>.

Verify:

```bash
curl -s localhost:8000/healthz | jq
curl -s localhost:8000/readyz | jq
```

`/readyz` should report `"status": "ready"` with `database`, `pgvector`,
`migrations`, `embedding_dim` and `seed` all `ok`. The `llm` check will read
`degraded` until you put a real key in `.env` — that is expected and does not
block retrieval work.

Interactive API docs: <http://localhost:8000/docs>

### If a port is already taken

`docker compose up` fails with `Bind for 0.0.0.0:8000 failed: port is already
allocated` rather than picking a free port. Set the host-side mapping in
`.env` — the container-side ports never change:

```bash
API_HOST_PORT=8001
POSTGRES_HOST_PORT=5433
```

Postgres already defaults to host port **5433** so it never collides with a
local Postgres on 5432.

---

## Configuration

Everything is environment-driven; see [`.env.example`](.env.example) for the
full annotated list. Nothing is hardcoded and `.env` is gitignored.

| What | Where it runs | Cost |
|---|---|---|
| PostgreSQL + pgvector | local Docker | free |
| Keyword search (Postgres FTS + BM25 rescoring) | local | free |
| Embeddings (`BAAI/bge-base-en-v1.5`) | local CPU | free |
| Reranking (`BAAI/bge-reranker-base`) | local CPU | free |
| **Answer generation (Anthropic)** | **API** | **the only paid component** |

`ANTHROPIC_API_KEY` is read server-side only. It is never sent to the
frontend, never returned in a response, and never written to a log.

### LLM cost

`ANTHROPIC_MODEL` defaults to `claude-opus-5`. Every request's token usage and
estimated cost is recorded in `query_logs`, using this table
(`app/core/config.py`, USD per million tokens):

| Model | Input | Output |
|---|---:|---:|
| `claude-opus-5` | $5.00 | $25.00 |
| `claude-sonnet-5` | $3.00 | $15.00 |
| `claude-haiku-4-5` | $1.00 | $5.00 |

A typical grounded answer sends ~4k tokens of context and returns ~300 tokens,
so roughly **$0.03 per question** on `claude-opus-5`. A 30-question evaluation
run is well under a dollar. If you want to spend less while iterating, change
one line in `.env`:

```bash
ANTHROPIC_MODEL=claude-haiku-4-5
```

Retrieval quality is unaffected by that choice — only generation is — so the
retrieval metrics stay comparable across models.

---

## Design decisions worth defending

**Denormalised ACLs on `chunks`.** `document_permissions` is the source of
truth, but `chunks.access_group_ids` carries a denormalised `int[]` with a GIN
index so the permission check collapses to one indexable predicate:

```sql
WHERE c.access_group_ids && :user_group_ids
```

The normalised alternative joins `chunks → documents → document_permissions →
user_groups` *after* the HNSW scan, which is exactly when you cannot afford it.
The cost is an eventual-consistency window on ACL changes, closed by a
propagation job — with revocations propagated synchronously, because a
revocation lag is a security issue in a way a grant lag is not.

**Filtering, not post-filtering.** Both retrievers apply the ACL predicate
inside their SQL. Post-filtering would be wrong twice over: anything that
reaches the context window has already leaked, and discarding 17 of 20
retrieved rows silently leaves you generating from 3 chunks while believing
you had 20.

**Postgres FTS for candidates, real BM25 for scoring.** `ts_rank_cd` is not
BM25 — no term-frequency saturation, different length normalisation. Postgres
gives us fast, ACL-filterable candidate generation; a rescoring pass computes
genuine BM25 over those candidates using the statistics in `term_stats` and
`corpus_stats`.

**HNSW over IVFFlat.** No training step, so it works from an empty table, and
better recall at the same latency. With a selective ACL filter, pgvector's
iterative index scans matter — a filtered HNSW search can otherwise return
fewer than `k` rows.

**Synchronous SQLAlchemy.** The expensive work — embedding a query, scoring 30
pairs with a cross-encoder — is blocking CPU work in C extensions. Async would
buy false concurrency and force `run_in_executor` plumbing through every
layer. FastAPI runs plain `def` handlers in a threadpool, which gives real
parallelism for the same code.

**No LangChain or LlamaIndex.** Not dogma — the entire value of this project is
that the hybrid retrieval, fusion, ACL enforcement, citation resolution and
grounding are implemented and understood rather than imported. Small focused
libraries are fine; the retrieval pipeline is not.

---

## Project layout

```
enterpriseiq/
├── backend/
│   ├── app/
│   │   ├── api/routes/      # thin HTTP layer
│   │   ├── core/            # config, logging
│   │   ├── db/              # models, session, repositories
│   │   ├── ingestion/       # parsers, chunking, manifest
│   │   ├── retrieval/       # ports, vector, keyword, fusion, reranker, filters
│   │   ├── generation/      # prompts, context, citations, grounding
│   │   ├── evaluation/      # dataset, metrics, runner
│   │   ├── services/        # orchestration
│   │   └── main.py
│   ├── alembic/versions/    # 0001_initial_schema.py
│   ├── scripts/             # seed_users.py, entrypoint.sh
│   └── tests/{unit,integration}/
├── corpus/                  # synthetic Northwind Systems knowledge base
│   └── manifest.yaml        # documents + their access groups
├── evaluation/              # benchmark dataset and committed results
├── docker-compose.yml
└── .env.example
```

---

## The demo corpus

`corpus/` contains a synthetic knowledge base for **Northwind Systems, Inc.**,
a fictional B2B logistics and payments company. Every document was written for
this project; it contains no real company data and is safe to publish.

`corpus/manifest.yaml` declares each document's metadata and access groups, so
the permission topology is reproducible on any machine. The deliberate cases:

| Document | Groups | Why it exists |
|---|---|---|
| `hr/compensation-policy.md` | `hr` | An engineer asking about it must get an abstention |
| `hr/performance-review-process.md` | `hr` | Second HR-restricted document |
| `finance/procurement-thresholds.md` | `finance` | Restricted, different department |
| `legal/security-incident-legal-playbook.md` | `legal` | Restricted, third department |
| `legal/vendor-policy.md` | `legal`, `finance` | Two-group document — tests array overlap |
| `hr/leave-policy.md` | `all-employees` | Same department, unrestricted |

The corpus also contains **deliberate gaps** — topics no document covers — so
the evaluation set can measure whether the system correctly abstains instead of
inventing an answer.

---

## Development

```bash
# Run the API against Docker's database, without the API container
docker compose up -d db
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
python -m scripts.seed_users
uvicorn app.main:app --reload

# Tests
pytest                      # unit tests, no database needed
pytest -m integration       # schema + seed tests, needs `docker compose up -d db`
ruff check . && ruff format --check .
mypy app
```

---

## Roadmap

- **Step 1 (done)** — schema, config, health, identity seeding, corpus
- **Step 2** — parsers, structure-aware chunking, embeddings, ingestion CLI
- **Step 3** — vector + keyword retrieval, RRF fusion, ACL predicate, `/search`
- **Step 4** — context assembly, grounded generation, server-side citations
- **Step 5** — evaluation harness (Recall@k, MRR, nDCG, abstention accuracy)
- **Then, each benchmarked against the frozen dataset** — reranking, query
  rewriting, feedback, Next.js UI, GitHub connector, analytics

Benchmark results will be committed under `evaluation/results/` as they are
measured. Until then this README contains no performance claims.
