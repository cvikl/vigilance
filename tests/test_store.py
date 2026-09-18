from pathlib import Path

import pandas as pd
import pytest

from auditpace.store import Store


def test_write_read_roundtrip_adds_hash(tmp_path: Path):
    with Store(tmp_path) as s:
        df = pd.DataFrame({"patient_id": ["a", "b"], "x": [1, 2]})
        out = s.write("patients", df, protocol_hash="abc")
        assert out == tmp_path / "patients.parquet"
        back = s.read("patients")
        assert list(back.columns) == ["patient_id", "x", "protocol_hash"]
        assert set(back.protocol_hash) == {"abc"}
        assert s.exists("patients") and not s.exists("nope")


def test_sql_over_views(tmp_path: Path):
    with Store(tmp_path) as s:
        s.write("cases", pd.DataFrame({"case_id": [1, 2, 3], "breached": [True, False, True]}), "h")
        n = s.sql("select count(*) as n from cases where breached").n[0]
        assert n == 2


def test_views_survive_reopen(tmp_path: Path):
    with Store(tmp_path) as s:
        s.write("events", pd.DataFrame({"e": [1]}), "h")
    with Store(tmp_path) as s2:
        assert s2.read("events").e[0] == 1


def test_write_rejects_bad_name(tmp_path: Path):
    with Store(tmp_path) as s:
        with pytest.raises(ValueError):
            s.write("bad-name", pd.DataFrame({"x": [1]}), "h")
        assert not any(tmp_path.glob("*.parquet"))


def test_init_ignores_non_identifier_parquet(tmp_path: Path):
    pd.DataFrame({"x": [1]}).to_parquet(tmp_path / "weird (1).parquet", index=False)
    with Store(tmp_path) as s, pytest.raises(ValueError):
        s.exists("weird (1)")


def test_partitions_write_read_exists(tmp_path: Path):
    with Store(tmp_path) as s:
        assert not s.exists("documents")
        p = s.write_part("documents", "b0001", pd.DataFrame({"doc_id": ["a", "b"]}), "h")
        assert p == tmp_path / "documents" / "b0001.parquet"
        s.write_part("documents", "b0000", pd.DataFrame({"doc_id": ["z"]}), "h")
        assert s.exists("documents")
        back = s.read("documents")
        assert list(back.doc_id) == ["z", "a", "b"]  # partitions concatenated in file-name order
        assert set(back.protocol_hash) == {"h"}
        assert s.sql("select count(*) as n from documents").n[0] == 3
    with Store(tmp_path) as s2:
        assert s2.sql("select count(*) as n from documents").n[0] == 3


def test_partition_rejects_bad_names(tmp_path: Path):
    with Store(tmp_path) as s:
        with pytest.raises(ValueError):
            s.write_part("documents", "../x", pd.DataFrame({"x": [1]}), "h")
        with pytest.raises(FileNotFoundError):
            s.read("documents")


def test_write_part_is_atomic_no_tmp_left_behind(tmp_path: Path):
    with Store(tmp_path) as s:
        s.write_part("documents", "b0000", pd.DataFrame({"doc_id": ["a", "b"]}), "h")
        part_dir = tmp_path / "documents"
        assert not list(part_dir.glob("*.tmp"))
        assert sorted(p.name for p in part_dir.glob("*")) == ["b0000.parquet"]
        assert list(s.read("documents").doc_id) == ["a", "b"]


def test_read_only_store_reads_partitions_and_refuses_writes(tmp_path):
    import pandas as pd
    import pytest

    from auditpace.store import Store
    with Store(tmp_path) as w:
        w.write_part("t", "b0000", pd.DataFrame({"a": [1, 2]}), "h")
        with Store(tmp_path, read_only=True) as r:  # opens while the writer still holds the db file
            assert r.exists("t") and len(r.read("t")) == 2
            assert r.sql("select count(*) as n from t").n[0] == 2
            with pytest.raises(PermissionError):
                r.write_part("t", "b0001", pd.DataFrame({"a": [3]}), "h")
            with pytest.raises(PermissionError):
                r.write("u", pd.DataFrame({"a": [3]}), "h")
