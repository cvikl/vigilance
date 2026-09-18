"""S6 fixtures: a compact `toy` builder for unit tests (no rendering, no replay) and `mini_verdicts`
— the 5-patient mini cohort with S5's recorded 27B verdicts replayed (session-scoped chain from
tests/adjudicate/conftest.py; needs Chromium + tessdata like the S5 tests)."""
import json

import pandas as pd
import pytest

from auditpace.adjudicate.stage import AdjudicateStage
from auditpace.estimate.reviews import assign_pool, review_frame
from auditpace.models import ModelClient
from tests.adjudicate.conftest import mini_readings, read_mini  # noqa: F401  (re-exported fixtures)

TS0 = pd.Timestamp("2020-03-02 08:00:00")


def toy(rows: list[dict], protocol, seed_ts: pd.Timestamp = TS0) -> dict[str, pd.DataFrame]:
    """Build verdicts/cases/patients from compact rows. Each row:
    {pid, crit, status, model_status?, reason?, hours?, end?(bool, default True), verified?(bool),
     org?, sex?, age?, week_offset?(int days)}. Structured truth `breached`/`true_reason` are set
    from `truth`/`true_reason` keys (only coverage tests read them)."""
    v_rows, c_rows, pats = [], [], {}
    for i, r in enumerate(rows):
        pid, cid = r["pid"], r["crit"]
        case_id = f"{pid}:{cid}"
        start = seed_ts + pd.Timedelta(days=r.get("week_offset", 0))
        has_end = r.get("end", True)
        hours = r.get("hours")
        end = start + pd.Timedelta(hours=hours) if (has_end and hours is not None) else (start + pd.Timedelta(hours=1) if has_end else pd.NaT)
        status = r["status"]
        ev = [{"kind": "from_time", "doc_id": f"{pid}:ward_note", "page_id": f"{pid}:ward_note:p1", "quote": "q",
               "start": 0, "end": 1, "bboxes": [{"x0": 0, "y0": 0, "x1": 1, "y1": 1}] if r.get("verified", True) else [],
               "found": True, "verified": r.get("verified", True)}]
        v_rows.append({
            "case_id": case_id, "patient_id": pid, "criterion_id": cid, "status": status,
            "model_status": r.get("model_status", status if status != "abstain" else None),
            "reason_tag": r.get("reason") if status == "breached" else None,
            "confidence": 0.9, "from_ts": start if status != "abstain" else pd.NaT,
            "to_ts": end if status != "abstain" else pd.NaT,
            "hours_documented": hours if status != "abstain" else float("nan"),
            "evidence": json.dumps(ev), "rationale": "", "n_docs": 2, "error": None, "model": "m",
            "prompt_version": "adj-test", "read_version": "read-test", "batch_id": "b0000",
            "created_ts": seed_ts, "protocol_hash": protocol.hash,
        })
        c_rows.append({
            "case_id": case_id, "patient_id": pid, "criterion_id": cid, "start_ts": start, "end_ts": end,
            "hours": hours if has_end else float("nan"), "breached": bool(r.get("truth", status == "breached")),
            "applies": True, "true_reason": r.get("true_reason", r.get("reason")), "start_has_time": True,
            "end_has_time": has_end, "protocol_hash": protocol.hash,
        })
        pats.setdefault(pid, {
            "patient_id": pid, "age_band": r.get("age", "40-59"), "sex": r.get("sex", "F"), "race": "white",
            "ethnicity": "nonhispanic", "organization_id": r.get("org", "orgA"), "icu": False, "died": False,
            "birthdate": pd.Timestamp("1970-01-01"), "deathdate": pd.NaT, "protocol_hash": protocol.hash,
        })
    verdicts = pd.DataFrame(v_rows)
    for col in ("model_status", "reason_tag", "error"):
        verdicts[col] = verdicts[col].astype(object).where(verdicts[col].notna(), None).astype("string")
    cases = pd.DataFrame(c_rows)
    patients = pd.DataFrame(list(pats.values()))
    return {"verdicts": verdicts, "cases": cases, "patients": patients}


@pytest.fixture
def mini_verdicts(mini_settings, locked_protocol, mini_readings):  # noqa: F811
    """mini_readings Store plus `verdicts` replayed from the recorded S5 fixtures."""
    client = ModelClient(mini_settings.models.adjudicator, mock=True,
                         fixtures_dir=mini_settings.paths.fixtures_dir, record=False)
    s = AdjudicateStage(mini_settings, locked_protocol, mini_readings, client=client).run()
    assert s.n_quarantined == 0, "S5 mini replay failed — see tests/adjudicate/test_replay.py"
    return mini_readings


def make_mini_reviews(store, protocol) -> pd.DataFrame:
    """Four reviews on the mini verdicts: confirm, override (to not_breached + reason None), flag,
    and one tuning-pool confirm. Chosen deterministically from called (non-abstain) cases."""
    v = store.read("verdicts")
    called = v[v.status != "abstain"].sort_values("case_id")
    frac = protocol.review.estimation_pool_fraction
    est = [c for c in called.case_id if assign_pool(c, protocol.hash, frac) == "estimation"]
    tun = [c for c in called.case_id if assign_pool(c, protocol.hash, frac) == "tuning"]
    assert len(est) >= 3, "mini cohort must yield >= 3 estimation-pool called cases"
    st = dict(zip(called.case_id, called.status))
    rows = [
        {"review_id": "r1", "case_id": est[0], "reviewer": "dr_a", "validation_state": "validated",
         "human_status": st[est[0]], "human_reason": None, "note": None, "pool": "estimation",
         "reviewed_ts": "2026-09-16T10:00:00", "protocol_hash": protocol.hash},
        {"review_id": "r2", "case_id": est[1], "reviewer": "dr_a", "validation_state": "disputed",
         "human_status": "not_breached" if st[est[1]] == "breached" else "breached", "human_reason": None,
         "note": "disagree", "pool": "estimation", "reviewed_ts": "2026-09-16T10:01:00", "protocol_hash": protocol.hash},
        {"review_id": "r3", "case_id": est[2], "reviewer": "dr_a", "validation_state": "flagged",
         "human_status": None, "human_reason": None, "note": "ask consultant", "pool": "estimation",
         "reviewed_ts": "2026-09-16T10:02:00", "protocol_hash": protocol.hash},
    ]
    if tun:
        rows.append({"review_id": "r4", "case_id": tun[0], "reviewer": "dr_b", "validation_state": "validated",
                     "human_status": st[tun[0]], "human_reason": None, "note": None, "pool": "tuning",
                     "reviewed_ts": "2026-09-16T10:03:00", "protocol_hash": protocol.hash})
    return review_frame(rows)
