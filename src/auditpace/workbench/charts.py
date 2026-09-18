"""Inline SVG for the Results tab: funnel plot and weekly run chart. No chart library (spec §5)."""
import pandas as pd

W, H, PAD = 520, 260, 36


def _scale(vals, lo, hi, out_lo, out_hi):
    span = (hi - lo) or 1.0
    return [out_lo + (float(v) - lo) / span * (out_hi - out_lo) for v in vals]


def _poly(xs, ys, cls: str) -> str:
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    return f'<polyline class="{cls}" fill="none" points="{pts}"/>'


def _line_if_complete(xs, series: pd.Series, cls: str) -> str:
    """Draw a polyline for `series` only when it has no NaN among the plotted rows.

    S6 can emit NaN centre/alert/alarm values (e.g. `estimate/funnel.py::centre_of` when a
    criterion has no `segment_key == "all"` estimate row). Filling those with 0 would draw a
    false "limit at rate = 0" line, so the whole line is skipped instead.
    """
    if series.isna().any():
        return ""
    ys = _scale(series, 0.0, 1.0, H - PAD, PAD)
    return _poly(xs, ys, cls)


def _frame(title_y: str) -> str:
    return (f'<svg class="chart" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img">'
            f'<line class="axis" x1="{PAD}" y1="{H - PAD}" x2="{W - PAD}" y2="{H - PAD}"/>'
            f'<line class="axis" x1="{PAD}" y1="{PAD}" x2="{PAD}" y2="{H - PAD}"/>'
            f'<text class="lab" x="{PAD}" y="{PAD - 8}">{title_y}</text>')


def funnel_svg(funnel: pd.DataFrame) -> str:
    f = funnel[~funnel.suppressed.astype(bool)].sort_values("n") if len(funnel) else funnel
    if f.empty:
        return ""
    n_lo, n_hi = 0.0, float(f.n.max())
    xs = _scale(f.n, n_lo, n_hi, PAD, W - PAD)

    out = [_frame("breach rate by organisation (n on x)")]
    out.append(_line_if_complete(xs, f["centre"], "centre"))
    for col in ("alert_lo", "alert_hi"):
        out.append(_line_if_complete(xs, f[col], "limit2"))
    for col in ("alarm_lo", "alarm_hi"):
        out.append(_line_if_complete(xs, f[col], "limit3"))
    ys = _scale(f.rate, 0.0, 1.0, H - PAD, PAD)
    for (_, r), x, yy in zip(f.iterrows(), xs, ys):
        if pd.isna(r.rate):
            continue
        out.append(f'<circle class="pt {r.signal}" cx="{x:.1f}" cy="{yy:.1f}" r="5">'
                   f"<title>{r.organization_id}: {100 * float(r.rate):.1f} % (n={int(r.n)})</title></circle>")
    out.append("</svg>")
    return "".join(out)


def runchart_svg(runchart: pd.DataFrame) -> str:
    rc = runchart[~runchart.suppressed.astype(bool)].sort_values("week_start") if len(runchart) else runchart
    if rc.empty:
        return ""
    xs = _scale(range(len(rc)), 0, max(len(rc) - 1, 1), PAD, W - PAD)

    out = [_frame("weekly breach rate")]
    out.append(_line_if_complete(xs, rc["centre"], "centre"))
    out.append(_line_if_complete(xs, rc["alert_hi"], "limit2"))
    out.append(_line_if_complete(xs, rc["alarm_hi"], "limit3"))
    out.append(_line_if_complete(xs, rc["rate"], "series"))
    ys = _scale(rc.rate, 0.0, 1.0, H - PAD, PAD)
    for (_, r), x, yy in zip(rc.iterrows(), xs, ys):
        if pd.isna(r.rate):
            continue
        cls = f"pt {r.signal}" + (" latest" if bool(r.latest) else "")
        out.append(f'<circle class="{cls}" cx="{x:.1f}" cy="{yy:.1f}" r="4">'
                   f"<title>{r.week}: {100 * float(r.rate):.1f} % (n={int(r.n)})</title></circle>")
    out.append("</svg>")
    return "".join(out)
