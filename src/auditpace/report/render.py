"""Render report.md from the payload: every figure through fmt, prose dropped in where marked (spec §9)."""
import hashlib

from jinja2 import Environment, PackageLoader

from auditpace.report import fmt
from auditpace.report.compare import Comparison
from auditpace.report.gateway import Payload
from auditpace.report.prose import Prose, ProseRejection
from auditpace.workbench.render import category_label

HEADINGS = ["Summary", "Findings", "Signals and recommended actions", "Health inequalities",
            "Change since previous run", "Methods", "Caveats",
            "Validation on the synthetic cohort (not available on live data)", "Appendix"]


def _signed(x) -> str:
    if x is None:
        return "—"
    s = f"{abs(x):.1f}"
    return f"−{s}" if x < 0 else f"+{s}"


def _k2(x) -> str:
    return "—" if x is None else f"{x:.2f}"


def _env() -> Environment:
    env = Environment(loader=PackageLoader("auditpace.report", "templates"), autoescape=False,
                      trim_blocks=False, lstrip_blocks=False, keep_trailing_newline=True)
    env.filters.update(pct=fmt.pct, ci=fmt.ci, hours=fmt.hours, num=fmt.num, signed=_signed, k2=_k2,
                       no_end_label=lambda cid: category_label("abstain_no_end", cid))
    return env


def _coverage_pairs(payload: Payload) -> list[dict]:
    rows: dict[tuple[str, float], dict] = {}
    if payload.validation:
        for r in payload.validation.coverage:
            rows.setdefault((r.criterion_id, r.fraction), {"criterion_id": r.criterion_id, "fraction": r.fraction,
                                                            "naive": None, "corrected": None})[r.method] = r.coverage
    return [rows[k] for k in sorted(rows)]


def render_report(payload: Payload, prose: Prose, comparison: Comparison | None, note: str,
                  rejections: list[ProseRejection], model_note: str | None, question: str = "") -> str:
    blob = payload.model_dump_json()
    pairs = _coverage_pairs(payload)
    h5_bias = any(r["criterion_id"] == "H5" and r["fraction"] < 1.0 and (r["naive"] or 0.0) < 0.9 for r in pairs)
    return _env().get_template("report.md.j2").render(
        p=payload, prose=prose, comparison=comparison, note=note, rejections=rejections, model_note=model_note,
        question=question, n_provisional=sum(1 for c in payload.criteria if c.provisional_reason),
        coverage_pairs=pairs, h5_bias=h5_bias, payload_sha=hashlib.sha256(blob.encode()).hexdigest(),
        payload_bytes=len(blob.encode()), n_paragraphs=3 * len(prose.criteria) + 3)
