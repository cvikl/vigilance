"""One browser pass: open a case, click 'show on page', a <rect> appears. Skips without Chromium."""
import socket
import threading
import time

import pytest
import uvicorn


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(toy_processed, toy_protocol):
    from auditpace.workbench.app import create_app
    port = _free_port()
    cfg = uvicorn.Config(create_app(toy_processed, toy_protocol), host="127.0.0.1", port=port,
                         log_level="error")
    srv = uvicorn.Server(cfg)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(50):
        if srv.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(timeout=5)


@pytest.mark.slow
def test_click_evidence_draws_rectangle(server):
    # Share the per-thread Playwright driver with render/browser.py: the sync API refuses a second
    # `sync_playwright().start()` on a thread that already has one (the session-scoped `renderer`
    # fixture in tests/render keeps its own open until the end of the run).
    from auditpace.render.browser import _acquire_driver, _release_driver
    try:
        pw = _acquire_driver()
    except Exception as e:  # noqa: BLE001 — any launch failure means "no browser here"
        pytest.skip(f"chromium unavailable: {e}")
    try:
        browser = pw.chromium.launch()
    except Exception as e:  # noqa: BLE001
        _release_driver()
        pytest.skip(f"chromium unavailable: {e}")
    try:
        page = browser.new_page()
        page.goto(f"{server}/queue?demo=1")
        assert page.locator("#demo-panel").count() == 1
        page.click('a[href="/case/dis:H4?demo=1"]')
        page.wait_for_selector("form.review")
        page.click("text=show on page")
        page.wait_for_selector("#pageview rect")
        assert page.locator("#pageview rect").count() == 1
        assert page.locator("#demo-C4").is_checked()
        # Override with no status: `required` (set only while the fieldset is open) blocks the submit
        # client-side; with it stripped, the server's 422 must still be swapped into the panel (spec §4)
        page.click("text=Override…")
        assert page.locator('fieldset.ov input[name="human_status"][required]').count() == 3
        assert page.evaluate("document.querySelector('form.review').checkValidity()") is False
        assert page.locator('button[value="confirm"]').is_disabled()
        page.evaluate("document.querySelectorAll('input[name=human_status]').forEach(r => r.required = false)")
        page.click('button[value="override"]')
        page.wait_for_selector("form.review p.err")
        assert "human_status required" in page.locator("form.review p.err").inner_text()
        assert page.locator("fieldset.ov").is_visible()  # re-opened for the retry, Confirm still parked
        # the swapped partial's inline script runs after htmx settles, so wait for its effect
        page.wait_for_function("document.querySelector('button[value=confirm]').disabled")
        assert page.locator('fieldset.ov input[name="human_status"][required]').count() == 3
        assert "reviewed 0 / 21" in page.locator("#progress").inner_text()
        page.click("fieldset.ov button.cancel")
        assert page.locator('input[name="human_status"][required]').count() == 0
        assert page.locator('button[value="confirm"]').is_enabled()
        page.click('button[value="confirm"]')
        page.wait_for_selector("text=Saved")
        assert "reviewed 1 / 21" in page.locator("#progress").inner_text()
        assert page.locator("#banner").count() == 1 and page.locator("#banner .banner").count() == 0
    finally:
        browser.close()
        _release_driver()
