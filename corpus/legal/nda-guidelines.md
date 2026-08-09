# NDA and Confidentiality Guidelines

**Owner:** Tom Lindqvist (General Counsel)
**Audience:** Everyone at Northwind. This is the document to read before you send a deck to someone outside the company.

Most confidentiality problems at Northwind are not dramatic. Nobody sells the
roadmap. What happens is that an engineer answers a prospect's question about
next quarter, or an account executive pastes an availability number into a
shared document, and a commitment we never made starts circulating outside the
company. These guidelines exist so you can be helpful without doing that.

---

## The one rule to remember

**A mutual NDA must be signed before you share any non-public roadmap or
metrics with anyone outside Northwind.**

Not "before a formal briefing." Before the first sentence. If you are on a
call and the conversation turns toward what we are building next quarter or
how many transactions we processed last month, the correct move is:

> "That's a good question, but it's not something we've published. Let me get
> a mutual NDA in place and then I can go into it properly."

Nobody has ever lost a deal to that sentence. Legal turns around standard NDAs
fast precisely so that it costs you a day, not a quarter.

---

## Confidentiality tiers

Northwind classifies information into four tiers. Use the tier name in
document titles and channel topics — it saves an enormous amount of guessing.

**Public** — already published, or approved for publication. Anyone may share
it with anyone, without an NDA. Examples: the marketing site, published API
documentation for `/v1` and `/v2`, the status page at status.northwind.example,
published pricing, job descriptions, our public subprocessor list, conference
talks after they have been given.

**Internal** — ordinary day-to-day company information. Freely shared inside
Northwind, including with contractors under contract; not shared outside
without an NDA, but its disclosure would be an embarrassment rather than a
wound. Examples: team plans and sprint boards, most engineering runbooks,
internal architecture diagrams, org charts, this document, the HR policy set,
meeting notes, internal service names and their responsibilities.

**Confidential** — would cause real commercial harm if it reached a competitor
or the press. Shared inside Northwind on a need-to-know basis, and outside only
under a signed NDA and with the owning team's agreement. Examples: the product
roadmap beyond what has been publicly announced, revenue and growth metrics,
customer names not in a published reference list, customer contract terms and
negotiated pricing, incident postmortems, security review findings for our
vendors, per-service reliability numbers, headcount plans, compensation ranges.

**Restricted** — access is granted individually and logged. An NDA is
necessary but not sufficient; someone must decide you specifically need it.
Examples: credentials and signing keys of any kind, customer personal data,
payment data, security incident investigation materials while an incident is
open, unannounced M&A or fundraising material, individual compensation and
performance records, legal advice covered by privilege, employee relations
matters.

### Quick reference

| Tier | Share inside Northwind | Share outside Northwind | Typical home |
|---|---|---|---|
| Public | Freely | Freely | Website, docs site, status page |
| Internal | Freely | Signed NDA | Internal wiki, team repos |
| Confidential | Need to know | Signed NDA + owner approval | Access-controlled space |
| Restricted | Named individuals only | Almost never; GC approval required | Restricted store, audited access |

When two tiers could apply, use the higher one. When you genuinely cannot
tell, ask the owning team rather than the person who wants the information.

---

## Which NDA do I need?

### Standard mutual NDA — the default

Northwind's standard mutual NDA covers both directions, runs for a fixed term,
and has been reviewed enough times that Legal does not need to look at it
again. Request it at legal@northwind.example with the counterparty's legal
entity name, the contact's name and email, and one line on the purpose.

**Turnaround: 1 business day** from a complete request to a signature-ready
document.

Use the standard mutual NDA for prospect conversations, partner exploration,
recruiting senior candidates who need real detail, and early vendor
discussions before the vendor diligence in vendor-policy.md begins.

### Custom or counterparty-paper NDA

Sometimes the other side insists on their own form, or wants changes to ours.
That is normal, especially with larger counterparties. **Turnaround: 5
business days**, longer if their form contains any of the following, which
Legal will always negotiate:

- A unilateral obligation where only Northwind is bound
- A perpetual confidentiality term with no end date
- Non-solicit or non-compete language bundled into an NDA
- Assignment of intellectual property arising from the discussions
- Obligations that would require us to breach an existing customer commitment
- A residuals clause that is broader than our own

Do not sign a counterparty NDA yourself, and do not tell the counterparty
their form "looks fine" before Legal has read it. That comment gets quoted
back at us.

### When you do not need an NDA

The information is Public; or the counterparty already has a signed master
agreement with confidentiality terms covering this discussion (check with
Legal rather than assuming); or you are speaking with a Northwind contractor
already under contract.

---

## Handling confidential information day to day

**Documents.** Put the tier in the title: `Confidential - 2026 Roadmap
Review`. Share by named person or an internal group, never by "anyone with the
link."

**Chat.** Assume anything in a channel with guests is external. Before you
paste a metric, look at the member list. Restricted material does not go in
chat at all.

