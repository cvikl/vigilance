import pandas as pd

from auditpace.estimate.categorise import categorise
from auditpace.estimate.reviews import empty_reviews
from auditpace.estimate.runchart import build_runchart
from auditpace.estimate.segments import build_estimates
from tests.estimate.conftest import toy

NOW = pd.Timestamp("2026-09-16 12:00:00")


def test_runchart_weeks_signal_and_latest(locked_protocol):
    rows = []
    for w in range(3):  # weeks 0,1 calm; week 2 (latest) all breached
        for i in range(12):
            breached = (w == 2) or (i < 2)
            rows.append({"pid": f"w{w}p{i}", "crit": "H1", "status": "breached" if breached else "not_breached",
                         "reason": "swab_delay", "hours": 30 if breached else 5, "week_offset": 7 * w})
    rows.append({"pid": "tiny", "crit": "H1", "status": "breached", "reason": "swab_delay", "hours": 30, "week_offset": 28})
    t = toy(rows, locked_protocol)
    cf = categorise(t["verdicts"], t["cases"], t["patients"], empty_reviews(), locked_protocol)
    est = build_estimates(cf, locked_protocol, NOW)
    rc = build_runchart(cf, est, locked_protocol, NOW).sort_values("week_start").reset_index(drop=True)
    assert list(rc.week) == ["2020-W10", "2020-W11", "2020-W12", "2020-W14"]
    assert rc.loc[2, "signal"] == "alarm_high" and rc.loc[2, "latest"]
    assert rc.loc[3, "suppressed"] and not rc.loc[3, "latest"] and rc.loc[3, "signal"] == "none"
    assert rc.latest.sum() == 1 and (rc.n == [12, 12, 12, 1]).all()
