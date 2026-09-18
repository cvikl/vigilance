"""Jinja environment and the display rules the templates share (spec §2, §4)."""
import math

from jinja2 import Environment, PackageLoader, select_autoescape

PROVISIONAL_MIN_REVIEWS = 20
NO_DISCREPANCY_TEXT = ("no review has yet disagreed with a verdict — the corrected interval is the naive one "
                       "relabelled")


def _isnan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def provisional_reason(n_reviewed: int, flag: str | None) -> str | None:
    """Why the corrected interval is provisional, or None when it is not (spec §2; S8 caveats the same two
    conditions by name)."""
    flag = None if _isnan(flag) else flag
    if flag == "n_reviewed_insufficient":
        return "fewer than 2 reviews"
    if flag == "no_discrepancy_observed":
        return NO_DISCREPANCY_TEXT
    if int(n_reviewed) < PROVISIONAL_MIN_REVIEWS:
        return f"fewer than {PROVISIONAL_MIN_REVIEWS} reviews"
    return None


def category_label(category: str, criterion_id: str) -> str:
    if category == "abstain_no_end":
        return "no follow-up documented" if criterion_id == "H6" else "no end event documented"
    return {
        "abstain": "abstained (end event exists)",
        "breached_system": "breached — stalled",
        "breached_legitimate": "breached — legitimate wait",
        "breached_undetermined": "breached — reason undetermined",
        "not_breached": "not breached",
    }.get(category, str(category))


def pct(x) -> str:
    return "—" if _isnan(x) else f"{100 * float(x):.1f} %"


def ci(lo, hi) -> str:
    return "—" if _isnan(lo) or _isnan(hi) else f"{100 * float(lo):.1f}–{100 * float(hi):.1f} %"


def hours(x) -> str:
    return "—" if _isnan(x) else f"{float(x):.1f} h"


ALERT_TEXT = {"criterion_below_target": "{c} below target, service-wide",
              "org_outlier": "organisation is an outlier on {c}",
              "week_outlier": "week is an outlier on {c}"}


def why_flags(reason: str | None) -> list[dict]:
    """The queue's priority_reason (S6 flags joined by "; ") as plain-language flags, strongest first.
    The raw string stays in the row's tooltip; this is only how it reads at a glance."""
    out = []
    for part in [p.strip() for p in (reason or "").split(";") if p.strip()]:
        if part == "model call ≠ computed status":
            out.append({"text": "model and computed status disagree", "kind": "warn"})
        elif part == "evidence not verified on page":
            out.append({"text": "quote not on page", "kind": "warn"})
        elif part == "abstained though end event exists":
            out.append({"text": "abstained despite end event", "kind": "abs"})
        elif part.startswith("in alerted cell: "):
            kind, crit = (part[len("in alerted cell: "):].split(":", 2) + ["", ""])[:2]
            tpl = ALERT_TEXT.get(kind)
            out.append({"text": tpl.format(c=crit) if tpl else f"in an alerted group ({kind})", "kind": "alert"})
        elif part.endswith("h over target"):
            out.append({"text": part, "kind": "over"})
        elif part.startswith("few reviews yet for "):
            out.append({"text": "few reviews yet on " + part[len("few reviews yet for "):], "kind": "ci"})
        else:
            out.append({"text": part, "kind": "note"})
    return out


REASON_WORDS = {"dna": "did not attend", "lost_to_follow_up": "lost to follow-up", "icu_full": "ICU full",
                "news2_not_recorded": "NEWS2 not recorded"}


def reason_label(tag) -> str:
    """Protocol reason code as words: not_booked -> not booked."""
    if tag is None or (isinstance(tag, float) and math.isnan(tag)) or tag == "":
        return ""
    return REASON_WORDS.get(str(tag), str(tag).replace("_", " "))


def hours_short(x) -> str:
    """Hours for the queue: whole numbers past 100 h, one decimal below."""
    if _isnan(x):
        return "—"
    x = float(x)
    return f"{x:.0f} h" if abs(x) >= 100 else f"{x:.1f} h"


def provisional_short(text) -> str:
    """The provisional reason in a few words; the full sentence stays in the tooltip."""
    if not text or (isinstance(text, float) and math.isnan(text)):
        return ""
    if "no review has yet disagreed" in str(text):
        return "no disagreeing review yet"
    return str(text)


def class_label(cls) -> str:
    return {"system": "system cause", "legitimate": "legitimate wait"}.get(str(cls), "undetermined")


def demo_href(path: str, demo: bool) -> str:
    if not demo:
        return path
    return f"{path}&demo=1" if "?" in path else f"{path}?demo=1"


def make_env() -> Environment:
    env = Environment(loader=PackageLoader("auditpace.workbench", "templates"),
                      autoescape=select_autoescape(default=True, default_for_string=True))
    env.filters.update({"pct": pct, "ci": ci, "hours": hours, "demo_href": demo_href,
                        "category_label": category_label, "provisional_reason": provisional_reason,
                        "why_flags": why_flags, "reason_label": reason_label, "hours_short": hours_short,
                        "provisional_short": provisional_short, "class_label": class_label})
    from markupsafe import Markup

    from auditpace.workbench.charts import funnel_svg, runchart_svg
    env.globals.update({"funnel_svg": lambda f: Markup(funnel_svg(f)), "runchart_svg": lambda f: Markup(runchart_svg(f))})
    return env
