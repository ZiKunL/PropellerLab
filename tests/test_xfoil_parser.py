"""Tests for XFOIL polar parsing and export."""

from __future__ import annotations

from propeller_lab.core.polar import TablePolar
from propeller_lab.core.xfoil_runner import XfoilRunner


def test_parse_xfoil_polar_skips_headers(tmp_path):
    """Typical XFOIL headers should be skipped."""

    polar_path = tmp_path / "polar.txt"
    polar_path.write_text(
        """
 XFOIL polar

 alpha      CL        CD       CDp       CM     Top_Xtr  Bot_Xtr
------  --------  --------  --------  --------  -------  -------
 -5.0   -0.4100   0.01900   0.01400  -0.0200   0.7500   0.6000
  0.0    0.0500   0.01150   0.00750  -0.0400   0.6500   0.5500
  5.0    0.5600   0.01700   0.01100  -0.0550   0.5500   0.4500
""",
        encoding="utf-8",
    )
    points = XfoilRunner.parse_xfoil_polar(polar_path)
    assert len(points) == 3
    assert points[0].alpha_deg == -5.0
    assert points[1].cl == 0.05


def test_parse_empty_xfoil_polar_returns_empty(tmp_path):
    """Empty files should produce an empty point list."""

    polar_path = tmp_path / "empty.txt"
    polar_path.write_text("", encoding="utf-8")
    assert XfoilRunner.parse_xfoil_polar(polar_path) == []


def test_export_xfoil_points_can_be_read_as_table_polar(tmp_path):
    """Exported XFOIL CSV should be readable by TablePolar."""

    source = tmp_path / "polar.txt"
    source.write_text(
        """
 -5.0   -0.4100   0.01900   0.01400  -0.0200   0.7500   0.6000
  0.0    0.0500   0.01150   0.00750  -0.0400   0.6500   0.5500
  5.0    0.5600   0.01700   0.01100  -0.0550   0.5500   0.4500
""",
        encoding="utf-8",
    )
    points = XfoilRunner.parse_xfoil_polar(source)
    csv_path = tmp_path / "xfoil.csv"
    XfoilRunner.export_xfoil_points_to_csv(points, csv_path)

    polar = TablePolar.from_csv(csv_path)
    cl, cd, cm, warnings = polar.lookup(0.0)
    assert cl == 0.05
    assert cd == 0.0115
    assert cm == -0.04
    assert warnings == []
