"""Tests for target optimization helpers."""

from __future__ import annotations

import dataclasses
import math
import random
from pathlib import Path

import pytest

from propeller_lab.core.export import export_optimization_history_csv, export_optimization_summary_csv
from propeller_lab.core.geometry import save_geometry_csv
from propeller_lab.core.models import GeometryStation, PolarPoint
from propeller_lab.core.optimizer import (
    TargetOptimizationInput,
    evaluate_candidate,
    geometry_to_genome,
    genome_to_geometry,
    random_genome,
    run_genetic_algorithm,
    run_random_search,
    run_target_optimization,
)
from propeller_lab.core.polar import MultiRePolar, TablePolar


ROOT = Path(__file__).resolve().parents[1]


def test_random_genome_returns_correct_length_and_finite_values():
    """Random genome should match control-point count and remain finite."""

    opt_input = _opt_input(control_points=5)
    genome = random_genome(opt_input, random.Random(3))

    assert len(genome) == opt_input.control_points * 2
    assert all(math.isfinite(value) for value in genome)


def test_target_optimizer_random_search_returns_finite_result():
    """Random search should return finite geometry and analysis values."""

    result = run_random_search(_opt_input(optimizer_method="random_search"), polar=_multi_re_polar())

    assert len(result.best_geometry) == result.input.elements
    assert result.evaluations > 0
    assert result.history
    _assert_no_invalid_numbers(result)


def test_target_optimizer_genetic_algorithm_returns_finite_result():
    """GA dispatch should return a finite optimized result."""

    result = run_genetic_algorithm(_opt_input(optimizer_method="genetic_algorithm"), polar=_multi_re_polar())

    assert len(result.best_geometry) == result.input.elements
    assert result.best_analysis.thrust_N >= -1e-9
    assert result.best_fitness < 1.0e9
    _assert_no_invalid_numbers(result)


def test_target_optimizer_geometry_conversion_is_bounded():
    """Genome to geometry conversion should respect requested bounds."""

    opt_input = _opt_input(control_points=4, elements=9)
    genome = [0.001, 0.1, 0.5, 0.2, -50.0, 10.0, 80.0, 20.0]
    geometry = genome_to_geometry(genome, opt_input)
    round_trip = geometry_to_genome(geometry, opt_input)

    assert len(geometry) == opt_input.elements
    assert len(round_trip) == opt_input.control_points * 2
    assert all(left.r_over_R < right.r_over_R for left, right in zip(geometry, geometry[1:]))
    assert all(opt_input.chord_min_ratio <= station.chord_over_R <= opt_input.chord_max_ratio for station in geometry)
    assert all(opt_input.beta_min_deg <= station.beta_deg <= opt_input.beta_max_deg for station in geometry)


def test_evaluate_candidate_returns_finite_default_result():
    """Candidate evaluation should produce finite performance values."""

    opt_input = _opt_input()
    candidate = evaluate_candidate(random_genome(opt_input, random.Random(7)), opt_input)

    assert candidate.analysis is not None
    assert math.isfinite(candidate.analysis.thrust_N)
    assert math.isfinite(candidate.analysis.torque_Nm)
    assert math.isfinite(candidate.analysis.power_W)
    assert math.isfinite(candidate.fitness)
    _assert_no_invalid_numbers(candidate)


@pytest.mark.parametrize(
    ("target_mode", "overrides"),
    [
        ("target_thrust_min_power", {"target_thrust_N": 0.4}),
        ("target_torque_max_thrust", {"target_torque_Nm": 0.04}),
        ("match_torque", {"target_torque_Nm": 0.04}),
        ("match_thrust", {"target_thrust_N": 0.4}),
    ],
)
def test_target_modes_do_not_crash(target_mode: str, overrides: dict[str, float]):
    """Required target modes should complete with tiny settings."""

    result = run_target_optimization(_opt_input(target_mode=target_mode, **overrides), polar=_multi_re_polar())

    assert result.best_analysis is not None
    _assert_no_invalid_numbers(result)


def test_low_speed_static_optimization_does_not_crash():
    """Static target optimization should remain finite."""

    result = run_target_optimization(_opt_input(v_inf=0.0, optimizer_method="random_search"))

    assert result.best_analysis is not None
    _assert_no_invalid_numbers(result)


