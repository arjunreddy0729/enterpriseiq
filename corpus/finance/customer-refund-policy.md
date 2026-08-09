# Customer Refund Policy

**Owner:** Dana Okafor (Controller) · **Audience:** all employees, and
specifically Support and Sales, who are the people customers ask ·
**Companion documents:** payment-service.md for the technical refund flow,
revenue-recognition.md for the accounting effect

This is what we will and will not refund, who approves it, and how long it takes.
It is written to be quoted to a customer. If you are on a call and need one
sentence, it is this:

> **Eligible charges can be refunded within 30 days of the invoice date, and
> approved refunds are processed within 10 business days.**

Everything else is the detail behind that sentence.

---

## Eligibility window

**Refund requests must be made within 30 days of the invoice date.**

The window runs from the **invoice date**, not the payment date, not the charge
date on the customer's card statement, and not the date the customer noticed. A
customer who pays a 1 March invoice on 25 March has until 31 March, not 24 April.

- The date the customer *requests* the refund is what counts, not the date we get
  around to approving it. A request logged on day 29 is in the window even if it
  is approved on day 34.
- Requests must be logged in the billing system to count. A request that lives
  only in a support agent's memory did not happen. Log it the same day, even if
  you expect to decline it.
- Outside 30 days, the answer is no by default. Exceptions exist and are covered
  under Approvals; they are decided by Finance, never by the person taking the
  request.

Do not tell a customer their request is outside the window without checking the
invoice date yourself. Customers routinely quote the wrong date, in both
directions.

---

## What is eligible

| Situation | Eligible | Notes |
|---|---|---|
| **Unused subscription time** after an approved early termination | Yes | Prorated by day; see Proration |
| **Duplicate charge** — the same invoice paid or charged twice | Yes | Always refunded, no 30-day limit, no approval debate |
| **Billing error** by Northwind — wrong tier, wrong seat count, wrong rate applied | Yes | Corrected to what the customer should have been billed |
| Charge on a cancelled subscription after the cancellation effective date | Yes | Treated as a billing error |
| Subscription cancelled within the first 30 days of an initial term | Case by case | Requires Sales and Finance agreement; often handled as a credit |
| Downgrade mid-term where the contract permits it | Yes, prorated | Most contracts do not permit it; check first |

Duplicate charges deserve their own note. They are the one category we refund
without argument, without the 30-day test, and without escalation. If a customer
was charged twice for the same invoice, refund it and investigate afterwards.
Making a customer prove a duplicate is bad practice and it is also bad for us,
because duplicates are usually a defect on our side.

---

## What is not eligible

| Situation | Refundable | Why |
|---|---|---|
| **Usage-based payment processing fees** | **No** | The service was performed. The transaction was processed, and our own costs were incurred at that moment |
| **Professional services already delivered** | **No** | The work was done. Undelivered scope on an open engagement is a different matter and can be refunded |
| Subscription time already consumed | No | The platform was available and used |
| Overage charges for volume actually shipped | No | Same reasoning as usage fees |
| Dissatisfaction after the 30-day window with no billing defect | No | Route to the account team as a renewal conversation, not a refund |
| Charges under a contract in a dispute or collections process | Not until resolved | Refunds are not a negotiating instrument mid-dispute |
| Amounts already credited, where the credit remains available | No | We do not refund the same money twice in two forms |

**Say the usage-fee rule early in the conversation.** It is the most common source
of a customer feeling misled, and it is much easier to state up front than to
walk back after someone has been led to expect a full refund of a large invoice
that is mostly processing fees. The phrasing that works: "Your subscription
portion is refundable on a prorated basis; the transaction processing fees are
for payments we already processed and settled, so those aren't refundable."

There is one narrow exception. Where a payment processing fee was charged on a
transaction that **failed** or was itself the result of a Northwind defect, the
fee is a billing error and is refundable. That is an error correction, not a
refund of a delivered service.

---

## Approval path

