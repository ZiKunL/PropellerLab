"""Tests for Reynolds range estimation and multi-Re XFOIL helpers."""

from __future__ import annotations

import math

from propeller_lab.core.geometry import estimate_reynolds_range, representative_reynolds_values
from propeller_lab.core.models import PropellerInput
from propeller_lab.core.xfoil_runner import XfoilPolarPoint, XfoilRunResult
from propeller_lab.ui.xfoil_worker import _combine_results


def test_estimate_reynolds_range_returns_positive_bounds():
    """Default inputs should produce a finite station Reynolds range."""

    estimate = estimate_reynolds_range(PropellerInput())

    assert estimate["re_min"] > 0.0
    assert estimate["re_max"] >= estimate["re_min"]
    assert estimate["re_root"] > 0.0
    assert estimate["re_tip"] > 0.0
    for value in estimate.values():
        assert math.isfinite(value)


def test_estimate_reynolds_range_tracks_rpm_and_chord():
    """Increasing RPM and chord should increase the estimated Reynolds range."""

    base = estimate_reynolds_range(PropellerInput(rpm=6000.0, root_chord_ratio=0.12, tip_chord_ratio=0.05))
    larger = estimate_reynolds_range(PropellerInput(rpm=12000.0, root_chord_ratio=0.18, tip_chord_ratio=0.08))

    assert larger["re_min"] > base["re_min"]
    assert larger["re_max"] > base["re_max"]


def test_representative_reynolds_values_uses_sorted_endpoints():
    """Representative Reynolds values should cover the requested range."""

    values = representative_reynolds_values(200000.0, 100000.0, 3)

    assert len(values) == 3
    assert values == sorted(values)
    assert math.isclose(values[0], 100000.0, rel_tol=1e-12)
    assert math.isclose(values[-1], 200000.0, rel_tol=1e-12)


def test_representative_reynolds_values_uses_log_spacing_for_wide_range():
    """Wide ranges should use log spacing so low Re is not under-sampled."""

    values = representative_reynolds_values(50000.0, 400000.0, 4)
    ratios = [right / left for left, right in zip(values, values[1:])]

    assert len(values) == 4
    assert math.isclose(values[0], 50000.0, rel_tol=1e-12)
    assert math.isclose(values[-1], 400000.0, rel_tol=1e-12)
    assert max(ratios) - min(ratios) < 1e-9


def test_xfoil_worker_combines_multiple_reynolds_tables():
    """Worker result combination should preserve all successful Re tables."""

    low_points = [_point(alpha, cl=0.1 * alpha, cd=0.01) for alpha in range(-2, 3)]
    high_points = [_point(alpha, cl=0.2 * alpha, cd=0.02) for alpha in range(-2, 3)]
    low = XfoilRunResult(low_points, "low", "", [], None, None, {100000.0: low_points})
    high = XfoilRunResult(high_points, "high", "", [], None, None, {200000.0: high_points})

    combined = _combine_results([low, high])

    assert combined.points == low_points
    assert sorted(combined.reynolds_tables) == [100000.0, 200000.0]
    assert combined.reynolds_tables[200000.0] == high_points


def _point(alpha: float, cl: float, cd: float) -> XfoilPolarPoint:
    """Build a compact XFOIL point for tests."""

    return XfoilPolarPoint(
        alpha_deg=float(alpha),
        cl=cl,
        cd=cd,
        cdp=cd,
        cm=-0.04,
        xtr_top=None,
        xtr_bottom=None,
    )
