"""Tests for polar models."""

from __future__ import annotations

import math
from pathlib import Path

from propeller_lab.core.polar import GenericPolar, MultiRePolar, TablePolar


ROOT = Path(__file__).resolve().parents[1]


def test_generic_polar_returns_valid_values():
    """GenericPolar should return finite values."""

    cl, cd, cm, warnings = GenericPolar().lookup(5.0, reynolds=100000.0, mach=0.1)
    assert math.isfinite(cl)
    assert math.isfinite(cd)
    assert math.isfinite(cm)
    assert cd > 0.0
    assert warnings == []


def test_table_polar_reads_sample_and_interpolates():
    """TablePolar should interpolate alpha values."""

    polar = TablePolar.from_csv(ROOT / "examples" / "sample_polar.csv")
    cl, cd, cm, warnings = polar.lookup(2.5)
    assert math.isclose(cl, 0.275, rel_tol=1e-6)
    assert math.isclose(cd, 0.015, rel_tol=1e-6)
    assert math.isclose(cm, -0.045, rel_tol=1e-6)
    assert warnings == []


def test_table_polar_out_of_range_warns():
    """Out-of-range alpha should clamp and warn."""

    polar = TablePolar.from_csv(ROOT / "examples" / "sample_polar.csv")
    cl, cd, cm, warnings = polar.lookup(30.0)
    assert cl == 1.15
    assert cd == 0.100
    assert cm == -0.07
    assert warnings


def test_multi_re_polar_interpolates_between_tables():
    """MultiRePolar should interpolate between two Reynolds tables."""

    low = TablePolar.from_csv(ROOT / "examples" / "sample_polar.csv")
    high = TablePolar.from_csv(ROOT / "examples" / "sample_polar.csv")
    for point in high.points:
        point.cl *= 2.0
    multi = MultiRePolar()
    multi.add_table(100000.0, low)
    multi.add_table(200000.0, high)

    cl, _cd, _cm, warnings = multi.lookup(5.0, reynolds=150000.0)
    assert math.isclose(cl, 0.825, rel_tol=1e-6)
    assert warnings == []
