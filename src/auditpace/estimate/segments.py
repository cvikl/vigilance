"""`estimates`: naive vs corrected breach rates per criterion × segment, with reason-class rates. Spec §5–6.

Ŷ (the verdict's call) and Y (the reviewer's call) are built as numpy arrays once per criterion; each
segment cell is a positional slice of them and every indicator — breach, reason class, reason tag — is a
numpy comparison on the slice, so no per-row Python runs inside the cell loop."""
import json
import math

import numpy as np
import pandas as pd

from auditpace.estimate.categorise import SEGMENT_COLS, reason_class_of
from auditpace.estimate.ppi import Estimate, estimate_rate, naive_rate, z_for
from auditpace.protocol import Protocol

_NAN = Estimate(math.nan, math.nan, math.nan, "naive", None, 0, 0)
CLASSES = ("system", "legitimate", "undetermined")
COUNTS = {"n_abstain": "abstain", "n_no_end": "abstain_no_end", "n_breached_system": "breached_system",
          "n_breached_legitimate": "breached_legitimate", "n_breached_undetermined": "breached_undetermined"}


def _classes(breached: np.ndarray, reasons: np.ndarray, cmap: dict) -> np.ndarray:
    """Reason class per row: None unless breached, "undetermined" for a null tag (`reason_class_of`'s rule)."""
    cls = np.array([cmap.get(r) for r in reasons], dtype=object)
    cls[breached & pd.isna(cls)] = "undetermined"
    cls[~breached] = None
    return cls


class CriterionArrays:
    """One criterion's rows as aligned numpy arrays. `yhat` is the verdict's breach call, `y` the
    reviewer's (False where no Y exists — see `has_y`); `vreason`/`ereason` the verdict's and the
    effective (post-review) reason tag; `vclass`/`hclass` their classes via `reason_class_of`."""

    def __init__(self, sub: pd.DataFrame, protocol: Protocol, cid: str):
        self.category = sub.category.to_numpy(dtype=object)
        self.estimable = sub.estimable.to_numpy(dtype=bool)
        self.yhat = (sub.verdict_status == "breached").to_numpy(dtype=bool)
        y = sub.y.to_numpy(dtype=object)
        self.has_y = ~pd.isna(y)
        self.y = np.where(self.has_y, y, False).astype(bool)
        self.vreason = sub.verdict_reason.to_numpy(dtype=object)
        self.ereason = sub.effective_reason.to_numpy(dtype=object)
        self.ebreached = (sub.effective_status == "breached").to_numpy(dtype=bool)
        tags = {t for t in np.concatenate([self.vreason, self.ereason]) if not pd.isna(t)}
        cmap = {t: reason_class_of(protocol, cid, "breached", t) for t in tags}
        self.vclass = _classes(self.yhat, self.vreason, cmap)
        self.hclass = _classes(self.y, self.ereason, cmap)  # on Y rows the effective call is the reviewer's

    def cell(self, idx: np.ndarray) -> "CellArrays":
        return CellArrays(self, idx)


