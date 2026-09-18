# AuditPace

A pipeline that turns a clinician's audit question into a verifiable, interpretable audit: models read the records, clinicians review a formalised row per patient with click-to-source evidence, and the reported rate carries a valid confidence interval whatever fraction of rows the clinicians managed to review.

## Language

### Protocol

**Protocol**:
The locked, clinician-approved definition of one audit: question, cohort rule, criteria, standards cited, reason taxonomy, review fraction. Identified by its hash.
_Avoid_: study design, config, spec

**Criterion**:
One yes/no standard the protocol measures each patient against, with the clinical standard it derives from.
_Avoid_: metric, KPI, measure, rule

**Handoff**:
A criterion of the form "time from PathwayEvent A to PathwayEvent B must be within a target". The worked example in this project; not the only kind of criterion.
_Avoid_: transition, gap, delay (delay is the *breach*, not the criterion)

**Reason taxonomy**:
The fixed list of causes a criterion may be breached for, defined in the protocol. Always includes `other`.
_Avoid_: tags, categories, labels

**Review fraction**:
The share of cases the protocol asks clinicians to review. Default 1.0 (everyone). Below 1.0 the estimator corrects for the unreviewed remainder.
_Avoid_: sample size, sampling rate

### Cohort and truth

**Patient**:
A person in the cohort. Referenced by id only outside the boundary.

**PathwayEvent**:
A timestamped fact derived from structured records (e.g. "hypoxaemia recorded", "admitted", "ICU"). Deterministic; no model involved.
_Avoid_: milestone, encounter (an encounter is one source of events)

**Case**:
One patient measured against one criterion. The unit of review, the row in the workbench.
_Avoid_: interval (the interval is the case's measured value), item, record

**Breach**:
A case whose measured value fails the criterion's target.
_Avoid_: delay, failure, non-compliance

**Structured truth**:
What the timestamps say about a case (breached or not, by how long). Known exactly for synthetic data.

**Narrative truth**:
The reason a breach happened, as written into the documents. In synthetic data this is *planted* and recorded; in real data it exists only in the notes.
_Avoid_: ground truth (ambiguous between the two truths)

### Documents

**Document**:
One authored clinical artefact for a patient (ward note, referral letter, lab report, discharge summary). Has a text and a rendered form.
_Avoid_: note (a note is one document type), file

**Page**:
One rendered image of a document, with the true position of every word.

**Reading**:
What the reader models recovered from a page: the MedGemma transcript (`reading_text`), Tesseract's words with boxes, and a word-level alignment from transcript character offsets to boxes. Imperfect by design; the clinician can always see the page instead.
_Avoid_: OCR output, extraction

### Adjudication

**Verdict**:
The adjudicator's answer for one case: `breached`, `not_breached` or `abstain`, with reason tag and evidence.
_Avoid_: prediction, label (label is the clinician's), classification

**Evidence**:
A verbatim quote from a reading, tied to the page region it came from.
_Avoid_: citation, source, rationale

**Verified evidence**:
Evidence whose quote is found verbatim in the reading. Only verified evidence gets a page region. Unverified evidence is shown as such, never hidden.

**Abstain**:
A verdict meaning "no document supports a decision". A first-class outcome, not an error.

### Review

**Review**:
A clinician's judgement on one case: confirm, override (with their own status and reason), or flag. Persisted; the only thing the estimator treats as truth.
_Avoid_: annotation, adjudication (that's the model's step), validation

**Validation state**:
Whether a case is `unvalidated` (verdict only), `validated` (reviewed and agreed), `disputed` (reviewed and overridden) or `flagged`.
_Avoid_: status (collides with verdict status)

**Estimation pool / Tuning pool**:
Reviews are split: the tuning pool may inform prompt changes; the estimation pool is sealed until the protocol is locked and only ever feeds the estimator.

### Results

**Estimate**:
For one criterion: the breach rate with a confidence interval, plus reason breakdown, segmented by demographics and organisation.

**Naive estimate**:
Rate computed from verdicts alone. Shown for contrast; never reported as the result.

**Corrected estimate**:
Rate combining verdicts and reviews (prediction-powered inference). Equals the classical clinician-only estimate when review fraction is 1.0.

**Boundary**:
The line patient-level data never crosses. Readers, adjudicator, workbench and estimator live inside; design and report live outside.

**Gateway**:
The allowlist filter every outbound payload passes through. Rejects anything that is not a protocol identifier, count, rate, interval or taxonomy code.

**Report**:
The narrative audit output written from gateway-approved aggregates: findings, where time is lost, why, recommended actions with owners, methods, caveats.
