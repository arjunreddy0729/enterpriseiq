# Compensation Policy

> **CLASSIFICATION: RESTRICTED — HUMAN RESOURCES ONLY.**
> This document describes how Northwind Systems, Inc. sets, reviews, and adjusts
> pay. It is **not** distributed to the general employee population, is **not**
> readable by Engineering, and must not be pasted into shared channels, tickets,
> customer-facing material, or any wiki outside the People Operations space.
> Managers receive a derived summary only — see "What Managers Are Told" below.
> Access requests go to Marcus Webb (marcus.webb@northwind.example); unauthorized
> redistribution is treated as a policy violation.
> **Owner:** Marcus Webb, People Operations · **Co-owner:** Aisha Nkemelu, HRBP

---

## 1. Scope and Principles

Applies to all regular employees across Austin (HQ), Denver, and Dublin;
contractors are out of scope. Total compensation has three components: base
salary, an annual cash bonus, and equity. Benefits and stipends are described in
benefits.md and do not count as compensation for band purposes.

Four principles, in priority order:

1. **Level first, then pay.** Decide what level someone is operating at, then pay
   inside that band. Never reverse-engineer a level to justify a salary number.
2. **Bands are national, not negotiated.** Negotiation moves people within a band;
   it does not move the band.
3. **Internal equity beats external anchoring.** A competing offer is input to a
   retention conversation, not an automatic band exception.
4. **Everything is written down.** Every off-cycle adjustment has a documented
   rationale in the employee record.

---

## 2. Level Framework

Engineering uses levels **L1 through L7**; management uses **M1 through M4**. The
ladders are equivalent in status and overlap in pay; moving from L5 to M1 is a
lateral change, not a promotion, and carries no automatic increase.

| Level | Track | Typical scope |
|-------|-------|---------------|
| L1 | IC | Learning the codebase; ships well-defined tasks with review |
| L2 | IC | Owns small features end to end within one service |
| L3 | IC | Owns a service area; participates fully in on-call |
| L4 | IC | Senior. Owns a service; mentors; leads multi-week projects |
| L5 | IC | Staff. Owns cross-service technical direction |
| L6 | IC | Senior Staff. Owns outcomes spanning multiple teams |
| L7 | IC | Principal. Company-level technical strategy |
| M1 | Management | Manages one team |
| M2 | Management | Manages a large team or two small teams |
| M3 | Management | Director. Manages managers |
| M4 | Management | VP. Owns a function |

Executive officers sit outside the published ladder. Behavioural expectations per
level live in the People Operations level guide, which **is** shared with
employees: this document is the pay layer, the level guide is the expectations
layer.

---

## 3. Base Salary Bands

### 3.1 How bands are built

Each level has one band expressed as a minimum, midpoint, and maximum. Bands are
rebuilt every January from blended third-party survey data for B2B SaaS companies
of comparable headcount and stage, aged forward to the April effective date. Band
width is 40% of the minimum; the midpoint sits at the market 50th percentile.

```text
band_min      = market_p50 / 1.20
band_mid      = market_p50
band_max      = band_min * 1.40
compa_ratio   = current_base / band_mid
```

### 3.2 Compa-ratio guidance

| Compa-ratio | Interpretation | Expected action |
|-------------|----------------|-----------------|
| < 0.85 | Below band health; usually new to level | Prioritise in merit; flag if sustained two cycles |
| 0.85 – 0.95 | Developing in level | Normal merit progression |
| 0.95 – 1.05 | Fully performing at level | Normal merit progression |
| 1.05 – 1.15 | Top of level | Merit slows; promotion is the path to more |
| > 1.15 | Above band health | No merit increase without VP approval |

Nobody is paid below their band minimum. If a band moves up in January and an
employee falls below the new minimum, they are brought to the minimum on 1 April
regardless of rating, and that correction is **not** charged to the merit pool.

### 3.3 Geographic differentials

Northwind runs a small number of pay geographies, not city-by-city pricing.

| Geography | Applies to | Band treatment |
|-----------|-----------|----------------|
| US Tier 1 | Austin (HQ) and Denver staff | Reference band; all US bands published against this tier |
| US Tier 2 | Fully-remote US staff outside the Austin and Denver metros | 95% of the Tier 1 band at each level |
| Dublin | Ireland-based staff | Separate EUR-denominated bands, benchmarked locally |

Geography follows the employee's registered work location, not their office
affiliation or where they are sitting in a given month; temporary work elsewhere
does not change the band, per remote-work-policy.md. A permanent relocation
triggers re-placement effective the first of the month following the move.
Downward re-placements move the band, but base salary is held flat, not cut.

---

## 4. Annual Merit Cycle

The merit and compensation review cycle is **annual, effective 1 April**, with
**calibration in March**.

| Phase | Timing | Owner |
|-------|--------|-------|
| Bands rebuilt and loaded | January | People Operations |
| Merit pool sized and approved | January–February | People Operations with Finance |
| Manager recommendations entered | Late February | Managers |
| Calibration sessions | March | People Operations facilitates |
| Approvals routed | Late March | Skip-level and function head |
| Statements delivered 1:1 | Final week of March | Managers |
| **Increases effective** | **1 April** | Payroll |

