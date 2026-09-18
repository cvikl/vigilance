from pathlib import Path

import pandas as pd

from auditpace.cohort.cases import build_cases
from auditpace.protocol import load_protocol

ROOT_PROTOCOL = Path(__file__).resolve().parents[2] / "protocol.yaml"


def _events():
    t = pd.Timestamp
    rows = [
        ("p1", "hypoxaemia", t("2020-03-01"), False),
        ("p1", "admitted", t("2020-03-01 06:00"), True),
        ("p1", "enoxaparin", t("2020-03-03"), False),          # > 24h → breached H4
        ("p1", "icu", t("2020-03-02 00:00"), True),
        ("p2", "hypoxaemia", t("2020-03-05"), False),
        ("p2", "admitted", t("2020-03-05 02:00"), True),        # H4 end missing → NaN, not breached
    ]
    return pd.DataFrame(rows, columns=["patient_id", "event_type", "ts", "has_time"]).assign(
        source_table="x", source_row_id="r"
    )


def test_cases_grid_and_breach():
    p = load_protocol(str(ROOT_PROTOCOL))
    cases = build_cases(_events(), p.criteria)
    h4 = cases.set_index("case_id").loc["p1:H4"]
    assert h4.applies and h4.breached and abs(h4.hours - 42.0) < 1e-6
    h4b = cases.set_index("case_id").loc["p2:H4"]
    assert h4b.applies and pd.isna(h4b.hours) and not h4b.breached
    h3 = cases.set_index("case_id").loc["p1:H3"]
    assert h3.applies and h3.breached and abs(h3.hours - 18.0) < 1e-6
    # p2 has no icu event → H3 does not apply
    assert not cases.set_index("case_id").loc["p2:H3"].applies
    assert cases.true_reason.isna().all()
    assert set(cases.columns) >= {"case_id", "patient_id", "criterion_id", "start_ts", "end_ts", "hours",
                                  "breached", "applies", "true_reason", "start_has_time", "end_has_time"}
