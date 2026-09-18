r"""Parse the time strings the adjudicator quotes (S5 design §5).

S2 plants event times as `HH:MM on DD/MM/YYYY` (synth.facts.TIME_FORMAT), but the model may quote
a date-first form instead: S2 discharge-summary header fields (`Discharge date: 22/03/2020, 21:22`,
`Admission date: 02/03/2020 (17:16)`) and S4 reader reorderings (`recorded 09/03/2020 at 09:07`).
`TIME_RE` accepts both — canonical alternative first, then `DD/MM/YYYY[,] [at |(]HH:MM` — tolerates
an OCR'd `.` for `:` and single-digit fields; the first match in the quote wins. Anything else
(a bare date, a bare time) is "not documented" and the case abstains (R1). Real EPR notes will
need a broader parser still — S5 design §11.

`re.search` with `|` alternation is leftmost-match, not longest- or best-match: within a single
position it tries the canonical alternative first, but across positions an earlier date-first
fragment in the quote wins over a later canonical string even though the canonical one would also
match. `\d{1,2}[:.]\d{2}` (either alternative's hour:minute) also matches a decimal number written
with a full stop, e.g. `1.25` in "SpO2 dropped to 1.25 on air" would parse as `01:25` if a date
happened to follow it in the right shape. Zero misparses of either kind were observed on the
2026-09-16 full run; hardening (`(?!\d)` after the minutes group so `12:345` can't donate its first
two digits, `\b` before the day group so a preceding digit can't be swallowed into `DD`) is deferred
to the next `prompt_version` bump rather than done opportunistically, since any regex edit here
moves `prompt_version` and forces a full re-run.
"""
import re

import pandas as pd

TIME_RE = re.compile(
    r"(?P<h>\d{1,2})[:.](?P<m>\d{2})\s*on\s*(?P<d>\d{1,2})/(?P<mo>\d{1,2})/(?P<y>\d{4})"
    r"|(?P<d2>\d{1,2})/(?P<mo2>\d{1,2})/(?P<y2>\d{4}),?\s*(?:at\s*|\()?(?P<h2>\d{1,2})[:.](?P<m2>\d{2})",
    re.IGNORECASE,
)


def parse_time_quote(quote: str | None) -> pd.Timestamp | None:
    """First `HH:MM on DD/MM/YYYY` or `DD/MM/YYYY[,] [at |(]HH:MM` in `quote` as a naive
    Timestamp; None when absent or invalid."""
    if not quote:
        return None
    m = TIME_RE.search(quote)
    if not m:
        return None
    g = m.groupdict()
    if g["h"] is not None:
        hh, mm, dd, mo, yy = (int(g[k]) for k in ("h", "m", "d", "mo", "y"))
    else:
        hh, mm, dd, mo, yy = (int(g[k]) for k in ("h2", "m2", "d2", "mo2", "y2"))
    try:
        return pd.Timestamp(year=yy, month=mo, day=dd, hour=hh, minute=mm)
    except ValueError:
        return None
