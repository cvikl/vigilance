"""Greedy whole-block pagination from measured block extents (S3 design §6)."""


def paginate(extents: list[tuple[float, float]], content_bottom: float) -> list[list[int]]:
    """Split blocks into pages. `extents[i] = (top, bottom)` measured on one unbounded render;
    every page starts its first block where block 0 started (same letterhead), so a block fits
    when `bottom - page_top <= box_h` with `box_h = content_bottom - extents[0].top`."""
    if not extents:
        return []
    box_h = content_bottom - extents[0][0]
    pages: list[list[int]] = [[]]
    page_top = extents[0][0]
    for i, (top, bottom) in enumerate(extents):
        if bottom - top > box_h:
            raise OverflowError(f"block {i} is {bottom - top:.0f}px, page box is {box_h:.0f}px")
        if pages[-1] and bottom - page_top > box_h:
            pages.append([])
            page_top = top
        pages[-1].append(i)
    return pages
