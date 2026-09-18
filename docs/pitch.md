# vigiLANCE — pitch

*Track 2, Pathway Breakdown (AlbionVC). **4 min pitch + demo, hard; −20 points per 2 min over.** 3 min questions. Judges score in Mentimeter against the rubric in [rubric_fit.md](rubric_fit.md). Sources: [roadmap](drive/audit_harness_roadmap.md.md) §2–4, [NHS England best-practice guide](drive/nhs_audit_best_practice_guide.txt), [design spec](superpowers/specs/2026-09-12-auditpace-design.md). Decisions of 2026-09-17 and 2026-09-18 (grill sessions) folded in: product name **vigiLANCE** (code and repo stay `auditpace`); slide 2 opens on the handoffs, not on audit; the stalled H4 case arrives live during the demo; H4 (VTE prophylaxis) is the thread from 2020 to the screen and H5 is the single "the model is wrong, watch the number move" beat; the technical slide carries the PPI figure and the dataset strip; the roadmap slide carries the three-slot animation. Deck assets and designer brief live in [pitch/](pitch/).*

## One line

Clinical audit is how the NHS finds where pathways break and why. It is mandated, it works, and nobody has time to do it — because someone has to read every note. vigiLANCE makes MedGemma read the notes, keeps the clinician in charge of every row, and reports a number you can defend.

## Timing budget — 3 : 10 target, 4 : 00 hard stop

| s | Part | On screen | Constraint |
|---|---|---|---|
| 0–20 | 1 Team | slide 1 | |
| 20–50 | 2 March 2020: handoffs broke, the check went dark | slide 2 | |
| 50–60 | 3a **Latest**, row 3: no timestamp → no summary ("— / 24 h", abstained) | live app | C1 |
| 60–68 | 3b Row 1: VTE prophylaxis late for a legitimate reason | live app | C2 |
| 68–95 | 3c `n` → stalled case lands; reason printed; Owner / next action; Confirm | live app | C2 C3 C4 |
| 95–115 | 3d Results & alerts: one organisation outside its limit; the org table | live app | C3 |
| 115–130 | 3e Audit report — the legal requirement, clinicians in the loop | live app | C5 |
| 130–160 | 4 How it works — the one technical slide | slide 3 | |
| 160–190 | 5 Roadmap and commercial path | slide 4 | |

Visible countdown on the presenter's screen. **Two people**: one speaks, one drives, from the printed beat list. Demo runs on recorded data — no model call at pitch time, no cold start. Appendix slides (six) sit behind a "Questions" slide for the 3-minute Q&A and never appear in the timed run.

## Narrative (speaker script)

### 1. Team (20 s) — slide 1

Three of us; one line each from the LinkedIn profiles given to the deck designer. What makes us suited: we have done audits by hand, and we know why they stop.

### 2. March 2020: handoffs broke first, and the check on them was switched off (30 s) — slide 2

Patients were lost between ED, the ward, ICU and follow-up. The NHS has one mechanism for finding where a pathway loses people — clinical audit — and it works: 292 randomised trials, +6.2 points of practice change; the hip-fracture audit took early surgery from 54 % to 71 % and cut 30-day mortality by a fifth.

But it runs on a clinician reading every note: 8 minutes 35 seconds per discharge summary, 28 hours per project, in unpaid time. So in March 2020, when the pathways were breaking fastest, NHS England suspended national audit by letter — VTE prophylaxis named in the list. The handoffs failed and the instrument that would have caught them went dark. **vigiLANCE is the audit that stays on.**

### 3. Demo — what the clinician sees (80 s) — live app

The beat-by-beat driver and speaker sheet is [demo_script.md](demo_script.md) — locked words, clicks, clock, fallbacks. Five beats on the **Latest** view: row 3, no timestamp → no summary (C1); row 1, late for a legitimate reason (C2); `n` — a stalled case lands, reason printed, owner and next action from the clinicians' protocol, Confirm (C2 C3 C4); Results & alerts — one organisation outside its limit, the organisation table: level two (C3); Audit report — the legal requirement, clinicians in the loop (C5). Check first and the H5 override stay ready for Q&A. Case ids in [demo_cases.txt](demo_cases.txt).

Flexibility line, spoken over the report: *"Handoffs are the example. Any standard with a yes/no criterion and a reason taxonomy fits the same harness — the protocol is the only thing that changes. It never raises a per-patient alert; this is audit, not surveillance."*

### 4. How it works (30 s) — slide 3, the one technical slide

Three bands under a boundary line that patient data never crosses.

