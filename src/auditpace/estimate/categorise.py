"""One row per applicable case with its effective status, reason class and estimator inputs (spec §4).

Two review-override rulings: (1) a row is categorised "abstain" whenever its `effective_status` is
"abstain" — whether that came from a verdict abstain (never overridden, since `usable` excludes
verdict-abstain rows) or from a reviewer setting `human_status="abstain"` on an otherwise-called verdict.
(2) `reviewed` means "a non-flagged latest review exists" for ANY row, decoupled from whether that
review's value was actually applied as the effective status.
"""
import json

import numpy as np
import pandas as pd

from auditpace.estimate.reviews import latest_reviews
from auditpace.protocol import Protocol

CATEGORIES = ["abstain_no_end", "abstain", "not_breached", "breached_system", "breached_legitimate",
              "breached_undetermined"]
SEGMENT_COLS = ["age_band", "sex", "race", "ethnicity", "organization"]


def reason_class_of(protocol: Protocol, criterion_id: str, status, reason) -> str | None:
    """None unless `status` is "breached"; "undetermined" for a breached row with no reason tag; else the
    protocol's class for the tag. The one place this rule lives — `segments` shares it for Ŷ and Y."""
    if status != "breached":
        return None
    if reason is None or pd.isna(reason):
        return "undetermined"
    return protocol.reason_class(criterion_id, reason)


def _any_unverified(evidence_json: str) -> bool:
    try:
        ev = json.loads(evidence_json) if evidence_json else []
    except (TypeError, ValueError):
        return True
    return any(not e.get("verified", False) for e in ev)


def _iso_week(ts: pd.Series) -> tuple[pd.Series, pd.Series]:
    iso = ts.dt.isocalendar()
    week = iso.year.astype(str) + "-W" + iso.week.astype(int).map("{:02d}".format)
    week_start = (ts - pd.to_timedelta(ts.dt.weekday, unit="D")).dt.normalize()
    return week, week_start


def categorise(verdicts: pd.DataFrame, cases: pd.DataFrame, patients: pd.DataFrame,
               reviews: pd.DataFrame, protocol: Protocol) -> pd.DataFrame:
    targets = {c.id: c.target_hours for c in protocol.criteria}
    c = cases[cases.applies][["case_id", "patient_id", "criterion_id", "start_ts", "end_ts"]]
    v = verdicts[["case_id", "status", "model_status", "reason_tag", "hours_documented", "evidence"]]
    applicable, have = set(c.case_id), set(v.case_id)
    if applicable != have:  # a partial `adjudicate --limit` run must not silently estimate over a subset
        raise ValueError(f"verdicts cover {len(applicable & have)} of {len(applicable)} applicable cases"
                         f"{f' (+{len(have - applicable)} unknown)' if have - applicable else ''}; "
                         "run `auditpace adjudicate` to completion")
    cf = c.merge(v, on="case_id", how="inner", validate="one_to_one")
    p = patients[["patient_id", "age_band", "sex", "race", "ethnicity", "organization_id"]].copy()
    p["organization"] = p.organization_id.astype(object).where(p.organization_id.notna(), "unknown")
    cf = cf.merge(p.drop(columns="organization_id"), on="patient_id", how="left")

    cf["verdict_status"] = cf.pop("status")
    cf["verdict_reason"] = cf.pop("reason_tag").astype(object).where(lambda s: s.notna(), None)
    cf["model_status"] = cf.model_status.astype(object).where(cf.model_status.notna(), None)
    no_end = cf.end_ts.isna()

    # effective status / reason: latest non-flagged review wins on rows that have data to review and
    # whose verdict wasn't itself an abstain (ruling 1: abstain of either kind is never overridden)
    lr = latest_reviews(reviews)
    lr = lr[["case_id", "validation_state", "human_status", "human_reason", "pool"]] if not lr.empty \
        else pd.DataFrame(columns=["case_id", "validation_state", "human_status", "human_reason", "pool"])
    cf = cf.merge(lr, on="case_id", how="left")
    cf["review_state"] = cf.validation_state.astype(object).where(cf.validation_state.notna(), None)
    cf["pool"] = cf.pool.astype(object).where(cf.pool.notna(), None)
    non_flagged_review = cf.review_state.notna() & (cf.review_state != "flagged")
    # ruling 2: reviewed just means "a non-flagged latest review exists", independent of category/override
    cf["reviewed"] = non_flagged_review
    # defensive: `review_frame` already rejects a non-flagged review without a status (rubric C1: never impute)
    usable = non_flagged_review & ~no_end & (cf.verdict_status != "abstain") & cf.human_status.isin(["breached", "not_breached", "abstain"])
    hs = cf.human_status.astype(object).where(cf.human_status.notna(), None)
    hr = cf.human_reason.astype(object).where(cf.human_reason.notna(), None)
    cf["effective_status"] = np.where(usable, hs, cf.verdict_status)
    cf["effective_reason"] = np.where(usable, hr, cf.verdict_reason)
    cf.loc[cf.effective_status != "breached", "effective_reason"] = None

    cf["reason_class"] = [reason_class_of(protocol, r.criterion_id, r.effective_status, r.effective_reason)
                          for r in cf.itertuples()]

    cat = pd.Series("not_breached", index=cf.index, dtype=object)
    breached_mask = cf.effective_status == "breached"
    cat[breached_mask] = "breached_" + cf.reason_class[breached_mask]  # always str here: never None on a breached row
    # ruling 1 (corrected): abstain, from either the verdict or a reviewer's human_status — usable already
    # excludes verdict-abstain rows so their effective_status stays "abstain" too; this also catches a
    # reviewer who sets human_status="abstain" on an otherwise-called verdict
    cat[cf.effective_status == "abstain"] = "abstain"
    cat[no_end] = "abstain_no_end"  # applied last: no-end always wins
    cf["category"] = cat
    cf["estimable"] = ~cf.category.isin(["abstain", "abstain_no_end"])
    cf["yhat"] = (cf.verdict_status == "breached") & cf.estimable
    y_ok = usable & (cf.pool == "estimation") & cf.estimable & cf.human_status.isin(["breached", "not_breached"])
    cf["y"] = [(bool(s == "breached") if ok else None) for s, ok in zip(hs, y_ok)]
    cf["y"] = cf.y.astype(object)

    cf["target_hours"] = cf.criterion_id.map(targets)
    cf["hours"] = cf.hours_documented.where(cf.estimable, np.nan)
    cf["excess_hours"] = (cf.hours - cf.target_hours).clip(lower=0).fillna(0.0)
    cf["any_unverified"] = [_any_unverified(e) for e in cf.evidence]
    cf["week"], cf["week_start"] = _iso_week(cf.start_ts)
    cols = ["case_id", "patient_id", "criterion_id", "category", "effective_status", "effective_reason", "reason_class",
            "verdict_status", "model_status", "verdict_reason", "hours", "target_hours", "excess_hours", "yhat",
            "estimable", "reviewed", "review_state", "pool", "y", "any_unverified", "week", "week_start", "start_ts",
            *SEGMENT_COLS]
    return cf[cols].reset_index(drop=True)
