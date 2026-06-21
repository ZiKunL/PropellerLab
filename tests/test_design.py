"""Tests for propeller twist design helpers."""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path

from propeller_lab.core.design import (
    DesignInput,
    DesignResult,
    apply_beta_offset,
    design_twist_with_target,
    find_alpha_design,
    find_alpha_max_ld,
)
from propeller_lab.core.export import export_design_station_csv
from propeller_lab.core.geometry import save_geometry_csv
from propeller_lab.core.models import GeometryStation, PolarPoint, PropellerInput
from propeller_lab.core.polar import GenericPolar, MultiRePolar, TablePolar


ROOT = Path(__file__).resolve().parents[1]


def test_default_design_generates_finite_geometry():
    """Default inputs should generate a finite twist design."""

    inp = _input()
    result = design_twist_with_target(inp, _design_input(inp))

    assert len(result.geometry) == inp.elements
    assert len(result.stations) == inp.elements
    assert result.analysis_result is not None
    assert math.isfinite(result.analysis_result.thrust_N)
    assert math.isfinite(result.analysis_result.torque_Nm)
    assert math.isfinite(result.analysis_result.power_W)
    assert all(math.isfinite(st.beta_deg) for st in result.geometry)
    assert all(math.isfinite(st.alpha_design_deg) for st in result.stations)
    _assert_no_invalid_numbers(result)


def test_find_alpha_max_ld_returns_finite_positive_drag():
    """Max Cl/Cd alpha selection should return a usable alpha point."""

    result = find_alpha_max_ld(GenericPolar(), reynolds=120000.0, mach=0.08)

    assert math.isfinite(float(result["alpha_deg"]))
    assert float(result["cd"]) > 0.0
    assert math.isfinite(float(result["ld"]))


def test_fixed_alpha_objective_returns_requested_alpha():
    """Fixed alpha objective should use the requested alpha."""

    design_input = DesignInput(
        rpm=8000.0,
        v_inf=5.0,
        rho=1.225,
        mu=1.81e-5,
        sound_speed=343.0,
        objective="fixed_alpha",
        fixed_alpha_deg=20.0,
        alpha_min_deg=-4.0,
        alpha_max_deg=12.0,
    )
    result = find_alpha_design(GenericPolar(), 100000.0, 0.05, math.radians(10.0), design_input)

    assert math.isclose(float(result["alpha_deg"]), 20.0, rel_tol=1e-12)


def test_target_thrust_mode_does_not_crash():
    """Target thrust mode should return a best-effort design."""

    inp = _input()
    result = design_twist_with_target(
        inp,
        _design_input(inp, target_type="thrust", target_value=0.5, max_iterations=3),
    )

    assert result.analysis_result is not None
    _assert_no_invalid_numbers(result)


def test_target_power_mode_does_not_crash():
    """Target power mode should return a best-effort design."""

    inp = _input()
    result = design_twist_with_target(
        inp,
        _design_input(inp, target_type="power", target_value=20.0, max_iterations=3),
    )

    assert result.analysis_result is not None
    _assert_no_invalid_numbers(result)


def test_design_exports_geometry_and_station_csv(tmp_path):
    """Designed geometry and design station CSV exports should work."""

    inp = _input()
    result = design_twist_with_target(inp, _design_input(inp))
    geometry_path = tmp_path / "designed_geometry.csv"
    stations_path = tmp_path / "design_stations.csv"

    save_geometry_csv(result.geometry, geometry_path)
    export_design_station_csv(result, stations_path)

    assert geometry_path.exists()
    assert stations_path.exists()
    assert geometry_path.stat().st_size > 0
    assert stations_path.stat().st_size > 0


def test_apply_beta_offset_respects_constraints():
    """Global beta offset should clamp to requested beta bounds."""

    geometry = [
        GeometryStation(0.3, 0.1, 5.0),
        GeometryStation(0.6, 0.1, 20.0),
        GeometryStation(0.9, 0.1, 55.0),
    ]
    offset = apply_beta_offset(geometry, 20.0, beta_min_deg=0.0, beta_max_deg=60.0)

    assert [st.beta_deg for st in offset] == [25.0, 40.0, 60.0]


def test_low_speed_static_design_does_not_crash():
    """Static design should use existing low-speed analysis safely."""

    inp = _input(v_inf=0.0)
    result = design_twist_with_target(inp, _design_input(inp, v_inf=0.0))

    assert result.analysis_result is not None
    _assert_no_invalid_numbers(result)


def test_sample_table_polar_works_with_design_mode():
    """Imported table polar should work with design mode."""

    inp = _input(v_inf=8.0)
    polar = TablePolar.from_csv(ROOT / "examples" / "sample_polar.csv")
    result = design_twist_with_target(inp, _design_input(inp, v_inf=8.0), polar=polar)

    assert result.analysis_result is not None
    _assert_no_invalid_numbers(result)


