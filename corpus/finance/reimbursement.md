# Expense Reimbursement Procedure

**Owner:** Dana Okafor (Controller) · **Audience:** every employee who files an
expense report, and every manager who approves one

expense-policy.md tells you **what** Northwind pays for and up to how much. This
document tells you **how** to get the money — what to type into NorthPay Expense,
who approves it, when it pays, and what to do when it comes back rejected.

Nothing here restates a spending limit. If you are looking for the meal cap, the
hotel cap, the mileage rate, or the receipt threshold, they are all in
expense-policy.md and that is deliberately the only place they live.

---

## Before you start

You will need:

- Receipt images for anything over the receipt threshold in expense-policy.md
- The business purpose, in a sentence you would be comfortable reading aloud in
  an audit
- The cost centre, if you are charging something other than your own team
- For client entertainment: the full attendee list
- For any pre-approval the policy requires — business class airfare, entertainment
  over $500 — the approval itself, as a file

The single biggest cause of delay is a report submitted without the business
purpose filled in. It is one sentence and it is the field auditors sample.

---

## Step by step in NorthPay Expense

**NorthPay Expense** is the only accepted channel. Emailed receipts, spreadsheets,
and direct messages to Finance are not expense reports and will be redirected
here, which costs you a payment run.

### 1. Create the report

One report per trip, or one report per calendar month for ad-hoc spend. Do not
file a separate report per receipt — a 14-line trip report is one approval; 14
single-line reports are 14 approvals and 14 chances for one to stall.

Name it so a human can identify it later: `Denver customer visit 2026-05-12` beats
`Expenses`.

### 2. Add each expense line

Every line needs all of these. NorthPay will not let you submit without them, and
the validation exists because we tried the honour system first.

```yaml
expense_line:
  date:              2026-05-13        # the date the money was spent
  merchant:          "Union Station Grill"
  amount:            64.20
  currency:          USD
  category:          meals-travel      # picked from the list, not typed free-form
  business_purpose:  "Dinner while onsite for the customer implementation review"
  cost_centre:       ENG-PLATFORM      # defaults to your own team
  attendees:         []                # required and non-empty for entertainment
  receipt:           receipt_20260513_union.jpg
  billable_to_customer: false
```

Category matters more than people think. It drives the general ledger account the
expense lands in, and a miscategorised line has to be reclassified by hand during
close. If you cannot find the right category, pick the closest and say so in the
business purpose; do not invent one.

### 3. Attach receipts

Receipt image standards — these are enforced, and a report can be rejected on
image quality alone:

| Requirement | Detail |
|---|---|
| Format | JPG, PNG, PDF, or HEIC |
| Maximum size | 10 MB per file |
| Legibility | Merchant name, date, currency, and total must be readable without zooming past 200% |
| Completeness | The whole receipt, including the bottom. Cropped totals are the most common rejection |
| Itemisation | Restaurant bills and hotel folios must be itemised, not just the card slip |
| Orientation | Right way up. NorthPay will rotate, but reviewers will not |

Email a receipt to `receipts@northwind.example` from your Northwind address and
it lands in your NorthPay inbox unattached, ready to drag onto a line. Doing this
on the day of the expense is the single habit that makes month-end painless.

Lost a receipt? File the missing-receipt attestation in NorthPay rather than
skipping the line. The attestation is a form, not an email.

### 4. Submit

Submitting locks the report for editing and routes it to your approval chain. You
will get a confirmation with a report ID of the form `EXP-2026-014882`. Quote
that ID in any question to Finance; without it we are searching by name and date.

---

## Approval routing and SLAs

| Stage | Who | Target | What happens if it stalls |
|---|---|---|---|
| Manager approval | Your direct manager | **3 business days** | Auto-reminder at day 3, escalation to their manager at day 5 |
| Finance review | Accounts Payable | **2 business days** | Only for reports meeting a review trigger, below |
| Payment | AP, on the next run | See the payment calendar | — |

Managers approve for policy fit and business justification. Finance reviews for
coding, documentation, and tax treatment. They are different questions, which is
why both happen.

**Finance review is triggered when any of these is true:**

- The report total exceeds **$1,000**
- Any single line exceeds **$1,000**
- The report contains client entertainment of any amount
- The report contains a missing-receipt attestation
- The report was submitted after the policy deadline in expense-policy.md
- The report contains an out-of-policy line with an attached exception approval
- The submitter's manager is also the submitter — self-approval is never valid,
  and these route to the next level up automatically

Reports under $1,000 with clean documentation and no trigger go straight from
manager approval into the next payment run.

Managers: approving is not a formality. You are attesting that the spend served a
business purpose you knew about. If you would not have authorised it in advance,
reject it now rather than complaining about it at budget review.

---

## Payment runs

Approved reimbursements pay out on **the 15th of the month and the last business
day of the month**. Two runs, every month, no exceptions and no off-cycle runs
for convenience.

- If the 15th falls on a weekend or a company holiday, the run moves to the
  **preceding** business day.
- The **cut-off is 17:00 Central on the business day before the run.** Fully
  approved by cut-off means paid on that run; approved at 17:05 means the next
  one.
- Payment is by ACH to the bank details on your employee record. Funds typically
  appear within 1-2 business days of the run.
