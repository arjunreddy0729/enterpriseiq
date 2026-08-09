# Observability Standards

Owner: Sofia Reyes (sofia.reyes@northwind.example), Engineering Manager, Infrastructure
Contributor: Priya Raman (priya.raman@northwind.example), Platform

These are the rules every Northwind service follows for traces, metrics, and
logs. They are requirements, not suggestions: a service that does not meet them
cannot be considered production-ready, and the readiness review checks for them
explicitly.

## The stack

| Signal | Tool | Notes |
|---|---|---|
| Traces | **OpenTelemetry** | SDK in every service; OTLP export |
| Metrics | **Prometheus** | Scrape-based; `/metrics` on every service |
| Dashboards | **Grafana** | Dashboards live in version control, not clicked together |
| Logs | **Loki** | Structured JSON; **90-day retention** |

Log retention is 90 days for application logs. That number is a legal and
compliance decision, not an engineering one — see `data-retention.md` for the
authoritative statement and for the different retention applied to security audit
logs. Do not build anything that depends on application logs older than 90 days;
they will not be there.

Grafana dashboards are defined as JSON in the repository and deployed with the
service. A dashboard that exists only in someone's browser does not exist during
an incident.

## The correlation ID

Everything hinges on one header: **`X-Request-ID`**, a **UUIDv4**.

- api-gateway assigns it if the caller did not supply a valid one. See
  `api-gateway.md`.
- Every service propagates it on every outbound call, without exception —
  including calls into background jobs and queue messages.
- It appears as a field in every structured log line.
- It appears as a span attribute on every trace span.
- It is echoed on every HTTP response, success or error.

The payoff: a customer reports a problem and gives us one string. That string
finds the trace, and the trace's spans find the log lines from every service
involved. If your service drops `X-Request-ID` somewhere in its call graph, you
have broken this for everyone downstream of you.

## Tracing

Every inbound request creates a span. Every outbound call — HTTP, database, PSP,
queue publish — creates a child span.

### Required span attributes

These are mandatory on the root span of every service:

| Attribute | Example | Notes |
|---|---|---|
| `service.name` | `payments-service` | Exactly the canonical service name |
| `service.version` | `9f4c2a1` | The image tag / commit SHA |
| `deployment.environment` | `production` \| `staging` | |
| `northwind.request_id` | `4b6d2f10-...` | The `X-Request-ID` value |
| `northwind.tenant_id` | `acct_04412` | Omit when there is no tenant context |
| `http.route` | `/v1/payments/{id}` | The **template**, never the filled path |
| `http.status_code` | `200` | |

`http.route` must be the route template. Putting the concrete path in there
produces unbounded cardinality and has taken out a metrics backend before.

### Attributes that must never appear on a span

- Access tokens, refresh tokens, or any value from `Authorization` or
  `X-Northwind-User-Token`.
- `Idempotency-Key` values.
- Card data of any kind, including PSP payment method tokens.
- Email addresses, phone numbers, or postal addresses.
- Raw request or response bodies.

Sampling: head-based, 10% of successful requests, **100% of requests that error
or exceed the service's p99 objective**. Never sample away the interesting ones.

## Logging

### Format

Structured JSON, one object per line, written to stdout. Nothing writes log files
to disk.

```json
{
  "ts": "2026-05-18T14:22:09.481Z",
  "level": "error",
  "service": "payments-service",
  "version": "9f4c2a1",
  "env": "production",
  "request_id": "4b6d2f10-8e57-4a91-b3c2-1f7d905ac48e",
  "trace_id": "7c1a55e0f3b24d9e8a6c02d417bb9f31",
  "span_id": "a9e4b71c2f083d55",
  "tenant_id": "acct_04412",
  "msg": "psp authorization failed",
  "psp": "cardinal",
  "payment_id": "pay_9f2c4a17d0",
  "error_code": "psp_timeout",
  "attempt": 3,
  "duration_ms": 5012
}
```

Required fields on every line: `ts`, `level`, `service`, `version`, `env`,
`request_id`, `msg`. Everything else is contextual.

Rules:

- `msg` is a short, **static** string. Variable data goes in its own field. A
  message of `"psp authorization failed"` with a `payment_id` field is
  greppable; `"authorization for pay_9f2c4a17d0 failed"` is not.
- Never log a token, secret, card number, or full request body. Log a hash or a
  last-four if you need identifiability.
- Never log at `error` for something you handled and recovered from. That is
  `warn`.

### Log levels

| Level | Use for | Alerting |
|---|---|---|
| `debug` | Local and staging diagnosis. Off in production by default. | Never |
| `info` | Business-meaningful events: a payment captured, a shipment created. | Never |
| `warn` | Degraded but handled: a retry succeeded, a fallback engaged. | Trend only |
| `error` | The request failed and a human may need to know. | Rate-based |
| `fatal` | The process cannot continue and is exiting. | Immediate page |

If `error` is a normal occurrence in your service at steady state, your levels
are wrong. `error` should be rare enough that a spike is meaningful.

## The four golden signals

