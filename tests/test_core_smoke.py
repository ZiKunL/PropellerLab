"""Smoke tests for the calculation core."""

from __future__ import annotations

import math

from propeller_lab.core.bemt import calculate_propeller
from propeller_lab.core.export import export_station_csv, export_summary_csv
from propeller_lab.core.models import PropellerInput


def test_default_input_calculates_and_exports(tmp_path):
    """Default input should produce finite totals and export files."""

    inp = PropellerInput()
    result = calculate_propeller(inp)

    assert len(result.stations) == inp.elements
    for value in (result.thrust_N, result.torque_Nm, result.power_W, result.ct, result.cq, result.cp):
        assert math.isfinite(value)

    station_path = tmp_path / "stations.csv"
    summary_path = tmp_path / "summary.csv"
    export_station_csv(result, station_path)
    export_summary_csv(result, summary_path)
    assert station_path.exists()
    assert summary_path.exists()
    assert station_path.stat().st_size > 0
    assert summary_path.stat().st_size > 0
