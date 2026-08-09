# api-gateway

Owner: Priya Raman (priya.raman@northwind.example), Staff Engineer, Platform

api-gateway is the single edge for all external traffic into the Northwind
platform. Written in Go. Every request from a customer, a partner integration, or
one of our own web clients arrives here first, and nothing reaches a backend
service except through it.

The gateway is intentionally boring. Its job is to be a fast, predictable,
uninteresting piece of infrastructure. Most requests to add a feature to the
gateway should be answered with "put it in the service."

See `authentication.md` for the token model this document assumes throughout.

## Responsibilities

The gateway does exactly seven things:

1. Terminates TLS.
2. Assigns or propagates `X-Request-ID`.
3. Validates the end-user JWT.
4. Enforces rate limits.
5. Rewrites headers for internal consumption.
6. Routes to a backend service by path prefix and version.
7. Emits access logs, traces, and metrics for everything it handled.

That is the whole list. If a proposed change does not fit into one of those
seven, it belongs somewhere else.

## What the gateway deliberately does not do

This section exists because the answer to "can the gateway just...?" is usually
no, and it is faster to point at a document than to relitigate it.

- **No business logic.** The gateway does not know what a payment, a shipment, or
  an invoice is. It knows path prefixes and nothing about the objects behind
  them.
- **No authorization decisions beyond authentication.** The gateway answers "is
  this a valid, unexpired token from our issuer?" It does **not** answer "may
  this user refund this payment?" Scope checks and resource-level authorization
  belong in the owning service, which is the only component with enough context
  to decide correctly.
- **No response body transformation.** The gateway does not reshape, filter, or
  enrich payloads. What the service returned is what the caller gets.
- **No request aggregation.** One inbound request maps to one backend request. We
  do not fan out and stitch. Clients that need composition build a
  backend-for-frontend, or the owning service exposes a composite endpoint.
- **No per-customer feature flags or routing.** Flags live in services.
- **No caching of backend responses.** The gateway holds no application data.
- **No stripping of the re-validation obligation.** Because the gateway validated
  a token does not excuse the downstream service from validating it too. See
  `authentication.md`.

## TLS termination

- Public TLS terminates at the gateway. Certificates are managed by the
  Infrastructure team; renewal is automated and alerts fire 21 days before
  expiry.
- TLS 1.2 minimum, TLS 1.3 preferred. TLS 1.0 and 1.1 are refused.
- HSTS is set on all public responses.
- Traffic from the gateway to backend services inside `northwind-prod` is TLS
  with server authentication only. **There is no mTLS on internal hops** — client
  authentication is application-layer, via the bearer token.

## JWT validation at the edge

The gateway validates the end-user JWT on every request to an authenticated
route:

- RS256 only. Any other `alg` in the header is rejected.
- The verification key is selected by `kid` from the JWKS at
  `https://identity.northwind.internal/.well-known/jwks.json`.
- The JWKS is cached and refetched on an unknown `kid`. Signing keys rotate every
  90 days with a 24-hour overlap window, so a correctly behaving cache never sees
  a rotation-induced failure.
- `exp`, `iss`, and `aud` are checked. Allowed clock skew is 60 seconds.
- Failure returns `401` with a short JSON error body. The gateway does not
  attempt a token refresh on the caller's behalf.

End-user access tokens have a 15-minute TTL, so a well-behaved client refreshes
frequently; a burst of 401s on a single client usually means its refresh loop is
broken, not that the gateway is.

Unauthenticated routes are a short, explicitly enumerated list: health checks,
the OpenAPI document, and the PSP webhook endpoints (which carry their own
signature verification — see `payment-service.md`).

## Header rewriting

Inbound to outbound, the gateway performs these rewrites:

| Inbound | Outbound | Notes |
|---|---|---|
| `Authorization: Bearer <end-user JWT>` | `X-Northwind-User-Token: <end-user JWT>` | The user token is moved, not copied |
| — | `Authorization: Bearer <gateway service token>` | The gateway's own client-credentials token |
| `X-Request-ID` (optional) | `X-Request-ID` | Preserved if a valid UUIDv4, otherwise replaced |
| `X-Forwarded-For` | `X-Forwarded-For` | Appended |
| `X-Northwind-*` (from the client) | *dropped* | Clients may not inject internal headers |

That last row matters: any inbound header in the `X-Northwind-` namespace is
stripped before routing. Otherwise a caller could forge
`X-Northwind-User-Token` directly. Even with the strip in place, downstream
services still re-validate, because defense in depth is the entire point.

The gateway obtains its own service token from identity-service via the OAuth 2.0
client credentials grant; those tokens are RS256 JWTs with a 3600-second TTL.

## Routing

