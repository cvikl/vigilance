"""Print page stats and check the word contract + box/ink agreement on a sample. Run after
`auditpace render` (works while it runs: read-only store)."""
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from auditpace.settings import load_settings
from auditpace.store import Store

s = load_settings()
with Store(s.paths.processed_dir, read_only=True) as store:
    pages = store.read("pages")
    docs = store.read("documents")
root = Path(s.paths.processed_dir)
print(f"pages={len(pages)} documents_rendered={pages.doc_id.nunique()}/{len(docs)} "
      f"render_versions={sorted(pages.render_version.unique())}")
print(pages.groupby(["doc_type", "style"]).size().to_string(), "\n")
print("pages per document:", pages.groupby("doc_id").size().value_counts().sort_index().to_dict())
words = pages.gt_words.map(lambda j: len(json.loads(j)))
print(f"words per page: min={words.min()} median={int(words.median())} max={words.max()}")

bad = []
missing = [p for p in pages.image_path if not (root / p).exists()]
if missing:
    bad.append(f"{len(missing)} image files missing, e.g. {missing[:3]}")
text = docs.set_index("doc_id").text
for doc_id, grp in pages.sort_values("page_no").groupby("doc_id"):
    if doc_id not in text.index:
        bad.append(f"page {grp.page_id.iloc[0]} has no document")
        break
    got = [w["word"] for r in grp.itertuples() for w in json.loads(r.gt_words)]
    if got != text[doc_id].split():
        bad.append(f"word contract broken for {doc_id}")
        break

# box/ink agreement + box-shape gate on a seeded sample of 200 pages: share of boxes whose crop
# has any dark pixel, and per-style box height (a wrapped word's union rect is ~2x tall).
rng = np.random.default_rng(0)
sample = pages.sample(min(200, len(pages)), random_state=0)
hits, total = 0, 0
heights_by_style: dict[str, list[int]] = {}
for r in sample.itertuples():
    g = np.asarray(Image.open(root / r.image_path).convert("L"))
    for w in json.loads(r.gt_words):
        total += 1
        hits += int(g[w["y0"]:w["y1"], w["x0"]:w["x1"]].min() < 128)
        heights_by_style.setdefault(r.style, []).append(w["y1"] - w["y0"])
ink = hits / max(total, 1)
print(f"boxes with ink (sample of {len(sample)} pages): {ink:.3f}")
if ink < 0.99:
    bad.append(f"only {ink:.3f} of word boxes contain ink (expect >= 0.99)")

max_h = {}
for style, hs in heights_by_style.items():
    median, mx = float(np.median(hs)), max(hs)
    max_h[style] = mx
    if mx > 1.5 * median:
        bad.append(f"{style} box height {mx} > 1.5x median {median:.1f}")
order = ["typed", "handwritten", *sorted(set(max_h) - {"typed", "handwritten"})]
print("max box height " + " ".join(f"{st}={max_h[st]}" for st in order if st in max_h))

out = Path("logs/render_samples")
shutil.rmtree(out, ignore_errors=True)
out.mkdir(parents=True)
for (dt, st), grp in pages.groupby(["doc_type", "style"]):
    r = grp.sample(1, random_state=rng.integers(1 << 30)).iloc[0]
    shutil.copy(root / r.image_path, out / f"{dt}_{st}{Path(r.image_path).suffix}")
print(f"samples in {out}/")

if bad:
    print("\n".join(bad))
    sys.exit(1)
print("ok")
