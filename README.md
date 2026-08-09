# EnterpriseIQ

A permission-aware enterprise RAG platform. Employees ask questions in plain
English; the system answers from company documents, cites exactly which passage
each claim came from, declines when the evidence isn't there, and never lets a
user retrieve a document they aren't allowed to read.

Everything runs locally except the answer-generation call to Claude.

```bash
cp .env.example .env          # add your ANTHROPIC_API_KEY
docker compose up --build
```

---

## The problem

Company knowledge is scattered across engineering docs, HR policies, finance
procedures and legal playbooks. Employees waste time searching it, and when
they do find something it's often outdated or wrong.

A naive "chat with your documents" system solves the search problem and creates
two worse ones:

1. **It leaks.** Ask "what are the salary bands?" and a vector search happily
   returns the restricted HR compensation policy, which then goes into the
   model's context and gets paraphrased back to whoever asked.
2. **It invents.** When retrieval finds nothing relevant, a language model will
   still produce a fluent, confident, wrong answer.

EnterpriseIQ is built around those two failures rather than around the happy
path.

---

## Architecture

```
                        ┌──────────────────────┐
                        │   FastAPI (routes)   │  thin: validate, authn, delegate
                        └──────────┬───────────┘
                                   │
              ┌────────────────────┴────────────────────┐
              │                                          │
     INGESTION PIPELINE                          QUERY PIPELINE
              │                                          │
   parse → blocks → chunk                 1. resolve identity → group ids
              │                           2. build access predicate
        embed (BGE, local)                3. ┌ keyword search (top 50) ┐
              │                              └ vector search  (top 50) ┘
              ▼                                 both filter in SQL ▲
   ┌─────────────────────────┐              4. RRF fusion → top 30
   │  PostgreSQL 16          │◄─────────────5. [reranker → top 6]  (off; measured)
   │   + pgvector  (HNSW)    │              6. context assembly + citation numbering
   │   + tsvector  (GIN)     │              7. Claude generates, or abstains
   │   + int[] ACL (GIN)     │              8. citation validation
   └─────────────────────────┘              9. grounding verification
                                           10. confidence banding
                                           11. query_logs
```

**Ports and adapters at four seams** — `Embedder`, `Retriever`, `Reranker`,
`LLMClient`. Moving to OpenSearch means writing one new `Retriever`; nothing
above the interface changes.

---

## The design decisions worth defending

### Permission filtering happens *inside* the retrieval query

Every retriever builds its `WHERE` clause in one place
([`app/retrieval/filters.py`](backend/app/retrieval/filters.py)) and the access
check is a single indexed predicate:

```sql
WHERE chunks.access_group_ids && :allowed_group_ids   -- GIN-indexed array overlap
```

The obvious alternative — fetch the top 20, then drop the ones the user can't
see — fails twice. Restricted text has already left the database and passed
through application memory and logs. And you asked for 20 candidates and kept
3: recall silently collapsed with no error, degrading worst for the users whose
access is most restricted.

`RetrievalQuery` has no default for `allowed_group_ids`, so forgetting it is a
`TypeError` at the call site rather than an unfiltered search at runtime.

Group ids are **denormalised onto every chunk row** so the check is one
indexable predicate instead of a three-table join executed after the vector
scan. `document_permissions` remains the source of truth; the ingestion
pipeline keeps the copy in step.

### Hybrid search, because embeddings lose exact tokens

An embedding compresses meaning into 768 floats, and that compression discards
rare, exact tokens — `X-Cardinal-Signature`, `client_id`, `payments:refund`,
`429`. Semantically an identifier is nearly content-free, so the vector barely
encodes it. Keyword search is the mirror image: IDF weights rare terms *most*.

The two fail on disjoint query sets, which is what makes fusing them worth more
than tuning either. Measured on this corpus: searching `X-Cardinal-Signature`
returns exactly one keyword hit — the right one — while the paraphrase *"how do
our services prove who they are to each other?"* is carried by the vector side.

