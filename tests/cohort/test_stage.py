import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from auditpace.cli import app
from auditpace.cohort.stage import CohortStage, age_band, anchor_dates
from auditpace.store import Store

_AT = pd.Timestamp("2020-01-01")


def _birthdate_for_age(years_days: int) -> pd.Timestamp:
    return _AT - pd.Timedelta(days=years_days)


def test_age_band():
    assert age_band(pd.Timestamp("1950-01-01"), pd.Timestamp("2020-03-01")) == "60-79"
    assert age_band(pd.Timestamp("2010-01-01"), pd.Timestamp("2020-03-01")) == "0-17"
    assert age_band(pd.Timestamp("1935-01-01"), pd.Timestamp("2020-03-01")) == "80+"


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (6210, "0-17"),  # exactly 17
        (6575, "18-39"),  # exactly 18
        (14245, "18-39"),  # exactly 39
        (14610, "40-59"),  # exactly 40
        (21550, "40-59"),  # exactly 59
        (21915, "60-79"),  # exactly 60
        (28855, "60-79"),  # exactly 79
        (29220, "80+"),  # exactly 80
    ],
)
def test_age_band_boundaries(days, expected):
    assert age_band(_birthdate_for_age(days), _AT) == expected


def test_age_band_over_200_is_open_ended_80_plus():
    # 250 years old must not raise (the old fixed upper bound of 200 would StopIteration here)
    assert age_band(pd.Timestamp("1770-01-01"), _AT) == "80+"


def test_age_band_negative_age_raises_value_error():
    with pytest.raises(ValueError, match="age_band: invalid"):
        age_band(pd.Timestamp("2021-01-01"), _AT)  # birthdate after "at"


@pytest.mark.parametrize(
    ("birthdate", "at"),
    [(pd.NaT, _AT), (pd.Timestamp("1950-01-01"), pd.NaT)],
)
def test_age_band_nat_raises_value_error(birthdate, at):
    with pytest.raises(ValueError, match="age_band: invalid"):
        age_band(birthdate, at)


def test_anchor_dates_prefers_admitted_else_earliest_event():
    events = pd.DataFrame(
        {
            "patient_id": ["p1", "p1", "p2"],
            "event_type": ["admitted", "confirmed", "confirmed"],
            "ts": [pd.Timestamp("2020-02-01"), pd.Timestamp("2020-01-01"), pd.Timestamp("2020-03-01")],
        }
    )
    anchor = anchor_dates(events)
    # p1 has an admitted event: use it, even though an earlier "confirmed" event exists.
    assert anchor.loc["p1"] == pd.Timestamp("2020-02-01")
    # p2 has no admitted event: fall back to its earliest event ts.
    assert anchor.loc["p2"] == pd.Timestamp("2020-03-01")


def test_stage_writes_three_tables_and_completeness(mini_settings, locked_protocol, capsys):
    with Store(mini_settings.paths.processed_dir) as store:
        s = CohortStage(mini_settings, locked_protocol, store)
        summary = s.run()
        assert (summary.n_in, summary.n_out, summary.n_quarantined) == (1, 1, 0)
        pats, _ev, cases = store.read("patients"), store.read("events"), store.read("cases")
        assert len(pats) == 5 and set(pats.age_band) <= {"0-17", "18-39", "40-59", "60-79", "80+"}
        assert pats.organization_id.notna().all()
        assert len(cases) == 5 * len(locked_protocol.criteria)
        assert (cases.protocol_hash == locked_protocol.hash).all()
        applies = cases[cases.applies & cases.hours.notna()]
        assert (applies.hours > 0).all()
        comp = store.read("cohort_completeness")
        assert set(comp.event_type) == set(locked_protocol.events)
        assert "cohort_completeness" in capsys.readouterr().out
        # second run is a no-op unless forced
        assert CohortStage(mini_settings, locked_protocol, store).run().n_out == 1


def test_cli_cohort_runs(mini_settings, locked_protocol, tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"paths:\n  synthea_dir: {mini_settings.paths.synthea_dir}\n  processed_dir: {tmp_path/'p2'}\n  fixtures_dir: {mini_settings.paths.fixtures_dir}\nmodels: {{}}\n")
    monkeypatch.setenv("AUDITPACE_CONFIG", str(cfg))
    proto = tmp_path / "protocol.yaml"
    proto.write_text(yaml.safe_dump(locked_protocol.model_dump(by_alias=True, mode="json"), sort_keys=False))
    r = CliRunner().invoke(app, ["cohort", "--protocol", str(proto)])
    assert r.exit_code == 0, r.stdout
    assert "cohort: in=1 out=1 quarantined=0" in r.stdout


def test_cli_cohort_exits_nonzero_when_quarantined(mini_settings, locked_protocol, tmp_path, monkeypatch):
    empty_synthea = tmp_path / "empty_synthea"
    empty_synthea.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"paths:\n  synthea_dir: {empty_synthea}\n  processed_dir: {tmp_path/'p2'}\n  fixtures_dir: {mini_settings.paths.fixtures_dir}\nmodels: {{}}\n")
    monkeypatch.setenv("AUDITPACE_CONFIG", str(cfg))
    proto = tmp_path / "protocol.yaml"
    proto.write_text(yaml.safe_dump(locked_protocol.model_dump(by_alias=True, mode="json"), sort_keys=False))
    r = CliRunner().invoke(app, ["cohort", "--protocol", str(proto)])
    assert r.exit_code == 1
    assert "quarantine" in r.stdout.lower() or "quarantine" in str(r.exception)
