"""Tests for target optimization helpers."""

from __future__ import annotations

import dataclasses
import math
import random
from pathlib import Path

import pytest

from propeller_lab.core.export import export_optimization_history_csv, export_optimization_summary_csv
from propeller_lab.core.geometry import save_geometry_csv
from propeller_lab.core.bemt import calculate_propeller
from propeller_lab.core.models import GeometryStation, PolarPoint, PropellerInput
from propeller_lab.core.optimizer import (
    TargetOptimizationInput,
    evaluate_candidate,
    estimate_optimization_reynolds_range,
    geometry_to_genome,
    genome_to_geometry,
    random_genome,
    run_genetic_algorithm,
    run_random_search,
    run_target_optimization,
)
from propeller_lab.core.polar import MultiAirfoilPolar, MultiRePolar, TablePolar


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


def test_target_optimizer_assigns_airfoil_ids_and_estimates_re_range():
    """Target geometry should use root-to-tip airfoil ids and estimate Re bounds."""

    opt_input = _opt_input(airfoil_ids=("4412", "2412", "0012"), elements=12)
    geometry = genome_to_geometry(random_genome(opt_input, random.Random(5)), opt_input)
    estimate = estimate_optimization_reynolds_range(opt_input)

    assert {station.airfoil_id for station in geometry} == {"naca4412", "naca2412", "naca0012"}
    assert estimate["re_min"] > 0.0
    assert estimate["re_max"] > estimate["re_min"]


def test_bemt_uses_station_airfoil_ids_with_multi_airfoil_polar():
    """BEMT station lookup should use GeometryStation.airfoil_id."""

    low = _constant_table_polar(cl=0.2)
    high = _constant_table_polar(cl=1.1)
    polar = MultiAirfoilPolar()
    polar.add_airfoil("naca1111", low)
    polar.add_airfoil("naca2222", high)
    geometry = [
        GeometryStation(0.35, 0.10, 20.0, "naca1111"),
        GeometryStation(0.75, 0.10, 20.0, "naca2222"),
    ]

    result = calculate_propeller(PropellerInput(elements=2, v_inf=8.0, calculation_mode="simple"), polar=polar, geometry=geometry)

    assert math.isclose(result.stations[0].cl, 0.2, rel_tol=1e-12)
    assert math.isclose(result.stations[1].cl, 1.1, rel_tol=1e-12)


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


def test_multi_airfoil_polar_works_with_optimizer():
    """Optimizer should work with a MultiAirfoilPolar and assigned airfoil ids."""

    polar = MultiAirfoilPolar()
    polar.add_airfoil("naca4412", _multi_re_polar())
    polar.add_airfoil("naca2412", _multi_re_polar(cl_scale=0.95))
    result = run_target_optimization(
        _opt_input(optimizer_method="random_search", airfoil_ids=("4412", "2412")),
        polar=polar,
    )

    assert {station.airfoil_id for station in result.best_geometry} == {"naca4412", "naca2412"}
    assert result.best_analysis is not None
    _assert_no_invalid_numbers(result)


def test_airfoil_comparison_worker_runs_uniform_candidates():
    """Uniform-airfoil comparison should optimize every candidate airfoil separately."""

    from propeller_lab.ui.optimization_worker import AirfoilComparisonWorker, TargetAirfoilComparisonResult

    polar = MultiAirfoilPolar()
    polar.add_airfoil("naca4412", _multi_re_polar())
    polar.add_airfoil("naca4612", _multi_re_polar(cl_scale=1.04))
    worker = AirfoilComparisonWorker(
        _opt_input(optimizer_method="random_search", airfoil_ids=("4412", "4612")),
        polar,
        None,
        ["4412", "4612"],
    )
    finished: list[TargetAirfoilComparisonResult] = []
    failed: list[str] = []
    worker.finished.connect(finished.append)
    worker.failed.connect(failed.append)

    worker.run()

    assert failed == []
    assert len(finished) == 1
    result = finished[0]
    assert {entry.airfoil_id for entry in result.entries} == {"naca4412", "naca4612"}
    for entry in result.entries:
        assert {station.airfoil_id for station in entry.result.best_geometry} == {entry.airfoil_id}
        _assert_no_invalid_numbers(entry.result)


def test_target_airfoil_xfoil_worker_accepts_mixed_sources(monkeypatch, tmp_path):
    """Target XFOIL preprocessing should allow NACA and DAT candidates together."""

    from propeller_lab.core.xfoil_runner import XfoilPolarPoint, XfoilRunResult
    from propeller_lab.ui import optimization_worker as worker_module
    from propeller_lab.ui.optimization_worker import TargetAirfoilXfoilItem, TargetAirfoilXfoilResult, TargetAirfoilXfoilWorker

    calls: list[tuple[str, str]] = []

    class FakeRunner:
        def __init__(self, _xfoil_path: str, _timeout: float) -> None:
            pass

        def run_naca_alpha_sweep(self, naca_code: str, *_args: object) -> XfoilRunResult:
            calls.append(("naca", naca_code))
            return _xfoil_run_result()

        def run_dat_alpha_sweep(self, dat_path: str, *_args: object) -> XfoilRunResult:
            calls.append(("dat", Path(dat_path).name))
            return _xfoil_run_result()

    monkeypatch.setattr(worker_module, "XfoilRunner", FakeRunner)
    dat_path = tmp_path / "Clark Y.dat"
    dat_path.write_text("Clark Y\n1 0\n0 0\n", encoding="utf-8")
    worker = TargetAirfoilXfoilWorker(
        "xfoil",
        [TargetAirfoilXfoilItem("naca", "4412"), TargetAirfoilXfoilItem("dat", str(dat_path))],
        [80000.0],
        0.0,
        -2.0,
        2.0,
        1.0,
        80,
        120,
        10.0,
        source_type="mixed",
    )
    finished: list[TargetAirfoilXfoilResult] = []
    failed: list[str] = []
    worker.finished.connect(finished.append)
    worker.failed.connect(failed.append)

    worker.run()

    assert failed == []
    assert calls == [("naca", "4412"), ("dat", "Clark Y.dat")]
    assert len(finished) == 1
    assert finished[0].airfoil_ids == ["naca4412", "clark_y"]


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


