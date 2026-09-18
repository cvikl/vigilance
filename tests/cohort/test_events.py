import pandas as pd

from auditpace.cohort.events import (
    _first_per_patient,
    derive_events,
    drop_post_mortem,
    organisation_of,
)
from auditpace.cohort.select import select_patients
from auditpace.cohort.source import SyntheaSource


def _setup(mini_settings, locked_protocol):
    src = SyntheaSource(mini_settings.paths.synthea_dir)
    pats = select_patients(src, locked_protocol.cohort)
    return src, pats


def test_every_patient_has_confirmed_and_admitted(mini_settings, locked_protocol):
    src, pats = _setup(mini_settings, locked_protocol)
    ev = derive_events(src, locked_protocol.events, list(pats.patient_id))
    assert set(ev.columns) == {"patient_id", "event_type", "ts", "source_table", "source_row_id", "has_time"}
    for et in ("confirmed", "admitted"):
        assert set(ev[ev.event_type == et].patient_id) == set(pats.patient_id), et
    assert ev.groupby(["patient_id", "event_type"]).size().max() == 1


def test_time_flags_and_ordering(mini_settings, locked_protocol):
    src, pats = _setup(mini_settings, locked_protocol)
    ev = derive_events(src, locked_protocol.events, list(pats.patient_id))
    assert ev[ev.source_table == "encounters"].has_time.all()
    assert not ev[ev.source_table == "conditions"].has_time.any()
    pid = pats[pats.icu].patient_id.iloc[0]
    e = ev[ev.patient_id == pid].set_index("event_type").ts
    assert e["icu"] >= e["admitted"]
    fu_pid = ev[ev.event_type == "follow_up"].patient_id.iloc[0]
    fu = ev[ev.patient_id == fu_pid].set_index("event_type").ts
    assert fu["follow_up"] > fu["discharged"]


def test_died_event_only_for_dead(mini_settings, locked_protocol):
    src, pats = _setup(mini_settings, locked_protocol)
    ev = derive_events(src, locked_protocol.events, list(pats.patient_id))
    assert set(ev[ev.event_type == "died"].patient_id) == set(pats[pats.died].patient_id)


def test_organisation_from_admission(mini_settings, locked_protocol):
    src, pats = _setup(mini_settings, locked_protocol)
    org = organisation_of(src, list(pats.patient_id))
    assert set(org.patient_id) == set(pats.patient_id) and org.organization_id.notna().all()


def test_first_per_patient_keeps_whole_row_not_first_non_null_per_column():
    # Earliest row for p1 has a null source_row_id; a later row for p1 has a non-null one.
    # groupby("patient_id").first() would splice the later row's source_row_id onto the
    # earliest ts. _first_per_patient must keep the earliest row intact instead.
    df = pd.DataFrame(
        {
            "patient_id": ["p1", "p1", "p2"],
            "ts": pd.to_datetime(["2020-01-01", "2020-01-05", "2020-01-02"]),
            "source_row_id": [None, "row-later", "row-p2"],
        }
    )
    out = _first_per_patient(df, "ts").set_index("patient_id")
    assert out.loc["p1", "ts"] == pd.Timestamp("2020-01-01")
    assert out.loc["p1", "source_row_id"] is None or pd.isna(out.loc["p1", "source_row_id"])
    assert out.loc["p2", "source_row_id"] == "row-p2"


def test_drop_post_mortem():
    pats = pd.DataFrame({"patient_id": ["A", "B"], "deathdate": pd.to_datetime(["2020-03-22", None])})
    ev = pd.DataFrame(
        [
            ("A", "discharged", "2020-03-22 11:22"),
            ("A", "follow_up", "2020-04-04 14:31"),
            ("A", "died", "2020-03-22 00:00"),
            ("B", "discharged", "2020-03-22 11:22"),
            ("B", "follow_up", "2020-04-04 14:31"),
        ],
        columns=["patient_id", "event_type", "ts"],
    )
    ev["ts"] = pd.to_datetime(ev.ts).astype("datetime64[us]")
    out = drop_post_mortem(ev, pats)
    assert list(zip(out.patient_id, out.event_type)) == [
        ("A", "discharged"), ("A", "died"), ("B", "discharged"), ("B", "follow_up"),
    ]
    assert list(out.index) == [0, 1, 2, 3]
