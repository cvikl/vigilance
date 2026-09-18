"""Print per-criterion cohort stats and check planted breach rates. Run after `auditpace cohort`."""
import sys

from auditpace.protocol import load_protocol
from auditpace.settings import load_settings
from auditpace.store import Store

s, p = load_settings(), load_protocol()
with Store(s.paths.processed_dir) as store:
    cases = store.read("cases")
    comp = store.read("cohort_completeness")
print(comp.to_string(index=False), "\n")
bad = []
for c in p.criteria:
    d = cases[(cases.criterion_id == c.id) & cases.applies]
    m = d[d.hours.notna()]
    rate = m.breached.mean() if len(m) else float("nan")
    print(f"{c.id} {c.name:<32} applies={len(d):5d} measured={len(m):5d} breach={rate:5.2f} "
          f"median_h={m.hours.median() if len(m) else float('nan'):7.1f} "
          f"reasons={m[m.breached].true_reason.value_counts().to_dict()}")
    target = (p.synthetic.breach_rates if p.synthetic else {}).get(c.id)
    if target is not None and len(m) >= 50 and abs(rate - target) > 0.08:
        bad.append((c.id, rate, target))
if bad:
    print("breach rate off target:", bad)
    sys.exit(1)
print("ok")
