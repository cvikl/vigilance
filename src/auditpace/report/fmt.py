"""How the report prints a figure — one place, shared by the template and the prose back-check so
"the number in the payload" and "the number on the page" are the same string."""
import math

from auditpace.report.gateway import Payload


def _nan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def pct(x) -> str:
    return "—" if _nan(x) else f"{100 * float(x):.1f}"


def ci(lo, hi) -> str:
    return "—" if _nan(lo) or _nan(hi) else f"{pct(lo)}–{pct(hi)}"


def hours(x) -> str:
    return "—" if _nan(x) else f"{float(x):.1f}"


def num(x) -> str:
    return "—" if _nan(x) else str(int(x))


def _rate_tokens(r) -> set[str]:
    return {pct(r.rate), pct(r.lo), pct(r.hi)}


def printed_tokens_by_kind(payload: Payload) -> dict[str, set[str]]:
    """`printed_tokens` split by what a token means, so the back-check can insist a %-suffixed
    figure came from a rate and an h-suffixed one from an hours field, not just from "some number
    in the payload" (a fabricated rate that happens to equal a real count would otherwise pass):
    "rate" — every pct() output and CI bound; "hours" — every hours() output; "count" — every other
    integer/decimal (n's, ranks, weeks-count, cohort_n, quarantine counts, suppress_below, the pool
    fraction and confidence, the provisional floors "2"/"20", coverage fractions and kappa strings);
    "id" — criterion ids, Org-nn, reason codes, runchart weeks, and period dates/years. The union of
    all four is exactly what `printed_tokens` used to return."""
    rate: set[str] = set()
    hrs: set[str] = set()
    count: set[str] = set()
    ident: set[str] = set()

    r = payload.run
    count |= {str(r.cohort_n), str(r.suppress_below), str(r.review.estimation_pool_fraction),
              str(r.review.confidence), "2", "20"}  # provisional floors
    rate |= {pct(r.review.confidence), str(round(100 * r.review.confidence))}  # "95.0" and "95" (the % CI level)
    if r.period is not None:
        ident |= {r.period.start, r.period.end, r.period.start[:4], r.period.end[:4]}
    for c in payload.completeness:
        count |= {str(c.n_with), str(c.n_without)}
    for c in payload.criteria:
        ident.add(c.id)
        count |= {str(c.n), str(c.n_reviewed), str(c.n_abstain), str(c.n_no_end), str(c.n_breached_system),
                  str(c.n_breached_legitimate), str(c.n_breached_undetermined), num(c.target_hours)}
        hrs.add(hours(c.target_hours))
        for r_ in (c.naive, c.corrected, c.rate_system, c.rate_legitimate, c.rate_undetermined):
            rate |= _rate_tokens(r_)
        if c.compliance_target is not None:
            rate.add(pct(c.compliance_target))
        for reason in c.reasons:
            ident.add(reason.code)
            count.add(str(reason.n))
            rate |= {pct(reason.rate), pct(reason.lo), pct(reason.hi)}
        for s in c.segments:
            ident.add(s.value)
            count.add(str(s.n))
            rate |= _rate_tokens(s.corrected)
        for f in c.funnel:
            ident.add(f.org)
            count.add(str(f.n))
            rate |= {pct(f.rate), pct(f.lo), pct(f.hi)}
        count.add(str(c.runchart.n_weeks))
        ident |= {w.week for w in c.runchart.signals}
        if c.runchart.latest:
            lw = c.runchart.latest
            ident.add(lw.week)
            rate |= {pct(lw.rate), pct(lw.lo), pct(lw.hi)}
        hrs |= {hours(c.timelost.hours_lost), hours(c.timelost.median_excess_h)}
        count.add(num(c.timelost.rank))
    for a in payload.alerts:
        ident |= {a.criterion_id, a.segment_value}
        rate |= {pct(a.rate), pct(a.lo), pct(a.hi)}
        count |= {str(a.n), str(a.n_reviewed)}
        hrs.add(hours(a.hours_lost))
        if a.dominant_reason:
            ident.add(a.dominant_reason)
    q = payload.quality
    count |= {str(q.n_cases), str(q.n_abstain), str(q.n_no_end), str(q.n_cites), str(q.n_unverified_cites),
              str(q.n_suppressed_cells), str(q.reviews.n_latest), str(q.reviews.n_validated),
              str(q.reviews.n_disputed), str(q.reviews.n_flagged),
              str(q.reviews.n_estimation_pool)} | {str(v) for v in q.quarantined.values()}
    rate |= {pct(q.abstain_rate), pct(q.no_end_rate), pct(q.unverified_cite_rate)}
    if payload.validation:
        for row in payload.validation.coverage:
            ident.add(row.criterion_id)
            count |= {str(row.fraction), f"{row.coverage:.2f}"}
            rate |= {pct(row.coverage), pct(row.mean_width)}
        for row in payload.validation.kappa:
            ident.add(row.criterion_id)
            count.add(str(row.n))
            if row.kappa is not None:
                count.add(f"{row.kappa:.2f}")
        for row in payload.validation.reason_accuracy:
            ident.add(row.criterion_id)
            count.add(str(row.n))
            if row.acc is not None:
                rate.add(pct(row.acc))
    for s in (rate, hrs, count, ident):
        s.discard("—")
    return {"rate": rate, "hours": hrs, "count": count, "id": ident}


def printed_tokens(payload: Payload) -> set[str]:
    """Every string the template may print for a figure or identifier. Model prose may use these and
    nothing else that looks like a number, criterion, organisation or reason code."""
    return set().union(*printed_tokens_by_kind(payload).values())
