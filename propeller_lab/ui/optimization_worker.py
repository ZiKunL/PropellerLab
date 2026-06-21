"""Qt worker for target optimization outside the GUI thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from propeller_lab.core.models import GeometryStation
from propeller_lab.core.optimizer import CandidateEvaluation, TargetOptimizationInput, run_target_optimization
from propeller_lab.core.polar import AirfoilPolar


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
