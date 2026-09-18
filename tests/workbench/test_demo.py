def test_demo_flag_adds_panel_and_script_only_when_present(client):
    off = client.get("/queue").text
    assert "demo-panel" not in off and "demo.js" not in off and "?demo=1" not in off
    on = client.get("/queue", params={"demo": "1"}).text
    assert 'id="demo-panel"' in on and "/static/demo.js" in on
    for c in ("C1", "C2", "C3", "C4", "C5"):
        assert f'id="demo-{c}"' in on
    assert 'href="/results?demo=1"' in on and 'href="/case/dis:H4?demo=1"' in on


def test_demo_flag_survives_case_and_results(client):
    assert 'href="/queue?demo=1"' in client.get("/case/dis:H4", params={"demo": "1"}).text
    assert 'id="demo-panel"' in client.get("/results", params={"demo": "1"}).text
    assert 'id="demo-panel"' in client.get("/report", params={"demo": "1"}).text


def test_demo_js_served_and_references_markers(client):
    js = client.get("/static/demo.js").text
    assert "data-demo" in js and "sessionStorage" in js and "IntersectionObserver" in js
