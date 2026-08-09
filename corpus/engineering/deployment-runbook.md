# Deployment Runbook

Owner: Sofia Reyes (sofia.reyes@northwind.example), Engineering Manager, Infrastructure

This is the operational runbook for shipping code to `northwind-staging` and
`northwind-prod`. It is written to be followed at 03:00 by someone who did not
write the change. If a step here is wrong, fix the step — do not work around it
and move on.

## The pipeline in one paragraph

A merge to `main` triggers GitHub Actions, which builds and tests, then pushes a
container image tagged with the commit SHA to `registry.northwind.internal`. A
follow-up job opens a pull request against the `northwind/deploy` repository
updating the image tag in the staging overlay. Argo CD watches
`northwind/deploy` and syncs the cluster to match. Promotion to production is a
second, separate pull request against the production overlay. Nothing is ever
deployed by running `kubectl apply` by hand.

```text
git push ──▶ GitHub Actions ──▶ registry.northwind.internal
                                        │
                                        ▼
                          PR to northwind/deploy (staging overlay)
                                        │
                                   Argo CD sync
                                        ▼
                              northwind-staging
                                        │
                          PR to northwind/deploy (prod overlay)
                                        │
                                   Argo CD sync
                                        ▼
                                northwind-prod
```

GitOps is the rule, not a preference: the state of `northwind/deploy` is the
state of the cluster, and if they diverge, the cluster is wrong.

## Deploy strategies

| Service | Strategy |
|---|---|
| api-gateway | rolling update |
| identity-service | rolling update |
| shipment-service | rolling update |
| notification-service | rolling update |
| **payments-service** | **blue/green** |
| **ledger-service** | **blue/green** |

Rolling update is the default. **payments-service and ledger-service use
blue/green** because a partial rollout that has two code versions writing to the
money path simultaneously is not an acceptable risk, even briefly.

Practical consequences of blue/green:

- Both versions run at full capacity during the cutover. Plan cluster headroom.
- The cutover is a single service-selector switch, so rollback is also a single
  switch and takes seconds.
- The green (new) stack must pass its readiness gate on production traffic
  mirrored at low volume before the switch. We do not switch on health checks
  alone.

## Deploy freeze windows

**No production deploys after 16:00 Friday.** **No production deploys from
December 20 through December 31.**

These are hard rules with one exception: a deploy that resolves an active SEV1 or
SEV2. That exception requires the Incident Commander to say so in the incident
channel, and the deploy PR must link the incident. "It's a tiny change" is not an
exception. "The customer is waiting" is not an exception.

Staging deploys are unaffected by the freeze.

## Pre-deploy checklist

Run through this before opening the production promotion PR. It is short on
purpose so that people actually do it.

- [ ] The change has been running in `northwind-staging` for at least 2 hours
      under real staging traffic.
- [ ] CI is green on the exact commit SHA being promoted — not on a later commit.
- [ ] No database migration in this release is destructive. See the migration
      policy below.
- [ ] If there is a migration, it has been applied to staging and the service ran
      against the migrated schema.
- [ ] Dashboards for the service are open in another window. See
      `observability-standards.md`.
- [ ] The current on-call primary knows the deploy is happening. See
      `oncall-rotation.txt`.
- [ ] It is not after 16:00 Friday, and it is not December 20-31.
- [ ] For payments-service or ledger-service: confirmed cluster headroom for two
      full stacks.
- [ ] The rollback path is understood by the person deploying. If you cannot say
      how you would roll this back, do not deploy it.

## Promoting staging to production

Verify what is currently running in staging:

```bash
kubectl --context northwind-staging \
  -n payments get deploy payments-service \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
# registry.northwind.internal/payments-service:9f4c2a1
```

Confirm Argo CD considers staging healthy and in sync:

```bash
argocd app get payments-service-staging --output wide
```

Open the promotion PR against `northwind/deploy`, editing only the image tag in
the production overlay:

```yaml
# northwind/deploy/overlays/prod/payments-service/kustomization.yaml
images:
  - name: registry.northwind.internal/payments-service
    newTag: 9f4c2a1     # was 8b1e7d0
```

A promotion PR should change exactly one line per service. If yours also changes
replica counts, resource limits, or environment variables, split it. Mixing a
code promotion with a config change makes rollback ambiguous, and ambiguous
rollbacks are how a five-minute incident becomes a forty-minute one.

After merge, Argo CD picks the change up on its next poll. To watch it:

```bash
argocd app wait payments-service-prod --health --timeout 600
kubectl --context northwind-prod -n payments rollout status deploy/payments-service
```

For the blue/green services, the merge deploys the green stack but does **not**
move traffic. Traffic moves when the service selector is switched:

```yaml
# northwind/deploy/overlays/prod/payments-service/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: payments-service
spec:
  selector:
    app: payments-service
    slot: green      # was: blue
  ports:
    - port: 8080
      targetPort: 8080
```

Watch for 15 minutes after the switch before you consider the deploy done. Error
rate, p99 latency against the 400 ms objective, and PSP call failure rate are the
three things to watch for payments-service.

## Rolling back

