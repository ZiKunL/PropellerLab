"""Qt worker for target optimization outside the GUI thread."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from propeller_lab.core.models import GeometryStation, PolarPoint
from propeller_lab.core.optimizer import (
    CandidateEvaluation,
    TargetOptimizationInput,
    TargetOptimizationResult,
    run_target_optimization,
)
from propeller_lab.core.polar import AirfoilPolar, MultiAirfoilPolar, MultiRePolar, TablePolar, normalize_airfoil_id
from propeller_lab.core.xfoil_runner import XfoilRunner


@dataclass
class TargetAirfoilXfoilResult:
    """Result from target multi-airfoil XFOIL preprocessing."""

    polar: MultiAirfoilPolar
    airfoil_ids: list[str]
    reynolds_values: list[float]
    warnings: list[str]


@dataclass(frozen=True)
class TargetAirfoilXfoilItem:
    """One target airfoil item with an explicit XFOIL source type."""

    source_type: str
    value: str


@dataclass
class TargetAirfoilComparisonEntry:
    """One uniform-airfoil optimization result."""

    airfoil_id: str
    result: TargetOptimizationResult


@dataclass
class TargetAirfoilComparisonResult:
    """Ranked comparison of uniform-airfoil propeller optimizations."""

    input: TargetOptimizationInput
    entries: list[TargetAirfoilComparisonEntry]
    warnings: list[str]


class OptimizationWorker(QObject):
    """QObject worker used inside a QThread for target optimization."""

    progress = Signal(int, int, object)
    finished = Signal(object)
    failed = Signal(str)
    log = Signal(str)

    def __init__(
        self,
        opt_input: TargetOptimizationInput,
        polar: AirfoilPolar | None,
        base_geometry: list[GeometryStation] | None,
    ) -> None:
        super().__init__()
        self.opt_input = opt_input
        self.polar = polar
        self.base_geometry = base_geometry
        self._stop_requested = False

    @Slot()
    def run(self) -> None:
        """Run the optimizer and emit the result."""

        try:
            self.log.emit("Starting target optimization.")
            result = run_target_optimization(
                self.opt_input,
                polar=self.polar,
                base_geometry=self.base_geometry,
                progress_callback=self._progress,
                stop_callback=self._should_stop,
            )
            self.log.emit(f"Target optimization finished after {result.evaluations} evaluation(s).")
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 - errors are shown in the UI.
            self.failed.emit(str(exc))

    @Slot()
    def request_stop(self) -> None:
        """Ask the optimizer to stop at the next safe checkpoint."""

        self._stop_requested = True
        self.log.emit("Stop requested.")

    def _should_stop(self) -> bool:
        """Return whether the user requested a stop."""

        return self._stop_requested

    def _progress(self, generation: int, total_generations: int, best: object) -> None:
        """Emit compact progress for the GUI thread."""

        if isinstance(best, CandidateEvaluation):
            self.log.emit(
                "Generation "
                f"{generation}/{total_generations}: fitness={best.fitness:.6g}, "
                f"target_error={best.target_error_fraction:.6g}"
            )
        self.progress.emit(generation, total_generations, best)


class AirfoilComparisonWorker(QObject):
    """QObject worker that optimizes one uniform-airfoil propeller per candidate."""

    progress = Signal(int, int, object)
    finished = Signal(object)
    failed = Signal(str)
    log = Signal(str)

    def __init__(
        self,
        opt_input: TargetOptimizationInput,
        polar: AirfoilPolar | None,
        base_geometry: list[GeometryStation] | None,
        airfoil_ids: list[str],
    ) -> None:
        super().__init__()
        self.opt_input = opt_input
        self.polar = polar
        self.base_geometry = base_geometry
        self.airfoil_ids = _unique([normalize_airfoil_id(item) for item in airfoil_ids if normalize_airfoil_id(item)])
        self._stop_requested = False

    @Slot()
    def run(self) -> None:
        """Run target optimization for each selected uniform airfoil."""

        try:
            if not self.airfoil_ids:
                raise ValueError("No target airfoils were selected.")
            if len(self.airfoil_ids) > 1 and not isinstance(self.polar, MultiAirfoilPolar):
                raise ValueError("Airfoil comparison requires target XFOIL multi-airfoil polar data.")
            missing = self._missing_airfoils()
            if missing:
                raise ValueError("Missing polar data for airfoil(s): " + ", ".join(missing))

            entries: list[TargetAirfoilComparisonEntry] = []
            warnings: list[str] = []
            for index, airfoil_id in enumerate(self.airfoil_ids, start=1):
                if self._should_stop():
                    warnings.append("Comparison stopped before all airfoils were optimized.")
                    break
                self.log.emit(f"Optimizing uniform airfoil {airfoil_id} ({index}/{len(self.airfoil_ids)}).")
                seed = self.opt_input.random_seed
                per_input = replace(
                    self.opt_input,
                    airfoil_ids=(airfoil_id,),
                    random_seed=None if seed is None else seed + index - 1,
                )
                result = run_target_optimization(
                    per_input,
                    polar=self.polar,
                    base_geometry=self.base_geometry,
                    progress_callback=lambda generation, total, best, candidate_index=index: self._progress(
                        candidate_index,
                        generation,
                        total,
                        best,
                    ),
                    stop_callback=self._should_stop,
                )
                entries.append(TargetAirfoilComparisonEntry(airfoil_id=airfoil_id, result=result))
                warnings.extend(f"{airfoil_id}: {warning}" for warning in result.warnings)
                self.log.emit(
                    f"Finished {airfoil_id}: fitness={result.best_fitness:.6g}, "
                    f"target_error={result.target_error_fraction:.6g}."
                )

            if not entries:
                raise ValueError("Airfoil comparison stopped before any candidate finished.")
            entries.sort(key=lambda entry: entry.result.best_fitness)
            comparison = TargetAirfoilComparisonResult(
                input=self.opt_input,
                entries=entries,
                warnings=_unique(warnings),
            )
            best = entries[0]
            self.log.emit(f"Best uniform airfoil: {best.airfoil_id} with fitness={best.result.best_fitness:.6g}.")
            self.finished.emit(comparison)
        except Exception as exc:  # noqa: BLE001 - errors are shown in the UI.
            self.failed.emit(str(exc))

    @Slot()
    def request_stop(self) -> None:
        """Ask the comparison worker to stop at the next safe checkpoint."""

        self._stop_requested = True
        self.log.emit("Stop requested.")

    def _should_stop(self) -> bool:
        """Return whether the user requested a stop."""

        return self._stop_requested

    def _progress(self, candidate_index: int, generation: int, total_generations: int, best: object) -> None:
        """Map per-airfoil optimizer progress into one combined progress range."""

        per_total = max(total_generations, 1)
        overall_generation = (candidate_index - 1) * per_total + generation
        overall_total = per_total * len(self.airfoil_ids)
        if isinstance(best, CandidateEvaluation):
            airfoil_id = self.airfoil_ids[candidate_index - 1]
            self.log.emit(
                "Airfoil "
                f"{airfoil_id} generation {generation}/{total_generations}: "
                f"fitness={best.fitness:.6g}, target_error={best.target_error_fraction:.6g}"
            )
        self.progress.emit(overall_generation, overall_total, best)

    def _missing_airfoils(self) -> list[str]:
        """Return selected airfoils absent from the multi-airfoil polar."""

        if not isinstance(self.polar, MultiAirfoilPolar):
            return []
        return [airfoil_id for airfoil_id in self.airfoil_ids if airfoil_id not in self.polar.airfoils]


class TargetAirfoilXfoilWorker(QObject):
    """QObject worker that builds MultiAirfoilPolar tables with XFOIL."""

    finished = Signal(object)
    failed = Signal(str)
    log = Signal(str)

    def __init__(
        self,
        xfoil_path: str,
        airfoil_items: list[str | TargetAirfoilXfoilItem],
        reynolds_values: list[float],
        mach: float,
        alpha_start: float,
        alpha_end: float,
        alpha_step: float,
        iter_limit: int,
        panels: int,
        timeout: float,
        source_type: str = "naca",
    ) -> None:
        super().__init__()
        self.xfoil_path = xfoil_path
        self.source_type = source_type
        self.airfoil_items = [
            item
            for item in (_normalize_xfoil_item(source_type, item) for item in airfoil_items)
            if item.value
        ]
        self.reynolds_values = list(reynolds_values)
        self.mach = mach
        self.alpha_start = alpha_start
        self.alpha_end = alpha_end
        self.alpha_step = alpha_step
        self.iter_limit = iter_limit
        self.panels = panels
        self.timeout = timeout

    @Slot()
    def run(self) -> None:
        """Run XFOIL for every selected airfoil and Reynolds value."""

        try:
            if not self.airfoil_items:
                raise ValueError("No target airfoils were selected.")
            if not self.reynolds_values:
                raise ValueError("No target Reynolds values were requested.")
            runner = XfoilRunner(self.xfoil_path or "xfoil", self.timeout)
            multi_airfoil = MultiAirfoilPolar()
            warnings: list[str] = []
            for item in self.airfoil_items:
                item_source = item.source_type
                item_value = item.value
                airfoil_id = _airfoil_id_from_item(item_source, item_value)
                re_tables: dict[float, TablePolar] = {}
                for reynolds in self.reynolds_values:
                    self.log.emit(f"Running XFOIL for {airfoil_id} at Re={reynolds:.6g}.")
                    if item_source == "dat":
                        result = runner.run_dat_alpha_sweep(
                            item_value,
                            reynolds,
                            self.mach,
                            self.alpha_start,
                            self.alpha_end,
                            self.alpha_step,
                            self.iter_limit,
                            self.panels,
                        )
                    else:
                        result = runner.run_naca_alpha_sweep(
                            _naca_code_from_airfoil_id(airfoil_id),
                            reynolds,
                            self.mach,
                            self.alpha_start,
                            self.alpha_end,
                            self.alpha_step,
                            self.iter_limit,
                            self.panels,
                        )
                    warnings.extend(result.warnings)
                    points = result.reynolds_tables.get(float(reynolds), result.points)
                    if len(points) < 5:
                        warnings.append(f"{airfoil_id} Re={reynolds:.6g}: fewer than 5 XFOIL points; skipped.")
                        continue
                    re_tables[float(reynolds)] = TablePolar(
                        [
                            PolarPoint(
                                alpha_deg=point.alpha_deg,
                                cl=point.cl,
                                cd=point.cd,
                                cm=point.cm,
                                cdp=point.cdp,
                                xtr_top=point.xtr_top,
                                xtr_bottom=point.xtr_bottom,
                            )
                            for point in points
                        ]
                    )
                if not re_tables:
                    warnings.append(f"{airfoil_id}: no usable XFOIL tables were generated.")
                    continue
                if len(re_tables) == 1:
                    multi_airfoil.add_airfoil(airfoil_id, next(iter(re_tables.values())))
                else:
                    multi_re = MultiRePolar()
                    for reynolds, table in sorted(re_tables.items()):
                        multi_re.add_table(reynolds, table)
                    multi_airfoil.add_airfoil(airfoil_id, multi_re)
            if not multi_airfoil.airfoils:
                raise ValueError("No usable target airfoil polar tables were generated.")
            result = TargetAirfoilXfoilResult(
                polar=multi_airfoil,
                airfoil_ids=list(multi_airfoil.airfoils),
                reynolds_values=sorted(self.reynolds_values),
                warnings=_unique(warnings),
            )
            self.log.emit(
                "Target XFOIL preprocessing finished for "
                f"{len(result.airfoil_ids)} airfoil(s) and {len(result.reynolds_values)} Reynolds value(s)."
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 - errors are shown in the UI.
            self.failed.emit(str(exc))


def _naca_code_from_airfoil_id(airfoil_id: str) -> str:
    """Return the NACA code expected by XFOIL."""

    normalized = normalize_airfoil_id(airfoil_id)
    if normalized.startswith("naca"):
        normalized = normalized[4:]
    if not normalized.isdigit():
        raise ValueError(f"Only NACA airfoil codes are supported here: {airfoil_id}")
    return normalized


def _airfoil_id_from_item(source_type: str, item: str) -> str:
    """Return the normalized airfoil id for a NACA code or DAT path."""

    if source_type == "dat":
        return normalize_airfoil_id(Path(item).stem)
    return normalize_airfoil_id(item)


def _normalize_xfoil_item(source_type: str, item: str | TargetAirfoilXfoilItem) -> TargetAirfoilXfoilItem:
    """Return an XFOIL item with explicit NACA/DAT source."""

    if isinstance(item, TargetAirfoilXfoilItem):
        item_source = item.source_type.strip().lower()
        item_value = item.value.strip().strip('"')
    else:
        text = str(item).strip().strip('"')
        item_source = source_type.strip().lower()
        item_value = text
        lower = text.lower()
        if item_source == "mixed":
            if lower.startswith("naca:"):
                item_source = "naca"
                item_value = text.split(":", 1)[1].strip().strip('"')
            elif lower.startswith("dat:"):
                item_source = "dat"
                item_value = text.split(":", 1)[1].strip().strip('"')
            elif Path(text).suffix.lower() == ".dat" or "\\" in text or "/" in text:
                item_source = "dat"
            else:
                item_source = "naca"
    if item_source not in {"naca", "dat"}:
        raise ValueError(f"Unsupported target airfoil source type: {item_source}")
    return TargetAirfoilXfoilItem(item_source, item_value)


def _unique(items: list[str]) -> list[str]:
    """Return strings without duplicates."""

    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
