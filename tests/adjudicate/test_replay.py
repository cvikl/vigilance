"""Replays the recorded MedGemma 27B adjudications of the mini cohort. Re-record after any change
to SYSTEM_PROMPT / USER_TEMPLATE / EVENT_GLOSS / REASON_GLOSS / reply_schema / the adjudicator model, or to anything upstream
that changes reading_text (READ_PROMPT, RENDER_VERSION), with the 27B server up (`ONLY=27b make serve`):
    AUDITPACE_RECORD=1 uv run pytest tests/adjudicate/test_replay.py -q -s
RECORD is captured at import because fixtures delete AUDITPACE_RECORD.
"""
import json
import os

from auditpace.adjudicate.stage import AdjudicateStage
from auditpace.models import ModelClient

RECORD = os.environ.get("AUDITPACE_RECORD") == "1"


def test_mini_cases_replay_recorded_verdicts(mini_settings, locked_protocol, mini_readings):
    client = ModelClient(mini_settings.models.adjudicator, mock=True,
                         fixtures_dir=mini_settings.paths.fixtures_dir, record=RECORD)
    stage = AdjudicateStage(mini_settings, locked_protocol, mini_readings, client=client)
    s = stage.run()
    # A recorded reply that fails validation surfaces here, not as stage.n_errors: the retry
    # appends RETRY_NOTE, which the mock client has no fixture for (MockMissing, uncaught),
    # quarantining the batch — delete the stale fixture(s) and re-record.
    assert (s.n_in, s.n_out, s.n_quarantined) == (1, 1, 0)
    assert stage.n_errors == 0
    v = mini_readings.read("verdicts")
    cases = mini_readings.read("cases")
    m = v.merge(cases[["case_id", "breached", "true_reason", "end_ts", "hours"]], on="case_id")
    has_end = m[m.end_ts.notna()]
    called = has_end[has_end.status != "abstain"]
    print(f"\nmini: {len(m)} cases, {len(has_end)} with end_ts, {len(called)} called, "
          f"{(m.end_ts.isna() & (m.status == 'abstain')).sum()} expected abstains")
    print(m[["case_id", "status", "model_status", "breached", "reason_tag", "true_reason", "hours", "hours_documented"]].to_string())
    assert len(called) / len(has_end) >= 0.8, "abstain rate too high on cases with a documented end"
    agree = ((called.status == "breached") == called.breached).mean()
    assert agree >= 0.8, f"agreement with structured truth {agree:.2f} < 0.8"
    ev = [e for row in v.evidence for e in json.loads(row)]
    times = [e for e in ev if e["kind"] in ("from_time", "to_time")]
    assert sum(e["found"] for e in times) / max(len(times), 1) >= 0.8
    assert all(bool(e["bboxes"]) == e["verified"] for e in ev)
    assert (m[m.end_ts.isna()].status == "abstain").all()
