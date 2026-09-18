"""`compute_all`: every S6 table from the store in one call (also used in-process by the workbench). Spec §10."""
import duckdb
import pandas as pd

from auditpace.estimate.alerts import build_alerts
from auditpace.estimate.categorise import categorise
from auditpace.estimate.funnel import build_funnel
from auditpace.estimate.queue import build_queue
from auditpace.estimate.reviews import empty_reviews
from auditpace.estimate.runchart import build_runchart
from auditpace.estimate.segments import build_estimates
from auditpace.estimate.timelost import build_timelost
from auditpace.protocol import Protocol
from auditpace.store import Store

VERDICT_COLS = ["case_id", "status", "model_status", "reason_tag", "hours_documented", "evidence", "protocol_hash"]


class StaleTable(ValueError):
    """A table carries rows for a different protocol hash (re-lock invalidates S5/S7 outputs)."""


def _check_hash(df: pd.DataFrame, name: str, protocol: Protocol) -> None:
    if "protocol_hash" in df.columns and len(df):
        stale = set(df.protocol_hash.dropna()) - {protocol.hash}
        if stale:
            raise StaleTable(f"{name}: {len(stale)} stale protocol_hash value(s) — run the upstream stage with --force")


def _read_verdicts(store: Store) -> pd.DataFrame:
    """Only the columns S6 uses, through DuckDB's view over the 300 partitions (one scan, ~0.2 s) rather
    than `store.read`'s per-file pandas reads (~2.5 s). Falls back to `store.read` when the table appeared
    after this store's views were registered."""
    try:
        return store.sql(f"select {', '.join(VERDICT_COLS)} from verdicts")
    except duckdb.CatalogException:
        return store.read("verdicts")[VERDICT_COLS]


def load_inputs(store: Store, protocol: Protocol) -> dict[str, pd.DataFrame]:
    for t, prev in (("verdicts", "adjudicate"), ("cases", "cohort"), ("patients", "cohort")):
        if not store.exists(t):
            raise FileNotFoundError(f"missing {t}; run `auditpace {prev}` first")
    out = {"verdicts": _read_verdicts(store), "cases": store.read("cases"), "patients": store.read("patients")}
    out["reviews"] = store.read("reviews") if store.exists("reviews") else empty_reviews()
    for t in ("verdicts", "reviews"):
        _check_hash(out[t], t, protocol)
    return out


def compute_all(store: Store, protocol: Protocol, now: pd.Timestamp | None = None) -> dict[str, pd.DataFrame]:
    now = now if now is not None else pd.Timestamp.now("UTC").tz_localize(None)
    inp = load_inputs(store, protocol)
    cf = categorise(inp["verdicts"], inp["cases"], inp["patients"], inp["reviews"], protocol)
    estimates = build_estimates(cf, protocol, now)
    funnel = build_funnel(cf, estimates, protocol, now)
    runchart = build_runchart(cf, estimates, protocol, now)
    timelost = build_timelost(cf, now)
    alerts = build_alerts(cf, estimates, funnel, runchart, timelost, protocol, now)
    queue = build_queue(cf, alerts, now)
    return {"estimates": estimates, "funnel": funnel, "runchart": runchart, "timelost": timelost,
            "alerts": alerts, "queue": queue}
