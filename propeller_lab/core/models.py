"""Data models used by the propeller calculation core."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PropellerInput:
    """Input parameters for a propeller calculation."""

    blades: int = 2
    diameter_m: float = 0.254
    hub_diameter_m: float = 0.035
    pitch_m: float = 0.1143
    root_chord_ratio: float = 0.16
    tip_chord_ratio: float = 0.06
    rpm: float = 8000.0
    v_inf: float = 0.0
    rho: float = 1.225
    mu: float = 1.81e-5
    sound_speed: float = 343.0
    elements: int = 50
    calculation_mode: str = "auto"
    polar_mode: str = "generic"
    use_tip_loss: bool = True
    use_hub_loss: bool = True


@dataclass
class GeometryStation:
    """Blade geometry at one radial station."""

    r_over_R: float
    chord_over_R: float
    beta_deg: float
    airfoil_id: str = "generic"


@dataclass
class OperatingPoint:
    """Operating-point properties."""

    rpm: float
    v_inf: float
    rho: float
    mu: float
    sound_speed: float


@dataclass
class PolarPoint:
    """Airfoil polar data at one angle of attack."""

    alpha_deg: float
    cl: float
    cd: float
    cm: float = 0.0
    cdp: float | None = None
    xtr_top: float | None = None
    xtr_bottom: float | None = None


@dataclass
class StationResult:
    """Calculated result at one radial station."""

    r_m: float
    r_over_R: float
    dr_m: float
    chord_m: float
    beta_deg: float
    phi_deg: float
    alpha_deg: float
    reynolds: float
    mach: float
    cl: float
    cd: float
    cm: float
    vi_mps: float
    vt_mps: float
    tip_loss_F: float
    dT_dr: float
    dQ_dr: float
    dL_dr: float
    dD_dr: float
    warning: str = ""


@dataclass
class PropellerResult:
    """Integrated propeller result."""

    input: PropellerInput
    thrust_N: float
    torque_Nm: float
    power_W: float
    eta: float
    ct: float
    cq: float
    cp: float
    stations: list[StationResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, float | str] = field(default_factory=dict)
