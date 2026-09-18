# vigiLANCE — numbers for the deck

*Fact sheet for slides, appendix and Q&A. Every figure below was measured on the full synthetic cohort; source and date on each line. Use these verbatim — do not round further than shown. Owner: D. R. Shah. Snapshot 2026-09-17.*

## Cohort and documents (S1–S3, 2026-09-13/14)

| Item | Value | Note |
|---|---|---|
| Source | Synthea COVID-19 synthetic cohort (100k patients, 2020) | cite the Synthea COVID dataset manuscript (in Drive folder) |
| Sampled patients | 1,500 | inpatient COVID-19, stratified by ICU / died, seed 42 |
| Handoffs (criteria) | 6 | H1 suspected→confirmed 24 h · H2 hypoxaemia→admission 4 h · H3 admission→ICU · H4 admission→VTE prophylaxis 24 h (NICE NG89) · H5 ICU→ventilation 6 h · H6 discharge→follow-up |
| Cases (patient × applicable handoff) | 6,220 | |
| Documents authored | 6,361 | lab_report 1,500 · ed_clerking 1,416 · ward_round 1,416 · discharge_summary 1,385 · clinic_letter 363 · icu_note 281 |
| Who wrote the notes | Claude Sonnet, not MedGemma | ADR 0003 — MedGemma is never graded on its own prose |
| Rendering | every document rendered to page images: typed, scanned, handwritten styles | S3; pages read back by MedGemma 4B (vision) — feasibility for paper-based / scanning trusts |
| Planted truth | breach rates by handoff: H1 20 % · H2 30 % · H3 25 % · H4 35 % · H5 15 % · H6 40 %; true reason per breach | this is what lets us measure κ and coverage |

## Adjudication (S5 full run, 2026-09-16, MedGemma 27B, vLLM guided JSON)

| Item | Value |
|---|---|
| Verdicts | 6,220, 0 errors, 0 quarantined |
| Wall clock | 1 h 54 min at 8 workers (≈ 9 s per case, ≈ 55 cases/min aggregate) |
| Status split | not_breached 3,534 · breached 1,445 · abstain 1,241 |
| Abstain by design | 1,020 cases have no documented end event (H6 no follow-up 1,015; H4 5) — reported as "no follow-up documented", never as compliance |
| Abstain for real | 234 of the 5,200 end-present cases (4.5 %) — quote without a time (156), time in an unparsed form (65), gap guard (13) |
| Agreement vs planted truth | 0.987 on 4,966 called rows; **pooled κ 0.968** |
| κ per handoff | H1 1.000 · H2 0.972 · H3 0.982 · H4 0.998 · **H5 0.505** · H6 1.000 |
| H5 failure | all 46 disagreements are false breaches: the model quoted the ICU note's *hospital*-admission time as ICU admission; model breach count 84 vs 39 true |
| Reason-tag accuracy | pooled 0.632 (H1 0.33 · H2 0.56 · H3 0.67 · H4 0.82 · H5 0.63 · H6 0.77) — indicative until reviewed; the report says so |
| Time quotes found on page | from 97.9 % · to 99.2 % |
| Time quotes verified (rectangle drawn) | from 97.7 % · to 98.6 % |
| Reason quotes found / verified | 99.0 % / 98.7 % |
| Code-computed hours agree with truth | 97.7 % |
| model_status ≠ computed status | 8.9 % (443 / 4,979) — the code's status is always used; the model's own arithmetic is not trusted |

## Estimation (S6, 2026-09-16, no reviews; workbench 2026-09-17 with 150 seeded reviews)

| Handoff | n estimable | naive breach rate (95 % CI) | corrected with 25 reviews each | note |
|---|---|---|---|---|
| H1 | 1,454 | 19.3 % (17.4–21.4) | 19.3 % (17.3–21.4) provisional | no review disagreed |
| H2 | 1,317 | 29.5 % (27.1–32.1) | 29.5 % (27.1–32.0) provisional | |
| H3 | 271 | 28.4 % (23.4–34.1) | 28.4 % (23.0–33.8) provisional | |
| H4 | 1,381 | 35.4 % (32.9–38.0) | 35.4 % (32.9–37.9) provisional | below 90 % target → alert |
| **H5** | 219 | **38.4 % (32.2–44.9)** | **29.7 % (16.2–43.1)** | model biased; correction moves the point and widens honestly |
| H6 | 324 | 38.6 % (33.4–44.0) | 38.6 % (33.3–43.9) provisional | most hours lost of any handoff |

Demo override (H5 case `9f78628c…`, override to not_breached): corrected 29.7 % (16.2–43.1) → **25.9 % (10.9–40.8)**; naive stays 38.4 % (32.2–44.9). Measured 2026-09-16 on the seeded store; reverted afterwards.

"Provisional" rule: interval is labelled provisional when fewer than 20 rows are reviewed or no review has yet disagreed with a verdict (the corrected interval then equals the naive one relabelled). Stated in the app and in the report caveats.

