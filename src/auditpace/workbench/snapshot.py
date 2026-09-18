"""Immutable frames for one page render: S6's tables via `compute_all` on a read-only store, plus the
raw tables the case view needs. Replaced wholesale after every review write (spec §2)."""
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from auditpace.estimate.categorise import reason_class_of
from auditpace.estimate.compute import compute_all
from auditpace.estimate.reviews import empty_reviews, latest_reviews
from auditpace.protocol import Criterion, Protocol
from auditpace.store import Store

# `cases` is never read here: its `start_ts` / `end_ts` / `hours` are structured (planted) timing and
# `breached` / `true_reason` are truth — the UI shows only what the verdict was decided on
# (`verdicts.from_ts` / `to_ts` / `hours_documented`); design invariant: truth never reaches the UI.
PATIENT_COLS = ["patient_id", "age_band", "sex", "organization_id"]
DOC_COLS = ["doc_id", "patient_id", "doc_type", "authored_ts", "style"]
PAGE_COLS = ["page_id", "doc_id", "page_no", "image_path", "width", "height"]


def _read(store: Store, name: str, cols: list[str] | None) -> pd.DataFrame:
    """Column-projected read through DuckDB's view (never `store.read`, which would load every
    column including truth ones like `cases.breached`); empty frame with those columns if the
    table is absent."""
    if not store.exists(name):
        return pd.DataFrame(columns=cols or [])
    sel = ", ".join(cols) if cols else "*"
    return store.sql(f"select {sel} from {name}")


@dataclass
class Evidence:
    idx: int
    kind: str
    doc_id: str
    page_id: str | None
    quote: str
    verified: bool
    bboxes: list[dict]
    doc_type: str | None
    page_no: int | None


@dataclass
class CaseView:
    case_id: str
    patient_id: str
    criterion: Criterion
    status: str
    model_status: str | None
    reason_tag: str | None
    reason_class: str | None
    confidence: float | None
    rationale: str | None
    start_ts: pd.Timestamp | None   # verdicts.from_ts — the quoted time the status was decided on
    end_ts: pd.Timestamp | None     # verdicts.to_ts
    hours: float | None             # verdicts.hours_documented
    target_hours: float
    computed_status_differs: bool
    evidence: list[Evidence]
    reviews: list[dict]
    category: str | None
    priority: float | None
    priority_reason: str | None
    age_band: str | None
    sex: str | None
    organization_id: str | None
    documents: list[dict]           # every document for the patient, each with its pages, oldest first
    owner: str = "unassigned"      # protocol.actions[criterion].owner — who picks this up
    action: str = ""               # next action for this verdict (protocol `actions:` block, never the model)


def next_action(protocol: Protocol, criterion_id: str, status: str, reason: str | None) -> str:
    """The owner's next action for one verdict. Breached → the protocol's action for the reason
    (`other` when untagged); abstain → find the record, never impute; within target → nothing."""
    if status == "breached":
        return protocol.action(criterion_id, reason)
    if status == "abstain":
        return "Locate the missing record — nothing is imputed"
    return "None — within target"


def _none(x):
    """pandas null → None, so templates and dataclasses see one kind of missing."""
    return None if x is None or (isinstance(x, float) and pd.isna(x)) or x is pd.NaT or x is pd.NA else x


def _evidence_summary(evidence_json: str) -> tuple[str, bool]:
    ev = json.loads(evidence_json) if evidence_json else []
    first = next((e.get("quote", "") for e in ev), "")
    return first, any(not e.get("verified", False) for e in ev)


