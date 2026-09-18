import pandas as pd
import pytest

from auditpace.cohort.source import SyntheaSource


def test_views_load_with_parsed_timestamps(mini_settings):
    src = SyntheaSource(mini_settings.paths.synthea_dir)
    assert set(src.table_names()) >= {"patients", "conditions", "encounters", "procedures", "medications"}
    enc = src.sql("select START, STOP from encounters limit 1")
    assert pd.api.types.is_datetime64_any_dtype(enc.START)
    cond = src.sql("select START from conditions limit 1")
    assert pd.api.types.is_datetime64_any_dtype(cond.START)
    assert src.sql("select count(*) as n from patients").n[0] == 5


def test_raises_file_not_found_for_missing_required_table(tmp_path):
    with pytest.raises(FileNotFoundError) as exc_info:
        SyntheaSource(tmp_path)
    assert "patients.csv" in str(exc_info.value)