def test_main_window_target_optimization_workspace_smoke(tmp_path):
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
    assert hasattr(window, "target_airfoil_codes_edit")
    assert hasattr(window, "target_airfoil_mode_combo")
    assert hasattr(window, "target_airfoil_source_combo")
    assert hasattr(window, "target_dat_paths_edit")
    assert hasattr(window, "target_build_xfoil_button")
    assert hasattr(window, "target_airfoil_comparison_table")
    assert window.target_thrust_spin.isEnabled()
    window.target_airfoil_codes_edit.setText("4412, 2412")
    assert window._target_airfoil_ids() == ["naca4412", "naca2412"]
    window.target_airfoil_mode_combo.setCurrentIndex(1)
    assert window._target_airfoil_mode() == "compare_uniform"
    assert not window.target_airfoil_source_combo.isEnabled()
    assert window.target_airfoil_codes_edit.isEnabled()
    assert window.target_dat_paths_edit.isEnabled()
    root_dat = tmp_path / "Root Airfoil.dat"
    tip_dat = tmp_path / "tip-airfoil.dat"
    root_dat.write_text("Root\n0 0\n1 0\n", encoding="utf-8")
    tip_dat.write_text("Tip\n0 0\n1 0\n", encoding="utf-8")
    window.target_dat_paths_edit.setPlainText(f"{root_dat}\n{tip_dat}")
    assert window._target_airfoil_ids() == ["naca4412", "naca2412", "root_airfoil", "tip-airfoil"]
    mixed_items = window._target_airfoil_items()
    assert [(item.source_type, item.value) for item in mixed_items] == [
        ("naca", "naca4412"),
        ("naca", "naca2412"),
        ("dat", str(root_dat)),
        ("dat", str(tip_dat)),
    ]
    window.target_airfoil_mode_combo.setCurrentIndex(0)
    window.target_airfoil_source_combo.setCurrentIndex(1)
    assert window._target_airfoil_ids() == ["root_airfoil", "tip-airfoil"]
    assert [(item.source_type, item.value) for item in window._target_airfoil_items()] == [
        ("dat", str(root_dat)),
        ("dat", str(tip_dat)),
    ]
    window.target_airfoil_source_combo.setCurrentIndex(0)
    window.estimate_target_optimization_re_range()
    assert window.target_re_min_spin.value() > 0.0
    assert window.target_re_max_spin.value() > window.target_re_min_spin.value()
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


def _multi_re_polar(cl_scale: float = 1.0) -> MultiRePolar:
    """Return a compact finite MultiRePolar for optimizer tests."""

    points = [
        PolarPoint(-8.0, -0.5 * cl_scale, 0.035, -0.02),
        PolarPoint(-2.0, -0.1 * cl_scale, 0.014, -0.02),
        PolarPoint(4.0, 0.45 * cl_scale, 0.015, -0.03),
        PolarPoint(8.0, 0.82 * cl_scale, 0.024, -0.04),
        PolarPoint(12.0, 1.0 * cl_scale, 0.055, -0.05),
        PolarPoint(16.0, 0.9 * cl_scale, 0.10, -0.06),
    ]
    multi = MultiRePolar()
    multi.add_table(50000.0, TablePolar(points))
    multi.add_table(250000.0, TablePolar([dataclasses.replace(point, cl=point.cl * 1.08, cd=point.cd * 0.95) for point in points]))
    return multi


def _xfoil_run_result():
    """Return a compact successful XFOIL result for worker tests."""

    from propeller_lab.core.xfoil_runner import XfoilPolarPoint, XfoilRunResult

    points = [
        XfoilPolarPoint(-2.0, -0.1, 0.02, 0.015, -0.02, None, None),
        XfoilPolarPoint(-1.0, 0.0, 0.018, 0.014, -0.02, None, None),
        XfoilPolarPoint(0.0, 0.1, 0.017, 0.013, -0.02, None, None),
        XfoilPolarPoint(1.0, 0.2, 0.018, 0.014, -0.02, None, None),
        XfoilPolarPoint(2.0, 0.3, 0.02, 0.015, -0.02, None, None),
    ]
    return XfoilRunResult(points, "", "", [], None, None, {80000.0: points})


def _constant_table_polar(cl: float) -> TablePolar:
    """Return a polar table with constant coefficients across alpha."""

    return TablePolar(
        [
            PolarPoint(-90.0, cl, 0.02, -0.03),
            PolarPoint(90.0, cl, 0.02, -0.03),
        ]
    )


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
