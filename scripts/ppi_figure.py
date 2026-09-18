"""The value-of-PPI figure for the technical slide (evaluation only — reads `cases.breached`, the
planted truth). Two panels from the same resampling as `estimate --coverage`, plus the
reviews-only arm the coverage table lacks:

  left  — H4 (model agrees with truth): 95 % CI width vs number of reviews, model-only (naive),
          reviews-only (classical Wilson on the reviewed subset) and prediction-powered; PPI sits on
          the model-only line — the model's certainty from a handful of reviews, and valid.
  right — H5 (model biased): coverage of the true rate vs number of reviews, model-only (naive)
          against prediction-powered; the naive interval never contains the truth, the corrected one does.

Usage: uv run python scripts/ppi_figure.py [--sims 500] [--out docs/pitch/ppi_figure]
Writes <out>.svg, <out>.png (Playwright, if installed) and <out>.md (the numbers behind the lines).
"""
import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

from auditpace.estimate.categorise import categorise
from auditpace.estimate.compute import load_inputs
from auditpace.estimate.ppi import estimate_rate, naive_rate, wilson, z_for
from auditpace.estimate.reviews import empty_reviews
from auditpace.protocol import load_protocol
from auditpace.settings import load_settings
from auditpace.store import Store

N_REVIEWS = (5, 10, 15, 20, 30, 40, 60, 80, 100, 150, 200)


def simulate(cf: pd.DataFrame, cases: pd.DataFrame, cid: str, z: float, sims: int, seed: int) -> pd.DataFrame:
    truth = dict(zip(cases.case_id, cases.breached.astype(bool)))
    est = cf[(cf.criterion_id == cid) & cf.estimable]
    yhat = est.yhat.to_numpy(dtype=bool)
    y = np.array([truth[c] for c in est.case_id], dtype=bool)
    N, true_rate = len(yhat), float(y.mean())
    rng = np.random.default_rng(seed)
    rows = []
    for n in [m for m in N_REVIEWS if m < N]:
        hit = {"naive": 0, "classical": 0, "ppi": 0}
        width = {"naive": 0.0, "classical": 0.0, "ppi": 0.0}
        for _ in range(sims):
            idx = rng.choice(N, size=n, replace=False)
            nv = naive_rate(yhat, z)
            _, clo, chi = wilson(int(y[idx].sum()), n, z)
            pv = estimate_rate(yhat, yhat[idx], y[idx], z)
            for k, lo, hi in (("naive", nv.lo, nv.hi), ("classical", clo, chi), ("ppi", pv.lo, pv.hi)):
                hit[k] += lo <= true_rate <= hi
                width[k] += hi - lo
        for k, h in hit.items():
            rows.append({"criterion_id": cid, "n_reviews": n, "N": N, "method": k, "coverage": h / sims,
                         "mean_width": width[k] / sims, "true_rate": true_rate,
                         "model_rate": float(yhat.mean())})
    return pd.DataFrame(rows)


# --- SVG (no plotting dependency; the deck designer gets a vector) -------------------------------

W, H, PAD = 1200, 460, {"l": 70, "r": 24, "t": 56, "b": 64}
COL = {"naive": "#9aa0a6", "classical": "#e67e22", "ppi": "#1f6feb"}
LABEL = {"naive": "model only (naive)", "classical": "reviews only", "ppi": "prediction-powered (PPI)"}


def _panel(x0: float, w: float, df: pd.DataFrame, ycol: str, title: str, sub: str, ymax: float,
           yfmt, methods: tuple[str, ...]) -> str:
    ph = H - PAD["t"] - PAD["b"]
    xs = sorted(df.n_reviews.unique())
    xmin, xmax = math.log10(xs[0]), math.log10(xs[-1])
    sx = lambda n: x0 + PAD["l"] + (math.log10(n) - xmin) / (xmax - xmin) * (w - PAD["l"] - PAD["r"])
    sy = lambda v: PAD["t"] + ph - (v / ymax) * ph
    out = [f'<text x="{x0 + PAD["l"]}" y="26" class="title">{title}</text>',
           f'<text x="{x0 + PAD["l"]}" y="44" class="sub">{sub}</text>']
    # axes + gridlines
    for i in range(5):
        v = ymax * i / 4
        out.append(f'<line x1="{x0 + PAD["l"]}" x2="{x0 + w - PAD["r"]}" y1="{sy(v):.1f}" y2="{sy(v):.1f}" class="grid"/>')
        out.append(f'<text x="{x0 + PAD["l"] - 8}" y="{sy(v) + 4:.1f}" class="tick" text-anchor="end">{yfmt(v)}</text>')
    for n in xs:
        if n in (15, 80):
            continue  # crowded on the log axis
        out.append(f'<text x="{sx(n):.1f}" y="{PAD["t"] + ph + 18}" class="tick" text-anchor="middle">{n}</text>')
    out.append(f'<text x="{x0 + PAD["l"] + (w - PAD["l"] - PAD["r"]) / 2:.1f}" y="{H - 22}" class="axis" text-anchor="middle">clinician reviews, of {int(df.N.iloc[0])} cases (log scale)</text>')
    for m in methods:
        d = df[df.method == m].sort_values("n_reviews")
        pts = " ".join(f"{sx(n):.1f},{sy(v):.1f}" for n, v in zip(d.n_reviews, d[ycol]))
        dash = ' stroke-dasharray="8 6"' if m == "naive" and ycol == "mean_width" else ""
        out.append(f'<polyline points="{pts}" fill="none" stroke="{COL[m]}" stroke-width="3" stroke-linejoin="round"{dash}/>')
        if not dash:
            for n, v in zip(d.n_reviews, d[ycol]):
                out.append(f'<circle cx="{sx(n):.1f}" cy="{sy(v):.1f}" r="3.5" fill="{COL[m]}"/>')
    lx, ly = x0 + w - PAD["r"] - 250, (PAD["t"] + ph - 70 if ycol == "coverage" else PAD["t"] + 14)
    for i, m in enumerate(methods):
        dash = ' stroke-dasharray="8 6"' if m == "naive" and ycol == "mean_width" else ""
        out.append(f'<line x1="{lx}" x2="{lx + 26}" y1="{ly + i * 20}" y2="{ly + i * 20}" stroke="{COL[m]}" stroke-width="3"{dash}/>')
        out.append(f'<text x="{lx + 34}" y="{ly + i * 20 + 4}" class="lab" fill="{COL[m]}">{LABEL[m]}</text>')
    return "\n".join(out)


