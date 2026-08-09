# Remote and Hybrid Work Policy

**Audience:** all Northwind employees
**Owner:** Marcus Webb, Director of People Operations (marcus.webb@northwind.example)
**Contributors:** Aisha Nkemelu (People Operations), Sofia Reyes (Infrastructure, on-call sections)

Northwind Systems, Inc. runs a hybrid company with genuinely remote roles in it.
That combination only works if the rules are explicit, so this document states
them: where you are expected to be, when you are reachable, what equipment you
get, and what you must clear before working from somewhere else.

---

## 1. Work Arrangements

Every role has exactly one of two designated arrangements.

### 1.1 Hybrid (the default)

**Austin-based staff are in the office 2 days per week.** That is the standard, it
is not aspirational, and managers are expected to hold it.

- The two days are chosen by the team, not by individuals, and published on the
  team calendar. Teams that let everyone pick their own days end up with an office
  full of people who never overlap — the one outcome this policy exists to prevent.
- Anchor days should be consistent week to week. Changing them constantly is worse
  than picking the wrong ones.
- A week where you are travelling for work, on PTO, or out sick carries no
  in-office expectation. Do not try to make up days.

Denver and Dublin site leads set local in-office expectations for their sites in
coordination with People Operations and publish them to their teams. If you are
based in Denver or Dublin and do not know what your expectation is, ask your
manager rather than assuming the Austin standard applies to you.

### 1.2 Fully remote

Fully-remote roles exist across the company and are **marked as such in the job
req**. This is a property of the role, recorded before the role is opened — not a
side agreement made after someone is hired.

```yaml
# Excerpt from a job requisition record
req_id: ENG-2026-0142
title: Senior Engineer, Payments
level: L4
work_arrangement: remote        # one of: hybrid | remote
hiring_location: US             # remote roles state the eligible geography
in_office_days_per_week: 0
```

If `work_arrangement` says `hybrid`, the role is hybrid, and no manager can
convert it informally. Converting a role between hybrid and remote requires a req
amendment approved by the function head and People Operations, because the change
affects pay geography — see compensation-policy.md — as well as team planning.

Fully-remote employees are not second-class. Section 4 exists to make that
structurally true rather than merely stated.

---

## 2. Core Collaboration Hours

We are distributed across time zones that overlap badly, so we protect a narrow
shared window rather than pretending everyone is always available.

| Group | Core hours | Notes |
|-------|-----------|-------|
| Austin and Denver | 10:00–15:00 US Central | Be reachable and meeting-available |
| Dublin | 15:00–18:00 local | Overlaps the Austin morning |
| Cross-office meetings | 09:00–11:00 US Central | The only reliable Austin/Dublin overlap |

Outside core hours you set your own schedule, provided your commitments are met
and your calendar reflects reality.

- Keep your working hours and time zone accurate in your calendar and profile.
- A meeting scheduled outside a participant's core hours is an ask, not an
  assignment. Decline freely.
- Recurring meetings permanently outside a Dublin participant's core hours must
  rotate, be recorded, or become a written update. Rotating the pain is
  acceptable; assigning it permanently to the smallest office is not.
- Nobody is expected to respond to messages outside their working hours. The only
  exception is an active page while you are on-call.

---

## 3. Equipment and Workspace

IT issues, at no cost and regardless of arrangement: a laptop with refreshes on
the standard hardware cycle, an external monitor, keyboard, mouse, a headset, and
any software licence your role requires. Company hardware stays on the company
device management platform and is returned on separation. Do not do Northwind work
on a personal machine.

A **one-time $500 home-office stipend** covers desk, chair, lighting, and similar
setup costs. It is claimed as a reimbursement, once per employee, not once per year
and not reset by relocation. Details of that and the other stipends are in
benefits.md.

You are responsible for a workspace that is safe, reasonably quiet for calls, and
adequate for the confidentiality of the work: a connection that reliably supports
video calls; screens not visible to others when handling customer data; devices
locked when unattended, including at home; and no work on public or shared
devices, ever. Coworking memberships are not a standard benefit.

---

## 4. How We Work: Documentation First

The most common way distributed teams fail is that the important context lives in
a hallway conversation. Our counter is a documentation-first default: **write it
down, then discuss it.**

- Decisions of any consequence are recorded in a written document or decision
  record, not only in chat and not only in a meeting.
- Meetings that make decisions produce notes with the decision and the owner
  within one business day. No notes, no decision.
- Design proposals circulate as documents ahead of the review meeting. The meeting
  is for disagreement, not for a read-along.
- Default to public channels over direct messages. A DM that could have been a
  channel message costs the whole team the context.
- Record anything cross-office and attach a written summary. A recording without a
  summary is not accessible; it is a 50-minute video nobody will watch.

**Meeting hygiene.** Every meeting has an agenda in the invite, or it can be
declined without explanation. If everyone is not in the same room, everyone is on
their own tile — a partial room of five people around one laptop reliably excludes
the remote attendees.

