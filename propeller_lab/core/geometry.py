"""Propeller geometry generation and CSV handling."""

from __future__ import annotations

import csv
import math
from pathlib import Path

from .models import GeometryStation, PropellerInput
from .numerics import finite_or_default, is_finite_number, safe_div

PITCH_ANGLE_REFERENCE_R_OVER_R = 0.70


def generate_pitch_geometry(inp: PropellerInput) -> list[GeometryStation]:
    """Generate blade stations from diameter, hub diameter, pitch, and chords."""

    if inp.elements < 1:
        raise ValueError("elements must be at least 1.")
    if inp.diameter_m <= 0.0:
        raise ValueError("diameter_m must be positive.")
    r_tip = inp.diameter_m / 2.0
    r_start = max(inp.hub_diameter_m / 2.0, 0.20 * r_tip)
    r_end = 0.98 * r_tip
    if r_start >= r_end:
        raise ValueError("hub diameter is too large for the propeller diameter.")
    pitch_m = effective_pitch_m(inp)
    dr = (r_end - r_start) / inp.elements
    stations: list[GeometryStation] = []
    for i in range(inp.elements):
        r = r_start + (i + 0.5) * dr
        t = (r - r_start) / max(r_end - r_start, 1e-30)
        chord_over_R = inp.root_chord_ratio + t * (inp.tip_chord_ratio - inp.root_chord_ratio)
        beta_deg = math.degrees(math.atan(pitch_m / max(2.0 * math.pi * r, 1e-30)))
        stations.append(
            GeometryStation(
                r_over_R=r / r_tip,
                chord_over_R=chord_over_R,
                beta_deg=beta_deg,
                airfoil_id="generic",
            )
        )
    validate_geometry(stations)
    return stations


def effective_pitch_m(inp: PropellerInput) -> float:
    """Return the pitch in meters selected by the pitch input mode."""

    if inp.pitch_input_mode == "pitch":
        return inp.pitch_m
    if inp.pitch_input_mode == "pitch_angle":
        return pitch_from_pitch_angle(inp.diameter_m, inp.pitch_angle_deg)
    raise ValueError(f"Unknown pitch_input_mode: {inp.pitch_input_mode}")


def pitch_from_pitch_angle(diameter_m: float, pitch_angle_deg: float) -> float:
    """Convert the 70 percent radius pitch angle to pitch in meters."""

    if diameter_m <= 0.0:
        raise ValueError("diameter_m must be positive.")
    if not is_finite_number(pitch_angle_deg):
        raise ValueError("pitch_angle_deg must be finite.")
    angle_rad = math.radians(pitch_angle_deg)
    radius_m = diameter_m / 2.0
    r_ref = PITCH_ANGLE_REFERENCE_R_OVER_R * radius_m
    return 2.0 * math.pi * r_ref * math.tan(angle_rad)


def pitch_angle_from_pitch(diameter_m: float, pitch_m: float) -> float:
    """Convert pitch in meters to pitch angle at 70 percent radius."""

    if diameter_m <= 0.0:
        raise ValueError("diameter_m must be positive.")
    radius_m = diameter_m / 2.0
    r_ref = PITCH_ANGLE_REFERENCE_R_OVER_R * radius_m
    return math.degrees(math.atan(pitch_m / max(2.0 * math.pi * r_ref, 1e-30)))


def estimate_reynolds_range(
    inp: PropellerInput,
    stations: list[GeometryStation] | None = None,
) -> dict[str, float]:
    """Estimate the station Reynolds number range from geometry and RPM."""

    geometry = stations if stations is not None else generate_pitch_geometry(inp)
    validate_geometry(geometry)
    radius_m = inp.diameter_m / 2.0
    omega = 2.0 * math.pi * inp.rpm / 60.0
    values: list[float] = []
    for station in geometry:
        r_m = station.r_over_R * radius_m
        chord_m = station.chord_over_R * radius_m
        wt = omega * r_m
        speed = math.hypot(inp.v_inf, wt)
        reynolds = safe_div(inp.rho * speed * chord_m, inp.mu)
        if is_finite_number(reynolds) and reynolds > 0.0:
            values.append(reynolds)
    if not values:
        raise ValueError("Could not estimate Reynolds range from the current inputs.")
    return {
        "re_min": finite_or_default(min(values)),
        "re_max": finite_or_default(max(values)),
        "re_root": finite_or_default(values[0]),
        "re_tip": finite_or_default(values[-1]),
    }


def representative_reynolds_values(re_min: float, re_max: float, count: int) -> list[float]:
    """Return sorted representative Reynolds numbers for XFOIL sweeps."""

    if count < 1:
        raise ValueError("Reynolds count must be at least 1.")
    if re_min <= 0.0 or re_max <= 0.0:
        raise ValueError("Reynolds bounds must be positive.")
    lo = min(re_min, re_max)
    hi = max(re_min, re_max)
    if count == 1 or abs(hi - lo) < 1e-9:
        return [finite_or_default(0.5 * (lo + hi))]
    if hi / lo > 2.5:
        log_lo = math.log(lo)
        log_hi = math.log(hi)
        values = [math.exp(log_lo + i * (log_hi - log_lo) / (count - 1)) for i in range(count)]
    else:
        values = [lo + i * (hi - lo) / (count - 1) for i in range(count)]
    return _unique_positive_values(values)


def _unique_positive_values(values: list[float]) -> list[float]:
    """Return positive finite values without near duplicates."""

    out: list[float] = []
    for value in values:
        clean = finite_or_default(value)
        if clean <= 0.0:
            continue
        if not any(abs(clean - existing) <= max(1.0, 1e-6 * existing) for existing in out):
            out.append(clean)
    return sorted(out)


def load_geometry_csv(path: str | Path) -> list[GeometryStation]:
    """Load radial blade geometry from CSV."""

    stations: list[GeometryStation] = []
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            normalized = {str(k).strip().lower(): v for k, v in row.items() if k is not None}
            try:
                stations.append(
                    GeometryStation(
                        r_over_R=float(normalized["r_over_r"]),
                        chord_over_R=float(normalized["chord_over_r"]),
                        beta_deg=float(normalized["beta_deg"]),
                        airfoil_id=str(normalized.get("airfoil_id") or "generic"),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid geometry CSV row: {row}") from exc
    validate_geometry(stations)
    return stations


def save_geometry_csv(stations: list[GeometryStation], path: str | Path) -> None:
    """Save radial blade geometry to CSV."""

    validate_geometry(stations)
    csv_path = Path(path)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["r_over_R", "chord_over_R", "beta_deg", "airfoil_id"],
        )
        writer.writeheader()
        for station in stations:
            writer.writerow(
                {
                    "r_over_R": station.r_over_R,
                    "chord_over_R": station.chord_over_R,
                    "beta_deg": station.beta_deg,
                    "airfoil_id": station.airfoil_id,
                }
            )


def validate_geometry(stations: list[GeometryStation]) -> None:
    """Validate radial geometry station ordering and values."""

    if not stations:
        raise ValueError("Geometry must contain at least one station.")
    previous = -1.0
    for station in stations:
        if not (0.0 < station.r_over_R <= 1.0):
            raise ValueError("r_over_R must satisfy 0 < r_over_R <= 1.")
        if station.r_over_R <= previous:
            raise ValueError("r_over_R must be strictly increasing.")
        if station.chord_over_R <= 0.0:
            raise ValueError("chord_over_R must be positive.")
        if not is_finite_number(station.beta_deg):
            raise ValueError("beta_deg must be finite.")
        previous = station.r_over_R
