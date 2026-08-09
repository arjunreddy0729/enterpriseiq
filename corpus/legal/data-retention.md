# Data Retention and Deletion Policy

**Owner:** Rina Malhotra (Privacy Counsel) · **Approver:** Tom Lindqvist (General Counsel)
**Audience:** All Northwind employees and contractors. No exceptions — if you create, copy, or export company data, this policy applies to you.

Northwind Systems handles shipment and payment data on behalf of mid-market
shippers. Some of that data is regulated, some contractually committed, and
some simply expensive to keep. This policy sets the single retention schedule
for the whole company so that individual teams do not have to guess.

Two ideas do most of the work here:

1. **Keep data for as long as we have a reason, and not one day longer.**
   "We might want it someday" is not a reason.
2. **Deletion is a system behaviour, not a person's chore.** If a retention
   period is not enforced by automation, it is not really a retention period.

If a system you own is retaining data outside this schedule, email
rina.malhotra@northwind.example rather than quietly fixing it — we usually need
to record the drift before it is corrected.

---

## 1. Retention schedule

This table is authoritative. Where a system's configuration disagrees with
this table, the table wins and the system is a defect.

| Data category | Retention period | Legal / business basis | Enforced by |
|---|---|---|---|
| Customer transaction records (payments, ledger entries, shipment records) | 7 years | Financial recordkeeping and tax obligations; revenue recognition support under ASC 606; dispute and chargeback defence | ledger-service and payments-service archival jobs |
| Application logs | 90 days | Operational debugging and incident reconstruction | Loki retention configuration |
| Security audit logs (authentication events, privilege changes, admin actions) | 13 months | Security investigation; SOC 2 evidence over a full audit period plus one month | Security log pipeline |
| Database backups | 35 days | Disaster recovery. Point-in-time recovery covers the most recent 7 days | Automated backup lifecycle |
| Corporate email and chat | 24 months from the message date | Business continuity; balanced against the cost of indefinite discovery exposure | Mail and chat platform retention rules |
| HR records for current employees | Duration of employment | Employment administration | People Operations systems |
| HR records after termination | 7 years from the termination date | Employment claim limitation periods; payroll and benefits recordkeeping | People Operations systems |
| Recruiting records for candidates not hired | 12 months from the final decision | Defence against discrimination claims; candidate re-engagement | Applicant tracking system |
| Vendor contracts and diligence files | 7 years after contract termination | Contract limitation periods; audit support (see vendor-policy.md) | Legal contract repository |
| Marketing contact records | Until the contact unsubscribes, plus 30 days | Consent-based processing | Marketing platform |

### Notes on specific categories

**Customer transaction records.** The 7-year clock starts at the date of the
transaction, not the end of the customer relationship. A customer who leaves
Northwind in 2026 still has 2024 transaction records retained into 2031.

**Application logs.** 90 days is short on purpose. Application logs are the
category most likely to contain incidental personal data that nobody planned
for — a shipping address in an error message, an email address in a stack
trace. Engineering must not extend Loki retention for a single service without
Privacy Counsel sign-off.

**Security audit logs.** 13 months rather than 12 so that an auditor examining
a full calendar year still has the earliest events available at the time of
fieldwork.

---

## 2. What counts as personal data

Any information that identifies or could reasonably be linked to a living
individual. At Northwind that most commonly means:

- Names, email addresses, and phone numbers of customer staff and of
  recipients on shipments
- Delivery addresses and contact details on shipment records
- Payment instrument metadata (last four digits, issuing country, expiry) —
  Northwind does not store full card numbers; those stay with the PSP
- Employee and candidate records
- Authentication identifiers and session metadata in security audit logs

If you are unsure whether a field is personal data, assume it is and ask.

---

## 3. Deletion requests

Northwind fulfils verified deletion requests for personal data **within 30
days of verification**. The clock starts when identity verification completes,
not when the request first arrives — but we do not use verification as a
stalling tactic, and verification should normally complete within 5 business
days.

### 3.1 Intake

Requests arrive through three channels:

| Channel | Typical requester | Routed to |
|---|---|---|
| privacy@northwind.example | Individual data subject | Privacy Counsel |
| Customer support ticket | Customer acting for its own end user | Support, then Privacy Counsel |
| Contractual request from a customer's DPO | Enterprise customer | Legal |

Every request is logged in the privacy request register on the day it is
received, whichever channel it came through. Do not action a deletion request
you receive directly — forward it to privacy@northwind.example and let the
register capture it.

### 3.2 Verification procedure

Verification is proportionate to the sensitivity of the data, not maximal by
default. The standard sequence:

1. **Confirm the requester's relationship to the data.** Are they the data
   subject, an authorised agent, or a customer acting as controller? If a
   customer is the controller, Northwind acts on the customer's instruction
   and does not independently verify the end user.
2. **Match the identifier.** Confirm the email address or account identifier
   in the request resolves to records we actually hold.
3. **Challenge from a known channel.** For direct data-subject requests, send
   a confirmation to the email address already on the record. Do not accept a
   new contact address supplied in the request body as proof of anything.
4. **Escalate anomalies.** Requests naming a third party, requests arriving
   with unusual urgency, or requests that would delete records under legal
   hold go to Privacy Counsel before any action.