- **The harness.** MedGemma **4B** reads every page, including handwriting and scans; **27B** adjudicates each case against the locked protocol — the protocol *is* the prompt, the reply is a guided-JSON schema with rationale before status and a verbatim quote for every claim; a **verifier** string-matches every quote to the page or it gets no rectangle; the **code**, not the model, computes elapsed hours from the quoted times; the **clinician** reviews; the **estimator** corrects; an **allowlist gateway** lets only counts, rates, intervals and taxonomy codes out — and 27B writes the report prose from those counts alone. Coded criteria are resolved by query, never by a model. Abstain is a first-class verdict.
- **Why reviewing a few cases is enough** — the PPI figure ([ppi_figure.svg](pitch/ppi_figure.svg), numbers in [ppi_figure.md](pitch/ppi_figure.md)). Left, H4, where the model agrees with the truth: the model-only interval is 5 points wide, prediction-powered inference keeps that width from five reviews on, and reviews alone need the whole cohort to match it. Right, H5, where the model is biased: the model-only interval contains the truth in **0 %** of 500 resamples at every review count; corrected, it reaches **93 % by ten reviews and 99 % by forty**. This is measured on our own cohort against planted truth, not a sketch.
- **The dataset.** Synthea COVID-19 — multi-organisation, full patient journeys, and incomplete exactly the way real records are. We sampled 1,500 inpatients, wrote 6,361 notes with a non-Google model (so MedGemma is never graded on its own prose), and rendered every one to a page image — typed, scanned and handwritten — so the pipeline reads pictures of notes, as a paper-based trust would need.

### 5. Roadmap and commercial path (30 s) — slide 4

Animation, three slots, the same harness each time — only the protocol box changes: **COVID handoffs** (today) → **hip fracture, surgery within 36 h** (the national audit from slide 2 — a YAML edit) → **trial eligibility, n2c2 2018** (288 patients, 13 expert-labelled criteria; a yes/no criterion type, and the same watch on every event becomes recruitment).

**Pilot:** in conversation with Cambridge University Health Partners and Cambridge Children's Hospital about shadow mode against a live manual audit; Cambridge runs Epic, one of 18 Epic trusts in England. **Beyond handoffs:** trial-eligibility screening for research groups and pharma — route through CUHP's ClinSilico consortium, target sponsors AstraZeneca and GSK, both Cambridge-based; per-clinician feedback on the standards clinicians are measured against. **The ask:** one Epic trust for shadow mode; one sponsor for an eligibility pilot. First customer is the trust audit department; the buyer is the medical director who signs the quality account.

## Slides (four + the live app + appendix)