Not negotiable: the merit pool is fixed, and a manager who wants to give more to
one person funds it from their own allocation; changes are delivered by the direct
manager in a live conversation, never by message alone; and nothing is
communicated before calibration closes, because pre-committing a number is the
most common source of escalations to People Operations.

Rating drives the merit multiplier. The rating scale, self-review mechanics, and
calibration ground rules live in performance-review-process.md; the multiplier
grid translating rating and compa-ratio into a percentage is released to managers
during the cycle only.

---

## 5. Bonus

An annual cash bonus, targeted by level and funded against company performance.
M1 and M2 carry a 15% target; M3 and M4 carry 20%.

| Level | Bonus target (% of base) |
|-------|--------------------------|
| L1 | 10% |
| L2 | 10% |
| L3 | 10% |
| L4 | 10% |
| L5 | 15% |
| L6 | 15% |
| L7 | 20% |

- Target is a target, not a guarantee. Payout is target × a company factor, set
  once by the CFO and applied uniformly, × an individual factor from the spring
  rating.
- Mid-year joiners are prorated by days employed; fiscal year = calendar year.
- An employee on an active performance improvement plan at payout is not eligible.
- Leave taken under leave-policy.md, including parental leave, does **not** reduce
  the target or the proration. Not subject to manager discretion.

---

## 6. Equity

Grants are made in restricted stock units, at hire, to all regular employees.

- **Vesting: 4-year vest, 1-year cliff, quarterly thereafter.** 25% vests on the
  first anniversary of the vest start date; the remainder vests in equal quarterly
  instalments over three years.
- Vest start date is the employee's start date, not the grant approval date.
- **Refresh grants are made at L4 and above**, evaluated in March calibration and
  granted with the April effective date. Not automatic, not sized by tenure.
- Promotion into L4 makes an employee eligible for the next refresh cycle; it does
  not trigger an immediate refresh.
- Employees below L4 stay on their new-hire grant. This is intentional; do not
  imply to candidates that refreshes exist below L4.
- Individual grant sizing guidance is held by People Operations and is not
  published, including to managers.

---

## 7. Promotion

### 7.1 Criteria

Promotion recognises sustained operation at the next level. It is not a reward for
tenure, a single strong quarter, or a retention risk. A case must show:

1. **Sustained scope** at the next level for at least two review cycles, roughly a
   year, with evidence from both.
2. **Independent evidence** — written examples from peers and partner teams, not
   only the manager's assessment.
3. **Durability.** Backfilling a departed colleague for six weeks is not a case.
4. **No open performance concerns.** Anyone on a PIP is ineligible.

### 7.2 Promotion committee

Decisions are made by committee, not by the direct manager.

- Composition: the function head, two managers from outside the candidate's
  reporting line, and a People Operations facilitator. The facilitator does not
  vote; they enforce the criteria and flag inconsistent standards.
- Cases are read from a written packet. The manager presents, then leaves the room.
- Promotions to **L6, L7, M3, and M4** additionally require the function's
  executive sponsor.

Committees convene twice yearly, aligned to the April and October review points.
March-committee promotions take effect **1 April** alongside merit;
October-committee promotions take effect **1 November**, funded outside the merit
pool. There is no third window; off-cycle promotions do not exist. A declined case
returns to the employee with written, specific gaps within five business days.

### 7.3 Off-cycle adjustments

Rare, requiring documented justification plus People Operations review. Legitimate
grounds: correcting a placement error including pay-equity remediation; a
material, permanent scope change short of a promotion; a band minimum correction
after the January rebuild. Counter-offers require the function head plus People
Operations, never place an employee above band maximum, and never substitute for a
promotion case.

---

## 8. Pay Equity

People Operations runs a pay-equity analysis annually, completed before March
calibration so findings can be remediated in the same cycle.

- The analysis regresses base salary against level, geography, and tenure and
  tests for unexplained residual gaps.
- Remediation is funded from a **separate pool**, applied upward only. It never
  comes out of the merit pool and never reduces another employee's increase.
- Findings go to the CFO and the Board's compensation committee.
- An anonymised summary of methodology and whether gaps were found is shared with
  all employees after the cycle closes. Individual data never is.

Managers have no access to the underlying analysis. Employee questions about their
own pay relative to band go to aisha.nkemelu@northwind.example.

---

## 9. What Managers Are Told

Managers receive: the band minimum, midpoint, and maximum for levels **on their
own team**; the compa-ratio of their direct reports; the merit multiplier grid
during the cycle; and the bonus targets in section 5. Managers do **not** receive
bands for other functions, equity sizing guidance, the pay-equity analysis, or any
compensation data outside their reporting line. Employees may be told their own
band range and their own compa-ratio — never anyone else's.

---

## Revision History

| Date | Author | Change |
|------|--------|--------|
| 2025-04-18 | Marcus Webb | Initial publication; consolidated three legacy comp memos into a single policy |
| 2025-11-06 | Aisha Nkemelu | Added compa-ratio guidance and geographic differential tiers; clarified equity refresh eligibility at L4+ |
| 2026-03-02 | Marcus Webb | Split promotion committee into March and October windows; added pay-equity remediation funding commitment |
