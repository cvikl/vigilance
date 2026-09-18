"""FastAPI app: GET routes read `app.state.snapshot`; POST /reviews writes then reloads it (spec §2, §4)."""
import threading
from pathlib import Path

import markdown
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles

from auditpace.estimate.compute import StaleTable
from auditpace.protocol import Protocol
from auditpace.workbench.demo import Arrivals
from auditpace.workbench.render import make_env
from auditpace.workbench.reviews_writer import form_to_review, write_review
from auditpace.workbench.snapshot import Snapshot

STATIC_DIR = Path(__file__).parent / "static"
REPORT_PATH = Path("docs/report.md")  # S8 output; confirmed at S8
DRAFT_PATH = Path("docs/report.draft.md")  # clinician's edited copy; never overwritten by the report stage
PAGE_SIZE = 50
CATEGORIES = ["breached_system", "breached_legitimate", "breached_undetermined", "not_breached", "abstain",
              "abstain_no_end"]
# one-click views over the same filters; `category` 'nodata' = abstain + abstain_no_end, `sort` 'excess' =
# hours over target, longest first (still the team's checking order, never a statement about care)
CHIPS = [("latest", "Latest", {"category": "", "sort": "latest"}),
         ("check", "Check first", {"category": "", "sort": "priority"}),
         ("stalled", "Stalled", {"category": "breached_system", "sort": "priority"}),
         ("legit", "Legitimate wait", {"category": "breached_legitimate", "sort": "priority"}),
         ("nodata", "No data", {"category": "nodata", "sort": "priority"}),
         ("longest", "Longest over target", {"category": "", "sort": "excess"})]


def reload_snapshot(app: FastAPI) -> None:
    """Replace the snapshot, or keep the old one and record the error for the banner (spec §6)."""
    try:
        app.state.snapshot = Snapshot.load(app.state.processed_dir, app.state.protocol)
        app.state.load_error = None
    except (StaleTable, ValueError, FileNotFoundError) as e:
        app.state.load_error = str(e)


def render(request: Request, template: str, status_code: int = 200, **ctx) -> HTMLResponse:
    app = request.app
    snap: Snapshot = app.state.snapshot
    reviewed, total = snap.progress()
    base = {
        "snapshot": snap, "protocol": snap.protocol, "demo": request.query_params.get("demo") == "1",
        "reviewed": reviewed, "total": total, "load_error": app.state.load_error,
        "reviewer": request.cookies.get("reviewer", "clinician"), "path": request.url.path, "nav_path": request.url.path,
    }
    html = app.state.env.get_template(template).render({**base, **ctx})
    return HTMLResponse(html, status_code=status_code)


def _version(app: FastAPI) -> str:
    """Changes whenever the queue would render differently: a review landed or an arrival was released."""
    return f"{app.state.snapshot.loaded_ts.isoformat()}/{app.state.arrivals.version}"


