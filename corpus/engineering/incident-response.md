# Incident Response

Owner: Sofia Reyes (sofia.reyes@northwind.example), Engineering Manager, Infrastructure

How Northwind runs incidents. This applies to every engineering team. The
rotation mechanics — who is on call, handoffs, swaps — are in
`oncall-rotation.txt`; this document is about what happens once something is
actually broken.

## Severity levels

| Severity | Definition | Examples |
|---|---|---|
| **SEV1** | Full outage, or payment loss | api-gateway down; payments-service unable to process any traffic; captured payments not recorded in the ledger |
| **SEV2** | Major degradation | p99 latency far above objective across a core flow; one region failing; refunds broken while payments work |
| **SEV3** | Minor degradation | A non-critical endpoint erroring; a background job backed up; a single tenant affected by a bounded bug |
| **SEV4** | Cosmetic, no customer impact | A dashboard rendering wrong; a log field missing; a typo in an error message |

Two rules about picking a severity:

- **Payment loss is always SEV1.** Money that moved and was not recorded, or was
  recorded and did not move, is a SEV1 regardless of how few customers are
  affected.
- **When in doubt, go one level higher.** Downgrading a SEV1 fifteen minutes in
  costs nothing. Upgrading a SEV3 ninety minutes in costs a great deal.

## Acknowledgement targets

| Severity | Ack target |
|---|---|
| SEV1 | **15 minutes** |
| SEV2 | **30 minutes** |
| SEV3 | **4 business hours** |
| SEV4 | Best effort; triaged into the backlog |

Acknowledgement means a human has seen the page and taken ownership. It does not
mean the problem is understood or fixed. Acking and then going back to sleep is
worse than not acking, because it stops the escalation ladder.

## Roles

Every SEV1 and SEV2 has three named roles. On a SEV1 they must be three different
people.

### Incident Commander (IC)

Owns the incident. Decides severity, directs the response, and is the single
point of authority on what happens next.

The IC does **not** debug. The moment the IC has their head in a stack trace,
nobody is running the incident. If you are the best-placed person to debug, hand
the IC role to someone else and go debug.

IC responsibilities:

- Declare the incident and set severity.
- Assign Comms Lead and Scribe.
- Maintain a working hypothesis and state it out loud, repeatedly.
- Decide on mitigations, including rollback and the freeze exception.
- Declare the incident resolved and name the postmortem owner.

### Communications Lead

Owns everything customers and internal stakeholders see. Updates
`status.northwind.example`, drafts customer messaging, and keeps Support and the
account teams informed so the IC is not fielding "any update?" messages.

The Comms Lead is also the one who checks whether the incident involves personal
data, because that triggers a legal obligation: security incidents involving
personal data are reported to affected customers within 72 hours of confirmation.
If there is any chance personal data is implicated, page Legal — Tom Lindqvist,
General Counsel — and Rina Malhotra, Privacy Counsel. Do not make that call
alone, and do not make it by reasoning about it in the incident channel at 02:00.

### Scribe

Keeps the timeline. Timestamps every significant observation, decision, and
action in the incident channel. Notes what was tried and what the result was,
including the things that did not work — those are usually the most valuable
lines in the postmortem.

Without a Scribe, the postmortem becomes an archaeology project reconstructed
from chat scrollback and memory, and it will be wrong.

## Paging and escalation

Paging path for a service:

1. **Primary on-call** for the owning team is paged.
2. If unacknowledged within the ack target for the severity, the page escalates
   to the **secondary on-call** for that team.
3. If still unacknowledged, it escalates to the **team's manager**.
4. For a SEV1, the Infrastructure on-call is paged in parallel from the start,
   not sequentially.

Anyone may declare an incident. You do not need permission, seniority, or
certainty. Declaring an incident that turns out to be nothing has no
consequences; not declaring one that turns out to be something has plenty.

Pull people in freely during a SEV1. The cost of waking someone unnecessarily is
much lower than the cost of a prolonged outage, and nobody at Northwind has ever
been criticized for being paged into an incident they turned out not to be needed
for.

Escalation to leadership: the IC notifies engineering leadership on any SEV1 at
declaration, and on any SEV2 that exceeds 60 minutes without a clear mitigation
path.

## Status page and communication cadence

Public status page: **status.northwind.example**

| Severity | First public update | Ongoing cadence | Who |
|---|---|---|---|
| SEV1 | Within 30 minutes of declaration | Every 30 minutes, even with no news | Comms Lead |
| SEV2 | Within 60 minutes if customer-visible | Every 60 minutes | Comms Lead |
| SEV3 | Only if customer-visible | On material change | Owning team |
| SEV4 | Not posted | — | — |

"Every 30 minutes even with no news" is the rule that matters. An update saying
"still investigating, no new information, next update at 15:30" is a real update.
Silence is read as abandonment.

