# Security Incident Legal Playbook

**Classification: RESTRICTED — Legal only.** Do not forward, quote, or
summarise this outside the Legal team. It describes how we establish and
maintain attorney-client privilege; circulating it undermines what it describes.
**Owner:** Tom Lindqvist (General Counsel) · **Deputy:** Rina Malhotra (Privacy Counsel)

This playbook covers Legal's role when a security incident may involve personal
data. The engineering response — detection, severity assignment, mitigation,
the Incident Commander model, and the postmortem — is in incident-response.md.

Our single hardest external commitment: **security incidents involving
personal data are reported to affected customers within 72 hours of
confirmation.** Everything below is organised around meeting that commitment
while saying only things that are true.

---

## 1. Engagement triggers

Legal is engaged, without waiting to be asked, when any of these is true:

| Trigger | Engage |
|---|---|
| A SEV1 or SEV2 is declared and personal data may be in scope, or any incident touches payment flows or the ledger | Immediately |
| Any incident, at any severity, where personal data may have been accessed, exfiltrated, or altered by an unauthorised party | Immediately |
| Suspected compromise of credentials or of the JWKS signing keys | Immediately |
| A vendor or subprocessor notifies us of an incident on their side | Same business day |
| Regulator, journalist, or researcher contact about a suspected exposure | Immediately |
| Suspected insider misuse of customer data | Immediately, and before the individual is confronted |

The Incident Commander pages Legal through the on-call escalation path. One
Legal responder is on call at a time: the General Counsel by default, Privacy
Counsel as deputy. Legal's acknowledgement follows the engineering ack targets
— 15 minutes for SEV1, 30 minutes for SEV2 — and Legal joins the incident
bridge rather than working over email.

**Legal does not run the incident.** The IC does. Legal's job is privilege,
preservation, notification analysis, and the communications gate. If Legal
starts directing remediation, both jobs get done badly.

---

## 2. The first hour

In order, executed by the Legal responder.

1. **Join the bridge and identify yourself as Legal.** Ask the IC for the
   working hypothesis, the severity, and whether personal data is in scope.
2. **Start the privileged file.** Open a new matter in the restricted Legal
   workspace. Every note Legal takes from now goes there, not the channel.
3. **Assert privilege over the investigation.** Post the privilege notice
   (section 3) into the incident channel and confirm the Scribe has seen it.
4. **Issue the preservation directive.** Section 4 — the step most often
   delayed, and application logs are only retained 90 days.
5. **Start the notification clock sheet.** Record first detection, Legal
   engagement, and confirmation. These timestamps will be examined later.
6. **Assess whether external counsel and the cyber carrier are needed.** Bias toward notifying early; a precautionary notice is cheap to retract.
7. **Close the communications gate.** Tell the Communications Lead that no
   external statement — status page, customer email, support macro, sales
   talking points — goes out without Legal approval until the gate reopens.

Nothing on this list requires knowing what happened. Do all of it while the
facts are still moving.

---

## 3. Privilege

The purpose of privilege here is narrow and legitimate: it lets counsel obtain
candid facts in order to advise Northwind on its legal obligations. It is not
a device for hiding the incident, and it does not stop us telling customers
the truth.

**Privileged:** investigation work performed at counsel's direction for the
purpose of legal advice — forensic analysis we commission, external counsel
work product, Legal's notes and analysis, notification decision memos, draft
regulatory assessments. **Not privileged**, and do not pretend otherwise: the
underlying facts, system logs, the incident timeline, the blameless postmortem,
ordinary engineering communications, and anything created before Legal was
engaged. Facts are never privileged because a lawyer later reads them.

Operating rules:

- Forensic engagements run **through counsel**: retained by external counsel,
  scoped in writing to supporting legal advice, reports delivered to counsel.
- Privileged material lives in the restricted Legal workspace with named access, never attached to the incident ticket.
- Mark privileged documents on every page: `PRIVILEGED AND CONFIDENTIAL —
  ATTORNEY-CLIENT COMMUNICATION — PREPARED AT THE DIRECTION OF COUNSEL`