| # | Slide | Content |
|---|---|---|
| 1 | Team | three names, roles, one line each; vigiLANCE wordmark + lance mark |
| 2 | March 2020: handoffs broke, the check went dark | the four handoff points; the March 2020 letter quote with VTE named; Cochrane +6.2pp, NHFD 54→71 %, 8 m 35 s, 27.8 h as one supporting line. Closes on "vigiLANCE is the audit that stays on" |
| — | Live app | constraint checklist overlay; queue (arrival) → stalled → legitimate → no data → H5 override → Results → Report |
| 3 | How it works | boundary line; band 1 harness (4B reads / 27B adjudicates / verifier / clinician / estimator / gateway, MedGemma boxes marked); band 2 the PPI figure; band 3 the dataset strip. **The only technical slide** |
| 4 | Roadmap and commercial | three-slot animation (COVID handoffs → hip fracture ≤ 36 h → n2c2 trial eligibility) over pilot (CUHP, Cambridge Children's, Epic ×18) / beyond handoffs (trials via ClinSilico → AZ, GSK; per-clinician feedback) / the ask |
| Q | Questions | blank divider |
| A1 | Is this a medical device? | aggregate only; MEDDEV 2.1/6; DPIA / DTAC / DCB0129/0160 |
| A2 | Who else does this | UCSD SEP-1, Salford, CogStack, Carta — and where vigiLANCE sits |
| A3 | What it gets wrong | H5 κ 0.505 and its cause; am/pm quotes unparsed 1,292; non-verbatim quotes 144; doc_id typos 64; all visible in the app |
| A4 | The statistics | naive vs corrected; the PPI figure at full size; tuning / estimation pool split |
| A5 | Synthetic data | Synthea COVID paper; notes by a non-Google model; render pipeline with page examples |
| A6 | Protocol flexibility | today: any timed handoff is a YAML edit; next: frontier-assisted authoring, yes/no criterion type |

## Key facts (cite on slides)

| Claim | Number | Source |
|---|---|---|
| Audit is statutory | CQC established to mandate clinical audit; providers must monitor quality incl. audit | Health and Social Care Act 2008; CQC (Registration) Regulations 2009; NHS Act 2006 — via NHSE best-practice guide §8.1 |
| Audit & feedback works | +6.2pp (95% CI 4.1–8.2), 292 RCTs | Ivers et al., Cochrane CD000259.pub5, 2026 |
| Hip fracture audit | early surgery 54.5→71.3%; 30-day mortality 10.9→8.5%; ~1,000 fewer deaths/yr | Neuburger et al., Med Care 2015 |
| Time per case | 8 min 35 s per discharge summary | Hudson et al., npj Digit Med 2026 |
| Time per project | mean 27.8 h (2–212); 12% re-audit; 27% "waste of time" | Leeds survey, PMID 9409499 |
| Non-completion | 57.9% of F1s failed to complete an audit | Br J Med Pract |
| Unpaid hours | 49.4% of staff | NHS Staff Survey 2025 |
| Policy | automate collection via EPR; near-real-time; release clinician time | NHSE Clinical audits and registries best practice guide, Feb 2026 |
| 2020 audit pause | "All national clinical audit, confidential enquiries and national joint registry data collection, including for national VTE risk assessment, can be suspended" (item 14) | NHSE, *Reducing burden and releasing capacity…*, March 2020 |
| LLM abstraction precedent | 90/100 agreement (κ 0.82); 4/10 disagreements were human error; 2026 cluster RCT improved compliance | Boussina et al., NEJM AI 2024; PMID 42348212 |
| Statistics | prediction-powered inference | Angelopoulos et al., Science 2023 |
| Local MedGemma in NHS | MedGemma 4B on hospital infrastructure | Healy et al., medRxiv 2026 (UCLH) |
| Epic in England | 14 trusts live (March 2026), 18 under contract after Somerset/Dorset | Verdict, 2026; Digital Health go-live reports |
| Our numbers | see [pitch/numbers.md](pitch/numbers.md) | S5 full run 2026-09-16; S6 estimate 2026-09-16; workbench with 150 seeded reviews 2026-09-17 |

Demo tie-in: H4 (admission → VTE prophylaxis) is the audit NHS England suspended by name in 2020 — it is the thread from slide 2 through the demo to the report. H5 appears once, as the handoff where the model is biased and a review moves the number.

## Anticipated questions (3 min)

- **Was that arrival live?** The case was read and adjudicated before the room — there is no GPU on stage. What is live is everything after: it lands in the queue, ranked, with its reason printed, without anyone refreshing. In service, that adjudication runs as the records land.
- **Why this patient, why now?** We prioritise the *team's* attention, not the patient's care: which handoff is losing the most hours this week, which ward is outside its funnel limit, which rows the clinician should check first and why (printed on the row). A per-patient alert would make this a medical device and put a model between a clinician and a patient; an audit does not.
- **Real-time?** Runs whenever records land; the estimate updates on every review. Lag is the reading time of the notes — minutes, not the months a manual audit takes.
- **Another system to check?** Audit is already mandated and already happens; we remove the chart-reading step and produce the report the trust already owes. Roadmap: launch from the EPR.
- **Why not just let the model do it?** Because the headline number then inherits model error you can't see — H5 in our own run: model breach count 84 vs 39 true. The model-only interval misses the truth in 500 out of 500 resamples; corrected, it holds it.
- **Why is H5 wrong, and can you fix it?** The two events are worded alike ("admitted to hospital" / "admitted to the intensive care unit"), the ED clerking carries the cleanest full time-and-date string, and our own worked example in the prompt starts with a hospital admission — so the model quotes the hospital time for the ICU event. It is the same mistake on every patient, which is why it biases the number instead of adding noise. Three fixes in cost order: reject a from-time quoted from the wrong document type (code, no re-run); reword the ICU gloss and use a neutral worked example (prompt version bump, ~2 h re-run); measure κ before and after. The point is that the corrected number was already right — the review loop makes it safe to ship with the bias still in.
- **What is κ?** Agreement beyond chance between the model's call and the truth: 1 is perfect, 0 is coin-flip. H4 is 0.998, H5 is 0.505 — moderate, and its disagreements all lean one way, which is bias.
- **Why would clinicians review at all if the model is good?** Default is they review everything — a minute per case instead of eight and a half. The correction is for when they can't.
- **Isn't this a medical device?** Aggregate-only, no per-patient output, no patient interaction. MEDDEV 2.1/6 device definition requires benefit to an individual patient. Written qualification opinion before deployment; DPIA/DTAC/DCB0129/0160 regardless.
- **Why MedGemma not a frontier model inside?** Data can't leave the trust. MedGemma runs locally; UCLH has done it. Frontier models only see aggregates.
- **Synthetic data — so what?** Synthetic lets us plant the truth and measure coverage and κ. We rendered the notes to scanned and handwritten pages to show it works for paper-based trusts. External validation next: n2c2 2018 track 1 (288 patients, 13 expert-labelled criteria), MIMIC-IV-Note under DUA.
- **What did MedGemma do?** Read every page (4B, including handwritten), adjudicated every case (27B), writes the report (27B, aggregates only). Claude wrote the synthetic notes so we weren't grading MedGemma on its own prose.
- **What does it get wrong?** Reason tags: 63 % agreement with the planted cause — indicative until reviewed, and the report says so. H5 as above. Quotes rewritten instead of copied fail verification (144 cites) and surface at the top of the queue — that is the design. All visible in the app, none hidden. Appendix A3 has the counts.
- **How flexible is the protocol?** Today: any timed handoff on any pathway is a YAML edit — criteria, events, targets, reasons, owners, actions. Next: a yes/no criterion type for eligibility screening, and frontier-model-assisted protocol drafting from the standard. We say which is which on the slide.
- **Per-clinician feedback?** Cochrane says individual feedback works best, but PSIRF just-culture concerns apply. Default is team/service level; individual views only to that clinician.
