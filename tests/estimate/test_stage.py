import shutil

import pandas as pd
import pytest
from typer.testing import CliRunner

from auditpace.cli import app
from auditpace.estimate.compute import StaleTable, compute_all, load_inputs
from auditpace.estimate.reviews import assign_pool, review_frame
from auditpace.estimate.stage import EstimateStage
from auditpace.store import Store
from tests.estimate.conftest import make_mini_reviews

TABLES = ["estimates", "funnel", "runchart", "timelost", "alerts", "queue"]
runner = CliRunner()


def test_compute_all_on_mini_without_reviews(locked_protocol, mini_verdicts):
    out = compute_all(mini_verdicts, locked_protocol)
    assert set(out) == set(TABLES)
    est = out["estimates"]
    allrows = est[est.segment_key == "all"].set_index("criterion_id")
    v = mini_verdicts.read("verdicts")
    cases = mini_verdicts.read("cases")
    assert allrows.n.sum() + allrows.n_abstain.sum() + allrows.n_no_end.sum() == int(cases.applies.sum()) == len(v)
    assert allrows.loc["H6", "n_no_end"] == int(cases[cases.applies & (cases.criterion_id == "H6")].end_ts.isna().sum()) == 2
    live = allrows[allrows.n > 0]
    assert (live.method == "naive").all() and (live.flag == "n_reviewed_insufficient").all()
    assert (out["alerts"].kind == "top_time_lost").sum() == 1
    assert out["alerts"].action.notna().all() and out["alerts"].owner.notna().all()
    q = out["queue"]
    assert len(q) == len(v) and (q[q.category == "abstain_no_end"].priority == 0).all()
    assert q.priority.is_monotonic_decreasing


def test_reviews_change_corrected_and_shrink_queue(locked_protocol, mini_verdicts):
    reviews = make_mini_reviews(mini_verdicts, locked_protocol)
    mini_verdicts.write("reviews", reviews, locked_protocol.hash)
    out = compute_all(mini_verdicts, locked_protocol)
    est = out["estimates"]
    n_rev = est[est.segment_key == "all"].n_reviewed.sum()
    assert n_rev == 2  # r1 validated + r2 disputed in the estimation pool; r3 flagged and r4 tuning don't count
    queued = set(out["queue"].case_id)
    assert set(reviews[reviews.validation_state != "flagged"].case_id).isdisjoint(queued)
    assert set(reviews[reviews.validation_state == "flagged"].case_id) <= queued
    # the disputed review's criterion counts it, but one review is not enough for PPI
    disputed = reviews[reviews.validation_state == "disputed"].case_id.iloc[0]
    cid = disputed.rsplit(":", 1)[1]
    row = est[(est.criterion_id == cid) & (est.segment_key == "all")].iloc[0]
    assert row.n_reviewed == 1 and row.method == "naive" and row.flag == "n_reviewed_insufficient"
    al = out["alerts"]
    assert set(al.columns) >= {"method", "n_reviewed"} and (al.method == "naive").all() and (al.n_reviewed == 0).all()
    # a second estimation-pool review on that criterion switches PPI on; the disputed call moves the corrected rate
    h, frac = locked_protocol.hash, locked_protocol.review.estimation_pool_fraction
    v = mini_verdicts.read("verdicts")
    more = v[(v.criterion_id == cid) & (v.status != "abstain") & ~v.case_id.isin(reviews.case_id)]
    more = [c for c in more.case_id if assign_pool(c, h, frac) == "estimation"]
    assert more, f"mini cohort must have another estimation-pool {cid} case"
    extra = review_frame([{"review_id": "r5", "case_id": more[0], "reviewer": "dr_a", "validation_state": "validated",
                           "human_status": v.set_index("case_id").status[more[0]], "human_reason": None, "note": None,
                           "pool": "estimation", "reviewed_ts": "2026-09-16T10:04:00", "protocol_hash": h}])
    extra["human_reason"] = extra.human_reason.where(extra.human_status == "breached", None)
    mini_verdicts.write("reviews", pd.concat([reviews, extra], ignore_index=True), h)
    est2 = compute_all(mini_verdicts, locked_protocol)["estimates"]
    row2 = est2[(est2.criterion_id == cid) & (est2.segment_key == "all")].iloc[0]
    assert row2.n_reviewed == 2 and row2.method == "ppi" and pd.isna(row2.flag)  # a discrepancy was observed
    assert row2.corrected_rate != row2.naive_rate and row2.naive_rate == row.naive_rate


