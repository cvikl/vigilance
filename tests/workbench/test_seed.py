import importlib.util
from pathlib import Path

import pandas as pd

from auditpace.estimate.reviews import latest_reviews
from auditpace.store import Store
from auditpace.workbench.snapshot import Snapshot

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed_reviews.py"


def _load():
    spec = importlib.util.spec_from_file_location("seed_reviews", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_writes_truth_labelled_reviews_and_respects_exclusions(toy_processed, toy_protocol):
    mod = _load()
    counts = mod.seed(toy_processed, toy_protocol, per_criterion=3, seed=1, exclude={"sys:H4", "dis:H4"})
    assert counts["H4"] == 3 and counts["H6"] == 3 and counts.get("H2", 0) == 0  # H2's only case is an abstain
    with Store(toy_processed, read_only=True) as s:
        rv = s.read("reviews")
    assert set(rv.reviewer) == {"seed"} and set(rv.validation_state) == {"validated"}
    assert {"sys:H4", "dis:H4", "abs:H2", "noend:H6"}.isdisjoint(set(rv.case_id))
    cases = pd.read_parquet(toy_processed / "cases.parquet").set_index("case_id")
    for r in rv.itertuples():
        truth = bool(cases.loc[r.case_id, "breached"])
        assert (r.human_status == "breached") == truth
        if truth:
            assert r.human_reason in toy_protocol.criteria[[c.id for c in toy_protocol.criteria].index(r.case_id.rsplit(":", 1)[1])].reasons
    snap = Snapshot.load(toy_processed, toy_protocol)
    assert snap.progress()[0] == 6


def test_seed_is_deterministic_and_wipe_resets(toy_processed, toy_protocol):
    mod = _load()
    mod.seed(toy_processed, toy_protocol, per_criterion=2, seed=7, exclude=set())
    with Store(toy_processed, read_only=True) as s:
        first = sorted(s.read("reviews").case_id)
    mod.seed(toy_processed, toy_protocol, per_criterion=2, seed=7, exclude=set(), wipe=True)
    with Store(toy_processed, read_only=True) as s:
        rv = s.read("reviews")
    assert sorted(rv.case_id) == first and len(latest_reviews(rv)) == len(rv)


def test_demo_cases_file_parses():
    mod = _load()
    ids = mod.read_exclude(Path(__file__).resolve().parents[2] / "docs" / "demo_cases.txt")
    assert isinstance(ids, set)
