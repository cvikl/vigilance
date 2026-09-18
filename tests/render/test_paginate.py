import pytest

from auditpace.render.paginate import paginate

# blocks measured on an unbounded page: (top, bottom); letterhead ends at 200,
# so first block starts there
EXT = [(200, 260), (280, 500), (520, 900), (920, 1500), (1520, 1700), (1720, 1800)]


def test_everything_fits_on_one_page():
    assert paginate(EXT, content_bottom=1800) == [[0, 1, 2, 3, 4, 5]]


def test_greedy_fill_restarts_each_page_at_first_block_top():
    # page box height = 1614 - 200 = 1414 px; block 4 ends at 1700 > 1614 -> new page, which then
    # holds blocks 4 and 5 (their span 1520..1800 = 280 px starting at 200 on the new page)
    assert paginate(EXT, content_bottom=1614) == [[0, 1, 2, 3], [4, 5]]


def test_block_taller_than_page_raises():
    with pytest.raises(OverflowError, match=r"block 2 is 380px, page box is 300px"):
        paginate(EXT, content_bottom=500)


def test_empty():
    assert paginate([], content_bottom=1614) == []
