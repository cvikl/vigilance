"""Replays the recorded MedGemma 1.5 4B transcripts for the mini cohort. Re-record after any
change to READ_PROMPT, the reader model, or anything that changes the page JPEG bytes
(RENDER_VERSION), with the 4B server up (`ONLY=4b make serve`):
    AUDITPACE_RECORD=1 uv run pytest tests/read/test_replay.py -q
RECORD is captured at import because the mini_documents fixture deletes AUDITPACE_RECORD.
"""
import os

from auditpace.models import ModelClient
from auditpace.read.stage import ReadStage

RECORD = os.environ.get("AUDITPACE_RECORD") == "1"


def test_mini_pages_replay_recorded_transcripts(mini_settings, locked_protocol, mini_pages, tessdata_dir):
    client = ModelClient(mini_settings.models.reader, mock=True,
                         fixtures_dir=mini_settings.paths.fixtures_dir, record=RECORD)
    stage = ReadStage(mini_settings, locked_protocol, mini_pages, client=client)
    s = stage.run()
    assert (s.n_in, s.n_out, s.n_quarantined) == (1, 1, 0)
    assert stage.n_fallback == 0, "a recorded reply was length-capped or empty; delete it and re-record"
    r = mini_pages.read("readings")
    assert (r.reader_used == "medgemma").all()
    typed, hand = r[r["style"] == "typed"], r[r["style"] == "handwritten"]
    assert typed.cer_medgemma.median() < 0.15
    assert typed.cer_tess.median() < 0.10
    assert typed.align_frac.median() > 0.8
    if len(hand):
        assert hand.cer_medgemma.median() < 0.40 and hand.cer_tess.median() < 0.60
    print("\nCER by style × reader:\n", r.groupby("style")[["cer_tess", "cer_medgemma", "align_frac"]].median())