@dataclass(frozen=True)
class Snapshot:
    protocol: Protocol
    processed_dir: Path
    frames: dict[str, pd.DataFrame]
    loaded_ts: pd.Timestamp

    @classmethod
    def load(cls, processed_dir: Path, protocol: Protocol, now: pd.Timestamp | None = None) -> "Snapshot":
        now = now if now is not None else pd.Timestamp.now("UTC").tz_localize(None)
        processed_dir = Path(processed_dir)
        with Store(processed_dir, read_only=True) as store:
            frames = compute_all(store, protocol, now)  # raises StaleTable / ValueError / FileNotFoundError
            frames["verdicts"] = _read(store, "verdicts", None)
            frames["patients"] = _read(store, "patients", PATIENT_COLS)
            frames["documents"] = _read(store, "documents", DOC_COLS)
            frames["pages"] = _read(store, "pages", PAGE_COLS)
            frames["reviews"] = _read(store, "reviews", None) if store.exists("reviews") else empty_reviews()
        return cls(protocol=protocol, processed_dir=processed_dir, frames=frames, loaded_ts=now)

    def criterion(self, criterion_id: str) -> Criterion:
        for c in self.protocol.criteria:
            if c.id == criterion_id:
                return c
        raise KeyError(criterion_id)

    def progress(self) -> tuple[int, int]:
        """(cases with a non-flagged latest review, applicable cases)."""
        total = len(self.frames["verdicts"])
        lr = latest_reviews(self.frames["reviews"])
        reviewed = int((lr.validation_state != "flagged").sum()) if len(lr) else 0
        return reviewed, total

    def page(self, page_id: str) -> Path:
        pages = self.frames["pages"]
        hit = pages[pages.page_id == page_id]
        if hit.empty:
            raise KeyError(page_id)
        return self.processed_dir / str(hit.image_path.iloc[0])

    def _case_table(self) -> pd.DataFrame:
        """Every applicable case with verdict, case, patient, queue and latest-review fields joined."""
        v = self.frames["verdicts"][["case_id", "patient_id", "criterion_id", "status", "model_status",
                                     "reason_tag", "hours_documented", "evidence", "from_ts", "to_ts"]].copy()
        # "latest" = the newest clinical activity the verdict quotes (end event, else start) — record
        # time, never adjudication time (batches share one timestamp) and never anything invented
        v["record_ts"] = pd.to_datetime(v.to_ts).fillna(pd.to_datetime(v.from_ts))
        v = v.drop(columns=["from_ts", "to_ts"])
        summ = [_evidence_summary(e) for e in v.evidence]
        v["first_quote"] = [s[0] for s in summ]
        v["any_unverified"] = [s[1] for s in summ]
        v = v.drop(columns="evidence").rename(columns={"hours_documented": "hours"})
        v = v.merge(self.frames["patients"], on="patient_id", how="left")
        q = self.frames["queue"][["case_id", "priority", "priority_reason", "category", "excess_hours"]]
        v = v.merge(q, on="case_id", how="left")
        lr = latest_reviews(self.frames["reviews"])
        if len(lr):
            v = v.merge(lr[["case_id", "validation_state"]].rename(columns={"validation_state": "review_state"}),
                        on="case_id", how="left")
        else:
            v["review_state"] = None
        v["review_state"] = v.review_state.astype(object).where(v.review_state.notna(), None)
        v["target_hours"] = v.criterion_id.map({c.id: c.target_hours for c in self.protocol.criteria})
        return v

    def queue_rows(self, criterion: str | None = None, category: str | None = None, org: str | None = None,
                   state: str = "pending", q: str | None = None, sort: str = "priority",
                   held: set[str] | None = None, recent: dict[str, dict] | None = None,
                   pinned: dict[str, float] | None = None) -> pd.DataFrame:
        """`held`: case ids hidden from every view until released (demo arrivals). `recent`: case id →
        {'priority', 'category'} as they were when the case was reviewed in this server session; those
        rows stay in the pending view at that priority and under that category, marked by
        `review_state`, so the queue does not reflow under the reviewer's eye. `pinned`: case id →
        arrival time for cases that landed during this session — they head the Latest view, newest
        first, reviewed ones ticked in place, so nothing lands unseen. `sort`: 'latest' (default: newest documented event
        first), 'priority' (the checking order) or 'excess' (hours over target, longest first)."""
        t = self._case_table()
        recent = recent or {}
        rp = {k: v["priority"] for k, v in recent.items()}
        rc = {k: v["category"] for k, v in recent.items()}
        if held:
            t = t[~t.case_id.isin(held)]
        pending = t.priority.notna()
        if state == "pending":
            t = t[pending | t.case_id.isin(recent)]
        elif state == "all":
            pass
        else:
            t = t[t.review_state == state]
        t = t.copy()
        t["category"] = t.category.astype(object).where(t.category.notna(), t.case_id.map(rc)).fillna("reviewed")
        if criterion:
            t = t[t.criterion_id == criterion]
        if category == "nodata":
            t = t[t.category.isin(["abstain", "abstain_no_end"])]
        elif category:
            t = t[t.category == category]
        if org:
            t = t[t.organization_id == org]
        if q:
            t = t[t.case_id.str.contains(q, regex=False)]
        t["_p"] = t.priority.fillna(t.case_id.map(rp)).fillna(-1)
        # no-end rows sort after every other row at equal priority: once reviews accumulate, unflagged
        # pending rows also sit at priority 0 and would otherwise interleave with "nothing to review"
        t["_z"] = t.category == "abstain_no_end"
        if sort == "excess":
            t["_p"] = t.excess_hours.fillna(-1)
        elif sort == "latest":
            t["_p"] = t.record_ts.fillna(pd.Timestamp.min).astype("int64")
        # arrivals head the Latest view (newest first, reviewed ones stay put and ticked); the other
        # views keep their own meaning — Check first is the checking order, nothing else
        t["_n"] = t.case_id.map(pinned or {}).fillna(0.0) if sort == "latest" else 0.0
        t = t.sort_values(["_n", "_p", "_z", "case_id"], ascending=[False, False, True, True], kind="stable")
        t["is_new"] = (t["_n"] > 0) & t.review_state.isna()
        t = t.drop(columns=["_p", "_z", "_n"])
        cols = ["case_id", "patient_id", "criterion_id", "priority", "priority_reason", "category", "review_state",
                "status", "model_status", "reason_tag", "hours", "target_hours", "excess_hours", "first_quote",
                "any_unverified", "age_band", "sex", "organization_id", "record_ts", "is_new"]
        out = t[cols].reset_index(drop=True)
        return out.astype(object).where(out.notna(), None)

    def case(self, case_id: str) -> CaseView:
        v = self.frames["verdicts"]
        hit = v[v.case_id == case_id]
        if hit.empty:
            raise KeyError(case_id)
        r = hit.iloc[0]
        crit = self.criterion(r.criterion_id)
        pats = self.frames["patients"].set_index("patient_id")
        p = pats.loc[r.patient_id] if r.patient_id in pats.index else None
        pages = self.frames["pages"].set_index("page_id") if len(self.frames["pages"]) else None
        evidence = []
        for i, e in enumerate(json.loads(r.evidence) if r.evidence else []):
            pid = e.get("page_id")
            pg = pages.loc[pid] if (pages is not None and pid in pages.index) else None
            docs = self.frames["documents"]
            dt = docs[docs.doc_id == e.get("doc_id")].doc_type
            evidence.append(Evidence(
                idx=i, kind=e.get("kind", ""), doc_id=e.get("doc_id", ""), page_id=pid,
                quote=e.get("quote", ""), verified=bool(e.get("verified", False)),
                bboxes=list(e.get("bboxes") or []), doc_type=(dt.iloc[0] if len(dt) else None),
                page_no=(int(pg.page_no) if pg is not None else None)))
        docs = self.frames["documents"]
        documents = []
        # ids compared as text: the store may hand back UUID objects on one side and strings on the other
        mine = docs[docs.patient_id.astype(str) == str(r.patient_id)] if len(docs) else docs
        for d in mine.sort_values("authored_ts", kind="stable").itertuples():
            pgs = self.frames["pages"]
            pgs = pgs[pgs.doc_id.astype(str) == str(d.doc_id)].sort_values("page_no") if len(pgs) else pgs
            documents.append({
                "doc_id": d.doc_id, "doc_type": d.doc_type, "authored_ts": _none(d.authored_ts),
                "pages": [{"page_id": pg.page_id, "page_no": int(pg.page_no),
                           "has_evidence": any(str(ev.page_id) == str(pg.page_id) for ev in evidence)} for pg in pgs.itertuples()],
            })
        rv = self.frames["reviews"]
        hist = rv[rv.case_id == case_id].sort_values("reviewed_ts", ascending=False, kind="stable") if len(rv) else rv
        reviews = [{k: _none(val) for k, val in row.items()} for row in hist.to_dict("records")]
        qf = self.frames["queue"]
        qrow = qf[qf.case_id == case_id]
        qrow = qrow.iloc[0] if len(qrow) else None
        status = str(r.status)
        reason = _none(r.reason_tag)
        return CaseView(
            case_id=case_id, patient_id=str(r.patient_id), criterion=crit, status=status,
            model_status=_none(r.model_status), reason_tag=reason,
            reason_class=reason_class_of(self.protocol, crit.id, status, reason),
            confidence=_none(r.confidence), rationale=_none(r.rationale),
            start_ts=_none(r.from_ts), end_ts=_none(r.to_ts), hours=_none(r.hours_documented),
            target_hours=crit.target_hours,
            computed_status_differs=(_none(r.model_status) is not None and str(r.model_status) != status),
            evidence=evidence, reviews=reviews,
            category=(str(qrow.category) if qrow is not None else None),
            priority=(float(qrow.priority) if qrow is not None else None),
            priority_reason=(str(qrow.priority_reason) if qrow is not None else None),
            age_band=_none(p.age_band) if p is not None else None,
            sex=_none(p.sex) if p is not None else None,
            organization_id=_none(p.organization_id) if p is not None else None,
            documents=documents,
            owner=self.protocol.owner(crit.id), action=next_action(self.protocol, crit.id, status, reason),
        )

    def results(self) -> dict:
        from auditpace.workbench.render import provisional_reason
        est, fun, rc = self.frames["estimates"], self.frames["funnel"], self.frames["runchart"]
        criteria = []
        for crit in self.protocol.criteria:
            rows = est[(est.criterion_id == crit.id) & (est.segment_key == "all")]
            row = {k: _none(v) for k, v in rows.iloc[0].items()} if len(rows) else None
            segs = est[(est.criterion_id == crit.id) & (est.segment_key != "all")]
            criteria.append({
                "criterion": crit, "row": row,
                "provisional": provisional_reason(row["n_reviewed"], row["flag"]) if row else None,
                "reason_breakdown": json.loads(row["reason_breakdown"]) if row and row["reason_breakdown"] else {},
                "segments": [{k: _none(v) for k, v in s.items()} for s in segs.to_dict("records")],
                "funnel": fun[fun.criterion_id == crit.id], "runchart": rc[rc.criterion_id == crit.id],
            })
        alerts = [{k: _none(v) for k, v in a.items()} for a in self.frames["alerts"].to_dict("records")]
        tl = self.frames["timelost"]
        ranked = tl[tl["rank"].notna()].sort_values("rank")
        by_org = tl[tl["rank"].isna()].sort_values("hours_lost", ascending=False)
        return {"alerts": alerts,
                "timelost": [{k: _none(v) for k, v in t.items()} for t in ranked.to_dict("records")],
                "timelost_orgs": [{k: _none(v) for k, v in t.items()} for t in by_org.to_dict("records")],
                "criteria": criteria}
