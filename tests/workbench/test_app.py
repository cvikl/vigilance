def test_root_redirects_to_queue(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"].endswith("/queue")


def test_queue_page_has_reasons_footer_and_copy(client):
    r = client.get("/queue")
    assert r.status_code == 200
    html = r.text
    assert "model call ≠ computed status" in html
    assert "orders the team's checking" in html
    assert "1 case with no end event — nothing to review, nothing imputed" in html
    assert "no follow-up documented" in html
    assert "reviewed 0 / 21" in html
    assert "urgency" not in html.lower() and "clinical priority" not in html.lower()
    assert 'href="/case/dis:H4"' in html
    assert "demo-panel" not in html and "demo.js" not in html
    assert "nan" not in html and "model: nan" not in html
    assert "demo.js" not in client.get("/queue", params={"demo": "0"}).text


def test_queue_filters_and_htmx_partial(client):
    r = client.get("/queue", params={"category": "breached_legitimate"})
    assert "leg:H4" in r.text and "sys:H4" not in r.text
    r = client.get("/queue", params={"criterion": "H6"}, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "<html" not in r.text and "noend:H6" in r.text
    r = client.get("/queue", params={"state": "validated"})
    assert r.status_code == 200 and "No cases match" in r.text


def test_unverified_badge_in_queue(client):
    html = client.get("/queue").text
    assert html.count("evidence not verified") >= 1


def test_page_image_and_404(client):
    r = client.get("/page/sys:ward_note:p1.jpg")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "max-age=86400"
    assert client.get("/page/nope.jpg").status_code == 404


def test_healthz(client, toy_protocol):
    j = client.get("/healthz").json()
    assert j["ok"] is True and j["protocol_hash"] == toy_protocol.hash and j["reviews"] == 0 and j["load_error"] is None


def test_static_htmx_served(client):
    r = client.get("/static/htmx.min.js")
    assert r.status_code == 200 and "htmx" in r.text[:2000]


def test_case_page_shows_verdict_evidence_and_form(client):
    r = client.get("/case/unv:H4")
    assert r.status_code == 200
    html = r.text
    assert "Admission to VTE prophylaxis" in html and "not_prescribed" in html
    assert "not found on page — no rectangle" in html
    assert 'name="action" value="confirm"' in html and 'value="override"' in html and 'value="flag"' in html
    assert 'type="button" class="reveal" data-show="ov"' in html
    assert html.index('value="confirm"') < html.index('value="override"')
    assert 'class="cancel"' in html
    assert html.count('id="banner"') == 1 and 'class="ov" hidden>' in html
    assert "required" not in html.split("<form")[1].split("<script")[0]  # required is toggled by JS, never static
    assert html.count('name="action"') == 3  # Confirm, Save override, Save flag
    assert "evidence not verified on page" in html  # priority_reason echoed on the case
    assert "(documented)" in html and "measured (from quoted times)" in html
    assert client.get("/case/nope:H4").status_code == 404


def test_case_model_disagreement_highlighted_and_rects_drawn(client):
    html = client.get("/case/dis:H4").text
    assert "model call ≠ computed status" in html
    assert html.count("<rect") == 1
    part = client.get("/case/dis:H4/page/dis:ward_note:p1", params={"evidence": 0}).text
    assert "<html" not in part and part.count("<rect") == 1 and "/page/dis:ward_note:p1.jpg" in part
    assert 'viewBox="0 0 200 100"' in part


def test_no_end_case_wording(client):
    html = client.get("/case/noend:H6").text
    assert "no follow-up documented" in html and "not documented" in html


def test_confirm_writes_review_and_updates_progress(client, toy_processed):
    r = client.post("/reviews", data={"case_id": "sys:H4", "action": "confirm", "human_status": "", "human_reason": "",
                                      "note": ""}, cookies={"reviewer": "dr_a"})
    assert r.status_code == 200
    assert "reviewed 1 / 21" in r.text and "dr_a" in r.text and "validated" in r.text
    assert "check next" in r.text
    assert len(list((toy_processed / "reviews").glob("r_*.parquet"))) == 1
    assert client.get("/healthz").json()["reviews"] == 1
    # the reviewed row stays in the pending view of this process, ticked in place (no reflow under the
    # reviewer's eye); a demo reset forgets it and it leaves the queue
    q = client.get("/queue").text
    assert 'data-case="sys:H4"' in q and "reviewed: validated" in q and 'class="tick"' in q
    assert client.post("/demo/reset").status_code == 200
    assert 'data-case="sys:H4"' not in client.get("/queue").text


def test_override_requires_status_and_moves_estimate(client):
    r = client.post("/reviews", data={"case_id": "dis:H4", "action": "override", "human_status": "", "human_reason": "",
                                      "note": "x"})
    assert r.status_code == 422 and "human_status required" in r.text
    assert 'id="banner" hx-swap-oob="true"' in r.text and "Estimates not refreshed" not in r.text
    assert 'class="ov" >' in r.text and 'class="fl" hidden>' in r.text  # Override re-opened for the retry
    assert 'name="action" value="confirm"' in r.text  # the form is not lost
    r = client.post("/reviews", data={"case_id": "dis:H4", "action": "override", "human_status": "not_breached",
                                      "human_reason": "not_prescribed", "note": "chart signed"})
    assert r.status_code == 200 and "disputed" in r.text  # reason silently dropped for a not_breached call
    from auditpace.estimate.reviews import assign_pool
    snap = client.app.state.snapshot
    est = snap.frames["estimates"]
    row = est[(est.criterion_id == "H4") & (est.segment_key == "all")].iloc[0]
    expect = 1 if assign_pool("dis:H4", snap.protocol.hash, snap.protocol.review.estimation_pool_fraction) == "estimation" else 0
    assert row.n_reviewed == expect


def test_flag_then_case_stays_in_queue(client):
    r = client.post("/reviews", data={"case_id": "leg:H4", "action": "flag", "human_status": "", "human_reason": "",
                                      "note": "ask consultant"})
    assert r.status_code == 200
    assert "leg:H4" in client.get("/queue").text


def test_unknown_case_review_is_404(client):
    r = client.post("/reviews", data={"case_id": "zz:H4", "action": "confirm", "human_status": "", "human_reason": "",
                                      "note": ""})
    assert r.status_code == 404


def test_htmx_404_is_plain_text_not_html(client):
    r = client.get("/case/<img src=x onerror=alert(1)>:H4", headers={"HX-Request": "true"})
    assert r.status_code == 404 and r.headers["content-type"].startswith("text/plain")
    assert r.text.startswith("unknown case")
    r = client.get("/page/<img src=x onerror=alert(1)>.jpg")
    assert r.status_code == 404 and r.headers["content-type"].startswith("text/plain")
    assert r.text == "unknown page <img src=x onerror=alert(1)>"


def test_stale_partition_after_write_shows_banner_and_keeps_old_snapshot(client, toy_processed, toy_protocol):
    from auditpace.estimate.reviews import review_frame
    from auditpace.store import Store
    rows = [{"review_id": "z", "case_id": "sys:H4", "reviewer": "x", "validation_state": "validated",
             "human_status": "breached", "human_reason": "not_prescribed", "note": None, "pool": "estimation",
             "reviewed_ts": "2026-09-16T10:00:00", "protocol_hash": "deadbeef"}]
    with Store(toy_processed) as s:
        s.write_part("reviews", "r_z", review_frame(rows), "deadbeef")
    r = client.post("/reviews", data={"case_id": "leg:H4", "action": "confirm", "human_status": "", "human_reason": "",
                                      "note": ""})
    assert r.status_code == 200
    assert "Saved" in r.text
    assert 'id="banner" hx-swap-oob="true"' in r.text and "Estimates not refreshed" in r.text  # spec §6: same response
    assert "stale protocol_hash" in r.text
    html = client.get("/queue").text
    assert "Estimates not refreshed" in html and "stale protocol_hash" in html
    assert html.count('id="banner"') == 1
    assert client.get("/healthz").json()["load_error"] and client.get("/healthz").json()["reviews"] == 0


def test_results_alert_cards_time_lost_and_provisional(client):
    html = client.get("/results").text
    assert "Respiratory clinic coordinator" in html or "Ward pharmacist / trust VTE lead" in html
    assert html.count('class="card alert') >= 1 and "<b>Action</b>" in html and "<b>Owner</b>" in html
    assert "model-only rate, 0 reviews yet" in html
    assert "provisional" in html and "fewer than 2 reviews" in html
    assert "H4 Admission to VTE prophylaxis" in html
    assert "<svg" in html  # funnel for H4 (two orgs with n >= 5)
    assert "no follow-up documented" in html  # H6 n_no_end cell
    assert 'data-demo="C3"' in html
    assert "None" not in html and ">1.0<" not in html


def test_results_after_seeded_reviews_says_corrected(client, toy_processed, toy_protocol):
    from auditpace.estimate.reviews import assign_pool
    est_cases = [c for c in ["p0:H4", "p1:H4", "p2:H4", "p3:H4", "p4:H4", "p5:H4", "r0:H4", "r1:H4", "r2:H4", "r3:H4"]
                 if assign_pool(c, toy_protocol.hash, 0.8) == "estimation"][:2]
    assert len(est_cases) == 2
    for cid in est_cases:
        assert client.post("/reviews", data={"case_id": cid, "action": "override", "human_status": "breached",
                                             "human_reason": "not_prescribed", "note": ""}).status_code == 200
    html = client.get("/results").text
    assert "corrected rate, 2 reviewed" in html or "method: ppi" in html
    assert "fewer than 20 reviews" in html


def test_report_tab_without_report(client, monkeypatch, tmp_path):
    from auditpace.workbench import app as appmod
    monkeypatch.setattr(appmod, "REPORT_PATH", tmp_path / "report.md")
    html = client.get("/report").text
    assert "No report yet" in html and "auditpace report" in html


def test_report_tab_renders_markdown(client, monkeypatch, tmp_path):
    from auditpace.workbench import app as appmod
    p = tmp_path / "report.md"
    p.write_text("# Findings\n\n- H6 loses the most hours\n")
    monkeypatch.setattr(appmod, "REPORT_PATH", p)
    html = client.get("/report").text
    assert "<h1>Findings</h1>" in html and "<li>H6 loses the most hours</li>" in html
