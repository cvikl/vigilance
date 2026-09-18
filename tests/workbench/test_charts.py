import pandas as pd

from auditpace.workbench.charts import funnel_svg, runchart_svg


def _funnel():
    return pd.DataFrame({
        "organization_id": ["a", "b", "c"], "n": [10, 40, 3], "rate": [0.2, 0.6, 0.5],
        "lo": [0.1, 0.5, 0.1], "hi": [0.3, 0.7, 0.9], "centre": [0.3, 0.3, 0.3],
        "alert_lo": [0.05, 0.15, 0.0], "alert_hi": [0.55, 0.45, 0.8], "alarm_lo": [0.0, 0.1, 0.0],
        "alarm_hi": [0.7, 0.5, 0.9], "signal": ["none", "alarm_high", "none"], "suppressed": [False, False, True],
    })


def test_funnel_one_circle_per_unsuppressed_org_with_signal_class():
    svg = funnel_svg(_funnel())
    assert svg.startswith("<svg") and svg.count("<circle") == 2
    assert 'class="pt alarm_high"' in svg and "<title>b" in svg and "<title>c" not in svg
    assert svg.count("<polyline") == 5  # centre + 2σ lo/hi + 3σ lo/hi


def test_funnel_empty_when_all_suppressed():
    f = _funnel()
    f["suppressed"] = True
    assert funnel_svg(f) == "" and funnel_svg(f.iloc[0:0]) == ""


def test_runchart_points_and_latest():
    rc = pd.DataFrame({
        "week": ["2020-W10", "2020-W11", "2020-W12"], "week_start": pd.to_datetime(["2020-03-02", "2020-03-09", "2020-03-16"]),
        "n": [8, 9, 2], "rate": [0.2, 0.5, 0.9], "centre": [0.3] * 3, "alert_hi": [0.5] * 3, "alarm_hi": [0.6] * 3,
        "signal": ["none", "alert_high", "none"], "latest": [False, True, False], "suppressed": [False, False, True],
    })
    svg = runchart_svg(rc)
    assert svg.count("<circle") == 2 and 'class="pt alert_high latest"' in svg
    assert "2020-W12" not in svg
    assert runchart_svg(rc[rc.suppressed]) == ""


def test_funnel_all_limits_nan_draws_no_lines_but_keeps_points():
    f = _funnel()  # keeps default suppressed pattern: a, b unsuppressed; c suppressed
    for col in ("centre", "alert_lo", "alert_hi", "alarm_lo", "alarm_hi"):
        f[col] = float("nan")
    svg = funnel_svg(f)
    assert svg.count("<circle") == 2
    assert svg.count("<polyline") == 0
    assert 'class="centre"' not in svg


def test_funnel_one_row_nan_limit_drops_only_that_line():
    f = _funnel()  # keeps default suppressed pattern: a, b unsuppressed; c suppressed
    f.loc[f.index[0], "alarm_hi"] = float("nan")
    svg = funnel_svg(f)
    assert svg.count("<polyline") == 4


def test_runchart_nan_rate_drops_point_and_series_line_only():
    rc = pd.DataFrame({
        "week": ["2020-W10", "2020-W11", "2020-W12"], "week_start": pd.to_datetime(["2020-03-02", "2020-03-09", "2020-03-16"]),
        "n": [8, 9, 2], "rate": [0.2, float("nan"), 0.9], "centre": [0.3] * 3, "alert_hi": [0.5] * 3, "alarm_hi": [0.6] * 3,
        "signal": ["none", "alert_high", "none"], "latest": [False, True, False], "suppressed": [False, False, False],
    })
    svg = runchart_svg(rc)
    assert svg.count("<circle") == 2
    assert svg.count("<polyline") == 3
    assert 'class="series"' not in svg
    assert 'class="centre"' in svg and 'class="limit2"' in svg and 'class="limit3"' in svg
