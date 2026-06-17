"""Qt worker for running XFOIL outside the GUI thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from propeller_lab.core.xfoil_runner import XfoilRunner


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
            if self.source_type == "DAT file":
                result = runner.run_dat_alpha_sweep(
                    self.dat_path,
                    self.reynolds,
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
                    self.reynolds,
                    self.mach,
                    self.alpha_start,
                    self.alpha_end,
                    self.alpha_step,
                    self.iter_limit,
                    self.panels,
                )
            self.log.emit(f"XFOIL finished with {len(result.points)} point(s).")
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 - errors are shown in the UI.
            self.failed.emit(str(exc))
