"""Stage 6: estimate → estimates, funnel, runchart, timelost, alerts, queue (+ coverage)."""
import pandas as pd

from auditpace.estimate.categorise import categorise
from auditpace.estimate.compute import compute_all, load_inputs
from auditpace.estimate.coverage import run_coverage
from auditpace.stage import Stage


class EstimateStage(Stage):
    name = "estimate"

    def __init__(self, settings, protocol, store, coverage: bool = False, sims: int = 500):
        super().__init__(settings, protocol, store)
        self.coverage = coverage
        self.sims = sims

    def items(self):
        return ["estimate"]

    def is_done(self, item) -> bool:
        return False  # always recompute: ~1 s, and reviews may have changed

    def _attempt(self, item):
        # One item, no quarantine: a stale/missing input must reach the CLI as exit 2 and an
        # arithmetic bug must surface, not hide in quarantine/estimate.jsonl (spec §11).
        return item, self.process(item), None

    def process(self, item):
        p = self.protocol
        now = pd.Timestamp.now("UTC").tz_localize(None)
        out = compute_all(self.store, p, now)
        for name, df in out.items():
            self.store.write(name, df, p.hash)
        counts = {k: len(v) for k, v in out.items()}
        if self.coverage:
            inp = load_inputs(self.store, p)
            cf = categorise(inp["verdicts"], inp["cases"], inp["patients"], inp["reviews"], p)
            cov = run_coverage(cf, inp["cases"], p, sims=self.sims, seed=self.settings.seed, now=now)
            self.store.write("coverage", cov, p.hash)
            counts["coverage"] = len(cov)
        est = out["estimates"]
        summary = est[est.segment_key == "all"][["criterion_id", "n", "n_reviewed", "n_abstain", "n_no_end",
                                                 "naive_rate", "corrected_rate", "corrected_lo", "corrected_hi", "method"]]
        print("estimates (all):\n" + summary.to_string(index=False), flush=True)
        al = out["alerts"][["kind", "criterion_id", "segment_value", "signal", "owner", "action"]]
        print("alerts:\n" + (al.to_string(index=False) if len(al) else "(none)"), flush=True)
        return counts