**Slides and screenshots.** The most common leak at Northwind is a screenshot
of a real dashboard used to illustrate a point. Redact customer names, use
round or synthetic numbers, and crop out anything you did not intend to share.

**Email.** Check the autocomplete before you send. External recipients on a
thread carrying Confidential material need to be there deliberately.

**Third-party tools.** Do not paste Confidential or Restricted material into
any tool that has not been through vendor review. See vendor-policy.md. This
includes tools you use personally and are convinced are private.

**Personal devices and exports.** Downloading a Confidential export to a
personal laptop makes you responsible for it. Delete it when you are done;
copies you make are still subject to retention rules and legal holds under
data-retention.md.

**Customer data is never an example.** If you need sample data for a demo, a
bug report, or a test, use synthetic data. Real shipment addresses and real
payment records are Restricted regardless of how convenient they are.

---

## Inbound NDAs from customers and prospects

Customers frequently send us their own NDA, often as a prerequisite to a
security review or a procurement process.

What to do:

1. **Forward it to legal@northwind.example.** Do not sign it, do not
   countersign it, and do not confirm you have "no issues with it."
2. **Tell Legal the context**: which deal, what stage, whether there is a
   deadline, and what you actually need to share.
3. **Let Legal handle the redlines.** Expect 5 business days for
   counterparty paper.
4. **Do not start sharing while it is in review.** An NDA that is "basically
   agreed" protects nothing.

Two situations that need Legal involved early rather than late:

- The NDA is bundled into a larger vendor onboarding portal that also contains
  service terms or an indemnity. Signing that portal is signing a contract,
  and the signature authority rules in vendor-policy.md apply.
- The customer asks for confidentiality obligations that would prevent us from
  meeting our own commitments — for example, restricting our ability to notify
  affected customers about a security incident within 72 hours of
  confirmation. We do not accept those terms.

---

## Recruiting and departures

**Candidates.** Interview loops can discuss the role and general technical
context without an NDA. Sharing the roadmap, financial metrics, or customer
names with a candidate requires a signed mutual NDA — most common at senior
levels, and Legal turns those around on the standard 1-business-day path.

**Incoming hires.** Never ask a candidate or new joiner about confidential
information from a previous employer, and do not accept documents they offer.
If someone brings material from a prior employer, tell Marcus Webb and Legal
immediately and do not open it.

**Departures.** Confidentiality obligations survive employment. Taking
Confidential or Restricted material with you when you leave is not a grey area.

---

## Suspected disclosure — what to do

If you think confidential information has left the company without
authorisation — a misdirected email, an over-shared document, a screenshot in
a public forum, a former colleague repeating something they should not know:

1. **Report it within 24 hours** to legal@northwind.example, or directly to
   Tom Lindqvist if it is urgent or sensitive.
2. **Do not investigate on your own.** Do not contact the recipient, and do
   not ask them to delete anything. Well-intentioned cleanup destroys the
   record of what happened and can make a recoverable situation worse.
3. **Do not delete anything.** Preserve the email, the document version
   history, the chat thread, and any link-sharing settings exactly as they are.
   A legal hold may follow, and data-retention.md prohibits deletion once one
   is issued.
4. **Write down what you know**: what was disclosed, to whom, when you noticed,
   and how. Send it with the report.

Legal assesses the exposure, decides whether the counterparty must be
notified, and coordinates any recovery. If the disclosure involves customer
personal data, credentials, or security material, it is a security incident as
well — report it through the engineering incident path in incident-response.md
at the same time, and let both processes run.

Reporting a disclosure you caused is not a disciplinary event. Concealing one
is. We would far rather hear about it on the day it happens.

---

## Frequently asked

**A prospect asked when a feature ships. Can I answer?**
If it has been publicly announced, yes. Otherwise no, not without a mutual
NDA, and even then say "we are working on it" rather than giving a date.

**Can I say who our customers are?**
Only the ones on the published reference list. Every other customer name is
Confidential and many contracts prohibit disclosure outright.

**Can I share a postmortem with a customer who was affected?**
Not directly. Postmortems are Confidential and written to be blameless
internally. Legal and the incident Communications Lead produce a customer-
facing summary instead.

**Can I put internal architecture in a conference talk?**
Yes, with the owning team's review and Legal's sign-off before submission.
Service names and general design are Internal; reliability numbers, customer
data flows, and security controls are Confidential.

**We already have an NDA from two years ago. Is it still good?**
Check with Legal — NDAs have terms, and the purpose clause may not cover the
new conversation.

---

## Revision History

| Date | Author | Change |
|---|---|---|
| 2025-05-06 | Tom Lindqvist | Initial guidelines; defined the four confidentiality tiers |
| 2026-01-27 | Tom Lindqvist | Added the inbound NDA path, standard vs custom turnaround times, and the recruiting section |
| 2026-06-02 | Rina Malhotra | Expanded the suspected disclosure procedure and its link to the incident process |
