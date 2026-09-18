# Rubric fit — finalised tracks + scoring (PDF of 2026-09-16)

*Source: [drive/Adeline Hackathon_Finalised Tracks + Scoring Rubric.pdf](drive/Adeline%20Hackathon_Finalised%20Tracks%20+%20Scoring%20Rubric.pdf). Supersedes the "Derived constraints" section of [hackathon_brief.md](hackathon_brief.md) where they differ. Decisions recorded in [adr/0005](adr/0005-actions-block-and-review-queue.md).*

## What the PDF adds

- Track 2 (AlbionVC) now has **five hard constraints** — "must satisfy every constraint below".
- Rubric: five criteria × 10 = 50. Constraint Compliance is judged **live**; Technical Quality allows **one slide**; Demo Completeness wants **multiple test cases**; Presentation wants a **credible commercial next step**.
- Format: **4 min pitch + demo**, 3 min questions, judges score in Mentimeter. **−20 per 2 min over** — 40 % of the total score; the single largest lever.
- Prep guide order: team overview → live demo → architecture → roadmap.
- Prizes: one winner per track from scores, plus one audience-choice award.

## Constraint → feature map

| # | Constraint | Where it is met | What still has to be built (stage) |
|---|---|---|---|
| C1 | Works from incomplete, inconsistent data without inventing what is missing | Abstain is a first-class verdict (1,241 / 6,220 on the full run); the verifier requires every quote to exist verbatim in the reading or it gets no page rectangle; `status` is computed from quoted times, never from model arithmetic; H6 "no follow-up documented" and null-organisation buckets; the report gateway is an allowlist so the report cannot invent a number | S6: abstain / no-end / undetermined-reason counted as their own categories in `estimates`. S7: unverified-evidence badge, abstain rows visible not hidden. Demo: click one abstain row and one unverified quote |
| C2 | Distinguishes a stalled patient from one legitimately waiting | Reason taxonomy already separates causes (`patient_declined`, `contraindication_documented`, `dna` vs `bed_unavailable`, `not_prescribed`, `icu_full` …) but nothing classifies them | Protocol `actions:` block gives every reason a `class: system | legitimate`. S6 splits breaches into *stalled* (system), *legitimate wait*, *undetermined* (null tag). S7 filter + column. Demo: one of each |
| C3 | Every alert names a specific next action and an owner | Design §6 stage 8 already asks for "recommended actions with owner" — report only | Protocol `actions:` block: `owner` per criterion, `action` per reason. S6 emits alerts (criterion over standard, organisation outside funnel limits, run-chart crossing) as rows carrying `action` + `owner`. S7 Results tab shows alert cards live. S8 report takes actions from the block — never from the model |
| C4 | Justifies its prioritisation — why this patient, why now, ahead of the others | Nothing yet. ADR 0002 / roadmap: no per-patient alert or triage | Two levels, both stated on screen. **Service:** rank handoffs and organisations by time lost (Σ excess hours over target, with CI) and by funnel/run-chart signal — "why this handoff, why now". **Review queue:** the workbench orders cases for *clinician checking* and shows the reason per row (abstain; unverified evidence; model call ≠ computed status; largest CI leverage; largest excess hours). This orders the clinician's checking, not the patient's care — see ADR 0005 |
| C5 | Usable inside an existing workflow, not another system to check | Framing: clinical audit *is* the existing workflow — statutory (Health and Social Care Act 2008 → CQC; CQC Registration Regulations 2009; NHS Act 2006), contractual (NCAPOP participation), and every trust runs an audit programme. AuditPace replaces the data-collection step, not the cycle | S8: report follows the NHSE best-practice-guide report structure so it drops into the trust's existing audit governance. Roadmap slide: EPR launch (Epic), FHIR export. Pitch says this out loud |

## Rubric → what we do

| Rubric item | Implication |
|---|---|
| 1 Innovation & effectiveness — real day-to-day pain, understood the user | Lead with the clinician's pain (8 m 35 s per summary, 27.8 h per project, audit suspended in 2020). Demo is the clinician's screen, nothing else |
| 2 Constraint compliance — **demonstrate live**, edge cases | Demo walks C1–C5 in order with a visible checklist; each constraint gets one on-screen moment. Edge cases shown: abstain, unverified quote, handwritten misread, model false breach (H5) corrected by review |
| 3 Technical quality — **one slide** | One architecture slide: boundary diagram + the harness (reader → adjudicator → verifier → clinician → estimator → gateway). Evaluation numbers (κ, CER, coverage) live in the app's Results tab, not on slides |
| 4 Demo completeness — working, intuitive, **multiple test cases** | ≥ 4 cases: stalled breach (H4 `not_prescribed`), legitimate wait (H4 `contraindication_documented` or H2 `patient_declined`), abstain / no data (H6 no follow-up), handwritten override, H5 false breach caught by review → interval moves |
| 5 Presentation & commercial — narrative clarity, credible next step | Commercial slide names the buyer and the contact (CUHP; Dr Rob Heuschkel, Addenbrooke's) and the expansion path (trial eligibility screening for research and pharma; per-clinician standards feedback; Epic estate) |
| 6 Time keeping — −20 per 2 min over | Script ≤ 3 : 40 with a visible timer; demo pre-loaded, no cold start; the app runs on recorded data, not live models |

## Decisions taken (2026-09-16)

1. **Protocol gains a hash-exempt `actions:` block** (`owner` per criterion; `class` and `action` per reason). `canonical_hash` pops it like `locked`/`hash`. Rationale: who fixes a breach and whether a cause is legitimate are operational metadata — a verdict does not depend on them — so changing them must not invalidate 6,220 verdicts (protocol hash `83174236e120` stays). Built in S6.
2. **Review-queue prioritisation is allowed.** Ordering which case the clinician *checks* next, with the reason printed, is not a per-patient clinical alert; the tool still never outputs a recommendation about a patient's care. ADR 0005.
3. **Existing S0–S5 code and archives are untouched.** Only docs, protocol block, and S6–S9 plans change.
4. **Pitch restructured** to the prep-guide order and to ≤ 3 : 40 — see [pitch.md](pitch.md).

## Stage plan changes

- **S6 estimate** — reason-class split; time-lost ranking per criterion and organisation (with CI); alerts table (`criterion_id`, `segment`, `signal`, `action`, `owner`); run-chart limit crossings; abstain/no-end/undetermined as explicit categories; review-queue score per case (`priority_reason`).
- **S7 workbench** — queue ordered by priority with the reason column; stalled / legitimate / undetermined filter; alert cards in Results with action + owner; unverified badge; constraint checklist overlay for the demo (`?demo=1`).
- **S8 report** — actions and owners come from the `actions:` block through the gateway (allowlisted codes); report sections follow the NHSE guide; caveats name H5 and the reason-tag accuracy by name.
- **S9 pitch** — deck to the four-part structure; one tech slide; constraint checklist; rehearsed timing; Q&A additions below.

## Q&A additions

- **"Why this patient, why now?"** — We prioritise the *team's* attention, not the patient's care: which handoff is losing the most hours this week, which ward is outside its funnel limit, and which rows the clinician should check first and why. A per-patient alert would make this a medical device and put a model between a clinician and a patient; an audit does not.
- **"Real-time?"** — Runs whenever the records land; the estimate updates on every review. The lag is the reading time of the notes, minutes not months.
- **"Another system to check?"** — Audit is already mandated and already happens; we remove the chart-reading step. Output is the trust's audit report. Roadmap: launch from the EPR.
