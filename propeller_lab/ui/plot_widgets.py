"""Matplotlib widgets used by the desktop UI."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "propeller_lab_mpl"))

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtWidgets import QVBoxLayout, QWidget

from propeller_lab.core.design import DesignStationResult
from propeller_lab.core.models import GeometryStation, PropellerResult, StationResult
from propeller_lab.core.optimizer import OptimizationHistoryRow
from propeller_lab.core.xfoil_runner import XfoilPolarPoint


class _BasePlotWidget(QWidget):
    """Common Matplotlib canvas wrapper."""

    def __init__(self) -> None:
        super().__init__()
        self.figure = Figure(figsize=(6.0, 4.0), tight_layout=True)
        self.canvas = FigureCanvas(self.figure)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

    def _redraw(self) -> None:
        self.figure.tight_layout()
        self.canvas.draw_idle()


class LoadPlotWidget(_BasePlotWidget):
    """Plot radial load distributions."""

    def update_plot(self, stations: list[StationResult]) -> None:
        """Update dT/dr and dQ/dr against radius ratio."""

        self.figure.clear()
        ax = self.figure.add_subplot(111)
        r = [s.r_over_R for s in stations]
        ax.plot(r, [s.dT_dr for s in stations], label="dT/dr, N/m")
        ax.plot(r, [s.dQ_dr for s in stations], label="dQ/dr, N")
        ax.set_title("Radial loads")
        ax.set_xlabel("r/R")
        ax.set_ylabel("Load")
        ax.grid(True)
        ax.legend()
        self._redraw()


class AeroPlotWidget(_BasePlotWidget):
    """Plot local aerodynamic state."""

    def update_plot(self, stations: list[StationResult]) -> None:
        """Update alpha, Re, Cl, and Cd plots."""

        self.figure.clear()
        r = [s.r_over_R for s in stations]
        axes = [self.figure.add_subplot(2, 2, i + 1) for i in range(4)]
        series = [
            ("alpha_deg", [s.alpha_deg for s in stations], "deg"),
            ("Re", [s.reynolds for s in stations], ""),
            ("Cl", [s.cl for s in stations], ""),
            ("Cd", [s.cd for s in stations], ""),
        ]
        for ax, (title, values, ylabel) in zip(axes, series):
            ax.plot(r, values, label=title)
            ax.set_title(title)
            ax.set_xlabel("r/R")
            ax.set_ylabel(ylabel or title)
            ax.grid(True)
        self._redraw()


class ScanPlotWidget(_BasePlotWidget):
    """Plot RPM sweep totals."""

    def update_plot(self, rows: list[dict[str, float]]) -> None:
        """Update T, Q, and P versus RPM."""

        self.figure.clear()
        axes = [self.figure.add_subplot(3, 1, i + 1) for i in range(3)]
        rpm = [float(row["RPM"]) for row in rows]
        series = [
            ("T, N", [float(row["T"]) for row in rows]),
            ("Q, N*m", [float(row["Q"]) for row in rows]),
            ("P, W", [float(row["P"]) for row in rows]),
        ]
        for ax, (label, values) in zip(axes, series):
            ax.plot(rpm, values, label=label)
            ax.set_ylabel(label)
            ax.grid(True)
            ax.legend()
        axes[-1].set_xlabel("RPM")
        axes[0].set_title("RPM sweep")
        self._redraw()


class PolarPlotWidget(_BasePlotWidget):
    """Plot XFOIL polar data."""

    def update_plot(self, points: list[XfoilPolarPoint]) -> None:
        """Update Cl, Cd, Cl/Cd, and Cm against alpha."""

        self.figure.clear()
        alpha = [p.alpha_deg for p in points]
        axes = [self.figure.add_subplot(2, 2, i + 1) for i in range(4)]
        cl_over_cd = [p.cl / p.cd if abs(p.cd) > 1e-12 else 0.0 for p in points]
        series = [
            ("Cl vs alpha", [p.cl for p in points], "Cl"),
            ("Cd vs alpha", [p.cd for p in points], "Cd"),
            ("Cl/Cd vs alpha", cl_over_cd, "Cl/Cd"),
            ("Cm vs alpha", [p.cm for p in points], "Cm"),
        ]
        for ax, (title, values, ylabel) in zip(axes, series):
            ax.plot(alpha, values, label=ylabel)
            ax.set_title(title)
            ax.set_xlabel("alpha, deg")
            ax.set_ylabel(ylabel)
            ax.grid(True)
        self._redraw()


class DesignPlotWidget(_BasePlotWidget):
    """Plot twist design station values."""

    def update_plot(self, stations: list[DesignStationResult]) -> None:
        """Update beta, alpha, chord, and Cl/Cd against radius ratio."""

        self.figure.clear()
        r = [s.r_over_R for s in stations]
        axes = [self.figure.add_subplot(2, 2, i + 1) for i in range(4)]
        series = [
            ("beta_deg", [s.beta_deg for s in stations], "deg"),
            ("alpha_design_deg", [s.alpha_design_deg for s in stations], "deg"),
            ("chord/R", [s.chord_over_R for s in stations], "chord/R"),
            ("Cl/Cd", [s.ld for s in stations], "Cl/Cd"),
        ]
        for ax, (title, values, ylabel) in zip(axes, series):
            ax.plot(r, values, label=title)
            ax.set_title(title)
            ax.set_xlabel("r/R")
            ax.set_ylabel(ylabel)
            ax.grid(True)
        self._redraw()


class OptimizationHistoryPlotWidget(_BasePlotWidget):
    """Plot target optimization convergence history."""

    def update_plot(self, history: list[OptimizationHistoryRow]) -> None:
        """Update fitness, target error, performance, and diagnostics."""

        self.figure.clear()
        axes = [self.figure.add_subplot(2, 2, i + 1) for i in range(4)]
        generation = [row.generation for row in history]
        series = [
            ("Best fitness", [row.best_fitness for row in history], "fitness"),
            ("Target error", [row.target_error_fraction for row in history], "fraction"),
            ("Best loads", None, ""),
            ("Constraints", None, ""),
        ]
        axes[0].plot(generation, series[0][1], label="fitness")
        axes[1].plot(generation, series[1][1], label="target error")
        axes[2].plot(generation, [row.best_thrust_N for row in history], label="T, N")
        axes[2].plot(generation, [row.best_torque_Nm for row in history], label="Q, N*m")
        axes[2].plot(generation, [row.best_power_W for row in history], label="P, W")
        axes[3].plot(generation, [row.max_mach for row in history], label="max Mach")
        axes[3].plot(generation, [row.stall_fraction for row in history], label="stall fraction")
        axes[3].plot(generation, [row.low_re_fraction for row in history], label="low Re fraction")
        for ax, (title, _values, ylabel) in zip(axes, series):
            ax.set_title(title)
            ax.set_xlabel("generation")
            ax.set_ylabel(ylabel or title)
            ax.grid(True)
            ax.legend()
        self._redraw()


class OptimizedGeometryPlotWidget(_BasePlotWidget):
    """Plot optimized blade geometry and optional radial loads."""

    def update_plot(
        self,
        geometry: list[GeometryStation],
        analysis: PropellerResult | None = None,
    ) -> None:
        """Update chord, beta, and optional load distributions."""

        self.figure.clear()
        axes = [self.figure.add_subplot(2, 2, i + 1) for i in range(4)]
        r = [station.r_over_R for station in geometry]
        axes[0].plot(r, [station.chord_over_R for station in geometry], label="chord/R")
        axes[1].plot(r, [station.beta_deg for station in geometry], label="beta_deg")
        if analysis is not None:
            station_r = [station.r_over_R for station in analysis.stations]
            axes[2].plot(station_r, [station.dT_dr for station in analysis.stations], label="dT/dr")
            axes[3].plot(station_r, [station.alpha_deg for station in analysis.stations], label="alpha_deg")
        axes[0].set_title("Chord distribution")
        axes[0].set_ylabel("chord/R")
        axes[1].set_title("Twist distribution")
        axes[1].set_ylabel("deg")
        axes[2].set_title("Radial thrust load")
        axes[2].set_ylabel("dT/dr")
        axes[3].set_title("Angle of attack")
        axes[3].set_ylabel("deg")
        for ax in axes:
            ax.set_xlabel("r/R")
            ax.grid(True)
            ax.legend()
        self._redraw()
