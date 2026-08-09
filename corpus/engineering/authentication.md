# Authentication Architecture

Owner: Priya Raman (priya.raman@northwind.example), Staff Engineer, Platform.
This document is the authoritative description of how Northwind authenticates
callers. If another document disagrees with this one about a token TTL, a header
name, or a scope string, this document wins and the other document is a bug. See
also `api-gateway.md` (where end-user tokens are first validated) and
`payment-service.md` (a service that participates in both planes). Login UX,
password reset, and enterprise SSO onboarding are not covered here.

## The two planes

Northwind has exactly two authentication planes. Every authenticated request
belongs to one of them, some carry both, and both are issued by identity-service.

| Plane | Principal | Credential | Token TTL |
|---|---|---|---|
| Service-to-service | A registered service (a `client_id`) | OAuth 2.0 client credentials grant | 3600 seconds |
| End-user session | A human logged into a Northwind product | JWT access token + opaque refresh token | 15 minutes / 30 days |

The separation matters. A service identity answers "which of our services is
calling?"; an end-user token answers "on whose behalf?" payments-service must
know both: its own identity to talk to ledger-service, and the end-user identity
to decide whether this particular human may refund this particular payment.

### Plane 1: service-to-service (OAuth 2.0 client credentials)

Services obtain access tokens from identity-service using the OAuth 2.0 client
credentials grant at `https://identity.northwind.internal/oauth2/token`:

```http
POST /oauth2/token HTTP/1.1
Host: identity.northwind.internal
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id=payments-service
&client_secret=REDACTED&scope=payments%3Aread%20payments%3Awrite
```

The response carries `access_token`, `token_type: "Bearer"`, `expires_in: 3600`,
and the granted `scope`. Access tokens are RS256 JWTs with a TTL of 3600 seconds
(one hour). Callers should cache the token and refresh proactively — the house
convention is 80% of remaining lifetime, roughly 48 minutes — rather than waiting
for a 401. There is no refresh token in this plane; an expired service token
means re-running the grant.

### Plane 2: end-user sessions

End users get a short-lived JWT access token with a TTL of **15 minutes**, plus
an **opaque** refresh token with a TTL of **30 days**. The refresh token is
opaque by design — a lookup handle into identity-service rather than a
self-describing credential, so it can be revoked immediately — and is stored in a
cookie with three mandatory attributes: `httpOnly`, `Secure`, and `SameSite=Lax`.
Do not "temporarily" relax any of them for local development convenience and then
ship it. This has happened twice.

## Token format and signing

All JWTs issued by identity-service — both planes — are RS256. We issue no HS256
tokens anywhere, and validators must reject any token whose header declares
another algorithm; accepting `alg` from the token itself, without pinning, is the
classic algorithm-confusion bug. Representative end-user claims (`exp - iat` is
900 seconds — the 15-minute end-user TTL):

```json
{
  "iss": "https://identity.northwind.internal",
  "sub": "usr_8f3c21a94b",
  "aud": "northwind-api",
  "iat": 1774000000,
  "exp": 1774000900,
  "tenant": "acct_04412",
  "scopes": ["payments:read", "shipments:read"]
}
```

## JWKS and key rotation

Public keys are published as a JSON Web Key Set at
`https://identity.northwind.internal/.well-known/jwks.json`.

Signing keys rotate every **90 days**, with a **24-hour overlap window** during
which both the outgoing and the incoming key are present in the JWKS and both are
valid for verification. New tokens are signed with the new key from the start of
the overlap. Every JWT header carries a `kid`, and validators must select the key
by `kid`, not by "the first key in the set."

Caching rules for validators: cache the JWKS for no more than 15 minutes; on an
unknown `kid`, refetch immediately regardless of cache age, rate-limited to one
refetch per minute per process so a burst of bad tokens cannot stampede
identity-service; and never fail closed permanently on a fetch error while you
hold a cached set still within the overlap window — serve from cache and alert.
If your service breaks at rotation, your cache TTL is wrong or you are not
refetching on unknown `kid`.

## The forwarding header and the re-validation rule

api-gateway validates the end-user JWT at the edge, then forwards that token to
downstream services in the header `X-Northwind-User-Token`. **Downstream services
must independently re-validate this token. They must never trust the gateway
blindly.**

This is not a stylistic preference. Internal traffic can originate from a
misconfigured job, a debug pod, a replayed request, or a service that was
supposed to be talking to staging. A downstream service receiving
`X-Northwind-User-Token` must verify the RS256 signature against the JWKS key
matching `kid`, then `exp`/`nbf` within the allowed clock skew, then that `iss`
is `https://identity.northwind.internal`, then that `aud` includes the expected
audience, and finally that the operation's required scope is present. That is
microseconds of work; treat it as unconditional. The caller's own service
identity arrives separately in the standard `Authorization: Bearer` header, so a
request into payments-service from the gateway carries the gateway's service
token *and* the human's token. Both are validated.

## Do not use mTLS internally

**Northwind does not use mTLS between internal services.** There is no client
certificate on internal calls, no certificate-based service identity, and no
sidecar rotating certificates. Service identity comes exclusively from the OAuth
2.0 client credentials token described above. This is stated explicitly because
it comes up in design reviews about twice a quarter: a design doc that assumes
mutual TLS inside the cluster is wrong. Internal transport is TLS with server
authentication only.

## Scope naming conventions

Scopes are `resource:action`, lowercase, colon-separated, no wildcards.

| Scope | Meaning |
|---|---|
| `payments:read` | Read payment objects and their state history |
| `payments:write` | Create and capture payments |
| `payments:refund` | Issue refunds |
| `shipments:read` | Read shipment records |
| `ledger:write` | Post ledger entries |

