"""DuckDB views over the Synthea CSV export. Dates are parsed to TIMESTAMP (UTC, naive)."""
from pathlib import Path

import duckdb
import pandas as pd

REQUIRED_TABLES = ["patients", "conditions", "encounters", "procedures", "medications"]
OPTIONAL_TABLES = ["observations", "careplans"]
TABLES = REQUIRED_TABLES + OPTIONAL_TABLES
_TS_COLS = {"START", "STOP", "DATE", "BIRTHDATE", "DEATHDATE"}


class SyntheaSource:
    def __init__(self, synthea_dir: Path):
        self.dir = Path(synthea_dir)
        self.con = duckdb.connect()
        for t in TABLES:
            p = self.dir / f"{t}.csv"
            if not p.exists():
                if t in REQUIRED_TABLES:
                    raise FileNotFoundError(f"Required Synthea table missing: {p}")
                continue
            rel = duckdb.read_csv(str(p), header=True, all_varchar=True)
            cols = rel.columns
            select = ", ".join(
                f"try_cast(replace({c}, 'Z', '') as TIMESTAMP) as {c}" if c in _TS_COLS else c for c in cols
            )
            self.con.execute(
                f"create view {t} as select {select} from read_csv('{p}', header=true, all_varchar=true)"
            )

    def table_names(self) -> list[str]:
        return [r[0] for r in self.con.execute("select table_name from information_schema.tables").fetchall()]

    def sql(self, query: str) -> pd.DataFrame:
        return self.con.execute(query).df()