class CellArrays:
    """A cell's slice of `CriterionArrays`: estimable rows only, with Y arrays restricted to reviewed rows."""

    def __init__(self, crit: CriterionArrays, idx: np.ndarray):
        est = idx[crit.estimable[idx]]
        self.n, self.n_reviewed = len(est), int(crit.has_y[idx].sum())
        self.counts = {k: int((crit.category[idx] == v).sum()) for k, v in COUNTS.items()}
        self.yhat, self.has_y = crit.yhat[est], crit.has_y[est]
        rev = est[self.has_y]
        self.y, self.hreason, self.hclass = crit.y[rev], crit.ereason[rev], crit.hclass[rev]
        self.vreason, self.vclass = crit.vreason[est], crit.vclass[est]
        self.ereason, self.ebreached = crit.ereason[est], crit.ebreached[est]

    def estimate(self, yhat_ind: np.ndarray, y_ind: np.ndarray, z: float) -> Estimate:
        """Corrected estimate of P(indicator): Ŷ from the verdict on every row, Y from the reviewer."""
        return estimate_rate(yhat_ind, yhat_ind[self.has_y], y_ind, z) if self.n else _NAN

    def tag_masks(self, tag: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(Ŷ, Y, effective) indicators for one reason tag; "undetermined" is a breach with a null tag."""
        if tag == "undetermined":
            return self.yhat & pd.isna(self.vreason), self.y & pd.isna(self.hreason), self.ebreached & pd.isna(self.ereason)
        return self.yhat & (self.vreason == tag), self.y & (self.hreason == tag), self.ebreached & (self.ereason == tag)


def cell_rates(a: CellArrays, z: float) -> tuple[Estimate, Estimate]:
    """(naive, corrected) breach-rate estimate for one cell — the funnel and run chart use this too."""
    return (naive_rate(a.yhat, z), a.estimate(a.yhat, a.y, z)) if a.n else (_NAN, _NAN)


def criterion_cells(sub: pd.DataFrame, key: str):
    """Yield `(value, row positions)` per value of `key` in a one-criterion frame, sorted; null keys dropped."""
    groups = sub.groupby(key, sort=True).indices
    for value in sorted(groups):
        yield value, groups[value]


def _row(a: CellArrays, cid: str, key: str, value: str, tags: list[str], protocol: Protocol, z: float, now) -> dict:
    nv, cv = cell_rates(a, z)
    suppressed = a.n < protocol.suppress_below
    row = {
        "criterion_id": cid, "segment_key": key, "segment_value": value, "n": a.n, "n_reviewed": a.n_reviewed, **a.counts,
        "naive_rate": nv.rate, "naive_lo": nv.lo, "naive_hi": nv.hi,
        "corrected_rate": cv.rate, "corrected_lo": cv.lo, "corrected_hi": cv.hi, "method": cv.method, "flag": cv.flag,
    }
    for cls in CLASSES:
        e = a.estimate(a.vclass == cls, a.hclass == cls, z)
        row[f"rate_{cls}"], row[f"rate_{cls}_lo"], row[f"rate_{cls}_hi"] = e.rate, e.lo, e.hi
    rb = {}
    for tag in tags:
        vi, yi, ei = a.tag_masks(tag)
        e = a.estimate(vi, yi, z)
        rb[tag] = {"n": int(ei.sum()), "rate": e.rate, "lo": e.lo, "hi": e.hi}
    row["reason_breakdown"] = json.dumps(rb, allow_nan=True)
    row["suppressed"] = suppressed
    if suppressed:
        for k in list(row):
            if k.startswith(("naive_", "corrected_", "rate_")):
                row[k] = math.nan
        row["reason_breakdown"] = json.dumps({t: {"n": rb[t]["n"], "rate": None, "lo": None, "hi": None} for t in rb})
    row["computed_ts"] = now
    return row


def build_estimates(cf: pd.DataFrame, protocol: Protocol, now: pd.Timestamp) -> pd.DataFrame:
    z = z_for(protocol.review.confidence)
    want = set(protocol.segments)  # protocol says `organization`; the case frame column is `organization`
    if not want <= set(SEGMENT_COLS):
        raise ValueError(f"unsupported segments {sorted(want - set(SEGMENT_COLS))}; supported: {SEGMENT_COLS}")
    keys = [s for s in SEGMENT_COLS if s in want]
    rows = []
    for c in protocol.criteria:
        sub = cf[cf.criterion_id == c.id].reset_index(drop=True)
        if sub.empty:
            continue
        tags = c.reasons + ["undetermined"]
        crit = CriterionArrays(sub, protocol, c.id)
        rows.append(_row(crit.cell(np.arange(len(sub))), c.id, "all", "all", tags, protocol, z, now))
        for key in keys:
            for value, idx in criterion_cells(sub, key):
                rows.append(_row(crit.cell(idx), c.id, key, str(value), tags, protocol, z, now))
    df = pd.DataFrame(rows)
    df["flag"] = df.flag.astype(object).where(df.flag.notna(), None).astype("string")
    return df