**One bug worth knowing about**: `websearch_to_tsquery` ANDs every term, so a
five-word question needed all five words in one chunk and matched *nothing* —
the keyword half was silently contributing zero. The parser is kept for its
quoting and negation handling, but the operator is swapped to OR; ranking sorts
out which matches more, and rarer, terms.

### RRF fuses on rank, not score

```
RRF(d) = Σ  1 / (k + rank_r(d))      k = 60
```

Cosine similarity lives in [-1, 1] and clusters around 0.55–0.90; `ts_rank_cd`
is unbounded and corpus-dependent. Any weighted sum of the two needs
normalisation, and every normalisation scheme breaks exactly when one retriever
returns garbage — its scores get stretched to fill the range and noise gets
promoted. Ranks are comparable by construction.

`k = 60` damps the head, so a document ranked 3rd by *both* retrievers beats one
ranked 1st by one and 200th by the other.

### Structure-aware chunking

Fixed-size splitting severs sentences, orphans code from its explanation, and
strips headings. A chunk reading *"It uses OAuth 2.0 with a 3600s TTL"* has lost
the word "payment" and is unretrievable for the query that needs it.

So: pack whole blocks to a token target, break at section boundaries, never
split a code fence or table, and **prefix every chunk with its heading path**
so it becomes *"Payments Service > Authentication\n\nIt uses OAuth 2.0…"*. That
prefix is embedded *and* indexed in the weight-`A` tsvector position, so it
helps both retrievers at once.

22 documents → **264 chunks**, median 252 tokens, none over the ceiling.

### Citations the model cannot fabricate

The model never names a document. Context passages are numbered server-side,
the number→chunk mapping is held in memory, and the model is asked only to
write `[1]`. Afterwards every marker is validated against that mapping:
unknown numbers are **stripped from the text**, surviving citations are
renumbered contiguously, and only cited passages are returned as sources.

Asking a model to write "according to compensation-policy.md" is asking it to
generate a fact. A number looked up in a server-side table cannot be invented.

### Grounding verification

Citation validation proves a citation points at a real passage. It does not
prove the passage *says* what the sentence claims. Each claim sentence is
scored against the passages it cites, blending lexical overlap with embedding
similarity — **weighted, not `max()`**.

That detail matters and a test caught it: taking the max let semantic
similarity alone carry a sentence, and semantic similarity cannot distinguish a
faithful paraphrase from a plausible invention on the same topic. *"Northwind
authenticates using biometric retina scanning"* sits close to a real passage
about authentication. Lexical overlap is what catches a changed number — `$85`
and `$75` are near-identical to an embedding and completely different as facts.

### Confidence is a band, never a percentage

`HIGH` / `MEDIUM` / `LOW`, returned alongside the signals that produced it.

A percentage asserts calibration: "94% confident" claims that among answers
scored 0.94, ~94% were correct. Demonstrating that needs labelled outcomes for
thousands of answers. Without them a percentage is a number with a decimal
point and no meaning — and decimal points are persuasive, which makes an
uncalibrated one actively harmful.

### Two abstention points

- **Before the model runs.** If nothing retrieved clears a relevance floor, no
  API call is made. Retrieval finding nothing relevant is the most common cause
  of an invented answer, and the cheapest to prevent.
- **After the model runs.** A sentinel token lets the model say the passages
  didn't answer the question, detected deterministically rather than by
  string-matching prose.

---

## Benchmark results

34 questions across four categories, run against the committed corpus. Raw
results in [`evaluation/results/`](evaluation/results/).

```
PERMISSION ENFORCEMENT                    PASS
  6 cases asked for a document the user may not read
  leaks: 0

RETRIEVAL  (23 answerable cases)
     k    recall   precision      nDCG
     1     0.891       0.957     0.957
     3     1.000       0.377     0.984
     5     1.000       0.226     0.984
  MRR   0.978

ABSTENTION
  accuracy            1.000
  correctly declined  11/11
  wrongly declined    0/23

GENERATION  (23 answered)
  fact coverage       1.000
  citation precision  0.790
  grounding           0.760
```