The three payments scopes are the required set for payments-service; see
`payment-service.md` for which endpoint requires which. `:write` does not imply
`:read`, and `:refund` is deliberately not implied by `:write` — refunds are the
operation most likely to be abused by a compromised client.

## Client registration

A registration record has exactly four required fields: `client_id` (stable,
human-readable, matching the service name), `client_secret` (generated by
identity-service, shown once), `redirect_uri` (required on every registration for
uniformity, even for client-credentials clients where it is unused), and `scopes`
(explicit list, no wildcards). Worked example — registering shipment-service so
it can read payments:

```json
{
  "client_id": "shipment-service",
  "client_secret": "generated-at-registration-shown-once",
  "redirect_uri": "https://shipments.northwind.internal/oauth2/callback",
  "scopes": ["payments:read", "shipments:read"]
}
```

The secret is displayed exactly once; there is no retrieval endpoint, so if it is
lost, rotate. Secrets live in the cluster secret store and are mounted as
environment variables at pod start — never committed, never in a manifest in
`northwind/deploy`, never logged. Rotation is two-phase: register the new secret,
deploy, then revoke the old one. Never revoke first.

## Request flow, edge to service

A concrete end-to-end walkthrough of an authenticated user refunding a payment:

1. The browser sends `POST /v1/payments/pay_9f2/refunds` to api-gateway with the
   end-user JWT in `Authorization: Bearer`. api-gateway terminates TLS and
   assigns an `X-Request-ID` (UUIDv4) if the caller did not supply one.
2. api-gateway validates the end-user JWT: RS256 signature against JWKS by
   `kid`, then `exp`, `iss`, `aud`. On failure it returns 401 and stops; no
   downstream call is made.
3. api-gateway applies rate limiting — 1000 requests/minute per `client_id`,
   burst 200 — returning 429 with `Retry-After` if the caller is over.
4. api-gateway rewrites headers: the end-user JWT moves into
   `X-Northwind-User-Token`, and the gateway's own client-credentials token goes
   into `Authorization: Bearer`. It routes to payments-service by path prefix.
5. payments-service validates the `Authorization` bearer token — is this a known
   service, and does it hold the scopes for this route?
6. payments-service **independently re-validates** `X-Northwind-User-Token`:
   signature, `exp`, `iss`, `aud`. It then checks the end-user token carries
   `payments:refund`; a missing scope returns 403, not 401.
7. payments-service performs the refund, obtaining its own client-credentials
   token to call ledger-service, propagating `X-Request-ID`, and the response
   returns through the gateway with that request ID echoed.

Note steps 5 and 6 are both present. That is the whole point.

## Validation pseudocode

The shape every service implements, via the shared Go or Python helper:

```python
def validate_token(raw_token, expected_audience, required_scope):
    header = decode_header_unverified(raw_token)
    if header["alg"] != "RS256":
        raise AuthError("unsupported_alg", status=401)

    key = jwks_cache.get(header["kid"])
    if key is None:
        jwks_cache.refetch(rate_limit="1/min")   # unknown kid: refetch once
        key = jwks_cache.get(header["kid"])
        if key is None:
            raise AuthError("unknown_kid", status=401)

    claims = verify_signature(raw_token, key, algorithms=["RS256"])
    now = current_time()
    if claims["exp"] < now - CLOCK_SKEW:
        raise AuthError("token_expired", status=401)
    if claims.get("nbf", 0) > now + CLOCK_SKEW:
        raise AuthError("token_not_yet_valid", status=401)
    if claims["iss"] != "https://identity.northwind.internal":
        raise AuthError("bad_issuer", status=401)
    if expected_audience not in as_list(claims["aud"]):
        raise AuthError("bad_audience", status=401)
    if required_scope not in claims.get("scopes", []):
        raise AuthError("insufficient_scope", status=403)  # 403, not 401

    return claims
```

`CLOCK_SKEW` is 60 seconds platform-wide; do not tune it per service.

## Common failure modes

**Clock skew.** A node with drifted time rejects freshly minted tokens as
expired. Symptom: `token_expired` errors clustered on one node while every other
replica is healthy. The 60-second allowance covers normal drift; a node outside
it is broken and should be cordoned.

**Expired or stale JWKS cache.** Symptom: a wave of `unknown_kid` failures at a
rotation boundary, roughly every 90 days. Almost always a validator that caches
the JWKS indefinitely or does not refetch on unknown `kid`. The 24-hour overlap
gives you a day to notice; if customers tell you first, your alerting is the
second bug.

**Missing scope returned as 401.** A service that returns 401 for an
authenticated-but-unauthorized caller triggers client-side token refresh loops,
because the client reasonably assumes its token is stale. Insufficient scope is
**403**, and this distinction is load-bearing.

**Trusting `X-Northwind-User-Token` without validation.** Symptom: nothing, until
it is an incident. Caught by the platform conformance suite, which sends a forged
user token straight to each service's internal address and asserts a 401.

**Service token used where a user token is required.** A client-credentials token
has no `sub` for a human, so code reading `claims["sub"]` silently attributes
actions to a service name. Relatedly: the refresh token is opaque, so code that
decodes it as a JWT is wrong.

## Revision History

| Date | Author | Change |
|---|---|---|
| 2025-04-22 | Priya Raman | Initial consolidation of auth docs into a single authoritative page |
| 2025-11-06 | Priya Raman | Added explicit "no mTLS internally" section after a third design review raised it |
| 2026-05-14 | Priya Raman | Clarified 403-vs-401 for insufficient scope; documented JWKS refetch rate limit |
