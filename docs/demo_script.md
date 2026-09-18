# vigiLANCE — demo script (≈ 80 s, five beats)

*Speaker talks, Driver clicks. Rows verified in the browser 2026-09-18 (after the workbench restyle merge, `38128e3`) against the reset state. Before every run: `make demo-reset` (≈ 30 s), open `http://127.0.0.1:8080/queue?demo=1`; click **Pitch assistant** (bottom-right) — the sheet's last line must read `held: 1 (n to release)` — and rows 1–3 wear the yellow "just landed" badge. Leave the sheet open; it carries the audit block, progress bar and the C1–C5 ticks. Demo starts at 0:50 of the pitch; ends ≈ 2:10, leaving buffer for the slides.*

Driver keys: `n` = release the held case (click the page title first so focus is off the text boxes) · `Esc` = back to the queue (the case page has no back button).

| Clock | C | Screen | Driver | Speaker |
|---|---|---|---|---|
| 0:50 | C1 | **Review queue**, chip **Latest**. Row 3 `d5a13f55` H4: hours column reads **— / 24.0 h**, status *abstained (end event exists)*, reason column *model said breached*. | Point at **row 3**. Don't click. | "Newest records first. Row three: the note gives a date for the first dose but no time. No timestamp, no summary — we don't fill gaps with guesses. It shows as a dash against 24 hours and waits for a clinician." |
| 1:00 | C2 | Row 1 `8eeabeae` H4, status *breached — legitimate wait*, reason *contraindication documented*, 178 h. | Point at **row 1**. | "Row one: VTE prophylaxis 178 hours late — for a legitimate reason: enoxaparin withheld, platelets 38. Counted, but not as a stalled patient." |
| 1:08 | C2 C3 C4 | New **row 1** `1f6e17d1` H4 slides in, "just landed", status *breached — stalled*, reason *prescription unsigned*. | Click the page title, press **`n`**. Click the **why-this-row text** under the patient id of row 1 (ticks C4; case opens). Point at the **Next step** card on the right (Owner: *Ward pharmacist / trust VTE lead*; Action: *Unsigned charts escalated at morning ward round*). Click **Confirm** (single primary button). Back on the queue, row 1 shows ✓. | "And one lands as the record arrives. Prophylaxis delayed because the prescription was unsigned — a stalled patient. Every row prints why it's here. The ward pharmacist is notified — chosen in the protocol the clinicians wrote and locked, not by the model. Information to inform a change in care; never a recommendation about the patient." |
| 1:35 | C3 | **Results & alerts**. Six handoff cards on top; scroll to **Alerts** — card 1: `alarm high · H1 · Organisation 37b4d73f is outside the funnel limit`; then **Time lost → By organisation** table just below. | Click the tab. Scroll past the handoff cards to **Alerts**, point at **card 1**, scroll on to the **By organisation** table. | "That serves the clinical team. Level two is the organisation: eighty-six organisations on one page — this one is outside its limit on swab-to-result, 197 hours lost, owner named. Regional management from the same numbers." |
| 1:55 | C5 | **Audit report**. | Click the tab. Tick **C5** by hand. | "And the report: the clinical audit the trust is legally required to run, written from counts only, with clinicians in the loop on every row. This is the audit that stays on." |
| 2:10 | | | Back to slides. | Slide 3. |

## Positions (reset state)

| View | Row | Case | Beat |
|---|---|---|---|
| Latest | 3 | `d5a13f55…:H4` | C1 — pointed at: "— / 24.0 h", abstained (end event exists) |
| Latest | 1 | `8eeabeae…:H4` | C2 — pointed at: legitimate wait |
| Latest after `n` | 1 | `1f6e17d1…:H4` | C2 C3 C4 — opened via the why-this-row text; Next step card; Confirm |
| Results, card 1 | — | H1 · org `37b4d73f` | C3 — alarm high |
| Results, scroll to Time lost | — | By organisation table | level two |

Not shown but ready if a judge asks for more: **Check first** row 1 `11ea4e1b` (the reason order); **`9f786`** row 1 H5 — Override → not breached → Results **H5 card** (or its `detail` link): corrected 29.7 → 25.9 %, naive stays 38.4 %.

## Fallbacks

- `n` does nothing → open **Pitch assistant** and click the `held: 1` line; or `curl -X POST http://127.0.0.1:8080/demo/release`. If the sheet says `held: 0`, type `1f6e1` in the case-id box; it is row 1.
- Wrong page → `Esc`; the queue keeps its filters and scroll.
- Server down → `make demo-reset` (30 s), restart at 0:50.
- Report tab empty → `cp docs/report.fallback.md docs/report.md`, reload.

## If asked

- **Was that live?** "Adjudicated before the room — no GPU on stage. What is live is the queue: it lands ranked, with its reason printed, without a refresh. In service the adjudication runs as records land."
- **Why this patient, why now?** "We order the team's checking, not the patient's care. A per-patient alert would make this a medical device." Then show **Check first**.
- **What if the model is wrong?** Show `9f786` → override → H5 moves. "The corrected number is the one the trust signs."
- **Why did the model get H5 wrong?** Two events worded alike, the ED clerking carries the cleanest timestamp, and our worked example starts with a hospital admission. Same mistake on every patient — bias, not noise; the review loop corrects it.