| Refund amount | Approver |
|---|---|
| Duplicate charge, any amount | Support lead, no further approval |
| Up to $1,000 | Support lead |
| $1,000 – $25,000 | Controller (Dana Okafor) |
| Above $25,000 | VP Finance (Ken Whitaker) |
| Any refund outside the 30-day window | Controller, regardless of amount |
| Any refund of usage-based payment fees | Controller, regardless of amount |
| Any refund tied to a contract dispute or a threatened claim | Controller **and** General Counsel (Tom Lindqvist) |

Rules around the ladder:

- **Nobody approves their own request.** An account executive cannot approve a
  refund for their own account, and a support agent cannot approve their own
  escalation.
- **Approvals are recorded in the billing system** against the refund record,
  with the reason. An approval in a chat thread is not an approval; it is a
  conversation about one.
- **Do not promise a refund you cannot approve.** "I'll request that for you and
  come back with an answer today" is always available and is never wrong. "Yes,
  we'll refund that" from someone without authority creates a commitment we
  usually end up honouring at a worse price than if we had said it properly.
- Refunds that would take a customer's net paid amount below zero for the period
  need Controller review whatever the ladder says. They are almost always a sign
  of a coding error somewhere upstream.

---

## Processing time

**Approved refunds are processed within 10 business days.** In most cases it is
much faster — the refund is initiated the same day or the next — but 10 business
days is the commitment we make and the number to quote.

What "processed" means: Northwind has initiated the refund and the funds have
left our control. It does not mean the money has appeared in the customer's
account. After we process it, the customer's bank or card issuer adds its own
time, typically 3-5 business days and occasionally up to two statement cycles for
a card refund. Explain both halves, in that order, or you will get a follow-up on
day 11.

| Stage | Typical | Commitment |
|---|---|---|
| Request logged to approval decision | 1-2 business days | — |
| Approval to refund initiated | Same or next business day | Within 10 business days of approval |
| Initiated to funds visible to the customer | 3-5 business days | Depends on the issuer, not on us |

Refunds are not paid on the internal expense payment run calendar. That calendar
in reimbursement.md is for employee reimbursements and has nothing to do with
customer refunds; people confuse the two constantly.

---

## Partial refunds and proration

Most refunds are partial. The arithmetic is boring and worth getting right,
because customers check it.

**Subscription proration is by day**, using the actual number of days in the
term. Not by month, not by 30-day month.

```text
refund = subscription_fee × (unused_days ÷ total_term_days)
```

Worked example. A customer pays $24,000 for a 365-day subscription starting
1 January 2026. Termination is approved effective 30 June 2026, having used 181
days.

```text
unused_days   = 365 − 181 = 184
daily_rate    = 24,000 ÷ 365       = 65.7534...
refund        = 24,000 × (184/365) = 12,098.63
```

The refundable amount is **$12,098.63**. Not $12,000, and not "half."

If that same customer also paid $9,400 in usage-based payment processing fees
over the six months, none of it is refundable, and the total refund stays
$12,098.63. This is exactly the conversation the eligibility section is warning
you about.

Other proration rules:

- **Implementation fees are not prorated** and are not refunded once onboarding
  has been delivered. The work happened.
- **Annual prepayment discounts are recovered.** A customer who took a 15% annual
  prepayment discount and terminates at month six has their refund computed
  against the equivalent monthly rate, which reduces it. Say this before the
  customer sees the number, not after.
- **Refunds do not extend or reinstate service.** The termination date is the
  termination date.
- Rounding is to the cent, half up. Nothing is rounded to a whole dollar to make
  it look tidier.

### Refund versus credit

Where a customer is staying with us, a **credit against the next invoice** is
often faster and preferred by the customer, and it avoids a card refund that may
take two statement cycles. Offer it as an option; never impose it. If the
customer wants their money back, they get their money back — an unwanted credit
is how a billing complaint becomes a churn conversation.

