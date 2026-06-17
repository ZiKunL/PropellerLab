"""Propeller geometry generation and CSV handling."""

from __future__ import annotations

import csv
import math
from pathlib import Path

from .models import GeometryStation, PropellerInput
from .numerics import is_finite_number


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
    dr = (r_end - r_start) / inp.elements
    stations: list[GeometryStation] = []
    for i in range(inp.elements):
        r = r_start + (i + 0.5) * dr
        t = (r - r_start) / max(r_end - r_start, 1e-30)
        chord_over_R = inp.root_chord_ratio + t * (inp.tip_chord_ratio - inp.root_chord_ratio)
        beta_deg = math.degrees(math.atan(inp.pitch_m / max(2.0 * math.pi * r, 1e-30)))
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
