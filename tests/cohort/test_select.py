from pathlib import Path

import pytest

from auditpace.cohort.select import select_patients
from auditpace.cohort.source import SyntheaSource


def test_selects_all_five_when_n_exceeds_eligible(mini_settings, locked_protocol):
    src = SyntheaSource(mini_settings.paths.synthea_dir)
    df = select_patients(src, locked_protocol.cohort)
    assert len(df) == 5
    assert list(df.columns) == ["patient_id", "birthdate", "deathdate", "sex", "race", "ethnicity", "icu", "died"]
    assert df.icu.sum() >= 1 and df.died.sum() >= 1


def test_stratified_sample_is_deterministic_and_keeps_strata(mini_settings, locked_protocol):
    src = SyntheaSource(mini_settings.paths.synthea_dir)
    rule = locked_protocol.cohort.model_copy(deep=True)
    rule.sample.n = 3
    a = select_patients(src, rule)
    b = select_patients(src, rule)
    assert list(a.patient_id) == list(b.patient_id) and len(a) == 3
    # both non-empty strata (died / icu) survive proportional allocation with min 1
    assert a.died.sum() >= 1 and a.icu.sum() >= 1


def test_n_smaller_than_strata_count_raises(mini_settings, locked_protocol):
    src = SyntheaSource(mini_settings.paths.synthea_dir)
    rule = locked_protocol.cohort.model_copy(deep=True)
    rule.sample.n = 1
    rule.sample.stratify_by = ["icu", "died"]
    # mini fixture has 3 non-empty (icu, died) strata: (True,True), (True,False), (False,False)
    with pytest.raises(ValueError):
        select_patients(src, rule)


def test_required_encounter_must_fall_within_period(tmp_path: Path, locked_protocol):
    """cohort.period bounds the require_any encounter too, not just the condition (controller ruling).

    Patient A has an inpatient encounter inside the 2020 period; patient B's only
    inpatient encounter is from 2015, outside it — B must be excluded even though B
    also has the COVID condition recorded in 2020.
    """
    synthea = tmp_path / "synthea"
    synthea.mkdir()
    (synthea / "patients.csv").write_text(
        "Id,BIRTHDATE,DEATHDATE,RACE,ETHNICITY,GENDER\n"
        "patA,1980-01-01,,white,nonhispanic,F\n"
        "patB,1980-01-01,,white,nonhispanic,F\n"
    )
    (synthea / "conditions.csv").write_text(
        "START,STOP,PATIENT,ENCOUNTER,CODE,DESCRIPTION\n"
        "2020-04-01,,patA,encA1,840539006,COVID-19\n"
        "2020-04-01,,patB,encB1,840539006,COVID-19\n"
    )
    (synthea / "encounters.csv").write_text(
        "Id,START,STOP,PATIENT,ENCOUNTERCLASS,CODE,DESCRIPTION\n"
        "encA1,2020-04-01,2020-04-10,patA,inpatient,1505002,Hospital admission for isolation\n"
        "encB1,2015-04-01,2015-04-10,patB,inpatient,1505002,Hospital admission for isolation\n"
    )
    (synthea / "procedures.csv").write_text("DATE,PATIENT,ENCOUNTER,CODE,DESCRIPTION,BASE_COST,REASONCODE,REASONDESCRIPTION\n")
    (synthea / "medications.csv").write_text(
        "START,STOP,PATIENT,PAYER,ENCOUNTER,CODE,DESCRIPTION,BASE_COST,PAYER_COVERAGE,DISPENSES,TOTALCOST,"
        "REASONCODE,REASONDESCRIPTION\n"
    )
    src = SyntheaSource(synthea)
    df = select_patients(src, locked_protocol.cohort)
    assert list(df.patient_id) == ["patA"]
