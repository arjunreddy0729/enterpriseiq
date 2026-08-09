# Revenue Recognition Policy

**Classification: Confidential — Finance only.**
**Owner:** Dana Okafor (Controller) · **Approver:** Jordan Kim (CFO) ·
**Standard:** ASC 606, *Revenue from Contracts with Customers*

Northwind sells a logistics and embedded-payments platform to mid-market
shippers. Two revenue streams, two very different recognition patterns, and
almost every error we make comes from applying one stream's pattern to the other.

> **The one-sentence version.** Subscription revenue is recognised **ratably over
> the subscription term**. Usage-based payment fees are recognised **in the month
> incurred**. Everything below is the detail behind those two sentences.

This policy binds the accounting. It does not describe what we tell customers
about refunds — that is customer-refund-policy.md — nor how we buy things, which
is procurement-thresholds.md.

---

## 1. Scope and revenue streams

| Stream | What it is | Pattern | Typical share of revenue |
|---|---|---|---|
| Platform subscription | Access to the Northwind platform for a stated term, tiered by shipment volume band | Ratable over the term | Majority |
| Usage-based payment fees | Per-transaction fees on payments processed through the platform | Point in time, month incurred | Material and growing |
| Implementation and onboarding | One-time setup, data migration, integration assistance | See section 5 | Small |
| Professional services | Scoped consulting on a statement of work | As delivered | Small |
| Overage | Shipment volume above the contracted band | Month incurred | Small |

Anything that does not fit one of these five rows goes to the Controller before
it is booked. New commercial constructs invented by Sales during a quarter-end
negotiation are the single largest source of restatement risk we carry.

---

## 2. The five steps, as we apply them

### Step 1 — Identify the contract

A contract exists when it is approved by both parties, rights and payment terms
are identifiable, it has commercial substance, and **collection is probable**.

At Northwind, in practice: the countersigned order form plus the master
subscription agreement is the contract, and an unsigned quote is not, no matter
how confident the account executive sounds. A click-through acceptance of our
online terms is also a contract. Collectibility is assessed at inception against
the credit review on file — a customer already 60+ days past due on an existing
balance is not "probable," and revenue is deferred until cash is received.
Contracts with the same customer entered into at or near the same time and
negotiated as a package are **combined** into one contract; structuring a single
deal as three order forms does not create three contracts.

### Step 2 — Identify the performance obligations

Our standard subscription contains these candidate obligations:

| Item | Distinct? | Treatment |
|---|---|---|
| Platform access for the term | Yes | Single obligation, satisfied over time |
| Standard support and updates | No | Not distinct from platform access; bundled |
| Payment processing per transaction | Yes | Variable consideration, satisfied at the point of transaction |
| Implementation and onboarding | Usually **not** | See section 5 |
| Named professional services engagement | Yes, if scoped and separately saleable | Recognised as delivered |
| Training beyond standard onboarding | Yes | Recognised as delivered |

Platform access is a **series** of daily services that are substantially the same
and have the same pattern of transfer, so it is treated as a single performance
obligation satisfied over time rather than as 365 separate obligations.

### Step 3 — Determine the transaction price

The fixed subscription fee is the starting point. Then:

- **Variable consideration** — usage-based payment fees and volume overage — is
  *not* estimated and included at inception. It qualifies for the **series
  allocation exception**: the fee relates specifically to the transfer of that
  month's service, so it is recognised in the period the underlying usage occurs.
  This is why usage fees are a month-incurred item, and it is the accounting
  reason, not a convenience.
- **Ramped pricing** across the term is levelled: a contract charging $4,000 a
  month in year one and $6,000 in year two is recognised at the average monthly
  rate over the combined term, not as billed.
- **Discounts and credits** reduce the transaction price. A service-level credit
  is a reduction of revenue, never a marketing expense.
- **Significant financing component**: not present in our standard contracts.
  Annual-in-advance billing over a 12-month term falls inside the practical
  expedient and is ignored.
- **Amounts collected for third parties**: we are the principal for payment
  processing fees charged to our customer. Interchange and PSP costs we pay are
  cost of revenue, not a reduction of revenue.

### Step 4 — Allocate the transaction price

Allocate to each distinct performance obligation on **relative standalone selling
price (SSP)**. SSP is set annually by Finance from observable list pricing and
realised transaction data, refreshed each January. The SSP file is maintained by
the Controller and is the sole authority — do not derive an SSP from one deal.
Where a contract bundles a discounted subscription with professional services,
the discount is allocated proportionately across all obligations unless there is
observable evidence it belongs to one of them. There almost never is.

### Step 5 — Recognise revenue when (or as) the obligation is satisfied

