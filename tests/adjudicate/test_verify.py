from auditpace.adjudicate.verify import (
    MIN_QUOTE_CHARS,
    VERIFY_RULES,
    PageReading,
    find_quote,
    normalise_with_map,
    verify_evidence,
)

TEXT = "Eastbrook Hospital\nBed initially unavailable on AMU; a side-room\nwas found. Bed initially unavailable on AMU; again."


def test_normalise_map_round_trips_to_raw_offsets():
    norm, idx = normalise_with_map("Ab, c\nD1!")
    assert norm == "abcd1"
    assert [ "Ab, c\nD1!"[i] for i in idx] == ["A", "b", "c", "D", "1"]
    assert len(idx) == len(norm)


def test_find_quote_ignores_punctuation_case_and_line_breaks():
    span = find_quote("bed initially unavailable on amu a side room was found", TEXT)
    assert span is not None
    s, e = span
    assert TEXT[s:e] == "Bed initially unavailable on AMU; a side-room\nwas found"


def test_find_quote_takes_first_occurrence():
    s, e = find_quote("Bed initially unavailable on AMU", TEXT)
    assert s == TEXT.index("Bed initially")
    assert TEXT[s:e] == "Bed initially unavailable on AMU"


def test_find_quote_rejects_short_and_absent():
    assert find_quote("on AMU", TEXT) is None                     # 5 normalised chars < MIN_QUOTE_CHARS
    assert MIN_QUOTE_CHARS == 8
    assert find_quote("patient declined admission", TEXT) is None
    assert find_quote("", TEXT) is None


def _page(page_id="d:p1", page_no=1, text=TEXT, alignment=None):
    return PageReading(page_id, page_no, text, alignment if alignment is not None else [])


def test_verify_found_without_alignment_is_not_verified():
    ev = verify_evidence("reason", "d", "Bed initially unavailable on AMU", [_page()])
    assert ev["found"] is True and ev["verified"] is False and ev["bboxes"] == []
    assert ev["page_id"] == "d:p1" and (ev["start"], ev["end"]) == (19, 51)
    assert ev["kind"] == "reason" and ev["doc_id"] == "d" and ev["quote"] == "Bed initially unavailable on AMU"


def test_verify_bboxes_are_exactly_the_overlapping_words():
    s = TEXT.index("Bed initially")
    al = [
        {"start": 0, "end": 9, "x0": 0, "y0": 0, "x1": 5, "y1": 5},                 # "Eastbrook" — before
        {"start": s, "end": s + 3, "x0": 10, "y0": 0, "x1": 15, "y1": 5},           # "Bed"
        {"start": s + 4, "end": s + 13, "x0": 20, "y0": 0, "x1": 25, "y1": 5},      # "initially"
        {"start": s + 33, "end": s + 34, "x0": 30, "y0": 0, "x1": 35, "y1": 5},     # "a" — after
    ]
    ev = verify_evidence("reason", "d", "Bed initially", [_page(alignment=al)])
    assert ev["verified"] is True
    assert ev["bboxes"] == [{"x0": 10, "y0": 0, "x1": 15, "y1": 5}, {"x0": 20, "y0": 0, "x1": 25, "y1": 5}]


def test_verify_unknown_doc_or_absent_quote():
    ev = verify_evidence("from_time", "d", "14:20 on 12/03/2020", [])
    assert ev == {"kind": "from_time", "doc_id": "d", "page_id": None, "quote": "14:20 on 12/03/2020",
                  "start": None, "end": None, "bboxes": [], "found": False, "verified": False}
    ev = verify_evidence("reason", "d", "patient declined admission", [_page()])
    assert ev["found"] is False and ev["page_id"] is None


def test_verify_searches_pages_in_page_no_order():
    p2 = _page("d:p2", 2, "second page says Bed initially unavailable on AMU",
               [{"start": 17, "end": 20, "x0": 1, "y0": 1, "x1": 2, "y1": 2}])
    p1 = _page("d:p1", 1, "first page has nothing relevant")
    ev = verify_evidence("reason", "d", "Bed initially unavailable on AMU", [p2, p1])
    assert ev["page_id"] == "d:p2" and ev["verified"] is True and ev["start"] == 17


def test_rules_string_exists_for_versioning():
    assert "first occurrence" in VERIFY_RULES