Record the verification steps taken in the register entry. "Verified" without
a note is not a verification.

### 3.3 Fulfilment

Once verified, Privacy Counsel raises a deletion work item with the owning
service team. Deletion covers:

- Primary records in the owning service's PostgreSQL 16 database
- Derived copies in analytics and reporting stores
- Search and cache layers
- Any export the requester's data appears in that is still within its own
  retention window

Deletion does **not** cover records we are legally required to keep. Where a
transaction record must be retained for the full 7 years, we retain the record
and remove or truncate the personal fields that are not required for the
financial purpose. The register entry must say which of the two happened.

Confirmation goes back to the requester once the owning team confirms
completion, and always inside the 30-day commitment.

---

## 4. Legal holds

A legal hold suspends deletion. It always wins.

When Northwind reasonably anticipates litigation, receives a regulatory
inquiry, or opens an investigation where the underlying data is evidence, the
General Counsel issues a written legal hold notice. From that moment:

- **Automated deletion is paused** for the systems and date ranges named in
  the notice. Sofia Reyes' team implements the pause; Legal defines the scope.
- **Manual deletion is prohibited** for anyone who receives the notice. That
  includes clearing your own mailbox, emptying chat history, or deleting a
  local export.
- **Pending deletion requests are held**, not refused. The requester is told
  their request is subject to a legal obligation and will be completed when
  the obligation lapses.
- **The hold is released in writing** by the General Counsel. Nobody else can
  release it, and holds do not expire on their own.

Acknowledge a hold notice within 2 business days. If you are unsure whether
data you control falls inside a hold's scope, ask before you touch it — the
cost of over-preserving for a week is trivial next to the cost of spoliation.

Legal holds arising from a security incident follow the additional process in
security-incident-legal-playbook.md.

---

## 5. Backups and the deletion caveat

Deleting a record from a live database does not delete it from backups taken
before the deletion. This is a physical property of backups, not a policy
choice, and we state it plainly rather than pretending otherwise.

Northwind's position:

- Backups are retained **35 days**, with point-in-time recovery over the most
  recent **7 days**.
- We do not surgically edit backups. Rewriting a backup to remove one record
  destroys its integrity as a recovery artefact and its value as evidence.
- A deleted record therefore persists in backup media for at most 35 days
  after deletion, and then ages out automatically.
- Backups are access-controlled and are only restored for disaster recovery or
  under an authorised investigation. They are never used to re-populate
  production with data that was deliberately deleted.
- If a restore does reintroduce deleted records, the owning team must re-run
  the deletion against the restored environment within 5 business days and
  notify Privacy Counsel.

We disclose this behaviour to customers and data subjects when we confirm a
deletion. Do not tell a requester that their data is "gone everywhere
immediately" — it is not, and saying so creates a misrepresentation we then
have to correct.

---

## 6. Data residency

EU customer data stays in the Dublin region (`eu-west-1`). This is a
contractual commitment in our EU customer agreements and a design constraint
on every service, not a deployment preference.

Practical consequences:

- EU-scoped records are written to EU-resident data stores and their backups
  remain in region.
- Cross-region replication of EU customer data to US regions is not permitted.
  If a service needs EU data in a US analytics store, the answer is to
  aggregate in region and export the aggregate, not to copy the rows.
- Support and engineering staff outside the EU may access EU data for a
  legitimate support purpose; access is logged in the security audit log and
  retained 13 months. Access is not the same as storage, and remote access
  does not breach residency — bulk export does.
- Any new vendor that would store EU customer data outside the Dublin region
  requires Privacy Counsel approval before contracting. See vendor-policy.md.

Refunds, chargebacks, and EU card traffic routed through our fallback PSP are
in scope for residency review like any other EU processing.

---

## 7. Responsibilities

| Role | Responsibility |
|---|---|
| Service owners (engineering) | Implement and verify retention automation for their own data stores |
| Sofia Reyes (EM, Infrastructure) | Backup lifecycle, log retention configuration, legal hold implementation |
| Rina Malhotra (Privacy Counsel) | Owns this policy; runs the privacy request register; approves retention exceptions |
| Tom Lindqvist (General Counsel) | Issues and releases legal holds |
| Marcus Webb (Director, People Operations) | HR and recruiting record retention |
| Dana Okafor (Controller) | Financial record retention and audit support |
| Every employee | Do not create shadow copies; honour holds; report drift |

---

## 8. Exceptions

Retention exceptions are granted in writing by Privacy Counsel, for a stated
purpose, with an expiry date no more than 12 months out. An exception request
must say what data, what period, why the standard period is insufficient, and
who will delete the data when the exception lapses. Exceptions without an
expiry date are not granted. Recurring exceptions are a signal that the
schedule is wrong — if you request the same one twice, propose an amendment.

---

## Revision History

| Date | Author | Change |
|---|---|---|
| 2025-04-22 | Rina Malhotra | Initial policy; consolidated retention periods previously spread across team wikis |
| 2025-11-10 | Rina Malhotra | Added the backup deletion caveat and the 7-day PITR detail after a customer diligence question |
| 2026-05-18 | Tom Lindqvist | Clarified legal hold acknowledgement window and release authority; added recruiting record retention |
