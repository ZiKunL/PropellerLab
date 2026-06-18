"""Shared UI state for PropellerLab workspaces."""

from __future__ import annotations

from dataclasses import dataclass

from propeller_lab.core.design import DesignResult
from propeller_lab.core.models import GeometryStation, PropellerInput, PropellerResult
from propeller_lab.core.polar import AirfoilPolar


@dataclass
class AppState:
    """Shared application state across top-level workspaces."""

    prop_input: PropellerInput
    current_geometry: list[GeometryStation] | None = None
    current_polar: AirfoilPolar | None = None
    xfoil_cached_polar: AirfoilPolar | None = None
    last_analysis_result: PropellerResult | None = None
    last_design_result: DesignResult | None = None