- Reimbursements pay separately from payroll and appear as their own deposit,
  described as `NORTHWIND REIMB`.

Worked example: you submit on 8 May, your manager approves on 11 May, the report
is over $1,000 so Finance reviews it on 13 May. It is fully approved before the
14 May cut-off and pays on the 15 May run. Had Finance's review slipped to 15
May, it would pay on the last-business-day run instead.

To change your bank details, update your employee record — not NorthPay, and
never by emailing Finance. **Finance will never action a change of bank details
received by email or chat**, including from someone who appears to be you. That
rule has no exceptions and is not negotiable regardless of urgency.

---

## Rejections and resubmission

A rejected report comes back with a reason code and a comment. It is not a
judgement about you; roughly one report in eight is returned, and most are a
missing sentence.

| Code | Meaning | Fix |
|---|---|---|
| `R01` | Receipt missing or unreadable | Reattach a legible image, or file the missing-receipt attestation |
| `R02` | Business purpose absent or generic | Write what the spend achieved; "travel" is not a purpose |
| `R03` | Over policy limit, no exception attached | Attach the approval, or reduce the claim to the limit |
| `R04` | Wrong category or cost centre | Recode the line |
| `R05` | Duplicate of an already-submitted line | Delete the duplicate; check for a duplicate report first |
| `R06` | Past the submission deadline | Attach the required late approval per expense-policy.md |
| `R07` | Attendees missing on entertainment | Name every attendee and their organisation |
| `R08` | Personal expense on a corporate card | Remove the line and repay the company; see below |

Fixing a rejection re-opens the report for editing. **Resubmission restarts the
approval SLA**, so a rejection on day 2 of manager review does not carry over
your queue position. Edit only the rejected lines; approved lines stay approved
unless you touch them.

If you disagree with a rejection, reply in the report comments first. Escalation
path is manager, then Dana Okafor. Do not delete and re-file the report under a
new ID to get a different reviewer — it is transparent in the audit log and it
resets your clock.

### Personal spend on a corporate card

It happens; the wrong card comes out of the wallet. Flag the line as personal in
NorthPay, and the amount is deducted from your next reimbursement or, if you have
none pending, invoiced to you. Do the flagging yourself. A personal charge found
by Finance rather than declared by the cardholder is handled as a policy matter,
not an administrative one.

---

## Foreign currency

Claim in the currency you actually paid. Do not convert by hand — every manual
conversion we have seen has been wrong in the claimant's disfavour.

How NorthPay converts:

1. **Corporate card transactions** are booked at the amount the card issuer
   settled in USD. That is the real cost to Northwind and it supersedes any rate
   table.
2. **Personal card and cash transactions** are converted at the published daily
   rate for the **expense date**, loaded into NorthPay each morning.
3. If the rate on your personal card statement differs materially from the
   converted amount — more than **2%** — attach the statement line and claim the
   statement amount. Card issuer FX fees on a personal card used for business
   travel are reimbursable when evidenced this way.
4. Cash withdrawn from an ATM abroad is claimed as the individual purchases you
   made with it, not as the withdrawal. The ATM fee itself is reimbursable.

Dublin-based employees are reimbursed in EUR into a euro account and see the
mirror image of this: USD spend converts at the published daily rate for the
expense date. The payment run calendar is the same.

Receipts in a language other than English do not need translation, but write what
the expense was in the business purpose field. The reviewer may not read the
receipt.

---

## Special cases

**Travel advances.** Available where a large personal outlay would be a hardship,
for example a long-haul fare booked months ahead. Request through
`finance-ap@northwind.example` before booking. Advances are reconciled against an
expense report within 30 days of the trip ending; an unreconciled advance blocks
further advances.

**Paying a vendor directly.** For conference registrations, large deposits, or
anything you would rather not carry on a personal card, Finance can pay the
vendor. This is a purchase, not an expense, and it follows the procurement
approval chain rather than this procedure.

**Recharging a customer.** Set `billable_to_customer: true` and name the customer
in the business purpose. Billable travel must be permitted by that customer's
contract — check with the account owner, not with Finance.

**Leaving Northwind.** File your final expense report before your last working
day. After your NorthPay access is deactivated, a claim has to be reconstructed
by AP from paper, and it will miss at least one payment run.

---

## Who to contact

| Question | Contact |
|---|---|
| How do I file this / NorthPay not working | `finance-ap@northwind.example` |
| Is this within policy | expense-policy.md first, then `finance-policy@northwind.example` |
| Where is my money | `finance-ap@northwind.example` with your `EXP-` report ID |
| Corporate card lost, stolen, or compromised | Freeze it in the issuer app, then `finance-ap@northwind.example` |
| Policy exception | Your manager, then per the exception table in expense-policy.md |
| Anything you suspect is fraud | Dana Okafor directly |

AP staffing is heaviest in the two business days before each payment run. A
question asked the day before cut-off may not get answered before it.

## Revision History

| Date | Author | Change |
|---|---|---|
| 2025-06-24 | Dana Okafor | First written version of a procedure that had been tribal knowledge |
| 2025-11-18 | Dana Okafor | Added rejection reason codes, the $1,000 Finance review trigger, and approval SLAs |
| 2026-02-14 | Dana Okafor | Documented FX handling for personal cards and the never-change-bank-details-by-email rule |
