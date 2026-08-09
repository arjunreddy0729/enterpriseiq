# Procurement and Purchase Approval

**Classification: Confidential — Finance only.** This document contains internal
approval limits and signature authority. Do not forward it outside Finance; if a
budget owner needs to know their limit, tell them their limit.

**Owner:** Dana Okafor (Controller) · **Escalation:** Ken Whitaker (VP Finance) ·
**Above $100,000:** Jordan Kim (CFO) with Tom Lindqvist (General Counsel)

This policy governs committing Northwind money to an outside party. It does not
govern employee travel and personal reimbursement, which is expense-policy.md and
reimbursement.md. It runs in parallel with, and does not replace, the vendor risk
process in vendor-policy.md.

---

## 1. The approval chain

Approval is required **before** the commitment is made, where "commitment" means
a signature, a click-through acceptance, a verbal yes to a sales rep, or a
corporate card charge. Approval obtained afterwards is a ratification, and
ratifications are reported to the Controller monthly.

| Purchase value | Approver |
|---|---|
| Under $5,000 | Budget owner's manager |
| $5,000 – $25,000 | Director of the owning function |
| $25,000 – $100,000 | VP Finance (Ken Whitaker) |
| Above $100,000 | CFO (Jordan Kim) **and** General Counsel (Tom Lindqvist), both |

Reading the boundaries: the bands are inclusive at the lower end. A purchase at
exactly $25,000 sits in the director band; at $25,000.01 it is VP Finance. A
purchase at exactly $100,000 is VP Finance; above $100,000 it needs both CFO and
General Counsel. Legal applies the same $100,000/year test to contract signature
authority — see vendor-policy.md — so at that level you are collecting two
signatures regardless of which document you start from.

Rules that are not negotiable:

- **Approval is cumulative, not substitutive.** A VP Finance approval on a
  $60,000 purchase does not remove the requirement for the budget owner and the
  director to have agreed it belongs in their plan.
- **Nobody approves their own purchase.** If the budget owner is also the natural
  approver, the request routes one level up.
- **Nobody approves a purchase that benefits them personally.** Declare it and
  step out.
- **Approvers may not delegate downward.** A director cannot approve a $40,000
  purchase because the VP is on holiday. Delegation goes to a peer or upward, and
  is recorded in writing for a named period.

---

## 2. What counts as one purchase

This is where most policy breaches originate, and almost all of them are
accidental.

**A single purchase is the total value of everything a vendor will be paid under
one commercial decision, measured over the whole committed term.**

Concretely:

| Scenario | Value that determines the approver |
|---|---|
| One-time hardware order, $8,400 | $8,400 — director band |
| SaaS at $3,000/month on a 12-month contract | **$36,000** — VP Finance band, not $3,000 |
| SaaS at $3,000/month, month-to-month, no commitment | Annualised: **$36,000**. Cancellability does not reduce the commitment for approval purposes |
| 3-year contract at $45,000/year, paid annually | **$135,000** — CFO and General Counsel |
| Statement of work, $60,000, phased over two quarters | $60,000 — VP Finance |
| Four separate $4,500 orders to one vendor in a quarter | **$18,000** — director band. See below |

### Aggregation

Splitting a purchase to stay under a threshold is a policy violation whether or
not it was intended as one. Finance aggregates by vendor and by rolling
12 months, and reviews the aggregation report at each month-end close.

Aggregate when the purchases are to the same vendor or its affiliates, within a
rolling 12-month window, and for related goods or services or under a common
master agreement. Do not aggregate genuinely unrelated purchases from a large,
diversified supplier — a laptop order and a conference sponsorship from the same
conglomerate are two decisions. When unsure, aggregate and get the higher
approval. It costs a day.

**Renewals and expansions aggregate with the underlying contract.** Adding 40
seats to an existing tool at $30,000/year, on top of an existing $80,000/year
commitment, is a $110,000/year relationship and needs CFO and General Counsel —
not the director who owns the $30,000 increment.

### Multi-year contracts

Approve on **total contract value**, not annual value. A 3-year deal is a
three-year commitment even when it is cancellable, because cancellation is a
negotiation, not a right. Where a contract has a genuine unilateral termination
right with under 90 days' notice, note it on the request; Finance approves on the
committed minimum plus one notice period, and records the reduced basis.
Auto-renewing contracts are valued at the renewal term, not the remainder of the
current one.

---

## 3. Purchase requests and purchase orders

### When a PO is required

