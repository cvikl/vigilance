"""One DuckDB file with views over parquet tables under data/processed/.

A table is either one file `<name>.parquet` or a directory `<name>/<part>.parquet` (one partition
per stage batch, so a resumable stage can write as it goes). Each partition is written atomically
(to `<part>.parquet.tmp`, then `os.replace` onto the final name) so a concurrent reader's glob over
`<name>/*.parquet` never observes a partially-written file. The DuckDB connection is not
thread-safe; every use goes through `_lock` so stages may call `write_part` from worker threads.
"""
import os
import re
import threading
from pathlib import Path
from typing import Self

import duckdb
import pandas as pd

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _check_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise ValueError(f"invalid table name {name!r}")


class Store:
    def __init__(self, processed_dir: Path, read_only: bool = False):
        self.dir = Path(processed_dir).resolve()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.read_only = read_only
        self._lock = threading.Lock()
        # A read-only consumer (sanity scripts while a stage runs) must not take DuckDB's file
        # lock, so it gets an in-memory connection with the same views over the parquet files.
        db_path = str(self.dir / "auditpace.duckdb")
        self.con = duckdb.connect() if read_only else duckdb.connect(db_path)
        for pq in self.dir.glob("*.parquet"):
            if _NAME_RE.match(pq.stem):
                self._register(pq.stem)
        for d in self.dir.iterdir():
            if d.is_dir() and _NAME_RE.match(d.name) and any(d.glob("*.parquet")):
                self._register(d.name)

    def _source(self, name: str) -> str:
        if self.path(name).exists():
            return str(self.path(name))
        return str(self.part_dir(name) / "*.parquet")

    def _register(self, name: str) -> None:
        with self._lock:
            self.con.execute(f"create or replace view {name} as select * from read_parquet('{self._source(name)}')")

    def path(self, name: str) -> Path:
        _check_name(name)
        return self.dir / f"{name}.parquet"

    def part_dir(self, name: str) -> Path:
        _check_name(name)
        return self.dir / name

    def exists(self, name: str) -> bool:
        return self.path(name).exists() or any(self.part_dir(name).glob("*.parquet"))

    def write(self, name: str, df: pd.DataFrame, protocol_hash: str) -> Path:
        if self.read_only:
            raise PermissionError("store opened read_only")
        _check_name(name)
        df = df.copy()
        if "protocol_hash" not in df.columns:
            df["protocol_hash"] = protocol_hash
        out = self.path(name)
        df.to_parquet(out, index=False)
        self._register(name)
        return out

    def write_part(self, name: str, part: str, df: pd.DataFrame, protocol_hash: str) -> Path:
        if self.read_only:
            raise PermissionError("store opened read_only")
        _check_name(name)
        _check_name(part)
        df = df.copy()
        if "protocol_hash" not in df.columns:
            df["protocol_hash"] = protocol_hash
        d = self.part_dir(name)
        d.mkdir(parents=True, exist_ok=True)
        out = d / f"{part}.parquet"
        tmp = out.with_name(out.name + ".tmp")
        df.to_parquet(tmp, index=False)
        os.replace(tmp, out)
        self._register(name)
        return out

    def read(self, name: str) -> pd.DataFrame:
        if self.path(name).exists():
            return pd.read_parquet(self.path(name))
        parts = sorted(self.part_dir(name).glob("*.parquet"))
        if not parts:
            raise FileNotFoundError(f"no table {name!r} under {self.dir}")
        return pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)

    def sql(self, query: str) -> pd.DataFrame:
        with self._lock:
            return self.con.execute(query).df()

    def close(self) -> None:
        with self._lock:
            self.con.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
