"""Review queue: which case the clinician should check next, and why (printed). Orders checking,
never care — ADR 0005. Spec §8."""
import pandas as pd

WEIGHTS = {"model_disagrees": 4, "unverified_evidence": 3, "abstain": 3, "in_alerted_segment": 2,
           "excess_hours": 2, "ci_leverage": 2}
NO_END_TEXT = {"H6": "no follow-up documented — nothing to review"}
NO_END_DEFAULT = "no end event documented — nothing to review"


def build_queue(cf: pd.DataFrame, alerts: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    pending = cf[cf.review_state.isna() | (cf.review_state == "flagged")].copy()
    max_excess = cf.groupby("criterion_id").excess_hours.max()
    n_y = cf[cf.y.notna()].groupby("criterion_id").size()
    org_alerts = {(a.criterion_id, a.segment_value): a.alert_id for a in alerts.itertuples() if a.kind == "org_outlier"}
    crit_alerts = {a.criterion_id: a.alert_id for a in alerts.itertuples() if a.kind == "criterion_below_target"}
    week_alerts = {(a.criterion_id, a.segment_value): a.alert_id for a in alerts.itertuples() if a.kind == "week_outlier"}
    rows = []
    for r in pending.itertuples():
        if r.category == "abstain_no_end":
            rows.append((r.case_id, r.patient_id, r.criterion_id, r.category, 0.0,
                         NO_END_TEXT.get(r.criterion_id, NO_END_DEFAULT), 0.0))
            continue
        fired: list[tuple[float, str]] = []
        if r.model_status is not None and not pd.isna(r.model_status) and r.model_status != r.verdict_status:
            fired.append((WEIGHTS["model_disagrees"], "model call ≠ computed status"))
        if r.any_unverified:
            fired.append((WEIGHTS["unverified_evidence"], "evidence not verified on page"))
        if r.category == "abstain":
            fired.append((WEIGHTS["abstain"], "abstained though end event exists"))
        hit = org_alerts.get((r.criterion_id, r.organization)) or crit_alerts.get(r.criterion_id) \
            or week_alerts.get((r.criterion_id, r.week))
        if hit:
            fired.append((WEIGHTS["in_alerted_segment"], f"in alerted cell: {hit}"))
        mx = float(max_excess.get(r.criterion_id, 0.0))
        if r.excess_hours > 0 and mx > 0:
            fired.append((WEIGHTS["excess_hours"] * r.excess_hours / mx, f"{r.excess_hours:.1f} h over target"))
        if int(n_y.get(r.criterion_id, 0)) < 5:
            fired.append((WEIGHTS["ci_leverage"], f"few reviews yet for {r.criterion_id}"))
        fired.sort(key=lambda t: -t[0])
        rows.append((r.case_id, r.patient_id, r.criterion_id, r.category, float(sum(w for w, _ in fired)),
                     "; ".join(t for _, t in fired), float(r.excess_hours)))
    df = pd.DataFrame(rows, columns=["case_id", "patient_id", "criterion_id", "category", "priority", "priority_reason", "excess_hours"])
    df["computed_ts"] = now
    return df.sort_values(["priority", "case_id"], ascending=[False, True], kind="stable").reset_index(drop=True)