def test_imported_sample_polar_works_with_optimizer():
    """Imported sample polar should work with target optimization."""

    polar = TablePolar.from_csv(ROOT / "examples" / "sample_polar.csv")
    result = run_target_optimization(_opt_input(optimizer_method="random_search"), polar=polar)

    assert result.best_analysis is not None
    _assert_no_invalid_numbers(result)


def test_target_optimizer_export_csv(tmp_path):
    """Optimization history and summary exports should write CSV files."""

    result = run_target_optimization(_opt_input(optimizer_method="random_search"), polar=_multi_re_polar())
    history_path = tmp_path / "history.csv"
    summary_path = tmp_path / "summary.csv"
    geometry_path = tmp_path / "geometry.csv"

    export_optimization_history_csv(result, history_path)
    export_optimization_summary_csv(result, summary_path)
    save_geometry_csv(result.best_geometry, geometry_path)

    assert "generation" in history_path.read_text(encoding="utf-8-sig")
    assert "best_fitness" in summary_path.read_text(encoding="utf-8-sig")
    assert "chord_over_R" in geometry_path.read_text(encoding="utf-8-sig")


def test_evaluate_candidate_handles_bad_geometry_without_nan():
    """Bad candidate inputs should be repaired or converted to finite fallbacks."""

    opt_input = _opt_input()
    candidate = evaluate_candidate([float("nan")] * (opt_input.control_points * 2), opt_input)

    assert candidate.analysis is not None
    assert math.isfinite(candidate.fitness)
    _assert_no_invalid_numbers(candidate)


def test_main_window_target_optimization_workspace_smoke():
    """MainWindow should expose target optimization controls."""

    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from propeller_lab.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert window.workspace_combo.count() == 3
    assert window.workspace_combo.itemText(2) == "Target Optimization"
    window.workspace_combo.setCurrentIndex(2)
    assert window.workspace_stack.currentIndex() == 2
    assert hasattr(window, "start_target_button")
    assert hasattr(window, "target_mode_combo")
    assert window.target_thrust_spin.isEnabled()
    window.target_mode_combo.setCurrentIndex(4)
    assert not window.target_thrust_spin.isEnabled()
    assert window.target_torque_spin.isEnabled()
    app.processEvents()


def _opt_input(**overrides: object) -> TargetOptimizationInput:
    """Return a compact optimizer input for tests."""

    values = {
        "target_mode": "target_thrust_min_power",
        "target_thrust_N": 0.4,
        "blades": 2,
        "diameter_m": 0.254,
        "hub_diameter_m": 0.035,
        "rpm": 6500.0,
        "v_inf": 0.0,
        "elements": 10,
        "control_points": 4,
        "chord_min_ratio": 0.03,
        "chord_max_ratio": 0.18,
        "beta_min_deg": 4.0,
        "beta_max_deg": 35.0,
        "population_size": 6,
        "generations": 3,
        "random_seed": 4,
        "stop_generations": 10,
    }
    values.update(overrides)
    return TargetOptimizationInput(**values)


def _multi_re_polar() -> MultiRePolar:
    """Return a compact finite MultiRePolar for optimizer tests."""

    points = [
        PolarPoint(-8.0, -0.5, 0.035, -0.02),
        PolarPoint(-2.0, -0.1, 0.014, -0.02),
        PolarPoint(4.0, 0.45, 0.015, -0.03),
        PolarPoint(8.0, 0.82, 0.024, -0.04),
        PolarPoint(12.0, 1.0, 0.055, -0.05),
        PolarPoint(16.0, 0.9, 0.10, -0.06),
    ]
    multi = MultiRePolar()
    multi.add_table(50000.0, TablePolar(points))
    multi.add_table(250000.0, TablePolar([dataclasses.replace(point, cl=point.cl * 1.08, cd=point.cd * 0.95) for point in points]))
    return multi


def _assert_no_invalid_numbers(value: object) -> None:
    """Recursively assert no NaN or inf appears in dataclass results."""

    if dataclasses.is_dataclass(value):
        for field in dataclasses.fields(value):
            _assert_no_invalid_numbers(getattr(value, field.name))
    elif isinstance(value, dict):
        for item in value.values():
            _assert_no_invalid_numbers(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_no_invalid_numbers(item)
    elif isinstance(value, GeometryStation):
        _assert_no_invalid_numbers(dataclasses.astuple(value))
    elif isinstance(value, float):
        assert math.isfinite(value)
