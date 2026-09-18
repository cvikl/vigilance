import json
from pathlib import Path

import pandas as pd

from auditpace.cohort.cases import build_cases
from auditpace.cohort.plant import plant_timeline
from auditpace.protocol import SyntheticConfig, load_protocol
from auditpace.synth.plan import DOC_TYPES, DocSpec, build_plan

P = load_protocol(Path(__file__).resolve().parents[2] / "protocol.yaml")
ORDER = list(P.events)
PATIENT = pd.Series({"patient_id": "p0", "age_band": "60-79", "sex": "F"})


def _events(pid="p0", *, icu=True, ventilated=True, follow_up=True, admitted=True, died=None, n_days=10):
    d = pd.Timestamp("2020-03-05")
    rows = [("suspected", d, False), ("confirmed", d, False), ("hypoxaemia", d, False)]
    if admitted:
        rows += [("admitted", d + pd.Timedelta(hours=13, minutes=31), True), ("enoxaparin", d, False),
                 ("discharged", d + pd.Timedelta(days=n_days, hours=19), True)]
    if icu:
        rows.append(("icu", d + pd.Timedelta(days=2, hours=13), True))
    if ventilated:
        rows.append(("ventilated", d + pd.Timedelta(days=2), False))
    if follow_up:
        rows.append(("follow_up", d + pd.Timedelta(days=n_days + 20, hours=16), True))
    if died is not None:
        rows.append(("died", pd.Timestamp(died), False))
    ev = pd.DataFrame([{"patient_id": pid, "event_type": e, "ts": t, "source_table": "x", "source_row_id": "r",
                        "has_time": h} for e, t, h in rows])
    ev["ts"] = ev.ts.astype("datetime64[us]")
    return ev


def _planted(ev, rates=None):
    cases = build_cases(ev, P.criteria)
    syn = SyntheticConfig(augment_times=True, breach_rates=rates or {c.id: 0.5 for c in P.criteria})
    return plant_timeline(ev, cases, P.criteria, syn, seed=3)


def _plan(ev, rates=None, seed=3):
    ev2, cases = _planted(ev, rates)
    return build_plan(PATIENT, ev2, cases, P.criteria, ORDER, seed), cases


def test_full_pathway_has_all_six_docs_in_order_and_is_deterministic():
    specs, _ = _plan(_events())
    assert [s.doc_type for s in specs] == DOC_TYPES == ["lab_report", "ed_clerking", "ward_round", "icu_note",
                                                        "discharge_summary", "clinic_letter"]
    assert all(s.doc_id == f"p0:{s.doc_type}" and s.patient_id == "p0" for s in specs)
    assert specs == _plan(_events())[0]
    assert all(isinstance(s, DocSpec) for s in specs)


def test_time_facts_cover_every_measured_case_via_carrier_table():
    specs, cases = _plan(_events())
    by_type = {s.doc_type: s for s in specs}
    carrier = {"H1": "lab_report", "H2": "ed_clerking", "H3": "icu_note", "H4": "ward_round", "H5": "icu_note", "H6": "clinic_letter"}
    for r in cases[cases.applies & cases.end_ts.notna()].itertuples():
        c = next(c for c in P.criteria if c.id == r.criterion_id)
        texts = {(f.event_type, f.text) for f in by_type[carrier[r.criterion_id]].facts if f.kind == "time" and f.case_id == r.case_id}
        assert (c.from_, pd.Timestamp(r.start_ts).strftime("%H:%M on %d/%m/%Y")) in texts
        assert (c.to, pd.Timestamp(r.end_ts).strftime("%H:%M on %d/%m/%Y")) in texts


def test_reason_on_breached_only_distractor_on_unbreached_only():
    specs, cases = _plan(_events(), rates={c.id: 1.0 for c in P.criteria})
    facts = [f for s in specs for f in s.facts]
    reasons = {f.case_id for f in facts if f.kind == "reason"}
    measured = set(cases[cases.applies & cases.end_ts.notna()].case_id)
    assert reasons == measured and not any(f.kind == "distractor" for f in facts)
    reason_docs = {f.case_id: s.doc_type for s in specs for f in s.facts if f.kind == "reason"}
    assert reason_docs["p0:H1"] == "ed_clerking" and reason_docs["p0:H4"] == "ward_round" and reason_docs["p0:H5"] == "icu_note"
    specs0, _ = _plan(_events(), rates={c.id: 0.0 for c in P.criteria})
    facts0 = [f for s in specs0 for f in s.facts]
    assert not any(f.kind == "reason" for f in facts0)
    # ~30% distractor share: over many seeds some but not all cases get one
    counts = [sum(f.kind == "distractor" for sp in build_plan(PATIENT, *_planted(_events(), {c.id: 0.0 for c in P.criteria}), P.criteria, ORDER, seed) for f in sp.facts) for seed in range(30)]
    assert 0 < sum(counts) < 30 * 6


