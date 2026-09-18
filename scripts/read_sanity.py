"""Print reading stats and gate on CER / alignment / fallback. Run after `auditpace read`
(works while it runs: read-only store). Writes three annotated samples to logs/read_samples/."""
import json
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from auditpace.settings import load_settings
from auditpace.store import Store

s = load_settings()
with Store(s.paths.processed_dir, read_only=True) as store:
    r = store.read("readings")
    pages = store.read("pages")
root = Path(s.paths.processed_dir)

print(f"readings={len(r)} pages={len(pages)} read_versions={sorted(r.read_version.unique())} "
      f"render_versions={sorted(r.render_version.unique())}")
print("\nreader_used:", r.reader_used.value_counts().to_dict())
print("\nCER (median / mean) and align_frac by style × reader:")
g = r.groupby("style")
print(g[["cer_tess", "cer_medgemma", "align_frac"]].median().round(4).to_string())
print(g[["cer_tess", "cer_medgemma", "align_frac"]].mean().round(4).to_string())
print("\nalign_frac quartiles:", r.align_frac.quantile([0.25, 0.5, 0.75]).round(3).to_dict())

bad = []
if set(r.page_id) != set(pages.page_id):
    bad.append(f"page_id sets differ: {len(set(pages.page_id) - set(r.page_id))} pages unread, "
               f"{len(set(r.page_id) - set(pages.page_id))} orphan readings")
typed = r[r["style"] == "typed"]
if typed.cer_tess.median() >= 0.05:
    bad.append(f"median typed cer_tess {typed.cer_tess.median():.3f} >= 0.05")
if r.align_frac.median() <= 0.8:
    bad.append(f"median align_frac {r.align_frac.median():.3f} <= 0.8")
fb = (r.reader_used == "tesseract").mean()
if fb >= 0.02:
    bad.append(f"fallback rate {fb:.3%} >= 2%")
for row in r.itertuples():
    for a in json.loads(row.alignment):
        if not row.reading_text[a["start"]:a["end"]].strip():
            bad.append(f"empty alignment slice on {row.page_id}")
            break
    else:
        continue
    break

out = Path("logs/read_samples")
shutil.rmtree(out, ignore_errors=True)
out.mkdir(parents=True)
picks = [r[r["style"] == "typed"].head(1), r[r["style"] == "handwritten"].head(1), r[r["reader_used"] == "tesseract"].head(1)]
img_by_page = pages.set_index("page_id").image_path
for df in picks:
    for row in df.itertuples():
        im = Image.open(root / img_by_page[row.page_id]).convert("RGB")
        d = ImageDraw.Draw(im)
        for a in json.loads(row.alignment):
            d.rectangle([a["x0"], a["y0"], a["x1"] - 1, a["y1"] - 1], outline=(255, 0, 0))
        name = f"{row.style}_{row.reader_used}_{row.page_id.replace(':', '_')}.png"
        im.save(out / name)
        print(f"sample: {out/name} cer_tess={row.cer_tess:.3f} cer_medgemma={row.cer_medgemma:.3f} align_frac={row.align_frac:.3f}")

if bad:
    print("\nFAIL:\n  " + "\n  ".join(bad))
    sys.exit(1)
print("\nok")