- Do not mark everything. Over-marking is the fastest way to lose a privilege
  argument, because it shows the label was applied reflexively.
- Keep the postmortem clean. The blameless postmortem required for SEV1 and
  SEV2 within 5 business days is a factual engineering document, is not
  privileged, and must not contain legal analysis or liability speculation.

The notice Legal posts into the incident channel at engagement:

> Legal is engaged on this incident. Analysis performed at Legal's request for
> the purpose of legal advice belongs in the restricted Legal workspace, not
> here. Keep this channel for operational facts and actions. Do not speculate
> in writing about cause, fault, or liability. Do not delete anything.

---

## 4. Evidence preservation and legal hold

Preservation is issued in writing by the General Counsel and implemented by
Sofia Reyes' team. It follows the legal hold mechanics in data-retention.md,
with incident-specific scope. Standard scope for a personal-data incident:
application logs covering the incident window, pinned before the 90-day
retention expires; security audit logs for the affected principals and
services (13-month retention gives more room, but pin them anyway); database
backups covering the incident window, exempted from the 35-day lifecycle;
container images and deployed manifests from the relevant Argo CD revisions;
affected node and pod state, snapshotted rather than recycled; and the
incident channel, bridge recordings, the IC's timeline, and relevant email and
chat for named individuals.

Cautions learned the expensive way:

- **Say "pause deletion", not "delete nothing ever".** An unscoped hold that
  freezes company-wide retention indefinitely creates its own discovery problem.
- **Preservation before remediation, where they conflict.** Rebuilding a
  compromised node destroys the evidence of how it was compromised; if the
  fastest fix is destructive, ask the IC for a snapshot first.
- **Watch the 90-day log window.** In slow-burn incidents discovered late, the
  earliest relevant application logs may already be near expiry on day one.
- **Hold notices are acknowledged within 2 business days**, and released only in writing by the General Counsel.

---

## 5. Notification analysis

Two separate questions, often confused. Answer them separately.

### 5.1 Customer notification — the 72-hour commitment

Northwind reports security incidents involving personal data to affected
customers **within 72 hours of confirmation**.

"Confirmation" means Legal and the IC jointly conclude, on the evidence
available, that personal data was involved. It is not the moment we know the
full scope, the root cause, or the exact record count. Waiting for
completeness is the failure mode this commitment exists to prevent.

Record in the notification memo: the time of confirmation and who made the call;
what is known, suspected, and unknown; the set of affected customers and how it
was derived; whether EU customer data in the Dublin region is in scope; and whether updates will follow, on what cadence.

Notice goes to each affected customer's designated security or privacy contact
under their agreement. Some contracts specify a shorter window or a named
recipient, and where a contract commits us to something faster than 72 hours,
the contract wins — read the actual contracts. If confirmation is genuinely
uncertain at hour 60, notify on what we believe and say so plainly: "we are
still investigating" is defensible, silence is not.

### 5.2 Regulatory notification

A separate analysis, run by Privacy Counsel in parallel — never as a follow-on
to the customer notice. It covers:

| Question | Why it matters |
|---|---|
| Are we controller or processor for the affected data? | For customer personal data Northwind is ordinarily a processor; the customer notifies its regulator and we support them. For employee data we are the controller. |
| Which jurisdictions are implicated? | Driven by where the affected individuals are, not where the servers are |
| Is EU customer data involved? | Dublin region data pulls in EU supervisory authority obligations and shortens the timeline |
| What triggers apply in US states where affected individuals reside? | State breach notification statutes vary in threshold, timing, and content |
| Do payment card obligations apply? | Card network and PSP notification duties for Cardinal, and Halcyon for EU card traffic |
| Does any customer contract impose a regulator-facing duty on us? | Some enterprise agreements do; check the contract, not the standard terms |

Where Northwind is a processor, our duty is to notify our customer without
undue delay and support their own filing. Do not file on a customer's behalf
and do not tell a customer whether they must notify — give them the facts and
let their counsel decide. Every conclusion, including "no notification
required", is written up and filed in the privileged matter with the reasoning
and the date. The decision not to notify needs the better record.

