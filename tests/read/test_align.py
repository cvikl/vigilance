from auditpace.read.align import ALIGN_RULES, align_words, alignment, normalise, reading_words
from auditpace.read.tesseract import TessWord


def _tw(words, y=10):
    return [TessWord(w, 90.0, 10 * i, y, 10 * i + 8, y + 20) for i, w in enumerate(words)]


def test_normalise():
    assert normalise("SARS-CoV-2.") == "sarscov2"
    assert normalise("admission,") == "admission"
    assert normalise("—") == ""


def test_identical_lists_pair_everything():
    a = ["Day", "1", "of", "admission."]
    assert align_words(a, list(a)) == [(0, 0), (1, 1), (2, 2), (3, 3)]


def test_equal_length_replace_pairs_typos():
    a = ["Day", "1", "of", "admission."]
    b = ["Day", "1", "of", "admicsion."]
    assert align_words(a, b) == [(0, 0), (1, 1), (2, 2), (3, 3)]


def test_letterhead_prefix_unpaired_body_paired():
    reading = ["Eastbrook", "Hospitals", "Day", "1", "of", "admission."]
    tess = ["Day", "1", "of", "admission."]
    assert align_words(reading, tess) == [(2, 0), (3, 1), (4, 2), (5, 3)]


def test_unequal_replace_and_insert_pair_nothing():
    assert align_words(["a", "b", "c"], ["a", "x", "y", "c"]) == [(0, 0), (2, 3)]


def test_reading_words_offsets():
    text = "Day 1\nof  admission."
    got = reading_words(text)
    assert got == [("Day", 0, 3), ("1", 4, 5), ("of", 6, 8), ("admission.", 10, 20)]
    assert all(text[s:e] == w for w, s, e in got)


def test_alignment_entries_and_frac():
    text = "Eastbrook Trust\nDay 1 of admission."
    tess = _tw(["Day", "1", "of", "admission."])
    entries, frac = alignment(text, tess)
    assert [text[e["start"]:e["end"]] for e in entries] == ["Day", "1", "of", "admission."]
    assert entries[0] == {"start": 16, "end": 19, "x0": 0, "y0": 10, "x1": 8, "y1": 30}
    assert frac == 4 / 6


def test_pure_punctuation_excluded_from_denominator():
    text = "Day — 1"
    entries, frac = alignment(text, _tw(["Day", "1"]))
    assert len(entries) == 2 and frac == 1.0


def test_empty_reading():
    assert alignment("", _tw(["x"])) == ([], 0.0)


def test_align_rules_is_descriptive():
    assert "lower" in ALIGN_RULES and "replace" in ALIGN_RULES