Credits expire at the end of the contract term unless the contract says
otherwise, and unused credit at termination is refundable if the underlying
charge was.

---

## How a refund reaches the customer

Refunds return to the **original payment method**. We do not refund a card
payment by bank transfer, and we do not send a refund to a different account
than the one that paid, even at the customer's request. That rule is a fraud
control and there is no exception path that Support can invoke.

| Original payment | Refund route | Customer sees |
|---|---|---|
| Card | Back to the same card | A credit line on the card statement, usually 3-5 business days after processing |
| ACH or bank transfer | Back to the originating account | A deposit, typically 1-3 business days |
| Card no longer valid or account closed | Bank transfer, after verification | Longer — verification is required and it is not optional |

On the customer's statement, a card refund appears as a separate credit, not as a
reversal of the original charge. The original charge stays visible. Customers
reading a statement often expect the charge to disappear and report the refund as
missing when it has not; check for a separate credit line before escalating.

A refund of a payment made in a currency other than the invoice currency is
refunded in the currency of the original payment, and the customer may see a
small difference from what they paid because of exchange rate movement between
the two dates. That difference is the issuer's, not ours, and we do not top it up.

---

## How this connects to payments-service

The mechanics live in payment-service.md; what matters to a non-engineer is the
shape of the thing.

- A refund is executed against the **original payment**, which must have reached
  the `captured` or `settled` state. An authorised-but-not-captured payment is
  **voided**, not refunded — a different operation, and it is why some very recent
  charges resolve almost immediately.
- The refund goes back through **the same payment service provider that captured
  the payment**. A payment captured on Cardinal is refunded on Cardinal; EU card
  traffic that went to Halcyon is refunded on Halcyon. We cannot switch providers
  mid-lifecycle, which is why "just refund it another way" is not available.
- A fully refunded payment ends in the `refunded` state, which is terminal.
  Partial refunds reduce the refundable balance and multiple partials against one
  payment are supported.
- Refund calls require the `payments:refund` scope, which is deliberately
  separate from ordinary write access. Being able to take a payment does not
  imply being able to give it back.
- Every refund write carries an `Idempotency-Key`, so a retried request cannot
  double-refund. If a refund appears not to have gone through, **do not submit a
  second one** — check the refund record first. A double refund is real money
  leaving the company and is far harder to recover than it was to send.

If a refund fails technically, it becomes an engineering matter and follows
incident-response.md. Payment loss is a SEV1. Do not re-attempt a failed refund
by hand while an incident is open.

---

## Recording and reporting

Every refund is recorded against the original invoice with an amount, a reason
code, an approver, and a free-text note. Reason codes matter more than they look
— they drive the monthly refund analysis and they are how we find the defects
that cause refunds in the first place.

| Code | Use for |
|---|---|
| `DUP` | Duplicate charge |
| `ERR` | Northwind billing error |
| `TERM` | Approved early termination, unused subscription time |
| `DOWN` | Contractually permitted mid-term downgrade |
| `SLA` | Service-level credit issued as a refund |
| `GOOD` | Goodwill, outside normal eligibility, Controller approved |

Finance reconciles approved refunds, processed refunds, and the accounting
entries monthly; the treatment on the books is in revenue-recognition.md. A
refund approved late in a month usually settles in the next one, which is normal
and handled by an accrual — it is not a sign that anything is stuck.

`GOOD` volume is reviewed quarterly. Consistent goodwill refunding for a
recurring cause is a signal to fix the cause, not to keep approving refunds
faster.

## Revision History

| Date | Author | Change |
|---|---|---|
| 2025-08-05 | Dana Okafor | Replaced the ad-hoc refund practice with a written policy and approval ladder |
| 2025-12-01 | Dana Okafor | Added proration worked example, reason codes, and the credit-versus-refund guidance |
| 2026-05-06 | Dana Okafor | Clarified the 30-day window runs from the invoice date, and documented the original-payment-method rule |
