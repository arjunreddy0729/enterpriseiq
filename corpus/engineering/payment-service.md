# payments-service Architecture

Owner: Dev Shah (dev.shah@northwind.example), Senior Engineer, Payments.
payments-service is the payment orchestration layer for the Northwind platform:
Python 3.12, FastAPI, PostgreSQL 16. It sits behind api-gateway and in front of
our payment service providers, and it is the only service permitted to hold a
PSP credential.

Related reading: `authentication.md` (the two auth planes — this service uses
both), `api-gateway.md` (what the edge has already done to a request before we
see it), and `deployment-runbook.md` (blue/green, which applies here).

## Responsibilities

- Orchestrating the lifecycle of a payment across its state machine.
- Talking to the PSPs: Cardinal, and Halcyon for EU card traffic.
- Enforcing idempotency on every write.
- Receiving and verifying PSP webhooks.
- Emitting ledger postings to ledger-service so money movement is recorded
  double-entry.
- Exposing payment state to shipment-service and the customer-facing API.

Explicitly **not** our responsibility:

- We are not the ledger. Balances, journals, and the double-entry invariants live
  in ledger-service; payments-service emits postings and does not own that truth.
- We do not store raw card numbers. Card data goes to the PSP and comes back as a
  token. There is no PAN column anywhere in our schema and never will be.
- We do not decide pricing or invoice amounts, and we do not send customer email
  — that is notification-service.

## Payment state machine

Six states. The happy path is a linear walk through the first four.

```text
created ──▶ authorized ──▶ captured ──▶ settled
   │             │             │            │
   └─────────────┴─────────────┴────────────┴──▶ failed
                               │            │
                               └────────────┴──▶ refunded
```

| State | Meaning | Terminal |
|---|---|---|
| `created` | Payment intent recorded; no funds reserved yet | no |
| `authorized` | Funds reserved at the issuer; not yet moved | no |
| `captured` | Capture request accepted by the PSP | no |
| `settled` | PSP has confirmed settlement in its payout file | yes |
| `failed` | Terminal failure at any earlier stage | yes |
| `refunded` | Full or partial refund completed | yes |

Rules we enforce in code, not by convention:

- Transitions are validated against an explicit allow-list. An unexpected
  transition raises and does **not** write.
- `settled` is only ever reached via a webhook from the PSP.
- `refunded` is reachable from `captured` or `settled` only. You cannot refund an
  authorization; you void it, which lands in `failed` with a void reason.
- Transitions are recorded in an append-only `payment_events` table, which is
  authoritative; the `payments` row carries current state for convenience.

## PSP integration: Cardinal, with Halcyon for EU cards

**Cardinal** is our primary payment service provider and handles the large
majority of traffic. **Halcyon** is a fallback PSP used **only for EU card
traffic** — not a general-purpose failover for the rest of the world. Routing
non-EU traffic to Halcyon is a misconfiguration, not a degraded mode.

Routing logic, in order:

1. If the payment is not EU card traffic, route to Cardinal. If Cardinal is
   unavailable, the payment fails; there is no alternative provider here.
2. If the payment is EU card traffic, route to Cardinal.
3. If Cardinal returns a retryable failure for EU card traffic, or the EU circuit
   breaker is open, route to Halcyon.

The PSP that handled a payment is recorded on the row (`psp` column) and never
changes. Refunds always go back to the PSP that captured the payment — you cannot
capture on Cardinal and refund on Halcyon. EU traffic is also subject to the data
residency requirement that EU customer data stays in the Dublin region; see
`data-retention.md` for the authoritative statement of that rule.

## Idempotency

**Every write endpoint requires an `Idempotency-Key` header.** No exceptions, no
"internal callers are trusted" carve-out.

- Keys are client-generated. We recommend a UUIDv4 per logical operation.
- Keys are retained for **24 hours**. After that the key is forgotten and a
  replay would be treated as a new request.