| Obligation | Timing | Measure of progress |
|---|---|---|
| Platform subscription | Over time | Straight line, by day, over the subscription term |
| Usage-based payment fees | Point in time | The month the transaction is processed |
| Overage | Point in time | The month the overage occurs |
| Professional services | Over time | Hours delivered against the scoped total |
| Non-distinct implementation | Over time | Straight line over the subscription term |

---

## 3. Subscription revenue — the ratable rule

Subscription revenue is recognised **ratably over the subscription term**, on a
daily basis, beginning when access is provisioned or the term start date,
whichever is later.

- A 12-month subscription of $120,000 starting 14 March recognises $120,000 ÷ 365
  per day, giving a partial month at each end.
- Billing frequency is irrelevant. Annual-in-advance, quarterly, and monthly
  billing of the same contract produce identical revenue and different deferred
  balances.
- Revenue **does not** start at signature. It starts at provisioning. The gap
  between the two is the most common cut-off error we find.
- A term that ends mid-month ends mid-month. The daily convention exists so we
  never have to argue about rounding to a month boundary.

---

## 4. Usage-based payment fees — the month-incurred rule

Payment processing fees are recognised **in the month the underlying transaction
is processed**, regardless of when we invoice or collect.

The mechanics at close:

1. Usage is extracted from the billing system for the calendar month.
2. Any transactions processed in the final days of the month but not yet invoiced
   are **accrued** as unbilled receivable, and reverse when invoiced.
3. Refunded transactions reduce fee revenue in the month the refund is processed,
   not in the original month. See section 9.
4. Usage revenue is never deferred and never straight-lined. A customer with a
   heavy December and a quiet January produces exactly that shape in revenue.

Because these fees are recognised as incurred, they carry no deferred revenue
balance. If you see usage fees sitting in deferred revenue, something has been
miscoded — usually an annual "processing credit" prepayment, which *is* a
contract liability and should be released as the credits are consumed.

---

## 5. Implementation and onboarding fees

Default treatment: **implementation is not a distinct performance obligation.**
Our onboarding does not transfer a good or service the customer could benefit
from on its own — it is setup activity that makes the platform usable. So:

- The implementation fee is added to the transaction price and recognised
  **ratably over the subscription term**, alongside the subscription.
- Costs of performing implementation are expensed as incurred, except where they
  qualify as costs to fulfil a contract, assessed case by case with the
  Controller.

The exception: where a customer buys a genuinely scoped, separately saleable
engagement — a custom integration a third party could equally have performed —
that **is** distinct and is recognised as delivered. Documenting why it is
distinct is the deal desk's job at signature, not the accountant's job at close.

**Amortisation period for the fee is the expected customer relationship, not the
initial term, where the contract renews and the setup is not repeated.** For our
current book we use 36 months for this purpose, reviewed annually.

---

## 6. Contract modifications

Modifications are frequent — expansions, downgrades, early renewals, term
extensions. Three treatments, and picking the wrong one moves revenue between
periods.

| Modification | Test | Treatment |
|---|---|---|
| Adds distinct services at their standalone selling price | Both true | **Separate contract.** Account for it independently; leave the original alone |
| Adds distinct services **not** at SSP | Remaining services are distinct | **Prospective.** Terminate the old contract, combine unrecognised consideration with the new, recognise over the remaining term |
| Changes scope or price of the same, not-distinct obligation | Single obligation continues | **Cumulative catch-up.** Adjust revenue in the modification period for the effect on progress to date |

In practice most Northwind modifications are mid-term seat or volume-band
expansions, priced off the same rate card at a discount, and land in the
**prospective** bucket. The recomputed monthly rate applies from the modification
effective date forward; prior months are not restated. Early renewals signed
before the current term expires are a modification, not a new contract, when they
extend the same platform obligation — recognising the new contract's revenue from
its signature date rather than from the extended term start is a real error we
have made and now specifically test for.

---

## 7. Deferred revenue mechanics, with a worked example

Deferred revenue is a **contract liability**: cash or a receivable recognised
ahead of the performance obligation being satisfied. Split current and
non-current at each reporting date; anything releasing beyond 12 months is
non-current.

### Worked example

Contract `ORD-2026-0417`. Subscription of $120,000 for 12 months beginning
1 April 2026, billed annually in advance. Implementation fee of $18,000, not
distinct, amortised over the 36-month expected relationship. Payment terms net
30. Usage fees billed monthly in arrears.

**1 April — invoice issued, nothing yet performed:**

```text
Dr  Accounts receivable                            138,000
    Cr  Deferred revenue — subscription                    120,000
    Cr  Deferred revenue — implementation                   18,000
```

**28 April — cash received:**

```text
Dr  Cash                                           138,000
    Cr  Accounts receivable                                138,000
```

**30 April — recognise one month of subscription and implementation:**

```text
Dr  Deferred revenue — subscription                 10,000
    Cr  Subscription revenue                                10,000     # 120,000 / 12

Dr  Deferred revenue — implementation                  500
    Cr  Subscription revenue                                   500     # 18,000 / 36
```