`precision@k` is divided by `k`, so with 1–2 relevant documents per question
the ceiling at k=10 is 0.1–0.2. The number to read there is recall.

### What the numbers don't say

- **The benchmark is small and easy.** 22 documents, 23 answerable questions.
  Recall@3 = 1.000 shows the pipeline works; it does not show it scales.
- **Citation precision 0.790 is probably a labelling artifact.** All nine cases
  that lowered it cite the right document *plus* a second one that genuinely
  discusses the same fact, while `expected_sources` names only one. Left
  unfixed rather than relabelled — tuning the benchmark to flatter the system
  is how benchmarks become worthless.
- **Grounding 0.760** is the number genuinely worth improving.

### The reranker measurement

`BAAI/bge-reranker-base` is implemented, benchmarked, and **left off**:

|                | baseline | reranked |
|----------------|---------:|---------:|
| recall@1       |    0.891 |    0.891 |
| recall@3       |    1.000 |    1.000 |
| MRR            |    0.978 |    0.978 |
| latency p50    |     41ms |   2238ms |

Not a no-op — rerank scores are populated and document ordering changes in
**32 of 34 cases**. It reshuffles results *below* the relevant document, which
no metric measures, because the fused ranking already puts the right document
first or second nearly every time. Recall@3 is already 1.000; there is no
headroom to recover.

A reranker fixes a *precision* problem. This corpus doesn't have one. Shipping
it anyway would cost 54× latency for nothing.

```bash
python -m scripts.run_eval                        # retrieval only, free
python -m scripts.run_eval --rerank
python -m scripts.compare_eval before.json after.json
```

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI + Pydantic v2 | typed request/response, free OpenAPI |
| Database | PostgreSQL 16 | documents, vectors, keyword index, ACLs and logs in one query plan |
| Vector search | pgvector 0.8, HNSW, cosine | no training step, works from an empty table |
| Keyword search | Postgres FTS, GIN, weighted tsvector | ACL predicate evaluated in the same plan |
| Embeddings | `BAAI/bge-base-en-v1.5`, 768d, CPU | free re-embedding while tuning chunking |
| Reranking | `BAAI/bge-reranker-base` | implemented, measured, disabled |
| Generation | Claude via the Anthropic SDK | the only paid component |
| Migrations | Alembic | |
| Tests | pytest — **308 passing** | |

**No LangChain or LlamaIndex.** Not dogma: hybrid retrieval, fusion, ACL
enforcement, citation resolution and grounding *are* this project. Behind a
framework, neither an interviewer nor I could tell whether I understood any of
them.

### Two details that cost real time

- **`sqlalchemy.ARRAY` vs `postgresql.ARRAY`.** Only the dialect-specific type
  exposes `.overlap()`, which renders the `&&` the entire ACL check depends on.
  With the generic type the permission predicate raises `AttributeError` on the
  first search.
- **`pip install torch` pulls CUDA on Linux.** ~2.9GB of nvidia wheels plus
  650MB of Triton, in a CPU-only image. Installing from PyTorch's cpu index
  first took the image from **8.94GB → 2.22GB**.

---

## Running it

```bash
cp .env.example .env                 # add ANTHROPIC_API_KEY
docker compose up --build            # Postgres + pgvector, migrations, seed, API
```

```bash
docker compose exec api python -m scripts.ingest_corpus
```

Ask a question as an HR user:

```bash
curl -s -X POST localhost:8000/api/v1/query \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-User: marcus.webb@northwind.example' \
  -d '{"query":"What are the bonus targets by level?"}'
```

Now ask the **identical** question as an engineer and watch it decline:

