"""Alerts: every fired signal as one row that names an action and an owner from the protocol's
`actions:` block — never from a model. Spec §7."""
import math

import pandas as pd

from auditpace.protocol import Protocol


def dominant_reason(cell: pd.DataFrame) -> str | None:
    br = cell[cell.effective_status == "breached"]
    if br.empty:
        return None
    sys_tags = br[br.reason_class == "system"].effective_reason.value_counts()
    n_und = int((br.reason_class == "undetermined").sum())
    if sys_tags.empty:
        return "undetermined" if n_und else None
    top = sys_tags.sort_index().sort_values(ascending=False, kind="stable")
    return "undetermined" if n_und > int(top.iloc[0]) else str(top.index[0])


def _pct(x: float) -> str:
    return "n/a" if x is None or math.isnan(x) else f"{100 * x:.0f} %"


def _row(kind, cid, key, value, signal, rate, lo, hi, n, method, hours_lost, cell, protocol, now, why) -> dict:
    """One alert. `method` is the cell estimate's (naive | ppi | classical) and `n_reviewed` the cell's
    estimation-pool reviews, so S7 can show whether the rate behind an alert is corrected yet."""
    dom = dominant_reason(cell)
    n_dom = int((cell.effective_reason == dom).sum()) if dom and dom != "undetermined" else int((cell.reason_class == "undetermined").sum())
    just = f"{cid} {'overall' if value == 'all' else 'in ' + str(value)}: {_pct(rate)} breached (CI {_pct(lo)}–{_pct(hi)}, n = {n}); {why}; {hours_lost:.0f} h lost" \
           + (f", mostly {dom} (n = {n_dom})" if dom else "")
    return {"alert_id": f"{kind}:{cid}:{value}", "kind": kind, "criterion_id": cid, "segment_key": key, "segment_value": str(value),
            "signal": signal, "rate": rate, "lo": lo, "hi": hi, "n": n, "n_reviewed": int(cell.y.notna().sum()), "method": method,
            "hours_lost": hours_lost, "dominant_reason": dom,
            "action": protocol.action(cid, dom), "owner": protocol.owner(cid), "justification": just, "computed_ts": now}


def build_alerts(cf, estimates, funnel, runchart, timelost, protocol: Protocol, now: pd.Timestamp) -> pd.DataFrame:
    rows = []
    tl_crit = timelost[timelost.organization_id == "all"].set_index("criterion_id")
    tl_org = timelost[timelost.organization_id != "all"].set_index(["criterion_id", "organization_id"])
    for c in protocol.criteria:
        cid = c.id
        sub = cf[cf.criterion_id == cid]
        if sub.empty:
            continue
        allrow = estimates[(estimates.criterion_id == cid) & (estimates.segment_key == "all")].iloc[0]
        hl = float(tl_crit.loc[cid, "hours_lost"])
        target = protocol.compliance_target(cid)
        if target is not None and not allrow.suppressed and (1 - allrow.corrected_lo) < target:
            rows.append(_row("criterion_below_target", cid, "all", "all", "below_target", allrow.corrected_rate, allrow.corrected_lo,
                             allrow.corrected_hi, int(allrow.n), allrow.method, hl, sub, protocol, now,
                             f"compliance at most {_pct(1 - allrow.corrected_lo)} vs target {_pct(target)}"))
        for f in funnel[funnel.criterion_id == cid].itertuples():
            if f.signal in ("alert_high", "alarm_high", "alert_low", "alarm_low"):
                kind = "org_outlier" if f.signal.endswith("high") else "org_exemplar"
                cell = sub[sub.organization == f.organization_id]
                rows.append(_row(kind, cid, "organization", f.organization_id, f.signal, f.rate, f.lo, f.hi, int(f.n), f.method,
                                 float(tl_org.loc[(cid, f.organization_id), "hours_lost"]), cell, protocol, now,
                                 f"vs {_pct(f.centre)} overall, {f.signal.replace('_', ' ')} on the funnel"))
        latest = runchart[(runchart.criterion_id == cid) & runchart.latest]
        if len(latest) and latest.signal.iloc[0] in ("alert_high", "alarm_high"):
            w = latest.iloc[0]
            cell = sub[sub.week == w.week]
            rows.append(_row("week_outlier", cid, "week", w.week, w.signal, w.rate, w.lo, w.hi, int(w.n), w.method,
                             float(cell[cell.category == "breached_system"].excess_hours.sum()), cell, protocol, now,
                             f"latest week {w.week} above the {'3σ' if w.signal == 'alarm_high' else '2σ'} limit"))
        if int(tl_crit.loc[cid, "rank"]) == 1:
            rows.append(_row("top_time_lost", cid, "all", "all", "rank_1", allrow.corrected_rate, allrow.corrected_lo,
                             allrow.corrected_hi, int(allrow.n), allrow.method, hl, sub, protocol, now, "most hours lost of any handoff"))
    cols = ["alert_id", "kind", "criterion_id", "segment_key", "segment_value", "signal", "rate", "lo", "hi", "n", "n_reviewed",
            "method", "hours_lost", "dominant_reason", "action", "owner", "justification", "computed_ts"]
    df = pd.DataFrame(rows, columns=cols)
    df["dominant_reason"] = df.dominant_reason.astype(object).where(df.dominant_reason.notna(), None).astype("string")
    return df
