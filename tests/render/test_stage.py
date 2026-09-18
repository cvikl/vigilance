import json
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from auditpace.cli import app
from auditpace.render.stage import RENDER_VERSION, Batch, RenderStage
from auditpace.render.templates import HEIGHT, WIDTH

pytestmark = pytest.mark.usefixtures("renderer")   # skip the whole module when Chromium is missing


def _run(settings, protocol, store, **kw):
    return RenderStage(settings, protocol, store).run(**kw)


def test_items_follow_documents_partitions(mini_settings, locked_protocol, mini_documents):
    assert list(RenderStage(mini_settings, locked_protocol, mini_documents).items()) == [
        Batch("b0000")
    ]


def test_run_writes_pages_and_pngs(mini_settings, locked_protocol, mini_documents):
    summary = _run(mini_settings, locked_protocol, mini_documents)
    assert (summary.n_in, summary.n_out, summary.n_quarantined) == (1, 1, 0)
    pages = mini_documents.read("pages")
    docs = mini_documents.read("documents")
    assert set(pages.doc_id) == set(docs.doc_id) and len(pages) >= len(docs)
    assert ((pages.render_version == RENDER_VERSION).all()
            and (pages.protocol_hash == locked_protocol.hash).all())
    assert (pages.width == WIDTH).all() and (pages.height == HEIGHT).all()
    assert (pages.page_id == pages.doc_id + ":p" + pages.page_no.astype(str)).all()
    for row in pages.itertuples():
        img = Path(mini_settings.paths.processed_dir) / row.image_path
        assert img.exists()
        assert row.image_path == f"pages/b0000/{row.doc_id}_p{row.page_no}.jpg"
        words = json.loads(row.gt_words)
        assert words and all(
            0 <= w["x0"] < w["x1"] <= WIDTH and 0 <= w["y0"] < w["y1"] <= HEIGHT for w in words
        )
        assert all(isinstance(w["x0"], int) for w in words)
        assert set(json.loads(row.artefact_params)) == {
            "angle_deg", "blur_sigma", "noise_sigma", "jpeg_q"
        }
    # word contract across pages
    for d in docs.itertuples():
        mine = pages[pages.doc_id == d.doc_id].sort_values("page_no")
        got = [w["word"] for r in mine.itertuples() for w in json.loads(r.gt_words)]
        assert got == d.text.split(), d.doc_id
    assert set(pages.columns) >= {
        "page_id", "doc_id", "patient_id", "doc_type", "style", "page_no", "page_count",
        "image_path", "width", "height", "gt_words", "artefact_params", "text_sha",
        "render_version", "batch_id", "protocol_hash",
    }


def test_second_run_is_noop_and_force_rerenders(mini_settings, locked_protocol, mini_documents):
    _run(mini_settings, locked_protocol, mini_documents)
    img = next((Path(mini_settings.paths.processed_dir) / "pages" / "b0000").glob("*.jpg"))
    before = img.stat().st_mtime_ns
    s = _run(mini_settings, locked_protocol, mini_documents)
    assert s.n_out == 1 and img.stat().st_mtime_ns == before
    _run(mini_settings, locked_protocol, mini_documents, force=True)
    assert img.stat().st_mtime_ns > before
    assert pd.read_parquet(img.parent.with_suffix(".parquet")).image_path.is_unique


def test_stale_render_version_refused_without_force(mini_settings, locked_protocol, mini_documents):
    _run(mini_settings, locked_protocol, mini_documents)
    part = Path(mini_settings.paths.processed_dir) / "pages" / "b0000.parquet"
    df = pd.read_parquet(part)
    df["render_version"] = "render-000000000000"
    df.to_parquet(part, index=False)
    with pytest.raises(ValueError, match="--force"):
        _run(mini_settings, locked_protocol, mini_documents)
    s = _run(mini_settings, locked_protocol, mini_documents, force=True)
    assert s.n_out == 1 and (pd.read_parquet(part).render_version == RENDER_VERSION).all()


