"""S7 fixtures: a processed dir built from the `toy()` rows (no rendering, no model) plus one JPEG
page so /page and the evidence rectangles can be exercised."""
from pathlib import Path

import pandas as pd
import pytest
from PIL import Image

from auditpace.store import Store
from tests.estimate.conftest import toy

ROWS = [
    *[{"pid": f"p{i}", "crit": "H4", "status": "not_breached", "hours": 4, "org": "orgA", "week_offset": 7 * (i % 3)}
      for i in range(6)],
    {"pid": "sys", "crit": "H4", "status": "breached", "reason": "not_prescribed", "hours": 30, "org": "orgA"},
    {"pid": "leg", "crit": "H4", "status": "breached", "reason": "contraindication_documented", "hours": 30, "org": "orgA"},
    {"pid": "dis", "crit": "H4", "status": "breached", "model_status": "not_breached", "reason": "not_prescribed",
     "hours": 40, "org": "orgB"},
    {"pid": "unv", "crit": "H4", "status": "breached", "reason": "not_prescribed", "hours": 26, "org": "orgB",
     "verified": False},
    *[{"pid": f"r{i}", "crit": "H4", "status": "not_breached", "hours": 5, "org": "orgB"} for i in range(4)],
    {"pid": "abs", "crit": "H2", "status": "abstain", "hours": 5, "org": "orgA"},
    {"pid": "noend", "crit": "H6", "status": "abstain", "end": False, "org": "orgA"},
    *[{"pid": f"q{i}", "crit": "H6", "status": "not_breached", "hours": 100, "org": "orgB"} for i in range(5)],
]
PAGE_W, PAGE_H = 200, 100


@pytest.fixture
def toy_protocol(locked_protocol):
    return locked_protocol


@pytest.fixture
def toy_processed(tmp_path: Path, toy_protocol) -> Path:
    """processed/ with verdicts (one partition), cases, patients, documents, pages and one JPEG."""
    processed = tmp_path / "processed"
    t = toy(ROWS, toy_protocol)
    h = toy_protocol.hash
    pids = sorted(t["patients"].patient_id)
    docs = pd.DataFrame([{"doc_id": f"{p}:ward_note", "patient_id": p, "doc_type": "ward_note",
                          "authored_ts": pd.Timestamp("2020-03-02 09:00:00"), "style": "typed",
                          "protocol_hash": h} for p in pids])
    pages = pd.DataFrame([{"page_id": f"{p}:ward_note:p1", "doc_id": f"{p}:ward_note", "patient_id": p,
                           "doc_type": "ward_note", "style": "typed", "page_no": 1, "page_count": 1,
                           "image_path": f"pages/b0000/{p}:ward_note_p1.jpg", "width": PAGE_W, "height": PAGE_H,
                           "protocol_hash": h} for p in pids])
    (processed / "pages" / "b0000").mkdir(parents=True)
    for p in pids:
        Image.new("RGB", (PAGE_W, PAGE_H), "white").save(processed / "pages" / "b0000" / f"{p}:ward_note_p1.jpg")
    with Store(processed) as store:
        store.write_part("verdicts", "b0000", t["verdicts"], h)
        store.write("cases", t["cases"], h)
        store.write("patients", t["patients"], h)
        store.write("documents", docs, h)
        store.write("pages", pages, h)
    return processed


@pytest.fixture
def snapshot(toy_processed, toy_protocol):
    from auditpace.workbench.snapshot import Snapshot
    return Snapshot.load(toy_processed, toy_protocol, now=pd.Timestamp("2026-09-16 12:00:00"))


@pytest.fixture
def client(toy_processed, toy_protocol):
    from fastapi.testclient import TestClient

    from auditpace.workbench.app import create_app
    app = create_app(toy_processed, toy_protocol)
    with TestClient(app) as c:
        yield c
