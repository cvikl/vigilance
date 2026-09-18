"""Replays the recorded claude -p response for the mini cohort. Re-record after any change to
SYSTEM_PROMPT, the plan, the phrase banks or the mini cohort:
    AUDITPACE_MOCK=1 AUDITPACE_RECORD=1 uv run pytest tests/synth/test_replay.py -q
"""
import json

from auditpace.synth.stage import SynthStage
from auditpace.synth.validate import BANLIST, fact_needle


def test_mini_batch_replays_recorded_documents(mini_settings, locked_protocol, mini_store):
    s = SynthStage(mini_settings, locked_protocol, mini_store)  # real ClaudeCLI in mock/record mode
    summary = s.run()
    assert (summary.n_in, summary.n_out, summary.n_quarantined) == (1, 1, 0)
    docs = mini_store.read("documents")
    assert 15 <= len(docs) <= 30
    assert docs.text.str.split().str.len().between(60, 600).all()
    assert not docs.text.str.contains(BANLIST).any()
    for d in docs.itertuples():
        for f in json.loads(d.planted_facts):
            # terminal punctuation may be swallowed into a continued sentence (validate.py)
            assert fact_needle(f["text"]) in d.text, (d.doc_id, f["fact_id"])