- A replay within the retention window returns the original response, byte for
  byte, with the original status code.
- A replay within the window carrying a *different* request body for the same key
  returns `409 Conflict`. We hash the canonicalized body and compare.
- A request with no `Idempotency-Key` on a write endpoint returns `400`.

The 24-hour window is why client retry budgets must sit well inside a day: a
retry attempted 26 hours later is not a retry, it is a second charge.

## Authentication

payments-service participates in **both** authentication planes described in
`authentication.md`. Worth restating, because it is the most common source of
confusion for new callers.

1. **Its own service identity.** payments-service obtains an access token from
   identity-service using the OAuth 2.0 client credentials grant at
   `https://identity.northwind.internal/oauth2/token`. Tokens are RS256 JWTs with
   a TTL of 3600 seconds. This is the identity it presents to ledger-service.

2. **Validation of the forwarded end-user JWT.** api-gateway forwards the
   end-user token in the `X-Northwind-User-Token` header. payments-service
   re-validates it independently — signature against the JWKS at
   `https://identity.northwind.internal/.well-known/jwks.json`, then `exp`,
   `iss`, and `aud`. **We do not trust the gateway blindly.** A forged
   `X-Northwind-User-Token` sent straight to the service's internal address gets
   a 401, and a conformance test asserts exactly this.

There is no mTLS between payments-service and any other internal service; service
identity is entirely application-layer bearer tokens.

### Required scopes

| Scope | Endpoints |
|---|---|
| `payments:read` | `GET /v1/payments`, `GET /v1/payments/{id}` |
| `payments:write` | `POST /v1/payments`, `POST /v1/payments/{id}/capture` |
| `payments:refund` | `POST /v1/payments/{id}/refunds` |

`payments:write` does **not** imply `payments:refund`. Insufficient scope returns
`403`, never `401`.

## Webhooks

Cardinal posts asynchronous events to
`https://api.northwind.example/v1/webhooks/cardinal`. Signature verification uses
the **`X-Cardinal-Signature`** header, carrying an **HMAC-SHA256** of the raw
request body under the shared webhook secret. Compare in constant time, never
with `==` on hex strings, and always verify against the **raw** body bytes before
any JSON parsing or re-serialization — round-tripping through a JSON parser
reorders keys and breaks the signature. This has bitten us.

```python
import hmac, hashlib

def verify_cardinal_signature(raw_body: bytes, header_value: str, secret: bytes) -> bool:
    expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_value)
```

Handling rules:

- An invalid signature returns `401`; the payload is discarded and logged as
  headers plus a body hash only, never the body.
- A valid webhook for an unknown payment ID returns `200` and is queued for
  reconciliation. An error response would make Cardinal retry forever against a
  payment we will never have.
- Webhook handlers are idempotent by PSP event ID. Cardinal will redeliver, and
  redelivery must not double-apply a state transition.
- Webhooks are the **only** path to the `settled` state.

Halcyon webhooks arrive on a separate path with a separate secret and are
verified with the same HMAC-SHA256 construction.

## SLO

| Objective | Target |
|---|---|
| Availability | 99.95% |
| Latency, p99 | 400 ms |

The latency objective covers our own processing and excludes time blocked on a
PSP, tracked as a separate dependency metric. See `observability-standards.md`.

## Database schema sketch

PostgreSQL 16. Abbreviated; indexes and constraints not exhaustive.

