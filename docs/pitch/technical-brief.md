# AuditPace — technical brief for the deck

*Source material for slide 3 (the one technical slide) and appendix slides A3–A6. Written for the deck designer and the presenter. Everything here is as built and measured on 2026-09-16/17 unless marked **next**. Numbers: [numbers.md](numbers.md). Do not mention how the software was developed — this brief is about the audit workflow and how MedGemma is used.*

## 1. The audit workflow, end to end

One locked protocol drives every stage. Patient data never leaves the trust boundary; only aggregates cross it.

```
 INSIDE THE TRUST ──────────────────────────────────────────────────────────────┐
 protocol.yaml ─► cohort + events ─► read pages ─► adjudicate ─► verify ─► review ─► estimate ─┤ gateway ├─► report
 (clinician,      (deterministic     (MedGemma 4B, (MedGemma 27B (string   (clinician, (PPI,      (allowlist:  (MedGemma 27B,
  locked, hashed)  SQL on coded data) vision)        guided JSON)  match)    workbench)  intervals)  codes+numbers) aggregates only)
```

| Stage | What happens | What MedGemma does | What the code does instead of the model |
|---|---|---|---|
| Protocol | Clinician writes the question, cohort rule, events (SNOMED codes), criteria (from → to, target hours, standard, reasons), and the `actions:` block (owner per criterion; class *system* / *legitimate* and action per reason). `locked: true`; SHA-256 hash stamps every downstream row. | nothing | validates schema; hash-locks; `actions:` is hash-exempt so owners can change without invalidating verdicts |
| Cohort + events | Patients selected and every event answerable from coded data resolved by query. | nothing | all of it — a model never decides who is in the cohort |
| Read | Every page image (typed, scanned, handwritten) is read to text with word-level bounding boxes. | **MedGemma 4B (vision)** | keeps the page ↔ text alignment so a quote can be drawn back onto the page |
| Adjudicate | For each case × handoff: met / not met / abstain, with a verbatim quote for the start event, the end event and the reason. | **MedGemma 27B**, one call per case, guided-JSON schema | computes elapsed hours from the two quoted times and sets the status itself; `model_status` is stored for the methods section only |
| Verify | Every quoted string is searched on the cited page after normalisation. | nothing | found → rectangle on the page; not found → red "evidence not verified" badge, no rectangle, row rises in the queue |
| Review | Workbench: queue ordered by printed reason; case view with page and rectangles; confirm / override / flag with reason tags. | nothing | reviews are the only labels the estimator trusts; a review never overrides an abstain |
| Estimate | Corrected breach rate + 95 % interval per handoff and segment; stalled / legitimate / undetermined split; funnel and run charts; time lost; alerts with action + owner; review queue priority. | nothing | prediction-powered inference; provisional label when < 20 reviews or no disagreement yet |
| Gateway | Allowlist of what may leave: protocol and criterion ids, counts, rates, intervals, reason codes, action/owner codes. Free text, quotes, identifiers rejected; every outbound payload logged. | nothing | schema validation + append-only log |
| Report | NHS England best-practice-guide structure: findings, actions, owners, methods, caveats. | **MedGemma 27B** writes the prose from the gateway payload only; every printed number is checked back against the payload | rejects any number in the prose that is not in the payload |

## 2. Working with MedGemma — what we learned and built in

*Slide 3, column 1: "Work with MedGemma".*