**Inclusion checks for managers.** Watch for proximity bias: in-office employees
being included in decisions, handed the visible projects, or rated higher for
being seen. This is checked against work location every review cycle — see
performance-review-process.md.

---

## 5. Working From Another Location

There is a real difference between working from a friend's flat for a long weekend
and working from another country for two months. The second creates tax,
employment, and data obligations for Northwind.

### 5.1 Within your country of employment

Working from a different city inside your country of employment needs manager
awareness only, provided you remain available during core hours. If it becomes
permanent, it is a relocation — see 5.3.

### 5.2 From another country

Requires **written approval in advance** from your manager **and** People
Operations, before you book anything.

| Rule | Detail |
|------|--------|
| Maximum duration | 30 calendar days per rolling 12 months |
| Notice | Request at least 30 days in advance |
| Approvals | Manager and People Operations, in writing |
| Legal review | Required beyond 30 days, or for any country where Northwind has no entity |
| On-call | Not permitted while working from another country unless explicitly agreed in the approval |

Why we are strict:

- **Tax.** Working days in another country can create a personal tax liability for
  you and a corporate presence obligation for Northwind.
- **Employment law.** Some jurisdictions attach local employment rights after a
  surprisingly short period of work performed there.
- **Immigration.** A tourist entry usually does not permit work.
- **Data residency.** EU customer data stays in the Dublin region (eu-west-1).
  Where you sit affects what you may access, and from where.

Questions about tax, entity, or immigration exposure go to Tom Lindqvist, General
Counsel, via People Operations. Do not rely on what another company allows, and do
not proceed on a verbal maybe. People Operations routes the request for you.

### 5.3 Permanent relocation

A permanent move needs approval before you commit to it. Relocation may change
your pay geography and therefore your salary band (compensation-policy.md), your
benefits, which are administered locally (benefits.md), your public holiday
schedule (leave-policy.md), and whether the role can continue at all if Northwind
has no entity where you are going. Approved relocations take effect on the first
of a month, to keep payroll and benefits clean.

---

## 6. Remote Work and On-Call

Being remote does not change on-call obligations, and being on-call constrains
where you work that week. The rotation is **weekly**, with **one primary and one
secondary per team**. Acknowledgement targets are the same wherever you are:

| Severity | Description | Ack target |
|----------|-------------|-----------|
| SEV1 | Full outage or payment loss | 15 minutes |
| SEV2 | Major degradation | 30 minutes |
| SEV3 | Minor degradation | 4 business hours |

While you are primary or secondary:

- Be able to reach a workstation and a reliable connection **within 15 minutes**
  at any hour of your shift. Phone-only acknowledgement does not count as being
  able to respond.
- Do not take a shift while working from another country unless it was explicitly
  approved.
- Swap the shift rather than take it somewhere unsuitable. Swaps are normal.
- Arrange coverage **before** submitting a PTO request that overlaps your shift —
  see leave-policy.md.

Two scheduling facts that interact with remote work: **no production deploys go
out after 16:00 on Friday**, so do not plan to ship at the end of a Friday from
anywhere; and **no production deploys happen during 20–31 December**, though
on-call still runs and coverage is finalised by 30 November. Employees returning
from parental leave are not placed on the rotation in their first four weeks back.

---

## 7. When Hybrid Expectations Are Not Met

Handled as a normal management conversation, not a compliance process. The manager
raises it directly and finds out what is going on — caring responsibilities,
commute changes, and health situations are common and usually solvable. Where a
genuine constraint exists, People Operations looks at accommodations, including a
temporary variation to the in-office expectation. Sustained, unexplained
non-attendance after a documented conversation goes through the normal performance
process. Nobody's attendance is tracked by badge data for performance purposes:
attendance is a team agreement held by the manager, not a metric.

---

## 8. Frequently Asked

**Which two days do I come in?** Whichever two your team publishes. Ask your
manager; do not pick your own. Austin-based employees whose teammates are all
remote still come in twice a week — the office is for cross-team collaboration,
not just your standup.

**Can I switch from hybrid to fully remote?** Only through a req amendment
approved by the function head and People Operations. It is not a manager-level
decision, and it may change your pay geography.

**Can I work from Dublin for three weeks in summer?** Possibly, with advance
written approval under section 5.2, and not while on-call. Ask before booking.

**Do remote employees get the same equipment?** Yes, identical, plus the same
one-time $500 home-office stipend.

**Is there a stipend for internet or electricity?** No. The stipends in
benefits.md are the complete list.

---

## Revision History

| Date | Author | Change |
|------|--------|--------|
| 2025-07-08 | Marcus Webb | Initial publication; formalised the 2-day hybrid standard and the remote designation on job reqs |
| 2026-02-16 | Sofia Reyes | Added the on-call section, including the 15-minute workstation expectation and the restriction on on-call while abroad |
| 2026-06-22 | Aisha Nkemelu | Added the 30-day cap on working from another country; clarified the relocation approval path |
