# Synthetic documents are authored by Claude, never by MedGemma

Synthea provides structured records only; we author the clinical documents. If MedGemma wrote the notes MedGemma is later evaluated on, reader and adjudicator scores would partly measure fluency on its own prose. Documents are therefore generated with Claude (`claude -p`, Sonnet). This also keeps the "MedGemma at every in-boundary step" claim honest: MedGemma reads, it does not write the test.