def test_stage_writes_tables_and_is_idempotent(mini_settings, locked_protocol, mini_verdicts):
    s = EstimateStage(mini_settings, locked_protocol, mini_verdicts).run()
    assert (s.n_in, s.n_out, s.n_quarantined) == (1, 1, 0)
    for t in TABLES:
        df = mini_verdicts.read(t)
        assert (df.protocol_hash == locked_protocol.hash).all(), t
    first = mini_verdicts.read("estimates").drop(columns="computed_ts")
    EstimateStage(mini_settings, locked_protocol, mini_verdicts).run()
    pd.testing.assert_frame_equal(first, mini_verdicts.read("estimates").drop(columns="computed_ts"))
    with Store(mini_settings.paths.processed_dir, read_only=True) as ro:
        out = compute_all(ro, locked_protocol)
        assert len(out["queue"]) == len(mini_verdicts.read("queue"))


def test_stage_coverage_table(mini_settings, locked_protocol, mini_verdicts):
    EstimateStage(mini_settings, locked_protocol, mini_verdicts, coverage=True, sims=20).run()
    cov = mini_verdicts.read("coverage")
    assert set(cov.method) == {"naive", "corrected"} and (cov.n_sims == 20).all()


def test_load_inputs_missing_verdicts(locked_protocol, mini_store):
    with pytest.raises(FileNotFoundError, match="missing verdicts"):
        load_inputs(mini_store, locked_protocol)


def test_partial_verdicts_raise(locked_protocol, mini_verdicts):
    """A `verdicts` table from `adjudicate --limit` must not silently estimate over a subset."""
    v = mini_verdicts.read("verdicts")
    shutil.rmtree(mini_verdicts.part_dir("verdicts"))
    mini_verdicts.write("verdicts", v.iloc[1:], locked_protocol.hash)
    with pytest.raises(ValueError, match=rf"verdicts cover {len(v) - 1} of {len(v)} applicable cases"):
        compute_all(mini_verdicts, locked_protocol)


def test_load_inputs_stale_hash(locked_protocol, mini_verdicts):
    v = mini_verdicts.read("verdicts")
    v["protocol_hash"] = "deadbeef"
    shutil.rmtree(mini_verdicts.part_dir("verdicts"))   # the partition dir; the single-file write below replaces it
    mini_verdicts.write("verdicts", v, "deadbeef")
    with pytest.raises(StaleTable, match="verdicts"):
        load_inputs(mini_verdicts, locked_protocol)


def test_stage_raises_on_stale_hash(mini_settings, locked_protocol, mini_verdicts):
    v = mini_verdicts.read("verdicts")
    v["protocol_hash"] = "deadbeef"
    shutil.rmtree(mini_verdicts.part_dir("verdicts"))
    mini_verdicts.write("verdicts", v, "deadbeef")
    with pytest.raises(StaleTable):
        EstimateStage(mini_settings, locked_protocol, mini_verdicts).run()


def test_estimate_exits_2_on_unlocked_protocol(mini_settings, locked_protocol, mini_verdicts, tmp_path, monkeypatch):
    proto = tmp_path / "protocol.yaml"
    proto.write_text(proto.read_text().replace("locked: true", "locked: false", 1))
    monkeypatch.setenv("AUDITPACE_CONFIG", str(tmp_path / "config.yaml"))
    result = runner.invoke(app, ["estimate", "--protocol", str(proto)])
    assert result.exit_code == 2, result.output
    assert "not locked" in result.output


def test_estimate_exits_2_on_stale_hash(mini_settings, locked_protocol, mini_verdicts, tmp_path, monkeypatch):
    v = mini_verdicts.read("verdicts")
    v["protocol_hash"] = "deadbeef"
    shutil.rmtree(mini_verdicts.part_dir("verdicts"))
    mini_verdicts.write("verdicts", v, "deadbeef")
    monkeypatch.setenv("AUDITPACE_CONFIG", str(tmp_path / "config.yaml"))
    result = runner.invoke(app, ["estimate", "--protocol", str(tmp_path / "protocol.yaml")])
    assert result.exit_code == 2, result.output
    assert "stale protocol_hash" in result.output
