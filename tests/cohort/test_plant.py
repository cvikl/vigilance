from pathlib import Path

import pandas as pd
import pytest

from auditpace.cohort.cases import build_cases
from auditpace.cohort.plant import plant_timeline, stable_int
from auditpace.protocol import Criterion, SyntheticConfig, load_protocol

ROOT_PROTOCOL = Path(__file__).resolve().parents[2] / "protocol.yaml"
P = load_protocol(ROOT_PROTOCOL)


def _frames(n=400, criterion_id="H4", gap_days=1, start_has_time=False, end_day_offset=None):
    """n single-criterion patients: `from` on day (i % 5), `to` gap_days later (date-only unless flagged).

    end_day_offset=-1 reproduces the Synthea artefact where a date-only end lands the calendar
    day before a timed start.
    """
    c = next(c for c in P.criteria if c.id == criterion_id)
    t = pd.Timestamp("2020-03-01 08:00:00") if start_has_time else pd.Timestamp("2020-03-01")
    rows = []
    for i in range(n):
        start = t + pd.Timedelta(days=i % 5)
        end = start.normalize() + pd.Timedelta(days=end_day_offset if end_day_offset is not None else gap_days)
        rows.append({"patient_id": f"p{i}", "event_type": c.from_, "ts": start, "source_table": "x",
                     "source_row_id": "r", "has_time": start_has_time})
        rows.append({"patient_id": f"p{i}", "event_type": c.to, "ts": end, "source_table": "x",
                     "source_row_id": "r", "has_time": False})
    ev = pd.DataFrame(rows)
    ev["ts"] = ev.ts.astype("datetime64[us]")
    return ev, build_cases(ev, [c])


def _target(cid):
    return next(c.target_hours for c in P.criteria if c.id == cid)


@pytest.mark.parametrize("criterion_id,gap_days", [("H4", 1), ("H2", 0), ("H6", 0), ("H5", 1)])
def test_breach_prevalence_and_consistency(criterion_id, gap_days):
    ev, cases = _frames(400, criterion_id, gap_days)
    syn = SyntheticConfig(augment_times=True, breach_rates={criterion_id: 0.35})
    ev2, out = plant_timeline(ev, cases, P.criteria, syn, seed=7)
    assert 0.27 < out.breached.mean() < 0.43
    assert ((out.hours > _target(criterion_id)) == out.breached).all()
    assert (out.end_ts > out.start_ts).all()
    assert out[out.breached].true_reason.notna().all() and out[~out.breached].true_reason.isna().all()
    assert set(out[out.breached].true_reason) <= set(next(c.reasons for c in P.criteria if c.id == criterion_id))
    # planted_ts mirrors the case times
    m = out.merge(ev2.pivot(index="patient_id", columns="event_type", values="planted_ts"), on="patient_id")
    c = next(c for c in P.criteria if c.id == criterion_id)
    assert (m.start_ts == m[c.from_]).all() and (m.end_ts == m[c.to]).all()
    assert str(ev2.planted_ts.dtype) == "datetime64[us]"


def test_deterministic_per_case():
    syn = SyntheticConfig(augment_times=True, breach_rates={"H4": 0.35})
    _, a = plant_timeline(*_frames(50), P.criteria, syn, seed=7)
    _, b = plant_timeline(*_frames(80), P.criteria, syn, seed=7)  # superset cohort
    m = a.merge(b, on="case_id", suffixes=("_a", "_b"))
    assert (m.breached_a == m.breached_b).all() and (m.start_ts_a == m.start_ts_b).all()
    assert isinstance(stable_int("p1:H4"), int)


def test_no_augment_leaves_cases_untouched_and_planted_ts_null():
    ev, cases = _frames(20)
    ev2, out = plant_timeline(ev, cases, P.criteria, SyntheticConfig(augment_times=False), seed=1)
    pd.testing.assert_frame_equal(out, cases)
    assert ev2.planted_ts.isna().all() and str(ev2.planted_ts.dtype) == "datetime64[us]"


def test_end_before_start_does_not_pile_up_at_floor():
    ev, cases = _frames(200, "H4", start_has_time=True, end_day_offset=-1)
    syn = SyntheticConfig(augment_times=True, breach_rates={"H4": 0.35})
    _, out = plant_timeline(ev, cases, P.criteria, syn, seed=7)
    assert (out.hours == 0.25).mean() < 0.05
    assert 0.27 < out.breached.mean() < 0.43
    assert ((out.hours > _target("H4")) == out.breached).all()


