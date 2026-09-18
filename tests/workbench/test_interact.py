"""Demo-day queue behaviour: held-back arrivals, one-click views with counts, paging, owner/action line."""
from pathlib import Path

import pytest

from auditpace.workbench.demo import Arrivals, read_held


def test_read_held_only_under_header(tmp_path: Path):
    f = tmp_path / "demo_cases.txt"
    f.write_text("# comment\na:H4\n## demo beats\nb:H4\n## held — hidden\n# note\nc:H4\nd:H5\n## other\ne:H6\n")
    assert read_held(f) == ["c:H4", "d:H5"]
    assert read_held(tmp_path / "missing.txt") == []


def test_arrivals_release_order_and_reset():
    a = Arrivals(held=["x", "y"])
    assert a.pending() == ["x", "y"] and a.hidden() == {"x", "y"}
    assert a.release() == "x" and a.is_new("x") and a.pending() == ["y"]
    v = a.version
    assert a.release() == "y" and a.release() is None and a.version == v + 1
    a.reset()
    assert a.pending() == ["x", "y"] and not a.is_new("x")


@pytest.fixture
def held_client(toy_processed, toy_protocol):
    from fastapi.testclient import TestClient

    from auditpace.workbench.app import create_app
    app = create_app(toy_processed, toy_protocol, held=["sys:H4"])
    with TestClient(app) as c:
        yield c


def test_held_case_hidden_until_released_then_marked_new(held_client):
    c = held_client
    assert 'data-case="sys:H4"' not in c.get("/queue").text
    assert c.get("/healthz").json()["held"] == 1
    v0 = c.get("/queue/version").json()["version"]
    r = c.post("/demo/release")
    assert r.status_code == 200 and r.json() == {"released": "sys:H4", "pending": 0}
    assert c.get("/queue/version").json()["version"] != v0
    q = c.get("/queue").text
    assert 'data-case="sys:H4"' in q and "just landed" in q and 'class="row breached_system new"' in q
    assert c.post("/demo/release").status_code == 404
    assert c.post("/demo/reset").json() == {"pending": 1}
    assert 'data-case="sys:H4"' not in c.get("/queue").text
    st = c.get("/demo/status").json()
    assert st["held"] == ["sys:H4"] and st["pending"] == ["sys:H4"] and st["released"] == []


def test_chips_counts_and_views(client):
    q = client.get("/queue").text
    assert 'class="view on"' in q and "Check first" in q and "Longest over target" in q
    stalled = client.get("/queue", params={"category": "breached_system"}, headers={"HX-Request": "true"}).text
    assert 'data-case="sys:H4"' in stalled and 'data-case="leg:H4"' not in stalled
    nodata = client.get("/queue", params={"category": "nodata"}).text
    assert 'data-case="abs:H2"' in nodata and 'data-case="noend:H6"' in nodata and 'data-case="sys:H4"' not in nodata
    longest = client.get("/queue", params={"sort": "excess"}).text
    first = longest.index('data-case="')
    assert longest[first:first + 40].startswith('data-case="dis:H4"')  # 40 h vs 24 h target — longest over


def test_queue_is_paged_with_show_more(client, monkeypatch):
    import auditpace.workbench.app as appmod
    monkeypatch.setattr(appmod, "PAGE_SIZE", 5)
    q = client.get("/queue").text
    assert q.count("<tr class=\"row") == 5 and "show more — 5 of" in q
    more = client.get("/queue", params={"offset": 5, "part": "rows"}).text
    assert more.count("<tr class=\"row") == 5 and "<table" not in more
    assert "show more — 10 of" in more


def test_case_page_names_owner_and_next_action(client):
    sys_ = client.get("/case/sys:H4").text
    assert "Ward pharmacist / trust VTE lead" in sys_ and "VTE prophylaxis on admission clerking checklist" in sys_
    assert 'data-demo="C3"' in sys_ and "/static/case.js" in sys_
    abs_ = client.get("/case/abs:H2").text
    assert "Locate the missing record — nothing is imputed" in abs_
    ok = client.get("/case/p0:H4").text
    assert "None — within target" in ok


def test_brand_is_vigilance(client):
    q = client.get("/queue").text
    assert "<title>vigilance" in q and 'class="logo"' in q and "/static/favicon.svg" in q
    assert "/static/queue.js" in q and "/static/interact.css" in q


def test_confirm_with_relabelled_reason_records_override_of_reason(client, toy_processed):
    page = client.get("/case/sys:H4").text
    assert 'name="confirm_reason"' in page and "not_prescribed — stalled" in page
    assert "contraindication_documented — legitimate wait" in page
    r = client.post("/reviews", data={"case_id": "sys:H4", "action": "confirm", "human_status": "", "human_reason": "",
                                      "note": "", "confirm_reason": "contraindication_documented"})
    assert r.status_code == 200 and "disputed" in r.text
    import pandas as pd
    rv = pd.concat(pd.read_parquet(f) for f in (toy_processed / "reviews").glob("r_*.parquet"))
    assert rv.iloc[0].validation_state == "disputed" and rv.iloc[0].human_status == "breached"
    assert rv.iloc[0].human_reason == "contraindication_documented"
    # unchanged reason → plain confirm
    r = client.post("/reviews", data={"case_id": "leg:H4", "action": "confirm", "human_status": "", "human_reason": "",
                                      "note": "", "confirm_reason": "contraindication_documented"})
    assert r.status_code == 200 and "validated" in r.text


def test_released_case_heads_latest_and_stays_after_review(held_client):
    c = held_client
    c.post("/demo/release")
    q = c.get("/queue").text  # default view is Latest
    first = q.index('data-case="')
    assert q[first:first + 40].startswith('data-case="sys:H4"') and "just landed · " in q
    prio = c.get("/queue", params={"sort": "priority"}).text  # Check first keeps its own order
    assert not prio[prio.index('data-case="'):].startswith('data-case="sys:H4"')
    c.post("/reviews", data={"case_id": "sys:H4", "action": "confirm", "human_status": "", "human_reason": "",
                             "note": "", "confirm_reason": "not_prescribed"})
    q = c.get("/queue").text
    first = q.index('data-case="')
    assert q[first:first + 40].startswith('data-case="sys:H4"') and "just landed" not in q  # ticked, still on top
