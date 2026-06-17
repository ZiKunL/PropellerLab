"""Regression tests for low-speed and static thrust stability."""

from __future__ import annotations

from dataclasses import fields
import math

from propeller_lab.core.bemt import calculate_propeller
from propeller_lab.core.models import PropellerInput, StationResult


def test_auto_low_speed_cases_succeed():
    """Auto mode should work from static thrust through low speed."""

    for v_inf in (0.0, 0.1, 0.5, 1.0):
        result = calculate_propeller(PropellerInput(calculation_mode="auto", v_inf=v_inf))
        assert result.diagnostics["actual_mode"] == "bemt_hover_dimensional"
        assert_result_is_finite(result)


def test_old_bemt_phi_static_does_not_crash():
    """Old bemt_phi mode should remain backward compatible."""

    result = calculate_propeller(PropellerInput(calculation_mode="bemt_phi", v_inf=0.0))
    assert result.diagnostics["requested_mode"] == "bemt_phi"
    assert result.diagnostics["actual_mode"] == "bemt_hover_dimensional"
    assert_result_is_finite(result)


def test_explicit_forward_static_uses_low_speed_warning():
    """Explicit forward phi-BEMT at static thrust should be replaced safely."""

    result = calculate_propeller(PropellerInput(calculation_mode="bemt_phi_forward", v_inf=0.0))
    assert result.diagnostics["actual_mode"] == "bemt_hover_dimensional"
    assert "Low-speed condition: forward-flight phi-BEMT was replaced by dimensional low-speed BEMT." in result.warnings
    assert_result_is_finite(result)


def test_explicit_hover_dimensional_static_succeeds():
    """The dimensional low-speed solver should work at static thrust."""

    result = calculate_propeller(PropellerInput(calculation_mode="bemt_hover_dimensional", v_inf=0.0))
    assert result.diagnostics["requested_mode"] == "bemt_hover_dimensional"
    assert result.diagnostics["actual_mode"] == "bemt_hover_dimensional"
    assert_result_is_finite(result)


def test_static_thrust_and_power_increase_with_rpm():
    """Static thrust and shaft power should increase with RPM."""

    low = calculate_propeller(PropellerInput(calculation_mode="auto", v_inf=0.0, rpm=6000.0))
    high = calculate_propeller(PropellerInput(calculation_mode="auto", v_inf=0.0, rpm=9000.0))
    assert high.thrust_N > low.thrust_N
    assert high.power_W > low.power_W
    assert_result_is_finite(low)
    assert_result_is_finite(high)


def test_diagnostics_include_required_solver_metrics():
    """Diagnostics should include requested mode, actual mode, J, and mu_adv."""

    result = calculate_propeller(PropellerInput(calculation_mode="auto", v_inf=0.0))
    for key in ("requested_mode", "actual_mode", "J", "mu_adv"):
        assert key in result.diagnostics
    assert_result_is_finite(result)


def assert_result_is_finite(result) -> None:
    """Assert no result or station numeric field contains NaN or infinity."""

    for value in (result.thrust_N, result.torque_Nm, result.power_W, result.eta, result.ct, result.cq, result.cp):
        assert math.isfinite(value)
    for value in result.diagnostics.values():
        if isinstance(value, float):
            assert math.isfinite(value)
    for station in result.stations:
        for field in fields(StationResult):
            value = getattr(station, field.name)
            if isinstance(value, float):
                assert math.isfinite(value)