def test_reauthored_document_invalidates_partition(mini_settings, locked_protocol, mini_documents):
    _run(mini_settings, locked_protocol, mini_documents)
    doc_part = Path(mini_settings.paths.processed_dir) / "documents" / "b0000.parquet"
    docs = pd.read_parquet(doc_part)
    doc_id = docs.doc_id.iloc[0]
    mask = docs.doc_id == doc_id
    docs.loc[mask, "text"] = docs.loc[mask, "text"] + " Extra sentence."
    docs.to_parquet(doc_part, index=False)
    stage = RenderStage(mini_settings, locked_protocol, mini_documents)
    assert stage.is_done(Batch("b0000")) is False
    with pytest.raises(ValueError, match="--force"):
        _run(mini_settings, locked_protocol, mini_documents)
    s = _run(mini_settings, locked_protocol, mini_documents, force=True)
    assert s.n_out == 1
    pages = mini_documents.read("pages")
    mine = pages[pages.doc_id == doc_id].sort_values("page_no")
    got = [w["word"] for r in mine.itertuples() for w in json.loads(r.gt_words)]
    assert got[-2:] == ["Extra", "sentence."]


def test_orphan_pages_partition_refused(mini_settings, locked_protocol, mini_documents):
    _run(mini_settings, locked_protocol, mini_documents)
    pdir = Path(mini_settings.paths.processed_dir) / "pages"
    (pdir / "b0000.parquet").rename(pdir / "b0042.parquet")
    with pytest.raises(ValueError, match="b0042"):
        _run(mini_settings, locked_protocol, mini_documents)


def test_overflow_quarantines_batch(mini_settings, locked_protocol, mini_documents, monkeypatch):
    # nothing fits under the letterhead
    monkeypatch.setattr("auditpace.render.stage.CONTENT_BOTTOM", 250)
    s = _run(mini_settings, locked_protocol, mini_documents)
    assert (s.n_out, s.n_quarantined) == (0, 1)
    q = (Path(mini_settings.paths.processed_dir) / "quarantine" / "render.jsonl").read_text()
    assert "OverflowError" in q and "block" in q
    assert not (Path(mini_settings.paths.processed_dir) / "pages" / "b0000.parquet").exists()


def test_deterministic_across_runs(mini_settings, locked_protocol, mini_documents):
    _run(mini_settings, locked_protocol, mini_documents)
    part = Path(mini_settings.paths.processed_dir) / "pages" / "b0000.parquet"
    first = pd.read_parquet(part)
    imgs = {p.name: p.read_bytes() for p in part.with_suffix("").glob("*.jpg")}
    _run(mini_settings, locked_protocol, mini_documents, force=True)
    second = pd.read_parquet(part)
    pd.testing.assert_frame_equal(first.sort_values("page_id").reset_index(drop=True),
                                  second.sort_values("page_id").reset_index(drop=True))
    assert all(p.read_bytes() == imgs[p.name] for p in part.with_suffix("").glob("*.jpg"))


def test_cli_exit_codes(mini_settings, locked_protocol, mini_documents, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITPACE_CONFIG", str(tmp_path / "config.yaml"))
    proto = str(tmp_path / "protocol.yaml")
    r = CliRunner().invoke(app, ["render", "--protocol", proto, "--workers", "1"])
    assert r.exit_code == 0 and "render: in=1 out=1 quarantined=0" in r.output
    monkeypatch.setattr("auditpace.render.stage.CONTENT_BOTTOM", 250)
    r = CliRunner().invoke(app, ["render", "--protocol", proto, "--force"])
    assert r.exit_code == 1 and "quarantined" in r.output


def test_cli_requires_documents(mini_settings, locked_protocol, mini_store, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITPACE_CONFIG", str(tmp_path / "config.yaml"))
    r = CliRunner().invoke(app, ["render", "--protocol", str(tmp_path / "protocol.yaml")])
    assert r.exit_code == 2 and "auditpace synth" in r.output