def test_known_events_never_after_authored_and_in_protocol_order():
    specs, _ = _plan(_events())
    for s in specs:
        assert all(t <= s.authored_ts for _, t in s.known_events)
        names = [e for e, _ in s.known_events]
        assert names == sorted(names, key=ORDER.index) and "died" not in names
    ed = next(s for s in specs if s.doc_type == "ed_clerking")
    assert {"hypoxaemia", "admitted"} <= {e for e, _ in ed.known_events}


def test_not_admitted_patient_gets_lab_report_only_with_h1_reason_fallback():
    specs, _cases = _plan(_events(admitted=False, icu=False, ventilated=False, follow_up=False), rates={"H1": 1.0})
    assert [s.doc_type for s in specs] == ["lab_report"]
    kinds = {(f.kind, f.case_id) for f in specs[0].facts}
    assert ("reason", "p0:H1") in kinds and ("time", "p0:H1") in kinds


def test_missing_events_drop_docs():
    specs, _ = _plan(_events(icu=False, ventilated=False, follow_up=False))
    assert [s.doc_type for s in specs] == ["lab_report", "ed_clerking", "ward_round", "discharge_summary"]


def test_death_caps_authored_and_drops_clinic_letter():
    ev = _events(died="2020-03-12", n_days=6)  # discharged 11/03 19:00, follow_up 31/03, died 12/03
    specs, _ = _plan(ev)
    types = [s.doc_type for s in specs]
    assert "clinic_letter" not in types and "discharge_summary" in types
    ds = next(s for s in specs if s.doc_type == "discharge_summary")
    assert ds.died == pd.Timestamp("2020-03-12") and ds.authored_ts <= pd.Timestamp("2020-03-12 23:59")
    assert not any(f.case_id == "p0:H6" for s in specs for f in s.facts)  # follow_up after death: undocumentable


def test_same_day_death_before_follow_up_still_gets_clinic_letter():
    # Synthea death dates are date-only (midnight); a follow_up later the same day must not be
    # treated as "after death" (that death_cap benefit-of-the-doubt is applied to the case's H6
    # fact too, so the carrier the fact needs must not have been dropped).
    ev = _events(n_days=6, died="2020-03-25")
    ev.loc[ev.event_type == "follow_up", "ts"] = pd.Timestamp("2020-03-25 16:00")
    specs, cases = _plan(ev)
    types = [s.doc_type for s in specs]
    assert "clinic_letter" in types
    h6 = cases[(cases.criterion_id == "H6") & cases.applies]
    assert not h6.empty and h6.iloc[0].end_ts <= pd.Timestamp("2020-03-25 23:59")
    by_type = {s.doc_type: s for s in specs}
    assert any(f.case_id == "p0:H6" for f in by_type["clinic_letter"].facts)


def test_handwritten_share_only_on_notes():
    styles = {}
    for i in range(60):
        pat = pd.Series({"patient_id": f"q{i}", "age_band": "18-39", "sex": "M"})
        ev2, cases = _planted(_events(pid=f"q{i}"))
        for s in build_plan(pat, ev2, cases, P.criteria, ORDER, 3):
            styles.setdefault(s.doc_type, []).append(s.style)
    assert set(styles["lab_report"]) == {"typed"} and set(styles["discharge_summary"]) == {"typed"}
    for t in ("ed_clerking", "ward_round"):
        share = styles[t].count("handwritten") / 60
        assert 0.05 < share < 0.45


def test_facts_serialisable():
    specs, _ = _plan(_events())
    json.dumps([f.to_dict() for s in specs for f in s.facts])


def _assert_plan_invariants(specs):
    for s in specs:
        known = {e for e, _ in s.known_events}
        assert all(f.event_type in known for f in s.facts if f.kind == "time"), s.doc_id
        assert all(t <= s.authored_ts for _, t in s.known_events), s.doc_id
        assert s.authored_ts.second == 0 and s.authored_ts.microsecond == 0, s.doc_id


def test_documents_are_authored_after_the_events_they_record():
    _assert_plan_invariants(_plan(_events())[0])
    _assert_plan_invariants(_plan(_events(), rates={c.id: 1.0 for c in P.criteria})[0])
    for i in range(60):
        pat = pd.Series({"patient_id": f"q{i}", "age_band": "18-39", "sex": "M"})
        ev2, cases = _planted(_events(pid=f"q{i}"), rates={c.id: 0.5 for c in P.criteria})
        _assert_plan_invariants(build_plan(pat, ev2, cases, P.criteria, ORDER, 3))


def test_ed_clerking_authored_before_icu():
    ev = _events()
    ev.loc[ev.event_type == "icu", "ts"] = pd.Timestamp("2020-03-05 14:00")  # 29 min after admitted
    for seed in range(20):
        ev2, cases = _planted(ev, rates={"H3": 0.0})
        specs = build_plan(PATIENT, ev2, cases, P.criteria, ORDER, seed)
        by_type = {s.doc_type: s for s in specs}
        tl = dict(zip(ev2.event_type, ev2.planted_ts))
        ed = by_type["ed_clerking"]
        assert tl["admitted"] < ed.authored_ts < tl["icu"], seed
        assert "icu" not in {e for e, _ in ed.known_events}