---

## 6. External counsel, forensics, and insurance

**External counsel.** Engaged for any incident with a plausible multi-
jurisdiction notification obligation, regulator or law enforcement contact,
suspected criminal conduct, or likely litigation. The General Counsel makes
the call, by written retainer stating the purpose is to advise Northwind on
its legal obligations. **Forensics** is retained by external counsel, not by
Northwind directly, for the privilege reasons in section 3.

**Cyber insurance.** Notice to our broker goes out the same business day that
a SEV1, or a SEV2 with suspected personal data involvement, is declared —
before we know whether coverage is engaged. Late notice is the most common
reason a claim is reduced. Before retaining anyone, check whether the carrier
requires panel counsel or panel forensics: using a non-panel provider without
pre-approval can put those costs outside coverage.

**Spend.** Incident-related external spend follows the standard approval chain —
VP Finance for $25,000-$100,000, CFO plus General Counsel above $100,000. A
serious incident crosses $100,000 quickly, so brief Jordan Kim early.

---

## 7. Communications gate

No external communication about a security incident leaves Northwind without
Legal approval — the one place where Legal has a hard veto during an active
incident. In scope: the status page at status.northwind.example, customer
notification emails and in-product notices, support macros and any answer to
an inbound "did this affect me?", sales talking points, any public statement
or press response, and employee-wide announcements, which reliably leak.

Working practice with the Communications Lead:

1. Comms drafts; Legal reviews. Legal does not write customer-facing copy from
   scratch — that produces text that damages trust more than the incident did.
2. Review against three tests: **is every sentence true**, **is it true on the
   evidence we actually have**, and **does it commit us to something we cannot
   deliver**.
3. Strip speculation about cause, and never state that no data was affected
   before the investigation supports it. Reversing that statement is the
   single most damaging thing we can do.
4. Keep operational status updates flowing. The gate is about characterising data
   exposure, not about suppressing "we are aware of degraded payments." Reliability language is the IC's; data-exposure language is Legal's.
5. Log every approved external statement with its timestamp in the privileged
   matter. Later regulatory correspondence will ask what we said and when.

The gate reopens when the General Counsel says it does, ordinarily once the
notification analysis is complete and the customer notice has gone out.

---

## 8. Post-incident

The engineering postmortem is due within 5 business days for SEV1 and SEV2 and
is blameless. Legal attends the review but does not edit it into legalese; a
sanitised postmortem is worse than no postmortem, because engineers stop
writing honest ones. Legal's own follow-through:

| Task | Timing | Owner |
|---|---|---|
| Notification memo finalised and filed in the privileged matter | Within 5 business days of the customer notice | Privacy Counsel |
| Customer follow-up updates delivered on the promised cadence | As committed | Legal + Comms |
| Regulatory correspondence tracked to closure, including questions arriving weeks later | Ongoing | Privacy Counsel |
| Contract review: did we meet every customer-specific commitment, and did any obligation surprise us? | Within 10 business days | Legal |
| Vendor incidents: reassess tier, contract terms, and DPA notification language under vendor-policy.md | Within 20 business days | Legal |
| Insurance claim documentation, cost capture, and playbook update | Within 20 business days | Legal + Finance |
| Legal hold scope review — narrow or release in writing | Monthly while open | General Counsel |

A regulatory inquiry can arrive months after an incident closes. Keep the matter
file, the privileged analysis, and the preserved evidence intact until the
General Counsel releases the hold in writing — not until the channel goes quiet.

---

## Revision History

| Date | Author | Change |
|---|---|---|
| 2025-06-11 | Tom Lindqvist | Initial playbook after the first tabletop exercise with the incident response team |
| 2025-12-08 | Rina Malhotra | Split customer and regulatory notification into parallel tracks; added the controller/processor analysis |
| 2026-03-25 | Tom Lindqvist | Added the first-hour checklist, panel counsel caution, and the post-incident follow-up table |
