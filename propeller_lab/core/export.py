"""CSV export helpers."""

from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .design import DesignResult
from .models import PropellerResult
from .optimizer import TargetOptimizationResult


def export_station_csv(result: PropellerResult, path: str | Path) -> None:
    """Export all station results to CSV."""

    fieldnames = [
        "r_m",
        "r_over_R",
        "dr_m",
        "chord_m",
        "beta_deg",
        "phi_deg",
        "alpha_deg",
        "reynolds",
        "mach",
        "cl",
        "cd",
        "cm",
        "vi_mps",
        "vt_mps",
        "tip_loss_F",
        "dT_dr",
        "dQ_dr",
        "dL_dr",
        "dD_dr",
        "warning",
    ]
    csv_path = Path(path)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for station in result.stations:
            writer.writerow(asdict(station))


def export_summary_csv(result: PropellerResult, path: str | Path) -> None:
    """Export inputs, integrated performance, and warnings to CSV."""

    csv_path = Path(path)
    rows: list[dict[str, Any]] = []
    for key, value in asdict(result.input).items():
        rows.append({"section": "input", "name": key, "value": value})
    for key in ("thrust_N", "torque_Nm", "power_W", "eta", "ct", "cq", "cp"):
        rows.append({"section": "result", "name": key, "value": getattr(result, key)})
    for key, value in result.diagnostics.items():
        rows.append({"section": "diagnostic", "name": key, "value": value})
    for idx, warning in enumerate(result.warnings, start=1):
        rows.append({"section": "warning", "name": f"warning_{idx}", "value": warning})
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["section", "name", "value"])
        writer.writeheader()
        writer.writerows(rows)


def export_scan_csv(scan_rows: list[dict[str, Any]], path: str | Path) -> None:
    """Export RPM scan rows to CSV."""

    fieldnames = ["RPM", "T", "Q", "P", "eta", "CT", "CQ", "CP", "warnings_count"]
    csv_path = Path(path)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in scan_rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def export_design_station_csv(design_result: DesignResult, path: str | Path) -> None:
    """Export design station rows to CSV."""

    fieldnames = [
        "r_over_R",
        "r_m",
        "chord_over_R",
        "chord_m",
        "phi_deg",
        "alpha_design_deg",
        "beta_deg",
        "reynolds",
        "mach",
        "cl",
        "cd",
        "cm",
        "ld",
        "objective_value",
        "warning",
    ]
    csv_path = Path(path)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for station in design_result.stations:
            writer.writerow({name: getattr(station, name) for name in fieldnames})


def export_optimization_history_csv(result: TargetOptimizationResult, path: str | Path) -> None:
    """Export target optimization history rows to CSV."""

    fieldnames = [
        "generation",
        "evaluations",
        "best_fitness",
        "best_thrust_N",
        "best_torque_Nm",
        "best_power_W",
        "best_eta",
        "best_ct",
        "best_cq",
        "best_cp",
        "target_error_fraction",
        "stall_fraction",
        "low_re_fraction",
        "max_mach",
    ]
    csv_path = Path(path)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in result.history:
            writer.writerow({name: getattr(row, name) for name in fieldnames})


def export_optimization_summary_csv(result: TargetOptimizationResult, path: str | Path) -> None:
    """Export target optimization input, result, diagnostics, and warnings."""

    rows: list[dict[str, Any]] = []
    for key, value in asdict(result.input).items():
        rows.append({"section": "input", "name": key, "value": value})
    analysis = result.best_analysis
    for key in ("thrust_N", "torque_Nm", "power_W", "eta", "ct", "cq", "cp"):
        rows.append({"section": "best_result", "name": key, "value": getattr(analysis, key)})
    rows.append({"section": "best_result", "name": "best_fitness", "value": result.best_fitness})
    rows.append({"section": "best_result", "name": "target_error_fraction", "value": result.target_error_fraction})
    rows.append({"section": "best_result", "name": "evaluations", "value": result.evaluations})
    for key, value in result.diagnostics.items():
        rows.append({"section": "diagnostic", "name": key, "value": value})
    for idx, warning in enumerate(result.warnings, start=1):
        rows.append({"section": "warning", "name": f"warning_{idx}", "value": warning})
    csv_path = Path(path)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["section", "name", "value"])
        writer.writeheader()
        writer.writerows(rows)