- **Split the record.** The coded half (timestamps, prescriptions, encounter codes) is resolved by query. MedGemma reads only the free-text half — where the *reason* lives ("enoxaparin withheld — platelets 38").
- **Two models, two jobs.** 4B with vision reads pages, including handwriting and scans, so a paper-based trust is in scope. 27B (text) adjudicates: it gets the locked criterion, the event glosses, the reason taxonomy and the patient's documents in one ≈ 3.5 k-token prompt.
- **Structure imposed on unstructured notes.** Reply is a guided-JSON schema enforced at decode time — no free-form output. Field order matters: `rationale` before `status`, otherwise the model commits to a status and reasons backwards.
- **Quote, don't paraphrase.** Every claim must carry a verbatim quote and a document id. Paraphrases fail verification and become visible.
- **Never trust the model's arithmetic.** 27B compares "7.25 hours" to a 4-hour target and says "not greater". So the code parses the two quoted times and computes hours and status. 8.9 % of verdicts have `model_status ≠ computed status`; the computed one is used every time.
- **Few-shot examples leak.** The prompt's worked example was copied verbatim as an answer in 2 cases; both sit at the top of the queue with a printed reason. **Next:** non-imitable example and rejection of quotes equal to the example.
- **Abstain is a verdict.** No end event → "no follow-up documented" (1,020 cases), not compliance, not breach. Time quoted for both events identical → abstain. Unparseable time → abstain. Abstains are counted as their own category in every estimate.

Throughput on one NVIDIA H100 NVL (96 GB): 6,220 adjudications in 1 h 54 min (≈ 9 s per case, 8 in flight). Reads and adjudication are resumable per batch and versioned by protocol hash and prompt hash.

## 3. Containing what it gets wrong

*Slide 3, column 2.*

| Guard | What it catches | Measured |
|---|---|---|
| Verifier (exact substring after normalisation, ≥ 8 chars) | rewritten quotes, wrong document, inserted tokens ("11:31 pm" on a page that says "11:31") | 97.7–98.7 % of quotes verified; 144 not-verbatim cites and 64 mis-copied doc ids all surfaced with badges |
| Code-computed status | model arithmetic errors, wrong direction, negative gaps | 392 model-not-breached rows are computed breached; H5's 46 false breaches are exposed by κ 0.505 |
| Abstain first-class | missing end event, unparseable time, same time for both events | 1,241 abstains, 1,020 by design |
| Gateway allowlist | any free text, quote or identifier trying to reach the report writer | every outbound payload validated and logged |
| Report back-check | any number in the prose not present in the payload | rejected before the report is written |

## 4. Clinician and model both in the loop

*Slide 3, column 3.*

- **Review queue prints the reason.** Priority = model call ≠ computed status · evidence not verified · abstained though an end event exists · in an alerted cell · few reviews on this handoff · largest interval leverage. This orders the *team's* checking, never a patient's care (ADR 0005).
- **Prediction-powered inference (Angelopoulos et al., Science 2023).** The model reads every case; the clinician reviews what they can. The reviewed rows estimate the model's error and correct the rate on the rest. The interval is valid whatever fraction was reviewed: wide but honest at 10 rows, narrowing live as reviews land.
- **Measured on our own bias.** H5 is the handoff where the model is systematically wrong. Model-only 95 % interval contains the truth **0 %** of the time at every review fraction. Corrected: 59 % at 2 % reviewed (4 rows), 91 % at 5 %, 96 % at 10 %, **98 % at 20 %**, 100 % at 50 %. Width cost: 0.26 vs 0.13 at 20 %. Every other handoff: both 100 % (model unbiased there). Chart: `coverage_h5.png`.
- **Honesty rule for small samples.** Fewer than 20 reviews, or no review has yet disagreed with a verdict → the interval is labelled *provisional* in the app and in the report caveats.
- **Overrides move the number on screen.** Demo: one H5 override moves the corrected rate 29.7 % → 25.9 %; the naive rate does not move.
- **Default is review everything.** A minute per case instead of eight and a half. The correction is for the night shift, the pandemic, the one registrar covering the ward.

## 5. Synthetic data — what we used and what we added

