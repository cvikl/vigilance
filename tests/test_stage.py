import json
from pathlib import Path

import pytest
import yaml

from auditpace.protocol import Protocol, ProtocolNotLocked, load_protocol, lock_protocol
from auditpace.settings import load_settings
from auditpace.stage import Stage
from auditpace.store import Store

ROOT = Path(__file__).resolve().parents[1]


class Doubler(Stage):
    name = "doubler"

    def items(self):
        return [1, 2, "bad", 4]

    def process(self, item):
        return item * 2 if isinstance(item, int) else 1 / 0


def _locked_protocol(tmp_path: Path):
    p = tmp_path / "protocol.yaml"
    p.write_text((ROOT / "protocol.yaml").read_text())
    lock_protocol(p)
    return load_protocol(p)


def _unlocked_protocol():
    # protocol.yaml itself is locked (T7); build an unlocked copy in memory to test this path.
    data = yaml.safe_load((ROOT / "protocol.yaml").read_text())
    data["locked"] = False
    data["hash"] = None
    return Protocol.model_validate(data)


def _settings(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"paths: {{synthea_dir: x, processed_dir: {tmp_path/'proc'}, fixtures_dir: y}}\nmodels: {{}}\n")
    return load_settings(cfg)


def test_run_quarantines_failures_and_counts(tmp_path: Path):
    st = _settings(tmp_path)
    with Store(st.paths.processed_dir) as store:
        s = Doubler(st, _locked_protocol(tmp_path), store)
        summary = s.run()
        assert (summary.n_in, summary.n_out, summary.n_quarantined) == (4, 3, 1)
        assert s.outputs == [2, 4, 8]
        q = (store.dir / "quarantine" / "doubler.jsonl").read_text().strip().splitlines()
        assert json.loads(q[0])["type"] == "ZeroDivisionError"
        assert str(summary) == "doubler: in=4 out=3 quarantined=1"


def test_limit_applies(tmp_path: Path):
    st = _settings(tmp_path)
    with Store(st.paths.processed_dir) as store:
        assert Doubler(st, _locked_protocol(tmp_path), store).run(limit=2).n_in == 2


def test_run_resets_outputs_on_reuse(tmp_path: Path):
    st = _settings(tmp_path)
    with Store(st.paths.processed_dir) as store:
        s = Doubler(st, _locked_protocol(tmp_path), store)
        s.run()
        summary = s.run(limit=2)
        assert s.outputs == [2, 4]
        assert (summary.n_in, summary.n_out, summary.n_quarantined) == (2, 2, 0)


def test_refuses_unlocked_protocol(tmp_path: Path):
    st = _settings(tmp_path)
    with Store(st.paths.processed_dir) as store, pytest.raises(ProtocolNotLocked):
        Doubler(st, _unlocked_protocol(), store).run()


def test_quarantine_file_truncated_per_run(tmp_path: Path):
    st = _settings(tmp_path)
    with Store(st.paths.processed_dir) as store:
        s = Doubler(st, _locked_protocol(tmp_path), store)
        s.run()
        s.run()
        q = (store.dir / "quarantine" / "doubler.jsonl").read_text().strip().splitlines()
        assert len(q) == 1


class SkipsItem2(Doubler):
    name = "skips_item2"

    def is_done(self, item):
        return item == 2


def test_is_done_skips_unless_force(tmp_path: Path):
    st = _settings(tmp_path)
    with Store(st.paths.processed_dir) as store:
        s = SkipsItem2(st, _locked_protocol(tmp_path), store)
        summary = s.run()
        assert s.outputs == [2, 8]  # item 2 skipped, not doubled
        assert summary.n_out == 3
        assert summary.n_quarantined == 1

        summary2 = s.run(force=True)
        assert s.outputs == [2, 4, 8]  # item 2 processed this time
        assert summary2.n_out == 3
        assert summary2.n_quarantined == 1


def test_workers_match_sequential(tmp_path: Path):
    st = _settings(tmp_path)
    with Store(st.paths.processed_dir) as store:
        seq = Doubler(st, _locked_protocol(tmp_path), store)
        a = seq.run()
        par = Doubler(st, _locked_protocol(tmp_path), store)
        b = par.run(workers=3)
        assert (a.n_in, a.n_out, a.n_quarantined) == (b.n_in, b.n_out, b.n_quarantined) == (4, 3, 1)
        assert seq.outputs == par.outputs == [2, 4, 8]
        q = (store.dir / "quarantine" / "doubler.jsonl").read_text().strip().splitlines()
        assert len(q) == 1 and json.loads(q[0])["type"] == "ZeroDivisionError"


def test_workers_respects_limit_and_is_done(tmp_path: Path):
    class Half(Doubler):
        def is_done(self, item):
            return item == 2

    st = _settings(tmp_path)
    with Store(st.paths.processed_dir) as store:
        s = Half(st, _locked_protocol(tmp_path), store)
        summary = s.run(limit=2, workers=2)
        assert (summary.n_in, summary.n_out, summary.n_quarantined) == (2, 2, 0)
        assert s.outputs == [2]  # item 2 was done, not reprocessed
