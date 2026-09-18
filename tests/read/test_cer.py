import pytest

from auditpace.read.cer import anchored_cer

BODY = "Day 1 of admission. Patient: female, 18-39 years, confirmed COVID-19 pneumonitis."
GT = BODY.split()


def test_identical_is_zero():
    assert anchored_cer(GT, BODY) == 0.0


def test_letterhead_and_footer_ignored():
    text = "Eastbrook University Hospitals\nHospital No: 123\n" + BODY + "\nPage 1 of 1"
    assert anchored_cer(GT, text) == 0.0


def test_line_breaks_inside_body_are_whitespace():
    assert anchored_cer(GT, BODY.replace(" Patient:", "\nPatient:")) == 0.0


def test_one_char_error_is_about_one_percent():
    text = BODY.replace("admission", "admicsion")
    assert anchored_cer(GT, text) == pytest.approx(1 / len(BODY), abs=1e-9)


def test_no_overlap_is_one():
    assert anchored_cer(GT, "completely unrelated words here") == 1.0


def test_empty_reader_is_one():
    assert anchored_cer(GT, "") == 1.0
    assert anchored_cer(GT, "   \n ") == 1.0


def test_junk_inside_body_penalised():
    text = BODY.replace("Patient:", "Patient: XXXX XXXX")
    assert 0.05 < anchored_cer(GT, text) < 0.2


def test_empty_gt_is_zero_when_reader_empty_else_one():
    assert anchored_cer([], "") == 0.0
    assert anchored_cer([], "anything") == 1.0