```bash
curl -s -X POST localhost:8000/api/v1/query \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-User: priya.raman@northwind.example' \
  -d '{"query":"What are the bonus targets by level?"}'
```

Retrieval only, no model, no cost:

```bash
curl -s -X POST localhost:8000/api/v1/search \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-User: priya.raman@northwind.example' \
  -d '{"query":"deployment rollback","include_debug":true}'
```

Inspect chunk boundaries before anything is embedded:

```bash
python -m scripts.show_chunks ../corpus/engineering/authentication.md
```

> Ports are configurable in `.env` (`API_HOST_PORT`, `POSTGRES_HOST_PORT`) —
> `docker compose up` fails rather than picking a free port if one is taken.

### The demo corpus

**Northwind Systems** is entirely fictional — 22 documents across engineering,
HR, finance and legal, written for this project and safe to publish.
`corpus/manifest.yaml` declares the permission topology, so anyone cloning this
repo reproduces the same ACLs and the same benchmark.

Deliberately built in:

- `compensation-policy.md` and `performance-review-process.md` are **HR-only** —
  the permission demo.
- One user (Sofia) is in *two* departments, exercising array overlap rather
  than single-group matching.
- Five topics are **absent on purpose** (crypto payments, a Tokyo office,
  sabbaticals, pet insurance, a bug bounty) so abstention is testable.
- The expense policy records a superseded `$75` meal cap alongside the current
  `$85`, so conflicting-source handling is testable.

---

## Project layout

```
backend/app/
  api/          routes, dependencies, error envelope
  core/         config, logging, identity
  db/           models, session
  ingestion/    parsers/ blocks chunking tokens pipeline manifest
  retrieval/    ports types filters keyword vector fusion reranker pipeline
  generation/   llm context prompts citations grounding confidence
  evaluation/   dataset metrics runner report
  services/     query_service
corpus/         22 synthetic documents + manifest.yaml
evaluation/     dataset.json + committed results
```

Layering is enforced by convention: routes never import from `db/` or
`retrieval/`. Routes → services → retrieval | generation | repositories.

---

## What's next

- **A harder benchmark.** The current one is saturated; a larger corpus with
  buried answers would make every number more meaningful and give the reranker
  a fair test.
- **Real BM25.** `ts_rank_cd` is cover-density ranking, not BM25 — no
  term-frequency saturation, different length normalisation. `term_stats` and
  `corpus_stats` are modelled and populated; the rescoring pass over FTS
  candidates is the remaining work.
- **Query rewriting**, measured against the same fixed dataset.
- **OpenSearch**, when the corpus outgrows a single Postgres. One new
  `Retriever`.
- **Next.js frontend.** The API is stable; this is presentation.

---

## Résumé description

> **EnterpriseIQ | Permission-Aware Enterprise RAG Platform**
> Python, FastAPI, PostgreSQL, pgvector, Sentence Transformers, Claude, Docker
>
> - Engineered a permission-aware RAG platform combining dense vector retrieval,
>   PostgreSQL full-text search and reciprocal rank fusion, enforcing
>   document-level access control **inside the retrieval query** as a
>   GIN-indexed array predicate rather than as a post-filter — achieving
>   **recall@3 = 1.00** and **MRR = 0.98** with **zero permission leaks** across
>   a 34-question benchmark.
> - Implemented server-assigned citation IDs with post-hoc validation, so
>   fabricated sources are structurally impossible, plus deterministic grounding
>   verification and two-stage abstention — **100% abstention accuracy** (11/11
>   correctly declined, 0 false refusals across 23 answerable questions).
> - Built an automated evaluation harness measuring Recall@K, Precision@K, MRR,
>   nDCG@K, citation precision, grounding and cost; used it to measure that a
>   cross-encoder reranker delivered **no metric improvement for 54× latency**
>   on this corpus, and shipped it disabled.

Every number above is reproducible: `python -m scripts.run_eval --full`.
