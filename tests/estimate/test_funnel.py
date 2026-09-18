import math

import pandas as pd

from auditpace.estimate.categorise import categorise
from auditpace.estimate.funnel import build_funnel, limits, signal_for
from auditpace.estimate.reviews import empty_reviews
from auditpace.estimate.segments import build_estimates
from tests.estimate.conftest import toy

NOW = pd.Timestamp("2026-09-16 12:00:00")


def test_limits_and_signals():
    lim = limits(0.3, 100)
    sd = math.sqrt(0.3 * 0.7 / 100)
    assert lim["alert_hi"] == 0.3 + 2 * sd and lim["alarm_lo"] == 0.3 - 3 * sd
    assert signal_for(0.3, lim) == "none"
    assert signal_for(0.3 + 2.5 * sd, lim) == "alert_high" and signal_for(0.3 + 3.5 * sd, lim) == "alarm_high"
    assert signal_for(0.3 - 2.5 * sd, lim) == "alert_low" and signal_for(0.3 - 3.5 * sd, lim) == "alarm_low"
    assert limits(0.0, 10)["alarm_lo"] == 0.0 and limits(1.0, 10)["alarm_hi"] == 1.0
    assert signal_for(math.nan, lim) == "none"
    assert all(math.isnan(v) for v in limits(float("nan"), 5).values())
    assert all(math.isnan(v) for v in limits(0.3, 0).values())
    assert signal_for(0.5, limits(float("nan"), 5)) == "none"


def test_funnel_flags_outlier_org(locked_protocol):
    rows = [{"pid": f"a{i}", "crit": "H2", "status": "breached" if i < 9 else "not_breached", "reason": "bed_unavailable", "hours": 10, "org": "bad"} for i in range(10)]
    rows += [{"pid": f"b{i}", "crit": "H2", "status": "breached" if i < 2 else "not_breached", "reason": "bed_unavailable", "hours": 10, "org": "ok"} for i in range(40)]
    rows += [{"pid": f"c{i}", "crit": "H2", "status": "not_breached", "hours": 1, "org": None} for i in range(3)]
    t = toy(rows, locked_protocol)
    cf = categorise(t["verdicts"], t["cases"], t["patients"], empty_reviews(), locked_protocol)
    est = build_estimates(cf, locked_protocol, NOW)
    f = build_funnel(cf, est, locked_protocol, NOW).set_index("organization_id")
    assert f.loc["bad", "signal"] == "alarm_high" and f.loc["ok", "signal"] in ("none", "alert_low", "alarm_low")
    assert f.loc["unknown", "suppressed"] and f.loc["unknown", "signal"] == "none" and math.isnan(f.loc["unknown", "rate"])
    assert (f.centre == est[(est.criterion_id == "H2") & (est.segment_key == "all")].corrected_rate.iloc[0]).all()
