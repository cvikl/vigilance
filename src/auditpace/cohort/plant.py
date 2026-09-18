"""Plant structured + narrative truth on synthetic data (spec §6 stage 1; S2 design §3).

One timeline per patient. Criteria are walked in protocol order; each event receives at most one
planted time, so an event shared by several criteria (`admitted` in H2/H3/H4, `icu` in H3/H5)
carries the same time in every case. `events.ts` keeps Synthea provenance; `events.planted_ts`
holds what S1 assigned (NaT where nothing was planted). No-op on real data.

A date-only Synthea end is honoured by drawing the planted end uniformly inside the part of the
Synthea end day that lies on the drawn side of the target (and after the 15-minute floor); when
that window is empty the drawn end is kept even if it falls outside the Synthea date, so the
drawn breach flag always wins. Drawing inside the window rather than clamping to its edge keeps
planted times from piling up at 00:00 / 23:59. Synthea date-only fields (medications, procedures)
are local dates while encounter timestamps are UTC, so a date-only end can land a calendar day
*before* a timed start; the window step is skipped in that case rather than collapsing the case
to the 15-minute floor.
"""
import zlib
from collections import Counter

import numpy as np
import pandas as pd

from auditpace.protocol import Criterion, SyntheticConfig

_OTHER_WEIGHT = 0.10
_DAY_START, _DAY_END = 6.0, 22.0  # hours; typed times-of-day for date-only events
_GUARD_EVENT = "discharged"  # pushed after every planted in-stay event (spec §3 step 3)
_GUARD_GAP = pd.Timedelta(hours=1)
_FLOOR = pd.Timedelta(minutes=15)


def stable_int(key: str) -> int:
    return zlib.crc32(key.encode())


def _draw_reason(rng: np.random.Generator, reasons: list[str]) -> str:
    others = [r for r in reasons if r != "other"]
    if not others:
        return "other"
    w = np.array([_OTHER_WEIGHT] + [(1 - _OTHER_WEIGHT) / len(others)] * len(others))
    return str(rng.choice(["other"] + others, p=w / w.sum()))


def _plant_end(rng, c: Criterion, start: pd.Timestamp, synthea_end: pd.Timestamp, end_has_time: bool, breached: bool):
    if breached:
        hours = c.target_hours * (1.0 + float(rng.lognormal(mean=0.0, sigma=0.6)))
    else:
        hours = c.target_hours * float(rng.uniform(0.1, 0.9))
    end = start + pd.Timedelta(hours=hours)
    if not end_has_time:
        end_day = pd.Timestamp(synthea_end).normalize()
        if end_day >= start.normalize():
            # Admissible window: inside the Synthea end day, after the floor, and on the drawn
            # side of the target. Draw uniformly inside it rather than clamping to its edge so
            # planted times do not pile up at 00:00 / 23:59.
            lo = max(end_day, start + _FLOOR)
            hi = end_day + pd.Timedelta(hours=23, minutes=59)
            target = start + pd.Timedelta(hours=c.target_hours)
            if breached:
                lo = max(lo, target + pd.Timedelta(minutes=1))
            else:
                hi = min(hi, target)
            if lo <= hi and not (lo <= end <= hi):
                end = lo + (hi - lo) * float(rng.uniform())
            # window empty: keep the drawn end (may fall outside the Synthea day; drawn truth wins)
    return max(end, start + _FLOOR).floor("us")


def plant_timeline(
    events: pd.DataFrame,
    cases: pd.DataFrame,
    criteria: list[Criterion],
    synthetic: SyntheticConfig | None,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    events = events.copy()
    if "planted_ts" not in events.columns:
        events["planted_ts"] = pd.NaT
    events["planted_ts"] = pd.to_datetime(events["planted_ts"]).astype("datetime64[us]")
    if not synthetic or not synthetic.augment_times:
        return events, cases
    dup = [e for e, n in Counter(c.to for c in criteria).items() if n > 1]
    if dup:
        raise ValueError(f"plant_timeline: event(s) {dup} are the `to` of more than one criterion")

    out = cases.copy()
    out["true_reason"] = out["true_reason"].astype(object)
    ev_by_pid = {pid: g for pid, g in events.groupby("patient_id", sort=False)}
    planted_all: dict[tuple[str, str], pd.Timestamp] = {}

    for pid, grp in out.groupby("patient_id", sort=False):
        pe = ev_by_pid[pid]
        source_ts = dict(zip(pe.event_type, pe.ts))
        has_time = dict(zip(pe.event_type, pe.has_time))
        planted: dict[str, pd.Timestamp] = {}
        for c in criteria:
            idx = grp.index[grp.criterion_id == c.id]
            if len(idx) == 0:
                continue
            i = idx[0]
            row = out.loc[i]
            if c.from_ == _GUARD_EVENT and _GUARD_EVENT in source_ts and planted:
                guarded = max(pd.Timestamp(source_ts[_GUARD_EVENT]), max(planted.values()) + _GUARD_GAP)
                planted[_GUARD_EVENT] = guarded.floor("us")
            if not row.applies or pd.isna(row.start_ts) or pd.isna(row.end_ts):
                continue
            rng = np.random.default_rng(seed + stable_int(row.case_id))
            breached = bool(rng.random() < synthetic.breach_rates.get(c.id, 0.0))
            if c.from_ in planted:
                start = planted[c.from_]
            else:
                start = pd.Timestamp(source_ts[c.from_])
                if not has_time[c.from_]:
                    start = start.normalize() + pd.Timedelta(hours=float(rng.uniform(_DAY_START, _DAY_END)))
                start = start.floor("us")
                planted[c.from_] = start
            end = _plant_end(rng, c, start, row.end_ts, bool(row.end_has_time), breached)
            planted[c.to] = end
            hours = (end - start) / pd.Timedelta(hours=1)
            breached = bool(hours > c.target_hours)
            out.at[i, "start_ts"] = start
            out.at[i, "end_ts"] = end
            out.at[i, "hours"] = hours
            out.at[i, "breached"] = breached
            out.at[i, "true_reason"] = _draw_reason(rng, c.reasons) if breached else None
        # reconcile every applicable case of this patient with the timeline (e.g. H6 with no
        # follow_up still takes the guarded discharged time as its start)
        for i in grp.index:
            row = out.loc[i]
            if not row.applies:
                continue
            c = next(k for k in criteria if k.id == row.criterion_id)
            if c.from_ in planted:
                out.at[i, "start_ts"] = planted[c.from_]
            if c.to in planted:
                out.at[i, "end_ts"] = planted[c.to]
        for e, t in planted.items():
            planted_all[(pid, e)] = t

    keys = list(zip(events.patient_id, events.event_type))
    events["planted_ts"] = pd.to_datetime([planted_all.get(k, pd.NaT) for k in keys]).astype("datetime64[us]")
    for col in ("start_ts", "end_ts"):
        out[col] = pd.to_datetime(out[col]).astype("datetime64[us]")
    return events, out
