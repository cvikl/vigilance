import pandas as pd


def test_mini_fixture_has_five_patients_with_covid(mini_settings):
    d = mini_settings.paths.synthea_dir
    pats = pd.read_csv(d / "patients.csv")
    conds = pd.read_csv(d / "conditions.csv")
    assert len(pats) == 5
    assert set(conds[conds.CODE == 840539006].PATIENT) == set(pats.Id)
    for t in ["encounters", "procedures", "medications", "observations", "careplans"]:
        assert set(pd.read_csv(d / f"{t}.csv").PATIENT) <= set(pats.Id)
