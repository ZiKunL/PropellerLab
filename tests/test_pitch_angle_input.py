"""Tests for pitch angle input mode."""

from __future__ import annotations

import math

from propeller_lab.core.bemt import calculate_propeller
from propeller_lab.core.geometry import (
    effective_pitch_m,
    generate_pitch_geometry,
    pitch_angle_from_pitch,
    pitch_from_pitch_angle,
)
from propeller_lab.core.models import PropellerInput, StationResult


def test_pitch_angle_converts_to_pitch_at_70_percent_radius():
    """Pitch angle mode should compute the equivalent pitch in meters."""

    base = PropellerInput()
    angle = pitch_angle_from_pitch(base.diameter_m, base.pitch_m)
    converted_pitch = pitch_from_pitch_angle(base.diameter_m, angle)
    assert math.isclose(converted_pitch, base.pitch_m, rel_tol=1e-12, abs_tol=1e-12)


def test_pitch_angle_mode_matches_pitch_geometry():
    """Equivalent pitch and pitch angle inputs should generate the same beta values."""

    base = PropellerInput()
    angle = pitch_angle_from_pitch(base.diameter_m, base.pitch_m)
    by_pitch = generate_pitch_geometry(base)
    by_angle = generate_pitch_geometry(
        PropellerInput(
            pitch_input_mode="pitch_angle",
            pitch_angle_deg=angle,
            pitch_m=0.0,
        )
    )
    assert math.isclose(effective_pitch_m(PropellerInput(pitch_input_mode="pitch_angle", pitch_angle_deg=angle)), base.pitch_m)
    assert len(by_pitch) == len(by_angle)
    for left, right in zip(by_pitch, by_angle):
        assert math.isclose(left.beta_deg, right.beta_deg, rel_tol=1e-12, abs_tol=1e-12)


def test_pitch_angle_mode_calculates_finite_result():
    """Pitch angle mode should run the full propeller calculation."""

    inp = PropellerInput(pitch_input_mode="pitch_angle", pitch_angle_deg=12.0)
    result = calculate_propeller(inp)
    for value in (result.thrust_N, result.torque_Nm, result.power_W, result.eta, result.ct, result.cq, result.cp):
        assert math.isfinite(value)
    for station in result.stations:
        for field in StationResult.__dataclass_fields__:
            value = getattr(station, field)
            if isinstance(value, float):
                assert math.isfinite(value)
