# Third-Party Vendor Management Policy

**Owner:** Tom Lindqvist (General Counsel) · **Contributors:** Rina Malhotra (Privacy Counsel), Dana Okafor (Controller)
**Audience:** Anyone who wants to buy, trial, or renew a third-party product or service.

Every vendor we plug into the platform inherits some of our customers' trust,
and a few of them inherit customer personal data. This policy describes how a
vendor gets approved, what Legal will and will not sign, and what happens when
we stop using them.

The short version: **no vendor touches customer PII without a security
review, a signed DPA, and a current SOC 2 Type II report.** Everything else
here is detail around that sentence.

Budget and purchase-approval thresholds are a Finance matter and live in
procurement-thresholds.md. This policy governs risk, contract terms, and
signature authority. You will usually need both.

---

## 1. When this policy applies

It applies whenever Northwind money, Northwind data, or the Northwind name is
committed to an outside party: paid SaaS tools including single-seat corporate
card purchases; free tools, if any Northwind data leaves our environment to
use them; professional services firms, contractors, and staffing agencies;
infrastructure providers and anything running inside `northwind-prod`; and
payment service providers and their subprocessors. It does not apply to
one-off purchases of goods with no data component — monitors, office supplies,
catering — which are governed by procurement-thresholds.md alone.

> A free tier is not an exemption. "It's free" tells us about cost, not about
> where the data goes.

---

## 2. Risk tiers

Every vendor is assigned a tier at intake. The tier determines how much
diligence is required and how long it takes.

| Tier | Applies when | Required diligence | Typical elapsed time |
|---|---|---|---|
| **1 — Critical** | Vendor stores or processes customer personal data, handles payment flows, or sits in the production path such that its failure degrades payments-service or shipment-service availability | Full security review, signed DPA, current SOC 2 Type II reviewed annually, subprocessor disclosure, business continuity questions, Privacy Counsel approval, General Counsel signature | 3-4 weeks |
| **2 — Elevated** | Vendor stores Northwind confidential information or employee personal data, but not customer personal data, and is not in the production request path. Examples: HR systems, code analysis tooling, contract repositories | Security review, DPA if any personal data is involved, SOC 2 Type II or an accepted alternative attestation, Legal review of terms | 2 weeks |
| **3 — Standard** | Vendor receives only internal, non-confidential information. Examples: a design tool for public marketing assets, a scheduling utility | Intake questionnaire, standard terms review, no DPA required | 3-5 business days |
| **4 — Minimal** | No Northwind data of any kind leaves our environment. Rare, and frequently mis-claimed | Intake questionnaire only | 1-2 business days |

**Tiering is done by Legal, not by the requester.** Requesters routinely
under-tier because a lower tier is faster. If the intake answers and the
requested tier disagree, Legal's assessment governs.

---

## 3. Intake questionnaire

Every vendor request starts with the intake questionnaire, filed by the
Northwind employee who wants the vendor (the "sponsor"). The sponsor stays
accountable for the vendor for as long as we use them. It captures:

```yaml
vendor_intake:
  vendor_legal_name:        # full legal entity, not the brand name
  sponsor:                  # requesting employee
  business_owner:           # who owns the relationship after signature
  what_it_does:             # two sentences, plain language
  data_shared:
    customer_personal_data: true|false
    employee_personal_data: true|false
    payment_data:           true|false
    northwind_confidential: true|false
  data_location:            # regions where data is stored at rest
  eu_customer_data:         true|false
  production_path:          true|false   # does an outage affect our SLOs?
  annual_cost_usd:
  contract_term_months:
  auto_renewal:             true|false
  existing_alternative:     # do we already own a tool that does this?
  security_contact:         # vendor-side security or trust contact
```

Two answers do most of the routing work. `customer_personal_data: true` forces
Tier 1 and pulls in Privacy Counsel. `eu_customer_data: true` triggers a data
residency check against data-retention.md — EU customer data stays in the
Dublin region (`eu-west-1`), and a vendor who cannot honour that will not be
approved for EU processing.

---

## 4. Security review

Mandatory for Tier 1 and Tier 2, and for any vendor that will touch customer
personal data no matter what tier the sponsor proposed. It is run jointly by
Legal and an engineering reviewer nominated by Sofia Reyes, and covers at
minimum:

| Area | What we look for |
|---|---|
| Authentication | Support for SSO; how service credentials are issued and rotated |
| Encryption | TLS in transit; encryption at rest; who holds the keys |
| Access control | Least privilege; admin action logging; support access to tenant data |
| Data location | Storage regions, replication targets, backup locations |
| Retention and deletion | Can they delete on request, and within what window |
| Subprocessors | Full list, with locations and functions |
| Incident handling | Notification commitment to us, and how fast |
| Recovery | RTO/RPO commitments, backup testing cadence |

Findings are recorded as blocking or non-blocking. Blocking findings must be
resolved, contractually mitigated, or formally accepted in writing by the
General Counsel before signature. "The vendor says they're working on it" is
not a resolution unless it is written into the contract with a date.

### SOC 2 Type II

Tier 1 and Tier 2 vendors provide a **current SOC 2 Type II report**, which
Legal reviews **annually**. Type I is not accepted for Tier 1 — a point-in-time
attestation tells us nothing about whether controls actually operated.

The annual review is not a filing exercise: the reviewer reads the exceptions
section, checks the report period is contiguous with the previous one,
confirms the scope still covers the service we actually use, and records any
carve-outs. A report more than 15 months old makes the vendor non-compliant
and triggers a remediation conversation with the business owner.

---

## 5. Data Processing Agreement