def test_date_only_ends_do_not_pile_up_at_day_boundary():
    ev, cases = _frames(400, "H4", gap_days=1)
    syn = SyntheticConfig(augment_times=True, breach_rates={"H4": 0.35})
    _, out = plant_timeline(ev, cases, P.criteria, syn, seed=7)
    tod = out.end_ts.dt.strftime("%H:%M")
    assert (tod == "23:59").mean() < 0.02 and (tod == "00:00").mean() < 0.02
    assert ((out.hours > _target("H4")) == out.breached).all()


def test_missing_end_stays_unbreached():
    ev, cases = _frames(5)
    ev = ev[~((ev.patient_id == "p0") & (ev.event_type == "enoxaparin"))]
    cases = build_cases(ev, [c for c in P.criteria if c.id == "H4"])
    syn = SyntheticConfig(augment_times=True, breach_rates={"H4": 1.0})
    _, out = plant_timeline(ev, cases, P.criteria, syn, seed=1)
    r = out[out.patient_id == "p0"].iloc[0]
    assert not r.breached and r.true_reason is None and pd.isna(r.end_ts)


def _full_pathway_events(pid="p0", n_days=10):
    """All ten protocol events for one patient, Synthea-style (encounters timed, rest date-only)."""
    d = pd.Timestamp("2020-03-05")
    rows = [
        ("suspected", d, False), ("confirmed", d, False), ("hypoxaemia", d, False),
        ("admitted", d + pd.Timedelta(hours=13, minutes=31), True),
        ("enoxaparin", d, False),
        ("icu", d + pd.Timedelta(days=2, hours=13), True),
        ("ventilated", d + pd.Timedelta(days=2), False),
        ("discharged", d + pd.Timedelta(days=n_days, hours=19), True),
        ("follow_up", d + pd.Timedelta(days=n_days + 20, hours=16), True),
    ]
    ev = pd.DataFrame([{"patient_id": pid, "event_type": e, "ts": t, "source_table": "x",
                        "source_row_id": "r", "has_time": h} for e, t, h in rows])
    ev["ts"] = ev.ts.astype("datetime64[us]")
    return ev


def test_shared_events_carry_one_time_across_cases():
    ev = _full_pathway_events()
    cases = build_cases(ev, P.criteria)
    syn = SyntheticConfig(augment_times=True, breach_rates={c.id: 0.5 for c in P.criteria})
    ev2, out = plant_timeline(ev, cases, P.criteria, syn, seed=3)
    o = out.set_index("criterion_id")
    assert o.loc["H2", "end_ts"] == o.loc["H3", "start_ts"] == o.loc["H4", "start_ts"]
    assert o.loc["H3", "end_ts"] == o.loc["H5", "start_ts"]
    tl = ev2.set_index("event_type").planted_ts
    assert tl["admitted"] == o.loc["H2", "end_ts"] and tl["icu"] == o.loc["H3", "end_ts"]
    assert pd.notna(tl["hypoxaemia"])  # from-event of H2 got a time-of-day
    assert (ev2.ts == ev.ts).all()  # Synthea provenance untouched


def test_discharged_guard_keeps_it_after_planted_inpatient_events():
    ev = _full_pathway_events(n_days=0)  # discharged same evening as admission
    cases = build_cases(ev, P.criteria)
    syn = SyntheticConfig(augment_times=True, breach_rates={"H4": 1.0, "H3": 1.0, "H5": 1.0})
    ev2, out = plant_timeline(ev, cases, P.criteria, syn, seed=5)
    tl = ev2.set_index("event_type").planted_ts
    inpatient = [tl[e] for e in ("admitted", "enoxaparin", "icu", "ventilated")]
    assert tl["discharged"] >= max(inpatient) + pd.Timedelta(hours=1)
    assert out.set_index("criterion_id").loc["H6", "start_ts"] == tl["discharged"]


def test_duplicate_to_event_raises():
    ev, cases = _frames(3)
    dup = Criterion(id="X9", name="dup", type="handoff", **{"from": "hypoxaemia"}, to="enoxaparin",
                    target_hours=1, standard="s", reasons=["other"])
    with pytest.raises(ValueError, match="enoxaparin"):
        plant_timeline(ev, cases, P.criteria + [dup], SyntheticConfig(augment_times=True), seed=1)