- **Cohort:** Synthea COVID-19 synthetic patient set (2020; cite the Synthea COVID dataset manuscript in the Drive folder). 1,500 inpatient COVID-19 patients sampled, stratified by ICU and death.
- **Planted truth:** breach rates and a true reason per breach are set in the protocol's `synthetic:` block, so κ, reason accuracy and interval coverage are measurable — impossible on real data without a second manual audit.
- **Notes authored by a different model family** (Claude Sonnet, ADR 0003): 6,361 documents in UK clinical register — ED clerking, ward rounds, ICU notes, discharge summaries, clinic letters, lab reports. MedGemma is never graded on its own prose.
- **Rendered to pages:** every document becomes page images in typed, scanned and handwritten styles, then read back by MedGemma 4B with bounding boxes. This is the feasibility claim for trusts that still scan paper: the pipeline never sees the source text, only the page.
- **Known gap:** synthetic notes are cleaner than real ones. External validation planned on n2c2 2018 track 1 (288 patients, 13 expert-labelled eligibility criteria) and MIMIC-IV-Note under DUA.

## 6. Protocol flexibility — today and next

*Appendix A6; the three-slot animation. Say which is which.*

**Today (as built).** The protocol is a YAML file the clinician owns. Changing the audit means editing values, not code:

```yaml
- id: H4
  name: "Admission to VTE prophylaxis"
  type: handoff
  from: admitted           # events: table + SNOMED code, resolved by query
  to: enoxaparin
  target_hours: 24
  standard: "NICE NG89 VTE prophylaxis"
  reasons: [not_prescribed, prescription_unsigned, contraindication_documented, drug_shortage, other]
actions:
  H4:
    owner: "Ward pharmacist / trust VTE lead"
    compliance_target: 0.9
    reasons:
      not_prescribed:              {class: system,     action: "VTE prophylaxis on admission clerking checklist; pharmacist reconciliation within 24 h"}
      prescription_unsigned:       {class: system,     action: "Unsigned charts escalated at morning ward round"}
      contraindication_documented: {class: legitimate, action: "None — confirm mechanical prophylaxis offered"}
```

Any timed handoff on any pathway — hip-fracture surgery ≤ 36 h (NHFD), sepsis antibiotics ≤ 1 h, stroke thrombolysis door-to-needle — is a new criterion block with its own events, target, reasons, owner and actions. The adjudication prompt, the verifier, the estimator, the alerts and the report all read from the protocol; nothing about COVID is in the code path except the event codes named in the protocol.

**Next (roadmap, not built).**
1. **Yes/no criterion type** for eligibility screening: "has a major diabetes complication documented", "creatinine above ULN in the last 12 months". The adjudication schema today requires two quoted times; a `type: presence` criterion needs one quoted passage and no arithmetic. Target: n2c2 2018 track 1's 13 criteria.
2. **Frontier-assisted protocol authoring.** A frontier model (e.g. Gemini Pro), given the trust's coding conventions and the guideline text, drafts the protocol — cohort rule, events, criteria, reasons, owners — for the clinician to edit and lock. No patient data is involved at this step, so it can run outside the boundary. Today the protocol is hand-written.
3. **Live update on a new handoff.** When a new record lands, the case is read, adjudicated and folded into the estimate within minutes; the run chart moves the same day.

Animation slots for the deck: COVID handoffs (today) → hip-fracture surgery ≤ 36 h (today, YAML edit) → n2c2 trial eligibility (next, needs the presence criterion).

## 7. Safety and governance in one paragraph (appendix A1)

Aggregate outputs only: service-level rates with intervals; no recommendation, risk score, diagnosis or alert about an individual patient; no patient interaction. MEDDEV 2.1/6 (followed by MHRA) requires a medical purpose for the benefit of the individual patient — population-level measurement sits outside; a written qualification opinion precedes any deployment. Regardless: DPIA, DTAC, DCB0129/0160. Data never leaves the trust (MedGemma runs locally; UCLH has run MedGemma 4B on hospital infrastructure). Feedback at team level by default; per-clinician views only to that clinician (PSIRF just culture). A reviewer who spots a safety issue escalates through clinical governance, not through the tool.