Routing is by path prefix, after the version segment. The routing table is
declarative and lives in the gateway config repo:

```yaml
routes:
  - prefix: /v1/payments
    service: payments-service
    timeout: 8s
  - prefix: /v1/shipments
    service: shipment-service
    timeout: 5s
  - prefix: /v1/ledger
    service: ledger-service
    timeout: 10s
  - prefix: /v1/notifications
    service: notification-service
    timeout: 5s
  - prefix: /v2/payments
    service: payments-service
    timeout: 8s
```

Rules:

- Longest prefix wins.
- A path with no matching route returns `404` from the gateway. It is never
  forwarded to a default backend.
- Timeouts are per route and are set slightly above the owning service's p99
  objective, not at it.
- Retries at the gateway are limited to idempotent methods (`GET`, `HEAD`) and to
  a single attempt. The gateway must never retry a `POST`; that is what the
  `Idempotency-Key` mechanism in payments-service is for.

## Rate limiting

The default limit is **1000 requests per minute per `client_id`**, with a
**burst of 200**.

- The limiter is a token bucket: 1000 tokens refilled over 60 seconds, bucket
  capacity 200 for burst absorption.
- The dimension is `client_id`, not IP address. IP-based limiting is useless
  behind customer NAT and punishes the wrong tenants.
- Over the limit, the gateway returns **HTTP 429** with a **`Retry-After`**
  header, in seconds, indicating when the caller may retry.
- Limits are enforced at the edge only. Backend services do not implement their
  own general-purpose rate limiting.

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 17
X-Request-ID: 4b6d2f10-8e57-4a91-b3c2-1f7d905ac48e
Content-Type: application/json

{
  "error": "rate_limited",
  "message": "Request rate exceeded for this client. Retry after the interval in Retry-After."
}
```

Raising a limit for a specific client is possible but is a deliberate, reviewed
change with an owner and an expiry date, not a config tweak. Clients that
routinely hit the limit usually need pagination or a bulk endpoint, not a bigger
bucket.

## Request ID propagation

- Header name: **`X-Request-ID`**. Value is a **UUIDv4**.
- If the client supplies a well-formed UUIDv4, the gateway preserves it.
  Malformed values are replaced rather than rejected — a bad request ID should
  not fail a request.
- The gateway propagates `X-Request-ID` to every downstream service, and every
  service must propagate it further on any call it makes.
- The ID is echoed on every response, including errors, so a customer reporting a
  problem can hand us one string that finds every log line and trace span.
- It appears in access logs, structured application logs, and as a trace
  attribute. See `observability-standards.md`.

## API versioning and deprecation

- Versions are a URL prefix: `/v1`, `/v2`. No header-based or query-parameter
  version negotiation.
- Within a version, changes must be additive. Adding an optional field is fine;
  removing a field, changing a type, tightening validation, or changing a default
  is not.
- A breaking change requires a new major version.
- **Deprecated versions get 6 months notice** before removal. The clock starts
  when the deprecation is announced to customers, not when the internal decision
  is made.
- During the notice period, responses on the deprecated version carry a
  `Deprecation` header and a `Sunset` header with the removal date.
- Two major versions may be live simultaneously. Three is a smell and requires an
  explicit exception.

```http
HTTP/1.1 200 OK
Deprecation: true
Sunset: Sat, 12 Dec 2026 00:00:00 GMT
Link: <https://docs.northwind.example/v2/payments>; rel="successor-version"
```

## Failure behavior

| Condition | Gateway response |
|---|---|
| Invalid or expired end-user JWT | `401` |
| Unknown path | `404` |
| Over rate limit | `429` with `Retry-After` |
| Backend connection refused | `502` |
| Backend exceeded route timeout | `504` |
| Gateway cannot reach identity-service for its own token | `503`, and pages |

The gateway never converts a backend's `4xx` into something else. If
payments-service returns `403` for insufficient scope, the caller sees `403`.

## Operational notes

- Deployed with a rolling update; blue/green is reserved for payments-service and
  ledger-service. See `deployment-runbook.md`.
- Subject to the platform deploy freeze: nothing to production after 16:00 Friday
  or between December 20 and December 31.
- Gateway saturation or a total edge failure is a SEV1. Elevated 5xx rates
  confined to one route are typically a SEV2 for the owning service, not for the
  gateway. See `incident-response.md`.
- The four golden signals for the gateway are dashboarded per route and per
  `client_id`; see `observability-standards.md`.

## Revision History

| Date | Author | Change |
|---|---|---|
| 2025-03-19 | Priya Raman | Initial gateway documentation |
| 2025-09-30 | Priya Raman | Added the "what the gateway does not do" section |
| 2026-04-07 | Priya Raman | Documented `X-Northwind-*` header stripping and the Sunset header convention |
