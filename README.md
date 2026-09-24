# vigilance

**The clinical audit that stays on.** Patient pathways lose time and people at the handoffs. vigilance reads the records, shows a clinician where each patient stalled and why, and reports a number the trust can sign.

Built in one day at the Adeline Sprint Sessions Health x AI Hackathon (Google HQ London, 18 September 2026), Track 2 — *Pathway Breakdown: closing the gaps at care handoffs* (AlbionVC). Uses Google's Health AI Developer Foundations models: **MedGemma 4B** (vision) reads the pages, **MedGemma 27B** adjudicates and writes the report prose.

## The problem

Clinical audit is how the NHS finds where a pathway loses time. It is statutory, it works (Cochrane: +6.2 points of practice change across 292 trials), and it stops the moment a ward gets busy — because the data collection is a clinician reading notes by hand: 8 min 35 s per discharge summary, 28 hours per audit project, mostly unpaid. In March 2020, when the pathways were breaking fastest, national audit was switched off by letter.

## What it does

1. **Protocol.** A clinician writes the audit as YAML: which handoffs, the target hours and the standard they come from, which reasons count as a *legitimate wait* and which as a *stalled patient*, and who owns the fix. Locked and hashed; everything downstream reads from it. See `protocol.yaml`.
2. **Cohort.** Code queries the coded record (encounters, conditions, medications) to decide who is in the cohort and which handoffs apply. No model.
3. **Read.** MedGemma 4B transcribes every page image — typed, scanned or handwritten — and Tesseract supplies word positions, so any quote can be pointed at on the page.
4. **Adjudicate.** MedGemma 27B, one guided-JSON call per case, returns three verbatim quotes: start event, end event, reason. Code verifies each quote exists on the page, computes the hours from the quoted times and sets the status itself. Abstain is a first-class outcome. The model's own arithmetic is never used.
5. **Review.** The workbench: a queue ordered by *why check this next*, a case page with the quote highlighted on the real page, Confirm / Override / Flag in a minute per case.
6. **Estimate.** Reviews correct the breach rate for the cases nobody checked (prediction-powered inference, Angelopoulos et al. 2023), so the confidence interval is valid whatever fraction was reviewed. Alerts name an action and an owner from the protocol.
7. **Report.** The audit report in NHS England's structure, written from counts and rates only. Clinicians can edit a draft, download it as Markdown, or export it to PDF.

It orders the team's checking, never a patient's care: aggregate outputs only, no per-patient alert. Audit, not surveillance.

## The five constraints, live

| Constraint | Where it is met |
|---|---|
| Works from incomplete, inconsistent data without inventing what is missing | Abstain on missing or unparseable times; a quote not found on the page gets a red badge and no rectangle; the report gateway is an allowlist |
| Distinguishes a stalled patient from one legitimately waiting | Every reason carries a class from the protocol: *system* (stalled) or *legitimate*; only stalled breaches count as time lost |
| Every alert names a specific next action and an owner | Alerts carry action and owner from the protocol's `actions:` block, never from the model |
| Justifies its prioritisation | Every queue row prints why it is next; results rank handoffs and organisations by hours lost |
| Usable inside an existing workflow | Clinical audit is the existing, statutory workflow; the output is the report the trust already owes |

## Repository

```
protocol.yaml          the locked audit definition (six COVID-19 admission-pathway handoffs)
config.yaml            paths and model endpoints
src/auditpace/         one package, one CLI, one subcommand per stage
  cohort/ synth/ render/ read/ adjudicate/ estimate/ report/ workbench/
scripts/               sanity gates, review seeding, demo reset
tests/                 pytest, mock mode needs no GPU
deploy/                container, compose and Caddy drop-in for the hosted demo
docs/                  pitch, demo script, rubric fit, decisions (ADRs), setup and rebuild runbooks
```

The package and CLI are still called `auditpace`; vigilance is the product name.

## Quick start

```bash
uv venv --python 3.12 && uv sync --extra dev
uv run auditpace protocol validate
make test                       # mock mode, no GPU, ~1.5 min
```

The workbench serves recorded pipeline outputs — no model call at review time:

```bash
uv run auditpace workbench --port 8080
# http://127.0.0.1:8080/home      landing page
# http://127.0.0.1:8080/queue     review queue   (?demo=1 adds the pitch assistant)
```

Running the pipeline end to end needs the Synthea COVID-19 dataset, a Hugging Face licence for MedGemma and a GPU for the read and adjudicate stages (`make serve`). Stage order and timings are in `docs/rebuild.md`; `docs/setup.md` covers the model server.

## Data

Synthetic only. Cohort: 1,500 inpatient COVID-19 patients from the Synthea COVID-19 dataset (6,220 patient × handoff cases). Clinical notes were authored by a non-Google model so MedGemma is never graded on its own prose, then rendered to typed, scanned and handwritten page images. Breach rates and true reasons are planted, which is what lets us measure agreement (pooled κ 0.97 against planted truth; H5 κ 0.51 where the model is systematically biased, which the review loop corrects). No real patient data anywhere.

## Team

Davod Shah · Timotej Cvikl · with Google MedGemma.

## Licence

MIT — see `LICENSE`.
