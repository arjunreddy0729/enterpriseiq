# Security

This is a demonstration project, not a product. It is also a project *about* a
security property, so it is worth being precise about which property, and what
is deliberately out of scope.

## The property this system claims

**A user cannot retrieve a document they are not permitted to read**, and
restricted text never reaches a model's context window.

That is enforced in three places, each independently sufficient:

1. **In the retrieval query.** Access groups are a GIN-indexed array predicate
   in the same SQL that does the vector and keyword search. Rows the caller
   may not read are never returned, so there is nothing to filter afterwards.
2. **In application code, after retrieval.** A second check re-verifies every
   candidate's groups. It should never remove anything; it exists for the day
   a new retriever forgets the predicate, and it logs at ERROR when it fires.
3. **At ingestion.** A source that has not declared `access_groups` fails at
   the boundary rather than being indexed with an unknown audience.

Group membership is read from the database on **every request**, not from the
token. A user removed from a group loses access on their next request even
while holding an unexpired token.

This is covered by an adversarial leak suite in CI — prompt injection, role
claims in the question, filter and token tampering — and by mutation testing
that disables each layer in turn to confirm the others still block every case.

## Deliberately out of scope

- **Multi-tenancy.** One organisation per deployment. There is no tenant
  isolation boundary.
- **The demo deployment is public by design.** `DEMO_MODE=true` shares one
  login per persona, disables permission edits, and caps model spend. Do not
  put real documents in it.
- **The `X-Dev-User` header** bypasses password authentication. With
  `ENVIRONMENT=production` the app **refuses to start** unless
  `AUTH_DEV_HEADER_ENABLED=false` — a config validator, not a runtime check,
  so the failure happens at deploy time rather than on the first request.
- **Rate limiting is in-process.** It does not hold across replicas.
- **Retrieved documents are untrusted input.** Passages are fenced and the
  system prompt says they are data, but prompt injection via document content
  is mitigated, not solved. The guarantee that holds under injection is the
  permission one: a model cannot leak a passage it was never given.

## Reporting

This is a personal portfolio project with no users to protect, so there is no
embargo process. Open a GitHub issue, or if you would rather not do so
publicly, say so in an issue with no detail and I will follow up.

If you find a way to retrieve a document as a user who should not see it, that
is the interesting bug and I would genuinely like to know.
