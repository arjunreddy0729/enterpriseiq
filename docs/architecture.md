# Architecture notes

The high-level picture, the component diagram, and the reasoning behind the
retrieval design live in the [root README](../README.md). This file holds the
operational procedures that are too detailed for it.

> The full architecture diagram (`docs/architecture.png`) is generated once the
> retrieval pipeline exists, so that it documents what was built rather than
> what was planned.

---

## Changing the embedding model

`EMBEDDING_MODEL` and `EMBEDDING_DIM` are configuration, but the dimension is
baked into the `chunks.embedding` column at migration time
(`vector(768)` for `bge-base-en-v1.5`, `vector(384)` for `bge-small-en-v1.5`).
Changing the model is therefore **not** a one-line `.env` edit on a database
that already holds data.

`/readyz` compares the configured dimension against the dimension recorded in
`pg_attribute.atttypmod` and fails the `embedding_dim` check if they diverge,
so a mismatch surfaces immediately instead of at the first insert.

### On an empty database

Edit both values in `.env`, drop the volume, and re-migrate:

```bash
docker compose down -v
docker compose up --build
```

### On a database with data

Every stored vector was produced by the old model. Vectors from two different
models are not comparable — mixing them silently destroys retrieval quality
rather than raising an error. The chunk text is unchanged, so nothing needs
re-parsing or re-chunking; only the embeddings must be recomputed.

The procedure:

1. Write a migration that adds a second column, e.g.
   `embedding_v2 vector(384)`, leaving the existing column untouched.
2. Backfill `embedding_v2` for every chunk with the new model, in batches,
   writing the new model name into `chunks.embedding_model`.
3. Build the new HNSW index on `embedding_v2` **concurrently**, so the running
   system keeps serving from the old index.
4. Cut the retriever over to the new column.
5. In a later migration, drop the old column and index.

This is why `chunks.embedding_model` is stored per row: after step 2 you can
find the not-yet-migrated rows with a `WHERE embedding_model <> :new_model`
predicate instead of guessing, and the backfill is resumable.

---

## Changing document access groups

`document_permissions` is the source of truth; `chunks.access_group_ids` is a
denormalised projection of it, which is what makes the retrieval-time ACL check
a single indexable predicate. The two must never disagree.

**Use the admin API, not SQL.**

```bash
PUT /api/v1/admin/documents/{document_id}/permissions   {"groups": ["hr"]}
PUT /api/v1/admin/users/{user_id}/groups                 {"groups": ["engineering"]}
```

`PermissionService.set_document_groups` rewrites `document_permissions`, the
chunk copies and the `permission_changes` audit row in **one transaction**.
Grants and revocations are both synchronous: there is no window in which the
permission table says "revoked" while the chunks still say "allowed", which is
the window a background propagation job would open. On this corpus a document
has at most a few dozen chunks, so the `UPDATE` is cheap; at millions of chunks
per document this would become a batched job, and revocations would then need
a denylist checked at query time to keep them immediate.

User group changes need no propagation at all. Tokens carry only a user id;
groups are read from `user_groups` on every request, so removing someone from
HR applies to their next request even with an unexpired token.

**Re-ingesting resets ACLs to the manifest.** `scripts.ingest_corpus` treats
`corpus/manifest.yaml` as the declarative definition of the demo corpus,
including its permissions. A change made through the API lasts until the next
re-ingest.

**The history is append-only.** A trigger on `permission_changes` rejects
`UPDATE` and `DELETE`, so the record of who changed what cannot be rewritten by
the application, including by a bug in it.

---

## Migration conventions

- One migration per logical change; never edit a migration that has been
  applied anywhere but your own laptop.
- Every migration must have a working `downgrade()`. CI enforces this by
  running `alembic downgrade base && alembic upgrade head` on every push.
- Schema changes to `chunks` are expand/contract: add the new column, backfill,
  switch readers, then drop — never a destructive change in the same release
  as the code that depends on it.
- The HNSW index is created with raw SQL because its operator class and build
  parameters cannot be expressed through SQLAlchemy. `alembic/env.py` excludes
  it from autogenerate so it is not dropped and recreated on every revision.

---

## Scaling notes (not yet implemented)

Recorded here so the reasoning is not lost, and so the interview answer is the
same as the design:

| Pressure | First response |
|---|---|
| Corpus grows past ~1M chunks | Partition `chunks` by tenant or department; tune `hnsw.ef_search` per query rather than adding replicas |
| Query latency dominated by reranking | Cut the fusion candidate set from 30 to 20 and measure the Recall@k cost before adding hardware |
| Multi-tenancy | `tenant_id` on every table + row-level security, so the ACL predicate and the tenant predicate are enforced by the same mechanism |
| Postgres FTS ranking becomes the bottleneck | Move keyword retrieval to OpenSearch behind the existing `Retriever` port; the ACL filter becomes a `terms` filter on the same group ids |
| Ingestion throughput | The pipeline is already per-document idempotent via `content_hash`; parallelise across documents, never within one |
