import math

import pandas as pd

from auditpace.estimate.categorise import categorise
from auditpace.estimate.reviews import empty_reviews
from auditpace.estimate.timelost import build_timelost
from tests.estimate.conftest import toy

NOW = pd.Timestamp("2026-09-16 12:00:00")


def test_time_lost_sums_system_breaches_only_and_ranks(locked_protocol):
    rows = [
        {"pid": "a", "crit": "H4", "status": "breached", "reason": "not_prescribed", "hours": 34, "org": "A"},          # +10
        {"pid": "b", "crit": "H4", "status": "breached", "reason": "contraindication_documented", "hours": 50, "org": "A"},  # legit, ignored
        {"pid": "c", "crit": "H4", "status": "breached", "reason": None, "hours": 60, "org": "B"},                     # undetermined, ignored
        {"pid": "d", "crit": "H2", "status": "breached", "reason": "bed_unavailable", "hours": 9, "org": "A"},          # +5
        {"pid": "e", "crit": "H2", "status": "breached", "reason": "bed_unavailable", "hours": 5, "org": "B"},          # +1
        {"pid": "f", "crit": "H2", "status": "not_breached", "hours": 1, "org": "B"},
    ]
    t = toy(rows, locked_protocol)
    cf = categorise(t["verdicts"], t["cases"], t["patients"], empty_reviews(), locked_protocol)
    tl = build_timelost(cf, NOW)
    crit = tl[tl.organization_id == "all"].set_index("criterion_id")
    assert crit.loc["H4", "hours_lost"] == 10 and crit.loc["H4", "n_breached_system"] == 1 and crit.loc["H4", "rank"] == 1
    assert crit.loc["H2", "hours_lost"] == 6 and crit.loc["H2", "median_excess_h"] == 3 and crit.loc["H2", "rank"] == 2
    orgs = tl[(tl.criterion_id == "H2") & (tl.organization_id != "all")].set_index("organization_id")
    assert orgs.loc["A", "hours_lost"] == 5 and orgs.loc["B", "hours_lost"] == 1 and math.isnan(orgs.loc["A", "rank"])
    assert tl.descriptive.all()