Every service dashboards all four. No exceptions, including internal-only
services.

1. **Latency** — request duration distribution. Always percentiles, never
   averages. p50, p95, p99 at minimum. An average latency graph has hidden more
   incidents than it has revealed.
2. **Traffic** — requests per second, broken down by route and by `client_id`.
3. **Errors** — error rate as a proportion of traffic, split by 4xx and 5xx.
   Client errors and server errors have different owners and must not share a
   line.
4. **Saturation** — the resource closest to its limit. For most services that is
   connection pool utilization or CPU, not memory.

Latency panels must be annotated with the service's objective. payments-service
has an availability SLO of 99.95% and a p99 latency objective of 400 ms; the p99
panel carries a threshold line at 400 ms so that "is this bad?" is answerable at
a glance during an incident. See `payment-service.md`.

## Required dashboards

Each service ships three dashboards, all in version control:

| Dashboard | Purpose | Audience |
|---|---|---|
| `<service>-overview` | The four golden signals, one screen, no scrolling | On-call, first 60 seconds |
| `<service>-dependencies` | Latency and error rate for every outbound dependency | On-call, minute two |
| `<service>-business` | Domain metrics: payment state transitions, shipment volume | Team and stakeholders |

The overview dashboard must fit on one screen. If an on-call engineer has to
scroll to find the error rate at 03:00, the dashboard has failed at its only job.

Platform-level dashboards maintained by Infrastructure: an edge dashboard for
api-gateway (per route and per `client_id`), a Kubernetes cluster health
dashboard for `northwind-prod` and `northwind-staging`, and a PostgreSQL
dashboard covering connections, replication lag, and slow queries.

## Required alerts

Minimum alert set per service:

| Alert | Condition | Routes to |
|---|---|---|
| Error rate elevated | 5xx rate above the service's error budget burn rate over 10 minutes | Page |
| Latency objective breached | p99 above objective for 10 consecutive minutes | Page |
| Service down | No successful scrape for 3 minutes | Page |
| Saturation | Primary saturation metric above 85% for 15 minutes | Ticket |
| Certificate expiry | Under 21 days remaining | Ticket |
| Dependency degraded | Outbound error rate to a dependency above 5% for 10 minutes | Ticket |

Payment-specific alerts (payments-service, and by extension ledger-service):

- PSP authorization failure rate above baseline for 5 minutes — page.
- Any payment stuck in `captured` for longer than the expected settlement window
  — ticket, escalating to a page if the count grows.
- Webhook signature verification failures above zero over 5 minutes — page. A
  nonzero rate means either a secret is wrong or something is forging webhooks,
  and both are urgent.

Alerts route by severity per `incident-response.md`. An alert that pages must
correspond to a SEV1 or SEV2 condition. An alert that would be a SEV3 files a
ticket.

## Alert fatigue rules

These exist because we have been on the wrong side of them.

- **Every page must be actionable.** If the on-call engineer's only possible
  response is "yes, I see it too," it is not a page. Convert it to a ticket or
  delete it.
- **Alert on symptoms, not causes.** Page on "checkout error rate is up," not on
  "a pod restarted." Users do not experience pod restarts.
- **Any alert that fires more than twice in a week without producing an action is
  broken.** Fix the threshold, fix the service, or delete the alert. Doing
  nothing is not an option, because the real cost is that the on-call engineer
  learns to ignore that alert — and then ignores it on the night it matters.
- **No alert without a runbook link.** The alert annotation must contain a link
  to the specific runbook section for that alert. "Page fired, no idea what it
  means" is a defect in the alert, not in the responder.
- **Review alert noise in the weekly operations meeting.** Every alert that fired
  in the last week is reviewed: did it page, was it actionable, did it lead to an
  action? Alerts that fail the test are changed that week, not "sometime."
- **Maintenance windows must silence alerts explicitly.** Expecting the on-call
  engineer to remember that a migration is running is not a plan.
- **No alert may be silenced for more than 7 days** without an owner and a linked
  ticket. Indefinite silences are how alerting dies quietly.

## Onboarding a new service

Checklist for the production readiness review:

- [ ] OpenTelemetry SDK wired; root span carries every required attribute.
- [ ] `X-Request-ID` accepted, propagated on all outbound calls, echoed on
      responses.
- [ ] `/metrics` endpoint exposed and scraped.
- [ ] Structured JSON logs to stdout with all required fields.
- [ ] Three dashboards committed to the repository and rendering.
- [ ] The minimum alert set configured, each with a runbook link.
- [ ] Latency panels annotated with the service's stated objective.
- [ ] Verified that no token, secret, or PII appears in any log line or span
      attribute — checked by reading actual staging output, not by reading the
      code.

## Revision History

| Date | Author | Change |
|---|---|---|
| 2025-07-16 | Sofia Reyes | Initial standards document |
| 2026-02-11 | Priya Raman | Added required span attributes and the cardinality rule for `http.route` |
| 2026-05-27 | Sofia Reyes | Added alert-fatigue rules and the weekly alert noise review |
