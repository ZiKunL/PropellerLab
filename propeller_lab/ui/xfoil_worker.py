"""Qt worker for running XFOIL outside the GUI thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from propeller_lab.core.xfoil_runner import XfoilPolarPoint, XfoilRunResult, XfoilRunner


class XfoilWorker(QObject):
    """QObject worker used inside a QThread."""

    finished = Signal(object)
    failed = Signal(str)
    log = Signal(str)

    def __init__(
        self,
        xfoil_path: str,
        source_type: str,
        naca_code: str,
        dat_path: str,
        reynolds: float,
        reynolds_values: list[float] | None,
        mach: float,
        alpha_start: float,
        alpha_end: float,
        alpha_step: float,
        iter_limit: int,
        panels: int,
        timeout: float,
    ) -> None:
        super().__init__()
        self.xfoil_path = xfoil_path
        self.source_type = source_type
        self.naca_code = naca_code
        self.dat_path = dat_path
        self.reynolds = reynolds
        self.reynolds_values = reynolds_values or [reynolds]
        self.mach = mach
        self.alpha_start = alpha_start
        self.alpha_end = alpha_end
        self.alpha_step = alpha_step
        self.iter_limit = iter_limit
        self.panels = panels
        self.timeout = timeout

    @Slot()
    def run(self) -> None:
        """Run the requested XFOIL sweep and emit the result."""

        try:
            self.log.emit("Starting XFOIL.")
            runner = XfoilRunner(self.xfoil_path or "xfoil", self.timeout)
            results: list[XfoilRunResult] = []
            for reynolds in self.reynolds_values:
                self.log.emit(f"Running XFOIL at Re={reynolds:.6g}.")
                if self.source_type == "DAT file":
                    result = runner.run_dat_alpha_sweep(
                        self.dat_path,
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
                        self.naca_code,
                        reynolds,
                        self.mach,
                        self.alpha_start,
                        self.alpha_end,
                        self.alpha_step,
                        self.iter_limit,
                        self.panels,
                    )
                results.append(result)
            result = _combine_results(results)
            self.log.emit(
                f"XFOIL finished with {len(result.reynolds_tables)} Reynolds table(s) and {len(result.points)} displayed point(s)."
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 - errors are shown in the UI.
            self.failed.emit(str(exc))


def _combine_results(results: list[XfoilRunResult]) -> XfoilRunResult:
    """Combine one or more single-Re XFOIL results."""

    if not results:
        return XfoilRunResult([], "", "", ["No XFOIL runs were requested."], None, None, {})
    tables: dict[float, list[XfoilPolarPoint]] = {}
    warnings: list[str] = []
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    display_points: list[XfoilPolarPoint] = []
    for result in results:
        stdout_parts.append(result.stdout)
        stderr_parts.append(result.stderr)
        warnings.extend(result.warnings)
        for reynolds, points in result.reynolds_tables.items():
            if points:
                tables[reynolds] = points
                if not display_points:
                    display_points = points
    return XfoilRunResult(
        display_points,
        "\n".join(part for part in stdout_parts if part),
        "\n".join(part for part in stderr_parts if part),
        _unique(warnings),
        results[-1].polar_path,
        results[-1].csv_path,
        tables,
    )


def _unique(items: list[str]) -> list[str]:
    """Return strings without duplicates."""

    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