def render_svg(h4: pd.DataFrame, h5: pd.DataFrame, sims: int) -> str:
    half = W / 2
    left = _panel(0, half, h4, "mean_width",
                  "H4 admission → VTE: width of the 95 % interval",
                  "model agrees with the truth here — PPI keeps the model's certainty from five reviews",
                  0.65, lambda v: f"{v * 100:.0f} pp", ("classical", "naive", "ppi"))
    right = _panel(half, half, h5[h5.method.isin(["naive", "ppi"])], "coverage",
                   "H5 ICU → ventilation: does the interval hold the truth?",
                   "model is biased here — model-only never does; corrected, it does",
                   1.0, lambda v: f"{v * 100:.0f} %", ("naive", "ppi"))
    cap = (f"500 resamples of our own 6,220-case synthetic cohort (planted truth, Synthea COVID-19); "
           f"{sims} draws per point. Nothing simulated beyond the data we adjudicated.")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H + 24}" viewBox="0 0 {W} {H + 24}" font-family="Inter, system-ui, sans-serif">
<style>
  .title {{ font-size: 17px; font-weight: 700; fill: #1b1f24; }}
  .sub {{ font-size: 13px; fill: #6a737d; }}
  .tick {{ font-size: 12px; fill: #6a737d; }}
  .axis {{ font-size: 13px; fill: #6a737d; }}
  .lab {{ font-size: 13px; font-weight: 600; }}
  .grid {{ stroke: #e6e9ed; stroke-width: 1; }}
  .cap {{ font-size: 12px; fill: #6a737d; }}
</style>
<rect width="100%" height="100%" fill="#ffffff"/>
{left}
{right}
<text x="{PAD["l"]}" y="{H + 14}" class="cap">{cap}</text>
</svg>
'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path("docs/pitch/ppi_figure"))
    a = ap.parse_args()
    s = load_settings()
    protocol = load_protocol(Path("protocol.yaml"))
    with Store(s.paths.processed_dir, read_only=True) as store:
        inp = load_inputs(store, protocol)
    cf = categorise(inp["verdicts"], inp["cases"], inp["patients"], empty_reviews(), protocol)
    z = z_for(protocol.review.confidence)
    h4 = simulate(cf, inp["cases"], "H4", z, a.sims, a.seed)
    h5 = simulate(cf, inp["cases"], "H5", z, a.sims, a.seed)
    both = pd.concat([h4, h5], ignore_index=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.with_suffix(".svg").write_text(render_svg(h4, h5, a.sims))
    md = ["# PPI figure — numbers behind the lines", "",
          f"*{a.sims} resamples per point, seed {a.seed}; truth = `cases.breached` (planted). Width in percentage points; coverage = share of resamples whose 95 % interval contained the true rate.*", "",
          "| handoff | N | true rate | model rate | reviews | method | coverage | mean CI width |", "|---|---|---|---|---|---|---|---|"]
    for r in both.itertuples():
        md.append(f"| {r.criterion_id} | {r.N} | {r.true_rate:.3f} | {r.model_rate:.3f} | {r.n_reviews} | {r.method} | {r.coverage:.3f} | {r.mean_width * 100:.1f} pp |")
    a.out.with_suffix(".md").write_text("\n".join(md) + "\n")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": W, "height": H + 24}, device_scale_factor=2)
            pg.set_content(a.out.with_suffix(".svg").read_text())
            pg.screenshot(path=str(a.out.with_suffix(".png")), full_page=True)
            b.close()
    except Exception as e:  # noqa: BLE001 — PNG is a convenience; the SVG is the deliverable
        print(f"png skipped: {e}")
    for cid, df in (("H4", h4), ("H5", h5)):
        piv = df.pivot(index="n_reviews", columns="method", values=["coverage", "mean_width"]).round(3)
        print(cid, "N =", int(df.N.iloc[0]), "true", round(float(df.true_rate.iloc[0]), 3), "model",
              round(float(df.model_rate.iloc[0]), 3))
        print(piv.to_string())
    print("wrote", a.out.with_suffix(".svg"), a.out.with_suffix(".md"))


if __name__ == "__main__":
    main()
