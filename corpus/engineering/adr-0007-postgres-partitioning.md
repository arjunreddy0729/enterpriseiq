# ADR-0007: Partition the ledger-service payments table

## Status

**Accepted** — 2026-02-24

Authors: Dev Shah (dev.shah@northwind.example), Priya Raman (priya.raman@northwind.example)
Reviewers: Sofia Reyes (Infrastructure). Supersedes: none.

## Context

ledger-service (Java, PostgreSQL 16) holds the double-entry record of every
payment Northwind has processed since 2019. Its `payments` table is a single
unpartitioned heap, and as of February 2026 it is the largest table in the
platform. The operational problems are no longer theoretical:

- **Autovacuum cannot keep up.** Vacuum runs routinely overlap the next
  scheduled run, and bloat is trending up. `REINDEX` on the primary btree is a
  multi-hour operation, which effectively means we never do it.
- **Query plans degrade at the tail.** Date-range reporting queries increasingly
  choose sequential scans, because whole-table row estimates are poor for the
  selective-but-not-tiny ranges Finance asks for.
- **Deleting old rows is impractical.** Customer transaction records are retained
  7 years (see `data-retention.md`). Past that boundary, removing rows from an
  unpartitioned heap means a large `DELETE` and a vacuum that will not return
  space to the OS. In practice we have never done it.
- **Restore time is worsening.** Backups are nightly, retained 35 days, with
  7-day PITR; recovery time is dominated by this one table.

Access patterns over 30 days of production query logs:

| Access pattern | Share of reads | Time range touched |
|---|---|---|
| Single payment by id | ~61% | any |
| Tenant activity feed | ~23% | last 90 days |
| Finance reporting and reconciliation | ~14% | current or prior month |
| Compliance and audit lookups | ~2% | arbitrary, up to 7 years back |

Nearly all reads touch recent data, and nearly all writes are inserts with a
`created_at` of "now". Updates to old rows are rare and bounded — a settlement
confirmation arriving days later, or a refund.

## Decision

**Convert `ledger.payments` to a range-partitioned table, partitioned monthly on
`created_at`, with a 24-month hot window.**

1. **Partition key `created_at` (`timestamptz`), range partitioning, one
   partition per calendar month**, named `payments_YYYY_MM`.
2. **Hot window: the most recent 24 months.** These partitions live on the
   primary tablespace with the full index set, covering every access pattern
   above except compliance lookups.
3. **Partitions older than 24 months are detached and moved to the archive
   tablespace**, retaining only the primary key index. They stay queryable — the
   7-year retention obligation is unchanged — but leave routine vacuum work.
4. **Partitions are created 3 months ahead by a scheduled job.** A missing
   partition is an insert failure and therefore a payment-path outage, so we
   alert when the furthest-future partition is less than 60 days out.
5. **The primary key becomes `(id, created_at)`**, because PostgreSQL requires
   the partition key to participate in any unique constraint. Application code
   continues to treat `id` as the identifier.
6. **The migration follows expand/contract** per `deployment-runbook.md`: build
   the partitioned table alongside the heap, dual-write, backfill, verify counts
   and checksums per month, cut reads over, then drop the old heap in a later
   release.

```sql
CREATE TABLE ledger.payments (
    id              TEXT        NOT NULL,
    tenant_id       TEXT        NOT NULL,
    amount_minor    BIGINT      NOT NULL,
    currency        CHAR(3)     NOT NULL,
    entry_type      TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

CREATE TABLE ledger.payments_2026_02 PARTITION OF ledger.payments
    FOR VALUES FROM ('2026-02-01 00:00:00+00') TO ('2026-03-01 00:00:00+00');

CREATE INDEX ON ledger.payments_2026_02 (tenant_id, created_at DESC);
```

Aging a partition out of the hot window:

```sql
ALTER TABLE ledger.payments
    DETACH PARTITION ledger.payments_2024_01 CONCURRENTLY;

ALTER TABLE ledger.payments_2024_01
    SET TABLESPACE archive;
```

## Consequences

### Positive

- Vacuum and index maintenance become per-partition operations on bounded
  tables; a month's partition can be reindexed in minutes.
- Range queries on `created_at` prune to a few partitions, and per-partition
  statistics are far more accurate than whole-table statistics.
- Aging data out becomes a metadata operation: at the 7-year boundary
  `DROP TABLE` is instant and reclaims space. Restore and PITR improve too,
  since most volume sits in cold archive partitions on cheaper storage.

### Negative

- **Lookups by `id` alone must scan every partition.** This is the real cost: the
  ~61% of reads fetching one payment by id currently use a single index; without
  a `created_at` predicate they fan out across the hot window. Mitigation: `id`
  is a prefixed, time-ordered identifier, so ledger-service derives a bounded
  `created_at` range from it and always includes it in the predicate. That is a
  code change, and the largest piece of work here.
- **Operational surface grows.** The partition-creation job can fail, and its
  failure mode is an insert error on the money path. It gets a page, not a ticket
  — see `observability-standards.md`.
- **DDL becomes more expensive** — adding a column or index touches every
  partition — and **cross-partition uniqueness is not enforceable** beyond the
  partition key. The migration itself is long: dual-write plus full-history
  backfill is weeks of soak, in the money path.

### Neutral

Retention obligations are unchanged (7 years for customer transaction records)
and the payments-service schema is untouched; see `payment-service.md`.

## Alternatives considered

**Do nothing.** Rejected; the trend lines are clear, and doing this under duress
after an incident would be worse.

**Partition by `tenant_id` (hash or list).** Rejected. It spreads write load but
does nothing for the dominant problem — old data being indistinguishable from new
to vacuum and to the planner. It also does not help age data out, and it would
make Finance's month-range queries touch every partition instead of one.

**Weekly partitions.** Rejected. Roughly 1,250 partitions at the 24-month
boundary versus 24. Planning time grows with partition count, the benefit over
monthly is marginal at our volume, and monthly matches how Finance queries.

**Move history to a separate archive service or warehouse.** Rejected for now. It
solves the size problem but introduces a second system of record for money — a
far larger correctness risk than the one we are fixing. Worth revisiting as its
own ADR if archive query volume grows materially.

**`pg_repack` plus aggressive autovacuum tuning.** Rejected as insufficient; it
buys perhaps a year without changing the shape of the problem.

## References

- `payment-service.md` — payments-service schema and the payment state machine.
- `deployment-runbook.md` — expand/contract migration policy and the rule against
  destructive changes in the same release.
- `observability-standards.md` — alerting for the partition-creation job.
- `data-retention.md` — 7-year retention, 35-day backups, 7-day PITR.
- ADR-0003: Choice of PostgreSQL 16 as the platform datastore.

## Revision History

| Date | Author | Change |
|---|---|---|
| 2026-01-30 | Dev Shah | Draft circulated for review |
| 2026-02-24 | Dev Shah | Accepted; added the composite primary key and the id-derived range predicate mitigation |
| 2026-06-05 | Priya Raman | Recorded the rejected weekly-partition option with the partition-count figures |
