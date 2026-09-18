import pandas as pd
import pytest

from auditpace.adjudicate.times import TIME_RE, parse_time_quote


@pytest.mark.parametrize("quote, expected", [
    ("14:20 on 12/03/2020", pd.Timestamp("2020-03-12 14:20")),
    ("Sample collected: 18:22 on 10/03/2020. Received", pd.Timestamp("2020-03-10 18:22")),
    ("14.20 on 12/03/2020", pd.Timestamp("2020-03-12 14:20")),          # OCR dot separator
    ("9:05 on 1/3/2020", pd.Timestamp("2020-03-01 09:05")),             # single-digit fields
    ("09:05 ON 01/03/2020", pd.Timestamp("2020-03-01 09:05")),          # case-insensitive
    # date-first forms: S2 discharge-summary header fields and S4 reader reorderings
    ("Discharge date: 22/03/2020, 21:22", pd.Timestamp("2020-03-22 21:22")),
    ("Admission date: 02/03/2020 (17:16)", pd.Timestamp("2020-03-02 17:16")),
    ("SpO2 90% on air recorded 09/03/2020 at 09:07", pd.Timestamp("2020-03-09 09:07")),
    ("22/03/2020 21:22", pd.Timestamp("2020-03-22 21:22")),
    ("22/03/2020, 21.22", pd.Timestamp("2020-03-22 21:22")),             # OCR dot, date-first
])
def test_parses_time_and_date(quote, expected):
    assert parse_time_quote(quote) == expected


@pytest.mark.parametrize("quote", [None, "", "14:20", "12/03/2020", "on 12/03/2020", "12/03/2020 at",
                                   "25:00 on 12/03/2020", "10:00 on 31/02/2020", "12/03/2020 (25:00)",
                                   "admitted overnight"])
def test_missing_or_invalid_is_none(quote):
    assert parse_time_quote(quote) is None


def test_first_match_wins():
    assert parse_time_quote("18:22 on 10/03/2020 and 21:22 on 10/03/2020") == pd.Timestamp("2020-03-10 18:22")


def test_first_match_wins_across_forms():
    # a date-first form earlier in the string beats a later canonical one, and vice versa
    assert parse_time_quote("Admission date: 09/03/2020, 11:27; hypoxaemic 09:07 on 09/03/2020") \
        == pd.Timestamp("2020-03-09 11:27")
    assert parse_time_quote("admitted 11:27 on 09/03/2020 (see letter of 22/03/2020)") \
        == pd.Timestamp("2020-03-09 11:27")


def test_pattern_is_exported_for_versioning():
    assert TIME_RE.pattern
