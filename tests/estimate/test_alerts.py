import pandas as pd
import yaml

from auditpace.estimate.alerts import build_alerts
from auditpace.estimate.categorise import categorise
from auditpace.estimate.funnel import build_funnel
from auditpace.estimate.reviews import empty_reviews
from auditpace.estimate.runchart import build_runchart
from auditpace.estimate.segments import build_estimates
from auditpace.estimate.timelost import build_timelost
from auditpace.protocol import Protocol
from tests.conftest import ROOT
from tests.estimate.conftest import toy

NOW = pd.Timestamp("2026-09-16 12:00:00")


def _all(protocol, rows):
    t = toy(rows, protocol)
    cf = categorise(t["verdicts"], t["cases"], t["patients"], empty_reviews(), protocol)
    est = build_estimates(cf, protocol, NOW)
    fun = build_funnel(cf, est, protocol, NOW)
    rc = build_runchart(cf, est, protocol, NOW)
    tl = build_timelost(cf, NOW)
    return cf, build_alerts(cf, est, fun, rc, tl, protocol, NOW)


def _rows():
    rows = [{"pid": f"a{i}", "crit": "H4", "status": "breached" if i < 9 else "not_breached", "reason": "not_prescribed", "hours": 40, "org": "bad"} for i in range(10)]
    rows += [{"pid": f"b{i}", "crit": "H4", "status": "breached" if i < 4 else "not_breached", "reason": "prescription_unsigned" if i < 2 else "not_prescribed", "hours": 30, "org": "ok"} for i in range(40)]
    rows += [{"pid": f"c{i}", "crit": "H1", "status": "not_breached", "hours": 2, "org": "ok"} for i in range(10)]
    return rows


def test_every_alert_names_action_and_owner_and_kinds_fire(locked_protocol):
    _cf, al = _all(locked_protocol, _rows())
    assert al.action.notna().all() and al.owner.notna().all() and (al.action != "").all()
    assert (al.kind == "top_time_lost").sum() == 1 and al[al.kind == "top_time_lost"].criterion_id.iloc[0] == "H4"
    org = al[al.kind == "org_outlier"]
    assert list(org.segment_value) == ["bad"] and org.signal.iloc[0] == "alarm_high"
    assert org.dominant_reason.iloc[0] == "not_prescribed"
    assert org.action.iloc[0].startswith("VTE prophylaxis on admission clerking") and org.owner.iloc[0] == "Ward pharmacist / trust VTE lead"
    assert "bad" in org.justification.iloc[0] and "not_prescribed" in org.justification.iloc[0]
    below = al[al.kind == "criterion_below_target"]
    assert list(below.criterion_id) == ["H4"]  # H4 target 0.9 compliance; 13/50 breached → compliance CI upper < 0.9
    assert al.alert_id.is_unique and (al.computed_ts == NOW).all()
    assert (al.method == "naive").all() and (al.n_reviewed == 0).all()  # no reviews: S7 can see the rate is uncorrected


def test_block_absent_gives_unassigned_and_no_target_alert(tmp_path):
    d = yaml.safe_load((ROOT / "protocol.yaml").read_text()); d.pop("actions")
    p = Protocol.model_validate(d)
    _, al = _all(p, _rows())
    assert (al.action == "unassigned").all() and (al.owner == "unassigned").all()
    assert not (al.kind == "criterion_below_target").any()
    assert (al.kind == "top_time_lost").sum() == 1


def test_dominant_reason_falls_back_to_other_when_undetermined(locked_protocol):
    rows = [{"pid": f"a{i}", "crit": "H4", "status": "breached", "reason": None, "hours": 40, "org": "A"} for i in range(6)]
    rows += [{"pid": f"b{i}", "crit": "H4", "status": "not_breached", "hours": 4, "org": "A"} for i in range(6)]
    _, al = _all(locked_protocol, rows)
    top = al[al.kind == "top_time_lost"].iloc[0]
    assert top.dominant_reason == "undetermined" and top.action == "Review at monthly audit meeting"