def create_app(processed_dir: Path, protocol: Protocol, held: list[str] | None = None) -> FastAPI:
    app = FastAPI(title="vigiLANCE workbench", docs_url=None, redoc_url=None)
    app.state.processed_dir = Path(processed_dir)
    app.state.protocol = protocol
    app.state.env = make_env()
    app.state.lock = threading.Lock()
    app.state.load_error = None
    app.state.arrivals = Arrivals(held=list(held or []))
    app.state.recent = {}  # case id → {priority, category} when reviewed in this process (rows stay put)
    app.state.snapshot = Snapshot.load(app.state.processed_dir, protocol)  # startup errors propagate (exit 2 in CLI)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def root(request: Request):
        qs = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(url=f"/queue{qs}", status_code=307)

    def _rows(snap: Snapshot, criterion, category, org, state, q, sort):
        """Rows for the current filters, plus chip counts computed before the category filter."""
        base = snap.queue_rows(criterion=criterion or None, org=org or None, state=state or "pending",
                               q=q or None, sort=sort or "latest", held=app.state.arrivals.hidden(),
                               recent=app.state.recent, pinned=dict(app.state.arrivals.released))
        counts = {"check": len(base), "stalled": int((base.category == "breached_system").sum()),
                  "legit": int((base.category == "breached_legitimate").sum()),
                  "nodata": int(base.category.isin(["abstain", "abstain_no_end"]).sum()), "longest": len(base),
                  "latest": len(base)}
        if category == "nodata":
            rows = base[base.category.isin(["abstain", "abstain_no_end"])]
        elif category:
            rows = base[base.category == category]
        else:
            rows = base
        return rows, counts

    @app.get("/queue", response_class=HTMLResponse)
    def queue(request: Request, criterion: str | None = None, category: str | None = None, org: str | None = None,
              state: str = "pending", q: str | None = None, sort: str = "latest", offset: int = 0,
              part: str | None = None):
        snap: Snapshot = app.state.snapshot
        rows, counts = _rows(snap, criterion, category, org, state, q, sort)
        n_all = len(rows)
        no_end = rows[rows.category == "abstain_no_end"]
        offset = max(0, offset)
        page = rows.iloc[offset:offset + PAGE_SIZE].to_dict("records")
        filters = {"criterion": criterion or "", "category": category or "", "org": org or "",
                   "state": state or "pending", "q": q or "", "sort": sort or "latest"}
        chip = next((k for k, _, f in CHIPS if f["category"] == filters["category"] and f["sort"] == filters["sort"]),
                    None)
        ctx = {"rows": page, "n_all": n_all, "offset": offset, "next_offset": offset + PAGE_SIZE,
               "has_more": offset + PAGE_SIZE < n_all, "n_no_end": len(no_end), "filters": filters,
               "chips": CHIPS, "chip": chip, "counts": counts, "page_size": PAGE_SIZE,
               "orgs": sorted(snap.frames["patients"].organization_id.dropna().unique().tolist()),
               "categories": CATEGORIES, "version": _version(app), "hx": bool(request.headers.get("HX-Request"))}
        if part == "rows":
            template = "partials/queue_rows.html"
        elif request.headers.get("HX-Request"):
            template = "partials/queue_table.html"
        else:
            template = "queue.html"
        return render(request, template, **ctx)

    @app.get("/queue/version")
    def queue_version():
        return {"version": _version(app)}

    @app.post("/demo/release")
    def demo_release():
        """Reveal the next held-back case (the pitch's 'a handoff just landed'); 404 when none is left."""
        case_id = app.state.arrivals.release()
        if case_id is None:
            return JSONResponse({"released": None, "pending": 0}, status_code=404)
        return {"released": case_id, "pending": len(app.state.arrivals.pending())}

    @app.post("/demo/reset")
    def demo_reset():
        app.state.arrivals.reset()
        app.state.recent.clear()
        return {"pending": len(app.state.arrivals.pending())}

    @app.get("/demo/status")
    def demo_status():
        a: Arrivals = app.state.arrivals
        return {"held": a.held, "pending": a.pending(), "released": list(a.released), "version": _version(app)}

    def _case_or_404(case_id: str):
        try:
            return app.state.snapshot.case(case_id)
        except KeyError:
            raise HTTPException(404, f"unknown case {case_id}") from None

    @app.get("/case/{case_id}", response_class=HTMLResponse)
    def case(request: Request, case_id: str):
        c = _case_or_404(case_id)
        first = next((e for e in c.evidence if e.verified and e.page_id), None) or (c.evidence[0] if c.evidence else None)
        return render(request, "case.html", c=c, ev=first, page=_page_ctx(first), error=None)

    def _page_ctx(ev):
        if ev is None or not ev.page_id:
            return None
        pages = app.state.snapshot.frames["pages"]
        hit = pages[pages.page_id == ev.page_id]
        if hit.empty:
            return None
        return {"page_id": ev.page_id, "width": int(hit.width.iloc[0]), "height": int(hit.height.iloc[0])}

    @app.get("/case/{case_id}/page/{page_id}", response_class=HTMLResponse)
    def case_page(request: Request, case_id: str, page_id: str, evidence: int = 0):
        c = _case_or_404(case_id)
        ev = next((e for e in c.evidence if e.idx == evidence), None)
        if ev is None or ev.page_id != page_id:
            raise HTTPException(404, "evidence/page mismatch")
        return render(request, "partials/page_view.html", c=c, ev=ev, page=_page_ctx(ev))

    @app.get("/case/{case_id}/doc/{page_id}", response_class=HTMLResponse)
    def case_doc(request: Request, case_id: str, page_id: str):
        """Any page of any of the patient's documents; evidence on that page is highlighted when there is some."""
        c = _case_or_404(case_id)
        if not any(pg["page_id"] == page_id for d in c.documents for pg in d["pages"]):
            raise HTTPException(404, "page is not one of this patient's documents")
        ev = next((e for e in c.evidence if e.page_id == page_id and e.verified), None)
        pages = app.state.snapshot.frames["pages"]
        hit = pages[pages.page_id == page_id]
        page = None if hit.empty else {"page_id": page_id, "width": int(hit.width.iloc[0]), "height": int(hit.height.iloc[0])}
        return render(request, "partials/page_view.html", c=c, ev=ev, page=page)

    @app.post("/reviews", response_class=HTMLResponse)
    def post_review(request: Request, case_id: str = Form(...), action: str = Form(...),
                    human_status: str = Form(""), human_reason: str = Form(""), note: str = Form(""),
                    note_flag: str = Form(""), confirm_reason: str | None = Form(None)):
        c = _case_or_404(case_id)
        reviewer = request.cookies.get("reviewer", "clinician")
        note = note or note_flag  # the Flag fieldset has its own input so a hidden Override note never leaks in
        if action == "confirm" and c.status == "breached" and confirm_reason is not None \
                and (confirm_reason or None) != c.reason_tag:
            # the clinician agrees it is a breach but relabels why — a stalled/legitimate call is a
            # reviewer's call, so it is recorded as an override of the reason at the same status
            action, human_status, human_reason = "override", c.status, confirm_reason
        try:
            state, status, reason = form_to_review(action, c.status, c.reason_tag, human_status or None,
                                                   human_reason or None)
            with app.state.lock:
                write_review(app.state.processed_dir, app.state.protocol, case_id=case_id, reviewer=reviewer,
                             validation_state=state, human_status=status, human_reason=reason, note=note or None)
                if c.priority is not None:
                    app.state.recent[case_id] = {"priority": float(c.priority), "category": c.category}
                reload_snapshot(app)
        except ValueError as e:
            # base.html forces htmx to swap a 422, so this partial (message + form, offending fieldset
            # re-opened) is what the reviewer sees; the banner partial rides along unchanged
            return render(request, "partials/review_panel.html", status_code=422, c=c, error=str(e), saved=False,
                          next_case=None, reopen={"override": "ov", "flag": "fl"}.get(action))
        snap: Snapshot = app.state.snapshot
        c = snap.case(case_id) if app.state.load_error is None else c
        pending = snap.queue_rows(held=app.state.arrivals.hidden())
        next_case = str(pending.case_id.iloc[0]) if len(pending) and app.state.load_error is None else None
        return render(request, "partials/review_panel.html", c=c, error=None, saved=True, next_case=next_case)

    @app.get("/results", response_class=HTMLResponse)
    def results(request: Request):
        return render(request, "results.html", r=app.state.snapshot.results())

    def _report_source() -> tuple[Path | None, bool]:
        """(path to show, is_draft): the clinician's draft when one exists, else the generated report."""
        if DRAFT_PATH.exists():
            return DRAFT_PATH, True
        return (REPORT_PATH, False) if REPORT_PATH.exists() else (None, False)

    @app.get("/report", response_class=HTMLResponse)
    def report(request: Request, edit: int = 0):
        src, is_draft = _report_source()
        if src is None:
            return render(request, "report.html", body=None, path=str(REPORT_PATH), text="", is_draft=False, edit=False)
        from markupsafe import Markup

        text = src.read_text(encoding="utf-8")
        body = Markup(markdown.markdown(text, extensions=["tables"]))
        return render(request, "report.html", body=body, path=str(REPORT_PATH), text=text, is_draft=is_draft,
                      edit=bool(edit))

    @app.post("/report/draft")
    def report_draft_save(request: Request, text: str = Form("")):
        DRAFT_PATH.parent.mkdir(parents=True, exist_ok=True)
        DRAFT_PATH.write_text(text.replace("\r\n", "\n"), encoding="utf-8")
        return RedirectResponse(url="/report" + ("?demo=1" if request.query_params.get("demo") == "1" else ""),
                                status_code=303)

    @app.post("/report/draft/reset")
    def report_draft_reset(request: Request):
        if DRAFT_PATH.exists():
            DRAFT_PATH.unlink()
        return RedirectResponse(url="/report" + ("?demo=1" if request.query_params.get("demo") == "1" else ""),
                                status_code=303)

    @app.get("/report/download")
    def report_download():
        src, is_draft = _report_source()
        if src is None:
            raise HTTPException(404, "no report yet")
        name = "audit-report-draft.md" if is_draft else "audit-report.md"
        return FileResponse(str(src), media_type="text/markdown", filename=name)

    @app.get("/home", response_class=HTMLResponse)
    def landing():
        """Standalone landing page; the workbench keeps the root (/ redirects to the queue)."""
        return HTMLResponse((STATIC_DIR / "landing.html").read_text(encoding="utf-8"))

    @app.exception_handler(HTTPException)
    def http_error(request: Request, exc: HTTPException):
        if request.url.path.startswith(("/page/", "/static/")) or request.headers.get("HX-Request"):
            # plain text: `detail` echoes the raw id from the URL, so it must never be parsed as HTML
            return PlainTextResponse(str(exc.detail), status_code=exc.status_code)
        return render(request, "error.html", status_code=exc.status_code, code=exc.status_code, detail=exc.detail)

    @app.get("/page/{page_id}.jpg", include_in_schema=False)
    def page(page_id: str):
        try:
            path = app.state.snapshot.page(page_id)
        except KeyError:
            raise HTTPException(404, f"unknown page {page_id}") from None
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})

    @app.get("/healthz")
    def healthz():
        snap: Snapshot = app.state.snapshot
        return {"ok": True, "loaded_ts": snap.loaded_ts.isoformat(), "protocol_hash": snap.protocol.hash,
                "reviews": len(snap.frames["reviews"]), "load_error": app.state.load_error,
                "held": len(app.state.arrivals.pending()), "version": _version(app)}

    return app
