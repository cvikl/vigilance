"""Headless Chromium renderer: screenshot + per-word client rects (S3 design §5).

Playwright's sync objects are bound to the thread that created them, so a `Renderer` is created,
used and closed on one thread (RenderStage opens one per batch). The sync API also refuses a
second `sync_playwright().start()` on a thread that already has one running, so every `Renderer`
on a thread shares one per-thread, refcounted Playwright driver (`_acquire_driver`/
`_release_driver`); it stops once the last `Renderer` on that thread closes.
"""
import threading
from dataclasses import dataclass
from typing import Self

from playwright.sync_api import Playwright, sync_playwright

from auditpace.render.templates import HEIGHT, WIDTH

_RECTS_JS = """() => ({
  words: [...document.querySelectorAll('.w')].map(e => {
    const r = e.getBoundingClientRect();
    return [e.textContent, r.left, r.top, r.right, r.bottom];
  }),
  blocks: [...document.querySelectorAll('.blk')].map(e => {
    const r = e.getBoundingClientRect();
    return [r.top, r.bottom];
  }),
})"""

_local = threading.local()


def _acquire_driver() -> Playwright:
    """One Playwright driver per thread: the sync API refuses a second `start()` on a thread that
    already has one. Every Renderer on the thread shares it; it stops when the last one closes."""
    if getattr(_local, "pw", None) is None:
        _local.pw = sync_playwright().start()
        _local.refs = 0
    _local.refs += 1
    return _local.pw


def _release_driver() -> None:
    _local.refs -= 1
    if _local.refs == 0:
        _local.pw.stop()
        _local.pw = None


@dataclass(frozen=True)
class Word:
    word: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class RenderResult:
    png: bytes                          # RGB PNG, WIDTH x HEIGHT
    words: list[Word]                   # DOM (reading) order, viewport px
    blocks: list[tuple[float, float]]   # (top, bottom) per .blk element, viewport px


class Renderer:
    def __init__(self, width: int = WIDTH, height: int = HEIGHT):
        pw = _acquire_driver()
        self._browser = None
        try:
            self._browser = pw.chromium.launch()
            self._page = self._browser.new_page(
                viewport={"width": width, "height": height}, device_scale_factor=1
            )
        except Exception:
            if self._browser is not None:
                self._browser.close()
                self._browser = None
            _release_driver()
            raise

    def render(self, html: str) -> RenderResult:
        self._page.set_content(html)
        self._page.wait_for_function("document.fonts.status === 'loaded'")
        rects = self._page.evaluate(_RECTS_JS)
        png = self._page.screenshot(full_page=False, type="png")
        words = [Word(t, x0, y0, x1, y1) for t, x0, y0, x1, y1 in rects["words"]]
        blocks = [(t, b) for t, b in rects["blocks"]]
        return RenderResult(png, words, blocks)

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
            _release_driver()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