| Situation | PO required |
|---|---|
| Any commitment of $5,000 or more | Yes |
| Any recurring or subscription commitment, any value | Yes |
| Any professional services engagement | Yes |
| Any vendor that will be paid by invoice rather than card | Yes |
| One-off card purchase under $5,000 from an approved vendor | No |

**No PO, no payment.** AP will not pay an invoice that cannot be matched to an
open PO where one was required. Vendors learn this quickly; the people it
surprises are internal.

### The request

Filed in NorthPay Expense under Purchase Requests. Required fields:

```yaml
purchase_request:
  requester:            sofia.reyes@northwind.example
  budget_owner:         sofia.reyes@northwind.example
  cost_centre:          INFRA
  vendor_legal_name:    "..."            # legal entity, not the brand
  description:          "..."            # what we are buying and why
  amount_usd:           42000
  basis:                total_contract_value
  term_months:          12
  auto_renewal:         true
  renewal_notice_days:  30
  budget_line:          "FY26 infrastructure tooling"
  in_approved_budget:   true
  vendor_intake_filed:  true             # see vendor-policy.md
  touches_customer_pii: false
  alternatives_considered: "..."         # including tools we already own
```

`in_approved_budget: false` is allowed and is not a rejection — it means the
request is unbudgeted and must be approved one band higher than its value would
otherwise require. An unbudgeted $20,000 purchase goes to VP Finance, not the
director.

`alternatives_considered` exists because the most common finding in the annual
spend review is that we bought a second tool to do something a tool we already
own does adequately.

### Three-way match

AP pays on a match of purchase order, receipt of goods or services, and invoice.
Tolerances before an exception is raised: **5% or $500, whichever is lower**, on
the invoice against the PO. Anything outside tolerance goes back to the budget
owner for a PO amendment, which re-runs approval **if the new total crosses a
band boundary**.

---

## 4. Hand-off to Legal

Procurement approves **whether we can afford it**. Legal approves **whether we
can safely sign it**. Both are required and they run at the same time. The
authoritative description of vendor diligence — risk tiers, security review,
DPAs, SOC 2 Type II — is vendor-policy.md, and Finance does not second-guess it.

The interlock, from Finance's side:

1. Requester files the purchase request **and** the vendor intake questionnaire
   on the same day. Legal's Tier 1 diligence runs three to four weeks and is
   always the long pole; a purchase request that waits for it will miss the
   quarter.
2. Finance validates budget, aggregation, and the approval band, and routes the
   spend approval.
3. **Finance does not release a purchase order until Legal marks diligence
   complete.** A PO issued against an incomplete vendor file is withdrawn.
4. Legal does not sign until Finance confirms the spend approval.
5. Above $100,000/year both the CFO and the General Counsel sign. This is the
   same signature requirement Legal states; it is one rule described in two
   places, not two rules.

Reminders for the Finance side of the conversation: any vendor touching customer
personal data requires a security review, a signed DPA, and a current SOC 2
Type II report reviewed annually — if the vendor refuses any of the three there
is no price at which we buy it, and Finance should stop working the deal rather
than negotiate the number down. EU customer data stays in the Dublin region, and
a vendor who cannot commit to that is not approvable for EU processing whatever
the commercial terms. A free tier that processes Northwind data still needs the
vendor process even though there is no spend for us to approve.

---

## 5. Software and SaaS renewals

SaaS is where money leaks quietly. Auto-renewal means a decision nobody makes
becomes a commitment everybody honours.

### The 60-day renewal review

**Every subscription is reviewed 60 days before its renewal date.** Finance
generates the renewal calendar monthly from the contract register and sends each
budget owner their upcoming renewals. Legal separately reminds the business owner
at the same 60-day mark; the two reminders are intentional redundancy.

The budget owner returns four answers, in writing, before the 30-day mark:

| Question | Why it matters |
|---|---|
| Are we still using it? | Roughly one renewal in six covers a tool nobody has opened in a quarter |
| How many seats are actually active? | Seat counts ratchet up and never come down on their own |
| Has the price changed? | Uplift clauses of 5-8% are common and are frequently unnoticed |
| Does anything we already own do this? | Consolidation is easiest at renewal and impossible mid-term |

No answer by the 30-day mark escalates to the budget owner's director. Still no
answer at the notice deadline and Finance serves non-renewal — we will take the
disruption of losing a tool nobody defended over an unexamined multi-year
commitment.

### Renewal approval

A renewal is a fresh purchase and re-runs the approval chain **at the current
annual value**, including any uplift. A tool that renewed last year at $23,000
and renews this year at $27,500 has moved from the director band to VP Finance.