Rollback is a revert, not a fix-forward. Decide within 10 minutes: if the deploy
is misbehaving and the cause is not obvious and small, roll back and diagnose
afterward with production stable.

### Rolling-update services

Revert the promotion commit in `northwind/deploy` and let Argo CD sync:

```bash
git -C northwind-deploy revert --no-edit <promotion-commit-sha>
git -C northwind-deploy push origin main
argocd app wait api-gateway-prod --health --timeout 600
```

Do not use `kubectl rollout undo`. It changes the cluster without changing
`northwind/deploy`, so Argo CD will detect drift and put the bad version straight
back. This is the single most common rollback mistake.

### Blue/green services

Switch the selector back. This is the fastest rollback we have.

```bash
kubectl --context northwind-prod -n payments \
  patch svc payments-service \
  -p '{"spec":{"selector":{"app":"payments-service","slot":"blue"}}}'
```

Then immediately open the revert PR against `northwind/deploy` so the repository
matches reality. The patch above is an emergency action; leaving the repo
inconsistent with the cluster is a second incident waiting to happen.

## Database migration policy

**Expand/contract. Never destructive in the same release as the code that stops
using the column.**

The sequence, always three releases minimum:

1. **Expand.** Add the new column, table, or index, nullable or with a default.
   Old code ignores it; new code writes it. Deploy.
2. **Migrate and dual-read.** Backfill. New code reads the new shape and falls
   back to the old. Deploy and let it soak — at least one full week for anything
   in the money path.
3. **Contract.** Only once nothing reads the old shape, drop it. This is its own
   release with its own rollback plan.

Hard rules:

- No `DROP COLUMN`, `DROP TABLE`, or destructive `ALTER` in the same release that
  changes application code.
- No migration that takes a long-held exclusive lock during business hours. Build
  indexes with `CREATE INDEX CONCURRENTLY`.
- Every migration must be forward-only. We do not write down-migrations; a
  rollback rolls back code, not schema. That is the whole reason the expand step
  must be backward compatible.
- Migrations run as a separate step before the new pods start, never in an
  application init path that races across replicas.

```yaml
# Migration job, run before the deployment is updated
apiVersion: batch/v1
kind: Job
metadata:
  name: ledger-migrate-0042
spec:
  backoffLimit: 0          # a failed migration must not silently retry
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: registry.northwind.internal/ledger-service:9f4c2a1
          command: ["/app/migrate", "up", "--timeout", "600s"]
```

`backoffLimit: 0` is deliberate: a migration that failed halfway should be looked
at by a human, not retried automatically.

Backups: PostgreSQL 16, nightly, retained 35 days, with point-in-time recovery
covering 7 days. A migration is not a backup strategy, and PITR is not an excuse
to skip expand/contract — restoring a production database is measured in hours.

## Worked rollback walkthrough

A real-shaped example. Times are illustrative.

**14:02** — payments-service `9f4c2a1` is promoted to production. Green stack
comes up healthy, readiness gate passes on mirrored traffic, selector switched to
`green`.

**14:09** — The p99 latency panel for payments-service crosses 400 ms and keeps
climbing. Error rate is normal; nothing is failing, everything is slow.

**14:10** — The deployer declares an incident in the on-call channel. Because
customer-facing degradation is real but payments are still succeeding, it is
opened as a SEV2. An Incident Commander is assigned per `incident-response.md`.

**14:11** — Decision: roll back now, diagnose later. Nobody understands the cause
yet, which is exactly the condition under which we roll back.

```bash
kubectl --context northwind-prod -n payments \
  patch svc payments-service \
  -p '{"spec":{"selector":{"app":"payments-service","slot":"blue"}}}'
```

**14:11:40** — Traffic is back on `blue` (`8b1e7d0`). p99 returns to normal
within one scrape interval.

**14:14** — Revert PR opened against `northwind/deploy` restoring `newTag:
8b1e7d0` in the prod overlay, linked to the incident. Merged.

```bash
argocd app get payments-service-prod --output wide   # Synced / Healthy
```

**14:20** — Comms Lead updates status.northwind.example to resolved. The green
stack is left running, with no traffic, for inspection.

**14:45** — Root cause found in the drained green pods: a connection-pool setting
carried in the same PR as the code change, which is exactly the mixing the
promotion rules above forbid.

**Next day** — Blameless postmortem drafted; due within 5 business days per
`incident-response.md`. Action item: CI check rejecting promotion PRs that touch
anything other than the image tag.

## Emergency access

Direct `kubectl` write access to `northwind-prod` exists for incidents and is
audited. Using it outside an incident is a process failure worth flagging, not a
shortcut. The blue/green selector patch above is the one routine exception, and it
must be reconciled into `northwind/deploy` immediately afterward.

## Revision History

| Date | Author | Change |
|---|---|---|
| 2025-05-08 | Sofia Reyes | Initial runbook covering the Actions to Argo CD flow |
| 2025-12-15 | Sofia Reyes | Added the December 20-31 freeze and clarified the SEV1/SEV2 exception |
| 2026-06-09 | Sofia Reyes | Added worked rollback walkthrough; strengthened the no-`rollout undo` warning |