Language rules for public updates:

- Describe impact in terms the customer experiences, not internal components.
  "Payments are failing for some customers" rather than "the Cardinal circuit
  breaker is open."
- Never speculate about cause in a public update.
- Never name a vendor as the cause before it is confirmed, and clear vendor
  attribution with Legal first.
- Never commit to a resolution time you do not have.

## First 15 minutes

Follow this in order. It is written for the person who just got paged and does
not yet know what is happening.

1. **Acknowledge the page.** Right now, before anything else. This stops the
   escalation ladder and tells everyone a human is on it.
2. **Open the service dashboard.** The four golden signals for the affected
   service — see `observability-standards.md`. You are looking for when the shape
   changed, not why yet.
3. **Set a severity.** Use the table above. Say it out loud in the incident
   channel. It can change later.
4. **Declare the incident and take IC**, or explicitly hand IC to someone else.
   The channel must contain the sentence "I am IC." Ambiguity about who is
   running the incident is the most common failure mode we have.
5. **Assign Comms Lead and Scribe** for SEV1/SEV2. Name people; do not ask for
   volunteers.
6. **Check for a recent deploy.** Look at Argo CD sync history for the affected
   service. A large fraction of incidents begin with a deploy in the previous
   hour. See `deployment-runbook.md`.
7. **If a recent deploy correlates, roll back.** Do not wait to understand the
   cause. For payments-service and ledger-service this is a blue/green selector
   switch and takes seconds.
8. **Check dependencies.** identity-service (is anything able to get a token?),
   the databases, and the PSPs. A wave of `unknown_kid` or `token_expired`
   failures points at authentication; see `authentication.md`.
9. **Post the first status page update** if the incident is customer-visible and
   at SEV1/SEV2.
10. **State your working hypothesis in the channel**, even if you are unsure.
    "Hypothesis: the 14:02 payments deploy. Testing by rolling back." A stated
    hypothesis lets others disprove it; an unstated one wastes everyone's time.
11. **Mitigate before you diagnose.** Restore service first. Understanding is a
    postmortem activity.
12. **Keep the Scribe fed.** Say what you are about to do before you do it.

If you have done all twelve and you are still lost, escalate. Being stuck for 15
minutes on a SEV1 is a reason to pull in more people, not a reason to try harder
alone.

## Resolution and follow-up

An incident is resolved when customer impact has ended, not when the root cause
is understood. The IC declares resolution explicitly in the channel, and the
Comms Lead posts a final status page update.

At resolution the IC must name:

- The postmortem owner (usually, but not necessarily, the IC).
- Any immediate follow-up actions with owners.
- Whether a temporary mitigation is still in place that must be unwound.

That last one is important. A rate limit lowered at 02:00 to shed load will stay
lowered forever unless someone owns removing it.

## Postmortems

**A postmortem is required for every SEV1 and SEV2.** It is **due within 5
business days** of resolution. SEV3 postmortems are optional and encouraged when
something surprising happened. SEV4 does not get one.

Required contents:

- **Impact** — who was affected, how, and for how long, in customer terms.
- **Timeline** — from first signal to resolution, drawn from the Scribe's notes.
  Include when we *detected* it, not just when it started; the gap between those
  two is often the most actionable finding.
- **Contributing factors** — plural, always. Single-cause incidents are rare and
  a single-cause postmortem usually means the analysis stopped early.
- **What went well** — genuinely. Response patterns that worked are worth
  reinforcing.
- **Action items** — each with a named owner and a due date. An action item
  without an owner is a wish.

### Blameless

Postmortems at Northwind are **blameless**, and this is enforced, not aspirational.

- Name systems, not people. "The promotion PR bundled a config change with a code
  change" — not "Dev bundled a config change."
- Assume everyone acted reasonably given the information they had at the time. If
  someone made a decision that looks obviously wrong in hindsight, the interesting
  question is what made it look right at the time.
- Human error is a starting point for investigation, never a conclusion. "The
  operator ran the wrong command" is the beginning of the analysis: why was the
  wrong command available, easy to run, and hard to distinguish from the right
  one?
- No postmortem finding ever feeds into performance review. This is a firm
  commitment, and if you believe it has been violated, escalate to People
  Operations.

Action items are tracked to completion. An open action item from a SEV1
postmortem is reviewed in the weekly operations meeting until it is closed.

## Revision History

| Date | Author | Change |
|---|---|---|
| 2025-04-03 | Sofia Reyes | Initial incident response policy |
| 2025-10-21 | Sofia Reyes | Added the first-15-minutes checklist and the "IC does not debug" rule |
| 2026-03-30 | Sofia Reyes | Clarified the personal-data escalation path to Legal |