Renewal notice deadlines are recorded in the contract register at signature.
Missing one and auto-renewing into an unwanted term is treated as an unplanned
commitment: it is reported in the month-end close package with the budget owner
named. This is not punitive theatre — the number is real and it has to be
explained somewhere.

### Standing rules on subscriptions

- No new subscription is approved with a term over 12 months at first purchase.
  Buy a year, prove it, then negotiate multi-year with a real usage baseline.
- Auto-renewal is acceptable; auto-renewal with a notice period over 60 days is
  not, without VP Finance approval.
- Price uplift caps are negotiated at signature. Ask for CPI-capped, settle for a
  stated percentage, never accept "at then-current list price."
- Per-seat tools are reconciled against the HR headcount file quarterly. Seats
  for departed employees are the most reliable saving available to us.

---

## 6. Budget owner responsibilities

A budget owner is the person accountable for a cost centre — typically a director
or above, occasionally a manager for a small discretionary line. Being a budget
owner means:

- **Own the forecast.** Submit a quarterly re-forecast for your cost centre,
  including known renewals, within five business days of quarter end.
- **Approve within your band, and no further.** Approving above your band is a
  finding at audit even when the purchase itself was sensible.
- **Know your renewals.** The renewal calendar is sent to you; unread is not an
  excuse and is not treated as one.
- **Explain variance over 10% or $10,000** against plan at the monthly business
  review, whichever is smaller.
- **Keep the vendor list honest.** Confirm annually that every vendor charged to
  your cost centre is still in use — this is the same annual confirmation
  vendor-policy.md asks the business owner for, and one answer satisfies both.
- **Do not commit against next year's budget.** A commitment signed in December
  for a January start is a commitment this fiscal year unless the contract term
  and the payment both begin in the new year.
- **Delegate properly.** One named delegate during absence, filed with Finance,
  for a named period, and never below the band the purchase requires.

---

## 7. Emergency purchases

An emergency is a situation where waiting for normal approval causes material
harm: a production incident requiring immediate vendor capacity, a security
response, a legal deadline, a business continuity event. Commercial urgency
manufactured by a vendor's quarter-end discount is **not** an emergency and
Finance will say so plainly.

The procedure:

1. **Get verbal or written approval from the approver the value requires**, or
   from any VP if that person is unreachable. One approver, one sentence: what,
   how much, why now. During a SEV1 the Incident Commander may commit spend up to
   $25,000 without prior approval.
2. **Commit only what the emergency needs.** Emergency approval covers the
   immediate need, not a 12-month contract signed in the same conversation.
3. **File the purchase request within 2 business days**, marked as an emergency,
   naming the approver and the time of approval.
4. **Vendor diligence still happens**, retrospectively and immediately. If the
   vendor will touch customer personal data, Legal is engaged the same day, and
   an emergency does not create an exception to the DPA and SOC 2 Type II
   requirements. It changes the order of operations, not the requirements.
5. **Finance reviews every emergency purchase at month-end close.** A pattern of
   emergencies from one team is a planning conversation, not a procurement one.

Emergency purchases above $100,000 still require the CFO and the General
Counsel. There is no threshold above which urgency substitutes for signature
authority.

---

## 8. What Finance watches

Reported at each month-end close, to the Controller and VP Finance:

| Report | What it catches |
|---|---|
| Vendor spend aggregation, rolling 12 months | Split purchases and quiet growth |
| POs opened without a completed vendor file | Interlock failures with Legal |
| Invoices paid without a PO | Process bypass, usually via corporate card |
| Approvals recorded below the required band | Delegation gone wrong |
| Emergency purchases | Whether the exception is becoming the rule |
| Auto-renewals that occurred without a 60-day review | Unmanaged commitment |
| Corporate card spend at software vendors | Shadow SaaS |

The last one deserves a note. Recurring card charges to software vendors under
$5,000 are the most common route around this policy and are entirely visible in
the card feed. Finance reviews that feed monthly and converts anything recurring
into a proper purchase request.

## Revision History

| Date | Author | Change |
|---|---|---|
| 2025-05-27 | Dana Okafor | Initial policy; set the four approval bands and the PO requirement |
| 2025-10-01 | Dana Okafor | Added aggregation rules and the 60-day renewal review after the FY25 spend review |
| 2026-04-02 | Ken Whitaker | Clarified band boundaries, unbudgeted requests, and the emergency purchase procedure |
