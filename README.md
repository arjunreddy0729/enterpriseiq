# EnterpriseIQ

A permission-aware enterprise RAG platform. Employees ask questions in plain
English; the system answers from company documents, cites the passage behind
every claim, declines when the evidence isn't there, and never retrieves a
document the asker isn't allowed to read.

**[Live demo →](https://huggingface.co/spaces/arjun0729/enterpriseiq)**
(free tier: sleeps when idle, takes a minute to wake)

Everything runs locally except the answer-generation call to Claude.

---

## The problem

Company knowledge is scattered across engineering docs, HR policies, finance
procedures and legal playbooks. A naive "chat with your documents" system
solves the search problem and creates two worse ones:

1. **It leaks.** Ask "what are the salary bands?" and a vector search returns
   the restricted HR compensation policy, which goes into the model's context
   and gets paraphrased back to whoever asked.
2. **It invents.** When retrieval finds nothing relevant, a language model
   still produces a fluent, confident, wrong answer.

This project is built around those two failures rather than the happy path.

Try it in the demo: ask **"What are the bonus targets by level?"** as Marcus
(HR) and get a cited answer; ask the identical question as Priya (Engineering)
and watch it decline.

---

## Quickstart

```bash
cp .env.example .env          # add your ANTHROPIC_API_KEY
make up                       # Postgres + pgvector, migrations, seed, API
make ingest                   # load the 22-document demo corpus
```

`make` lists every target. `make check` runs exactly what CI runs.

```bash
# Ask a question
curl -s -X POST localhost:8000/api/v1/query \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-User: marcus.webb@northwind.example' \
  -d '{"query":"What are the bonus targets by level?"}'

# Retrieval only — no model, no cost. Shows what the model would have seen.
curl -s -X POST localhost:8000/api/v1/search \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-User: priya.raman@northwind.example' \
  -d '{"query":"deployment rollback","include_debug":true}'
```

---

## How it works

```
  question
     │
     ├─ resolve identity ──────────► access group ids
     │
     ├─ keyword search (top 50) ─┐
     │  vector search  (top 50) ─┤   both filter by ACL *inside* the SQL
     │                           │
     │                      RRF fusion ──► top 30 ──► [reranker: off, measured]
     │                           │
     ├─ context assembly + server-assigned citation numbers
     ├─ Claude generates, or abstains
     ├─ citation validation ──► unknown numbers stripped
     ├─ grounding check ─────► per-claim support score
     └─ confidence band + audit row
```

Four interfaces mark the seams: `Embedder`, `Retriever`, `Reranker`,
`LLMClient`. Moving to OpenSearch means writing one new `Retriever`.

---

## Design decisions

**Permission filtering happens inside the retrieval query.** Access groups are
a GIN-indexed array predicate in the same SQL as the vector and keyword search:

```sql
WHERE chunks.access_group_ids && :allowed_group_ids
```

Post-filtering fails twice: restricted text has already left the database, and
you asked for 20 candidates and kept 3, so recall collapses with no error.
`RetrievalQuery` has no default for `allowed_group_ids` — forgetting it is a
`TypeError`, not an unfiltered search.

**Hybrid search, because embeddings lose exact tokens.** 768 floats compress
meaning and discard rare identifiers — `X-Cardinal-Signature`, `client_id`,
`429`. Keyword search is the mirror image: IDF weights rare terms most. The
two fail on disjoint queries, which is what makes fusing them worth more than
tuning either.

**RRF fuses on rank, not score.** Cosine similarity and `ts_rank_cd` aren't
comparable quantities, and every normalisation scheme breaks when one
retriever returns garbage. Ranks are comparable by construction.

**Structure-aware chunking.** Chunks are packed from whole blocks, broken at
section boundaries, never split across a code fence or table, and prefixed
with their heading path — so a chunk reading *"It uses OAuth 2.0 with a 3600s
TTL"* becomes retrievable for "payment service authentication".

**Citations the model cannot fabricate.** Passages are numbered server-side
and the model only writes `[1]`. Every marker is validated against that
mapping afterwards; unknown numbers are stripped from the text. A number
looked up in a server-side table cannot be invented.

**Confidence is a band, never a percentage.** `HIGH`/`MEDIUM`/`LOW`, with the
signals that produced it. "94% confident" asserts calibration that would need
labelled outcomes for thousands of answers to demonstrate.

---

## Results

34-question benchmark over the demo corpus. Raw results in
[`evaluation/results/`](evaluation/results/); reproduce with
`make eval-full`.

```
PERMISSION ENFORCEMENT                    PASS
  6 cases asking for a document the user may not read   leaks: 0

RETRIEVAL  (23 answerable cases)
     k    recall   precision      nDCG
     1     0.891       0.957     0.957
     3     1.000       0.377     0.984
  MRR   0.978

ABSTENTION
  accuracy 1.000     correctly declined 11/11     false refusals 0/23

GENERATION  (23 answered)
  fact coverage 1.000   citation precision 0.790   grounding 0.760
```

**Security suite** — 300 cases (50 user/forbidden-document pairs × 6 attack
styles: verbatim text, exact title, prompt injection, role claims, SQL, filter
tampering), each a real login and HTTP search. Forbidden chunks returned: **0**.
Mutation testing confirms each permission layer blocks every case on its own.

**The reranker.** `BAAI/bge-reranker-base` is implemented, benchmarked, and
**shipped disabled**:

| | baseline | reranked |
|---|---:|---:|
| recall@1 / recall@3 | 0.891 / 1.000 | 0.891 / 1.000 |
| MRR | 0.978 | 0.978 |
| latency p50 | 41 ms | 2,238 ms |

It isn't a no-op — ordering changes in 32 of 34 cases — but it reshuffles
results *below* the relevant document, which no metric measures. A reranker
fixes a precision problem; this corpus doesn't have one.

### What the numbers don't say

- **The benchmark is small and saturated.** 22 documents, 23 answerable
  questions. `recall@3 = 1.000` means it's too easy, not that retrieval is
  solved.
- **Citation precision of 0.790 is probably a labelling artifact.** Every case
  that lowered it cites the right document plus a second that genuinely
  discusses the same fact, while `expected_sources` names only one. Left
  unfixed — tuning a benchmark to flatter the system is how benchmarks become
  worthless.
- **Grounding at 0.760** is the number genuinely worth improving.

---

## Connecting real sources

Ingestion is written against a `Connector` contract, not a filesystem. A
connector answers three questions per document, and the third is what makes
this an enterprise problem:

1. What is it?
2. Has it changed?
3. **Who may read it?**

`access_groups` is required with no default — a source that hasn't decided its
audience fails at the boundary rather than indexing silently.

```bash
make ingest                                              # local corpus
make sync-github REPO=owner/name GROUPS=engineering      # a repository
```

Two properties make this a sync rather than an import:

- **Unchanged documents cost nothing.** A revision token (git blob SHA, mtime)
  is compared before anything is downloaded, parsed or embedded. Same command,
  same corpus: **25,781 ms** with `--force`, **144 ms** when nothing changed.
  An unchanged GitHub repo costs two API calls and zero downloads.
- **Deleting at the source deletes here.** Chunks are removed immediately; the
  row is kept as deleted for the audit trail. A document taken down that still
  answers questions is the same failure as a leak.

Verified against a live repository — two sources, one index, permissions
enforced across both.

**Not built:** SharePoint, Confluence, Drive. Each needs a tenant and admin
consent to test honestly, and an untested connector would be the one
unmeasured claim in a project whose results are otherwise all reproducible.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI + Pydantic v2 | typed contracts, generated OpenAPI |
| Database | PostgreSQL 16 | documents, vectors, keyword index, ACLs and audit in one query plan |
| Vector search | pgvector 0.8, HNSW, cosine | no training step, works from an empty table |
| Keyword search | Postgres FTS, GIN, weighted tsvector | ACL predicate in the same plan |
| Embeddings | `BAAI/bge-base-en-v1.5`, 768d, CPU | free re-embedding while tuning |
| Reranking | `BAAI/bge-reranker-base` | implemented, measured, disabled |
| Generation | Claude via the Anthropic SDK | the only paid component |
| Auth | JWT, groups resolved per request | revocation applies to the next request |
| Tests | pytest — **790 passing** | incl. 300-case leak suite |

**No LangChain or LlamaIndex.** Hybrid retrieval, fusion, ACL enforcement,
citation resolution and grounding *are* this project; behind a framework,
nobody could tell whether I understood any of them.

---

## Project layout

```
backend/app/
  api/          routes, dependencies, error envelope
  core/         config, logging, identity, security
  db/           models, session
  ingestion/    connectors/ parsers/ blocks chunking pipeline
  retrieval/    ports types filters keyword vector fusion reranker pipeline
  generation/   llm context prompts citations grounding confidence
  evaluation/   dataset metrics runner report
  services/     search, query, permissions
corpus/         22 synthetic documents + manifest.yaml
evaluation/     dataset.json + committed results
deploy/         Docker image, Hugging Face Space
docs/           architecture.md, deploy.md
```

Routes never import from `db/` or `retrieval/`: routes → services →
retrieval | generation | repositories.

---

## Limitations

This is a demonstration at demonstration scale. Honestly:

- 22 documents, not 100,000. The approach scales; this deployment hasn't been
  asked to.
- Permissions are flat groups. Real enterprises have inherited folders,
  per-document shares and deny rules.
- ACL changes propagate to chunks on re-sync. In production, revocation lag is
  a security issue, not a chore.
- Single tenant.

[`SECURITY.md`](SECURITY.md) states precisely what the system does and does not
guarantee.

---

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — component detail
- [`docs/deploy.md`](docs/deploy.md) — running the public demo
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — setup and conventions
- [`SECURITY.md`](SECURITY.md) — threat model and scope

## License

MIT — see [LICENSE](LICENSE).