**30 April — recognise April usage fees, invoiced in May:**

```text
Dr  Unbilled receivable                              4,820
    Cr  Payment fee revenue                                  4,820
```

Note what does **not** happen: the usage fee never touches deferred revenue. It
goes straight to revenue with an unbilled receivable, and the receivable clears
when the May invoice is raised.

**Balances at 30 April 2026:**

| Account | Balance | Note |
|---|---|---|
| Deferred revenue — subscription, current | 110,000 | Releases over the remaining 11 months |
| Deferred revenue — implementation, current | 5,500 | 11 months × $500 |
| Deferred revenue — implementation, non-current | 12,000 | 24 months × $500 |
| Unbilled receivable | 4,820 | Clears on the May invoice |

### Deferred revenue roll-forward

Prepared monthly, by contract, and reconciled to the general ledger. The
roll-forward is the primary control over subscription revenue:

```text
Opening deferred revenue
  + Amounts billed in the period
  − Revenue recognised in the period
  ± Modifications
  − Refunds and credits released
  = Closing deferred revenue
```

An unexplained difference between the roll-forward and the GL balance blocks the
close. It does not get a plug, and it does not get "investigated next month."

---

## 8. Monthly close timeline

Working days are counted from the first business day after month end. Revenue is
not the whole close, but it is on the critical path for most of it.

| Day | Activity | Owner |
|---|---|---|
| WD1 | Billing system cut-off confirmed; usage extract pulled and reconciled to the platform's own transaction counts | Revenue accountant |
| WD1 | New and modified contracts for the month collected from the deal desk | Revenue accountant |
| WD2 | Subscription schedules updated: new starts, terminations, modifications, provisioning dates confirmed | Revenue accountant |
| WD2 | Usage revenue booked; unbilled receivable accrual posted | Revenue accountant |
| WD3 | Deferred revenue roll-forward prepared and tied to the GL; refunds and credits applied per section 9 | Revenue accountant |
| WD4 | Controller review: revenue by stream, variance to forecast, manual entries over $10,000, and a 10-contract testing sample biased toward modifications | Dana Okafor |
| WD5 | Flux analysis and close package drafted | Dana Okafor |
| WD6 | CFO review and sign-off; books closed for the period | Jordan Kim |

Quarter-end adds two days for the SSP refresh check, the collectibility review,
and the disaggregated revenue disclosure. Year-end adds the full remaining
performance obligation (RPO) disclosure.

**Once the books are closed, the period is closed.** A late expense report or a
late invoice lands in the following period. This is why expense-policy.md is
unsentimental about its submission deadline.

---

## 9. Refunds, credits, and their effect on revenue

Customer-facing eligibility rules — the 30-day window from the invoice date, what
qualifies, the approval path, the 10-business-day processing commitment — are in
customer-refund-policy.md. Finance does not restate them here; we account for
their result.

Accounting treatment:

| Situation | Treatment |
|---|---|
| Refund of unused subscription time, current period | Reduce subscription revenue in the current period; release the related deferred revenue |
| Refund of unused subscription time, prior period already recognised | Reduce revenue in the **current** period. We do not restate a closed period for a routine refund |
| Duplicate charge | Not revenue at all. Reverse against the receivable or refund the cash; it never should have been revenue |
| Billing error | Correct in the current period; if material to a closed period, escalate to the Controller before booking |
| Usage-based payment processing fees | **Non-refundable** as a matter of policy. Where one is nonetheless approved as a goodwill exception, it reduces payment fee revenue in the month the refund is processed |
| Professional services already delivered | Not refundable under policy. An approved exception reduces services revenue in the current period |
| Service-level credit | Reduction of revenue, applied in the period the credit is granted. Not a marketing or support expense |

Two standing rules:

1. **A refund is a revenue event, not a cash event.** The cash movement runs
   through payments-service and the PSP; the revenue effect is booked from the
   approved refund record, and the two are reconciled at close rather than one
   being derived from the other.
2. **Refund accruals.** At each month end, approved refunds not yet processed are
   accrued. Because the customer-facing commitment is to process approved refunds
   within 10 business days, a refund approved on the 28th will usually settle in
   the following month, and the accrual keeps it in the right period.

The monthly refund reconciliation ties three populations: refunds approved in the
billing system, refunds processed in payments-service, and refund entries in the
ledger. Where they disagree, the payments-service record is the authority on what
cash moved, and the approval record is the authority on what should have moved.

## Revision History

| Date | Author | Change |
|---|---|---|
| 2025-04-01 | Dana Okafor | Initial ASC 606 policy adopted for FY25 |
| 2025-09-16 | Dana Okafor | Added the implementation fee 36-month amortisation basis and the modification decision table |
| 2026-01-30 | Jordan Kim | Approved the revised close calendar and the refund accrual requirement |