Any vendor that processes personal data on Northwind's behalf signs a DPA
before data flows. Not after the pilot. Not "once we're past the trial." Our
standard DPA requires:

- Processing only on documented instructions from Northwind
- Confidentiality obligations on vendor personnel
- Technical and organisational security measures, described specifically
- **Prior written notice of new subprocessors**, with a right to object
- Assistance with data subject requests, including deletion, on a timeline
  that lets us meet our own 30-day commitment (see data-retention.md)
- Security incident notification to Northwind **without undue delay**, fast
  enough that we can meet our own commitment to notify affected customers
  within 72 hours of confirmation
- Deletion or return of personal data at termination
- Audit rights, ordinarily satisfied by the SOC 2 Type II report
- Data location commitments, including the Dublin region for EU customer data

Vendors frequently propose their own DPA. That is acceptable if it covers the
list above. Rina Malhotra reviews vendor-paper DPAs; do not accept one on the
sponsor's own judgement.

---

## 6. Subprocessor disclosure — both directions

**Inbound.** Tier 1 vendors give us a complete subprocessor list at contract
signature and notify us in writing before adding one. On notice, Legal has 30
days to object; an unobjected subprocessor is deemed accepted, so notices go
to legal@northwind.example immediately and are not left in an inbox.

**Outbound.** Northwind is itself a processor for our customers, and our own
subprocessors must be disclosed to them. Our published subprocessor list
includes our payment service providers — Cardinal, and Halcyon for EU card
traffic — along with our infrastructure and communications providers. Adding a
Tier 1 vendor that processes customer personal data means updating that public
list and giving our customers advance notice. Build that lead time into the
project plan; it is the step most often discovered late.

---

## 7. Hand-off from Finance procurement

Procurement and vendor risk run in parallel, not in sequence, but they gate
each other at the end.

1. Sponsor files the intake questionnaire (this policy) **and** starts the
   purchase request (procurement-thresholds.md). Do not wait for one to finish
   before starting the other; Tier 1 diligence is the long pole.
2. Legal tiers the vendor and opens the security review.
3. Finance confirms budget and routes the spend approval chain: manager below
   $5,000; director $5,000-$25,000; VP Finance $25,000-$100,000; CFO plus
   General Counsel above $100,000. Ken Whitaker is the VP Finance approver in
   the $25,000-$100,000 band.
4. Legal negotiates terms, DPA, and subprocessor language.
5. **Neither side signs alone.** Finance does not release a purchase order
   until Legal marks diligence complete, and Legal does not sign until Finance
   confirms the spend is approved.
6. The executed contract, the DPA, the SOC 2 report, and the security review
   findings are filed together in the Legal contract repository. Diligence
   filed nowhere is diligence that did not happen.

Renewals follow the same path in miniature: confirm the tier is still right,
refresh the SOC 2 review, re-check subprocessors, and re-run the spend
approval at the current annual value.

---

## 8. Signature authority

| Annual contract value | Required signatures |
|---|---|
| Under $100,000/year | Authorised business signatory per the Finance approval chain |
| **$100,000/year and above** | **General Counsel and CFO** — Tom Lindqvist and Jordan Kim |

No other signature binds Northwind at or above $100,000/year. Clicking "I
agree" on an online order form is a signature, and accepting a click-through
renewal that pushes annual value over the threshold without General Counsel
and CFO sign-off is a policy violation even though it felt like a checkbox.

Legal records every renewal notice deadline in the contract repository at
signature, and the business owner is reminded 60 days ahead. A renewal that
happens because nobody watched the calendar is treated as an unplanned
commitment and reported to Finance.

---

## 9. Ongoing monitoring

| Activity | Cadence | Owner |
|---|---|---|
| SOC 2 Type II review | Annual | Legal |
| Subprocessor list reconciliation (Tier 1) | Annual | Privacy Counsel |
| Business owner confirms the vendor is still in use | Annual | Sponsor |
| Access review for vendors with production access | Twice yearly | Infrastructure |
| Vendor security incident follow-up | As it happens | Legal + Security |

A vendor that suffers a security incident affecting Northwind data is handled
under security-incident-legal-playbook.md, and its tier and contract are
reassessed once the incident closes.

---

## 10. Offboarding and data return

Stopping payment is not offboarding. A vendor relationship is only closed when
the data is dealt with. Checklist, owned by the business owner and confirmed
by Legal:

- [ ] Written termination notice served in line with the contract's notice period
- [ ] Auto-renewal cancelled and confirmed in writing
- [ ] Export of any Northwind data we need for our own retention obligations,
      taken before access is revoked
- [ ] Written confirmation from the vendor that Northwind data has been deleted
      or returned, per the DPA, within the contractual window
- [ ] Vendor accounts, API credentials, and SSO integrations disabled
- [ ] Any vendor access into `northwind-prod` or `northwind-staging` removed
      and the removal verified by Infrastructure
- [ ] Public subprocessor list updated if the vendor appeared on it
- [ ] Contract file closed with the termination date and deletion confirmation

Contract and diligence files are retained for 7 years after termination per
data-retention.md. Retaining the paperwork is not the same as retaining the
data — the vendor still deletes ours.

---

## Revision History

| Date | Author | Change |
|---|---|---|
| 2025-03-19 | Tom Lindqvist | Initial policy replacing the ad-hoc vendor approval thread |
| 2025-09-30 | Rina Malhotra | Added subprocessor disclosure obligations in both directions; tightened DPA requirements |
| 2026-04-14 | Tom Lindqvist | Documented the Finance hand-off, added the offboarding checklist and auto-renewal handling |