## Coverage experiment (S6, 500 simulated review draws per point, `coverage_h5.png`)

| Fraction reviewed | 2 % | 5 % | 10 % | 20 % | 50 % | 100 % |
|---|---|---|---|---|---|---|
| H5 naive coverage | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| H5 corrected coverage | 0.588 | 0.910 | 0.964 | **0.982** | 1.000 | 1.000 |
| H5 corrected mean width | 0.39 | 0.37 | 0.32 | 0.26 | 0.20 | 0.10 |
| H5 naive mean width | 0.128 at every fraction (narrow, confident, wrong) |

Every other handoff: naive and corrected coverage 1.000 at every fraction (model unbiased there). Slide sentence: *"On the handoff where the model is biased, the model-only interval contains the truth 0 % of the time. Corrected, 98 % after reviewing one case in five."*

## Alerts, time lost, queue (S6/S7)

| Item | Value |
|---|---|
| Alerts fired | 11 on the seeded store (9 before reviews): org_outlier H1 ×2, H2 ×2, H4 ×1, H5 ×2, H6 ×1 · org_exemplar H1 · criterion_below_target H4 · top_time_lost H6 |
| Every alert carries | signal, rate + CI, n, hours lost, dominant reason, **action**, **owner**, one-sentence justification — action and owner come from the protocol's `actions:` block, written by the clinician |
| Hours lost (system breaches, Σ excess over target) | H6 41,186 h · H4 11,694 h · H1 6,975 h · H5 5,909 h · H2 2,485 h · H3 1,052 h |
| H4 alert text | "H4 overall: 35 % breached (CI 33 %–38 %, n = 1381); compliance at most 67 % vs target 90 %" → action "Review at monthly audit meeting", owner "Ward pharmacist / trust VTE lead" |
| Review queue | 6,220 rows; every row prints its priority reason; 677 rows carry "model call ≠ computed status" |
| Queue page load | 0.4–0.7 s for 6,220 rows; a review click 1.5–3 s (estimate recomputed live) |

## Verdict-failure classes (measured 2026-09-17, for appendix A3 — honesty slide)

| Class | Count | Caught by |
|---|---|---|
| Quote not verbatim → not found on page | 144 cites (82 recoverable: the timestamp is on a page) | verifier → red badge, no rectangle, row rises in queue |
| doc_id mis-copied (UUID transposition) | 64 cites | verifier |
| am/pm inserted by model, page has none | 19 quotes | verifier + parser |
| Prompt worked-example copied as the answer | 2 verdicts (both at the top of the queue) | code abstains on a −225 h gap; verifier |
| Model not_breached vs computed breached | 392 rows | code computes status from quoted times |
| H5 hospital-admission quoted as ICU admission | 46 cases | κ 0.505 visible in app; clinician override |

Line for the slide: *"Every one of these is on screen, at the top of the queue, with a printed reason. None is hidden, none is invented."*

## Rubric cross-reference

C1 abstain 1,241 + verifier badges · C2 stalled / legitimate / undetermined split (H4: 381 system, 107 legitimate, 1 undetermined) · C3 11 alerts with action + owner · C4 priority reason on every row; time-lost ranking · C5 NHSE-structure report from aggregates only.

## External figures (already sourced in `pitch.md` Key facts)

Cochrane +6.2 pp (292 RCTs) · NHFD 54.5→71.3 % early surgery, mortality 10.9→8.5 % · 8 min 35 s per discharge summary (Hudson 2026) · 27.8 h per audit project · NHSE March 2020 letter item 14 · Boussina NEJM AI 2024 κ 0.82 · Epic: 14 trusts live March 2026, 18 under contract.

## PPI figure (scripts/ppi_figure.py, 2026-09-18, 500 resamples per point, seed 42)

| Item | Value |
|---|---|
| H4 (N = 1,381 estimable cases; true rate 35.3 %, model 35.4 %) | PPI 95 % interval width **5.0 pp at 5 reviews** and at every review count; reviews-only 60 pp at 5, 38 pp at 20, 13 pp at 200, 5 pp only with all 1,381 reviewed |
| H5 (N = 219; true rate 17.4 %, model 38.4 %) | model-only (naive) interval contains the truth in **0 of 500** resamples at every review count; corrected (PPI) 69 % at 5 reviews, **93 % at 10, 97 % at 15, 99 % at 40**, 100 % from 100 |
| Honest caveat | on H5 the corrected interval is no narrower than reviews-only (the model adds no information when it is biased) — it is *valid*, which the naive one is not; on H4 it is 10× narrower than reviews-only at 20 reviews |
| Full table | `docs/pitch/ppi_figure.md` |

## Live report (2026-09-18, 27B, run rpt-20260918T103336)

| Item | Value |
|---|---|
| Paragraphs sent / rejected by the prose back-check | 1 payload; 2 of 21 paragraphs rejected → placeholder text; `model_unavailable=0` |
| Fallback | `docs/report.fallback.md` (`--no-model`), identical tables and figures, narrative withheld |