def test_multi_re_polar_works_with_design_mode():
    """MultiRePolar should work with design mode."""

    points_low = [
        PolarPoint(-5.0, -0.3, 0.03, -0.02),
        PolarPoint(0.0, 0.0, 0.012, -0.03),
        PolarPoint(5.0, 0.5, 0.018, -0.04),
        PolarPoint(10.0, 0.9, 0.04, -0.05),
        PolarPoint(15.0, 1.0, 0.09, -0.06),
    ]
    points_high = [dataclasses.replace(point, cl=point.cl * 1.1, cd=point.cd * 0.95) for point in points_low]
    polar = MultiRePolar()
    polar.add_table(50000.0, TablePolar(points_low))
    polar.add_table(300000.0, TablePolar(points_high))

    inp = _input(v_inf=6.0)
    result = design_twist_with_target(inp, _design_input(inp, v_inf=6.0), polar=polar)

    assert result.analysis_result is not None
    _assert_no_invalid_numbers(result)


def test_main_window_workspace_smoke():
    """MainWindow should expose workspaces and legacy attributes."""

    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from propeller_lab.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert window.workspace_combo.count() == 3
    assert window.workspace_combo.itemText(0) == "Base Calculate"
    assert window.workspace_combo.itemText(1) == "Optimization Design"
    assert window.workspace_combo.itemText(2) == "Target Optimization"
    window.workspace_combo.setCurrentIndex(1)
    assert window.workspace_stack.currentIndex() == 1
    for attr in (
        "rpm_spin",
        "root_chord_spin",
        "tip_chord_spin",
        "re_min_spin",
        "re_max_spin",
        "xfoil_re_spin",
        "auto_re_range_check",
    ):
        assert hasattr(window, attr)
    app.processEvents()


def test_main_window_design_controls_lock_irrelevant_parameters():
    """Optimization Design controls should lock irrelevant inputs by mode."""

    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from propeller_lab.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert not window.design_target_type_combo.isEnabled()
    assert not window.design_target_value_spin.isEnabled()
    assert not window.design_allow_beta_offset_check.isEnabled()
    assert not window.design_fixed_alpha_spin.isEnabled()
    assert window.design_alpha_min_spin.isEnabled()
    assert window.design_stall_margin_spin.isEnabled()
    assert window.design_max_cl_fraction_spin.isEnabled()

    window.design_method_combo.setCurrentIndex(1)
    assert window.design_target_type_combo.currentData() == "thrust"
    assert not window.design_target_type_combo.isEnabled()
    assert window.design_target_value_spin.isEnabled()
    assert window.design_allow_beta_offset_check.isEnabled()

    window.design_alpha_objective_combo.setCurrentIndex(1)
    assert window.design_alpha_min_spin.isEnabled()
    assert window.design_alpha_max_spin.isEnabled()
    assert window.design_alpha_step_spin.isEnabled()
    assert not window.design_stall_margin_spin.isEnabled()
    assert not window.design_max_cl_fraction_spin.isEnabled()

    window.design_alpha_objective_combo.setCurrentIndex(2)
    assert window.design_fixed_alpha_spin.isEnabled()
    assert not window.design_alpha_min_spin.isEnabled()
    assert not window.design_alpha_max_spin.isEnabled()
    assert not window.design_alpha_step_spin.isEnabled()
    app.processEvents()


def test_main_window_xfoil_source_controls_and_save_name(tmp_path):
    """XFOIL source controls and default polar file name should follow the source."""

    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from propeller_lab.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    window.xfoil_display_reynolds = 100000.0
    assert window.naca_edit.isEnabled()
    assert not window.dat_path_edit.isEnabled()
    assert window._default_xfoil_polar_filename() == "naca4412_Re100000.csv"

    dat_path = tmp_path / "Clark Y.dat"
    dat_path.write_text("Clark Y\n", encoding="utf-8")
    window.dat_path_edit.setText(str(dat_path))
    window.airfoil_source_combo.setCurrentIndex(1)
    window.xfoil_display_reynolds = 152345.6

    assert not window.naca_edit.isEnabled()
    assert window.dat_path_edit.isEnabled()
    assert window.dat_browse_button.isEnabled()
    assert window._default_xfoil_polar_filename() == "clark_y_Re152346.csv"
    app.processEvents()


def _input(v_inf: float = 0.0) -> PropellerInput:
    """Return a compact propeller input for design tests."""

    return PropellerInput(elements=12, v_inf=v_inf, calculation_mode="auto")


def _design_input(
    inp: PropellerInput,
    v_inf: float | None = None,
    target_type: str = "none",
    target_value: float = 0.0,
    max_iterations: int = 5,
) -> DesignInput:
    """Return a compact design input for tests."""

    return DesignInput(
        rpm=inp.rpm,
        v_inf=inp.v_inf if v_inf is None else v_inf,
        rho=inp.rho,
        mu=inp.mu,
        sound_speed=inp.sound_speed,
        target_type=target_type,
        target_value=target_value,
        max_iterations=max_iterations,
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
    elif isinstance(value, float):
        assert math.isfinite(value)