```sql
CREATE TABLE payments (
    id                TEXT PRIMARY KEY,              -- pay_9f2c...
    tenant_id         TEXT NOT NULL,
    amount_minor      BIGINT NOT NULL,               -- minor units, never float
    currency          CHAR(3) NOT NULL,
    state             TEXT NOT NULL,
    psp               TEXT NOT NULL,                 -- 'cardinal' | 'halcyon'
    psp_reference     TEXT,
    payment_method_token TEXT NOT NULL,              -- PSP token, never a PAN
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE payment_events (
    id            BIGSERIAL PRIMARY KEY,
    payment_id    TEXT NOT NULL REFERENCES payments(id),
    from_state    TEXT,
    to_state      TEXT NOT NULL,
    reason        TEXT,
    source        TEXT NOT NULL,                     -- 'api' | 'webhook' | 'job'
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE idempotency_keys (
    key            TEXT PRIMARY KEY,
    request_hash   TEXT NOT NULL,
    response_body  JSONB NOT NULL,
    response_code  INT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()  -- purged after 24 hours
);

CREATE INDEX ON payments (tenant_id, created_at DESC);
CREATE INDEX ON payment_events (payment_id, occurred_at);
```

Amounts are always integer minor units; there is no floating point anywhere in
the money path. The corresponding ledger table in ledger-service is partitioned
— see `adr-0007-postgres-partitioning.md`.

## Create a payment

```http
POST /v1/payments HTTP/1.1
Host: api.northwind.example
Authorization: Bearer <end-user access token>
Idempotency-Key: 9c1e5b7a-2f43-4d18-8b0c-6a2e91f3d7cc
X-Request-ID: 4b6d2f10-8e57-4a91-b3c2-1f7d905ac48e
Content-Type: application/json

{
  "tenant_id": "acct_04412",
  "amount_minor": 128450,
  "currency": "USD",
  "payment_method_token": "pm_tok_7d21ba99",
  "capture": false,
  "description": "Freight invoice INV-20260518-0031"
}
```

Response:

```json
{
  "id": "pay_9f2c4a17d0",
  "tenant_id": "acct_04412",
  "amount_minor": 128450,
  "currency": "USD",
  "state": "authorized",
  "psp": "cardinal",
  "psp_reference": "crd_auth_51ab77e2",
  "payment_method_token": "pm_tok_7d21ba99",
  "description": "Freight invoice INV-20260518-0031",
  "captured_amount_minor": 0,
  "refunded_amount_minor": 0,
  "created_at": "2026-05-18T14:22:09Z",
  "updated_at": "2026-05-18T14:22:10Z"
}
```

`capture: false` produces `authorized`; `capture: true` attempts authorization
and capture in one call and produces `captured` on success.

## Retries and backoff

Outbound calls to a PSP:

- Retry only on network errors, HTTP 429, and HTTP 5xx. **Never** retry a 4xx
  other than 429 — the PSP is telling you the request is wrong.
- Exponential backoff with full jitter: base 200 ms, multiplier 2, cap 5 s.
- Maximum 4 attempts total for authorization, 6 for capture, because a lost
  capture is worse than a lost authorization.
- Every retry reuses the same PSP-side idempotency reference, so a retry can
  never double-charge.
- A circuit breaker opens after 20 consecutive failures in a 60-second window and
  half-opens after 30 seconds. For EU card traffic, an open Cardinal breaker is
  what triggers the Halcyon fallback.

Inbound client retries are handled entirely by the idempotency mechanism above. A
client retrying with the same key is safe; one retrying with a fresh key has
requested a second payment and will get one.

## Operational notes

- Deploys use blue/green, not rolling. See `deployment-runbook.md`.
- The service is subject to the platform deploy freeze: no production deploys
  after 16:00 Friday, and none from December 20 through December 31.
- Payment loss is a SEV1 by definition. See `incident-response.md`.
- Reconciliation runs nightly against the Cardinal and Halcyon settlement files
  and raises a ticket, not a page, for any mismatch under a materiality threshold
  agreed with Finance.

## Revision History

| Date | Author | Change |
|---|---|---|
| 2025-06-11 | Dev Shah | First version covering state machine and Cardinal integration |
| 2026-01-28 | Dev Shah | Documented Halcyon EU fallback and circuit breaker behavior |
| 2026-06-02 | Dev Shah | Added raw-body webhook verification warning after a signature mismatch incident |
