"""External XFOIL automation and polar parsing."""

from __future__ import annotations

import csv
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class XfoilPolarPoint:
    """One numeric row from an XFOIL polar file."""

    alpha_deg: float
    cl: float
    cd: float
    cdp: float
    cm: float
    xtr_top: float | None
    xtr_bottom: float | None


@dataclass
class XfoilRunResult:
    """Result from one XFOIL subprocess run."""

    points: list[XfoilPolarPoint]
    stdout: str
    stderr: str
    warnings: list[str]
    polar_path: Path | None
    csv_path: Path | None
    reynolds_tables: dict[float, list[XfoilPolarPoint]] = field(default_factory=dict)


class XfoilRunner:
    """Run XFOIL as an external executable."""

    def __init__(self, xfoil_path: str = "xfoil", timeout_s: float = 60.0) -> None:
        self.xfoil_path = xfoil_path or "xfoil"
        self.timeout_s = timeout_s

    def check_available(self) -> bool:
        """Return True if the XFOIL executable can be started."""

        try:
            completed = subprocess.run(
                [self.xfoil_path],
                input="QUIT\n",
                text=True,
                capture_output=True,
                timeout=min(max(self.timeout_s, 1.0), 10.0),
                check=False,
            )
            return completed.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    def run_naca_alpha_sweep(
        self,
        naca_code: str,
        reynolds: float,
        mach: float,
        alpha_start: float,
        alpha_end: float,
        alpha_step: float,
        iter_limit: int = 100,
        panels: int = 160,
        output_csv_path: str | Path | None = None,
    ) -> XfoilRunResult:
        """Generate a polar for a NACA airfoil through XFOIL."""

        source_lines = [f"NACA {naca_code.strip() or '4412'}"]
        return self._run_alpha_sweep(
            source_lines,
            reynolds,
            mach,
            alpha_start,
            alpha_end,
            alpha_step,
            iter_limit,
            panels,
            output_csv_path,
        )

    def run_dat_alpha_sweep(
        self,
        dat_path: str | Path,
        reynolds: float,
        mach: float,
        alpha_start: float,
        alpha_end: float,
        alpha_step: float,
        iter_limit: int = 100,
        panels: int = 160,
        output_csv_path: str | Path | None = None,
    ) -> XfoilRunResult:
        """Generate a polar for a DAT coordinate file through XFOIL."""

        dat_file = Path(dat_path)
        source_lines = [f"LOAD {dat_file}"]
        return self._run_alpha_sweep(
            source_lines,
            reynolds,
            mach,
            alpha_start,
            alpha_end,
            alpha_step,
            iter_limit,
            panels,
            output_csv_path,
        )

    @staticmethod
    def parse_xfoil_polar(path: str | Path) -> list[XfoilPolarPoint]:
        """Parse numeric rows from an XFOIL polar text file."""

        polar_path = Path(path)
        if not polar_path.exists() or polar_path.stat().st_size == 0:
            return []
        points: list[XfoilPolarPoint] = []
        with polar_path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                values = _parse_float_row(line)
                if len(values) < 4:
                    continue
                if len(values) >= 7:
                    point = XfoilPolarPoint(
                        alpha_deg=values[0],
                        cl=values[1],
                        cd=values[2],
                        cdp=values[3],
                        cm=values[4],
                        xtr_top=values[5],
                        xtr_bottom=values[6],
                    )
                elif len(values) >= 5:
                    point = XfoilPolarPoint(
                        alpha_deg=values[0],
                        cl=values[1],
                        cd=values[2],
                        cdp=values[3],
                        cm=values[4],
                        xtr_top=None,
                        xtr_bottom=None,
                    )
                else:
                    point = XfoilPolarPoint(
                        alpha_deg=values[0],
                        cl=values[1],
                        cd=values[2],
                        cdp=0.0,
                        cm=values[3],
                        xtr_top=None,
                        xtr_bottom=None,
                    )
                points.append(point)
        return points

    @staticmethod
    def export_xfoil_points_to_csv(points: list[XfoilPolarPoint], path: str | Path) -> None:
        """Export XFOIL polar points to TablePolar-compatible CSV."""

        csv_path = Path(path)
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "alpha_deg",
                    "cl",
                    "cd",
                    "cdp",
                    "cm",
                    "xtr_top",
                    "xtr_bottom",
                ],
            )
            writer.writeheader()
            for point in points:
                writer.writerow(
                    {
                        "alpha_deg": point.alpha_deg,
                        "cl": point.cl,
                        "cd": point.cd,
                        "cdp": point.cdp,
                        "cm": point.cm,
                        "xtr_top": "" if point.xtr_top is None else point.xtr_top,
                        "xtr_bottom": "" if point.xtr_bottom is None else point.xtr_bottom,
                    }
                )

    def _run_alpha_sweep(
        self,
        source_lines: list[str],
        reynolds: float,
        mach: float,
        alpha_start: float,
        alpha_end: float,
        alpha_step: float,
        iter_limit: int,
        panels: int,
        output_csv_path: str | Path | None,
    ) -> XfoilRunResult:
        """Run the shared XFOIL alpha sweep script."""

        warnings: list[str] = []
        run_dir = Path(tempfile.mkdtemp(prefix="propeller_lab_xfoil_"))
        polar_path = run_dir / "polar.txt"
        csv_path = Path(output_csv_path) if output_csv_path is not None else None
        script = self._build_script(
            source_lines,
            polar_path.name,
            reynolds,
            mach,
            alpha_start,
            alpha_end,
            alpha_step,
            iter_limit,
            panels,
        )
        stdout = ""
        stderr = ""
        try:
            completed = subprocess.run(
                [self.xfoil_path],
                input=script,
                text=True,
                cwd=run_dir,
                capture_output=True,
                timeout=self.timeout_s,
                check=False,
            )
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            if completed.returncode != 0:
                warnings.append(f"XFOIL exited with code {completed.returncode}.")
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="ignore") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="ignore") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
            warnings.append("XFOIL timed out.")
        except FileNotFoundError:
            warnings.append("XFOIL executable was not found.")
            return XfoilRunResult([], stdout, stderr, warnings, None, csv_path, {})
        except Exception as exc:  # noqa: BLE001 - errors are reported to the UI as warnings.
            warnings.append(f"XFOIL failed: {exc}")
            return XfoilRunResult([], stdout, stderr, warnings, None, csv_path, {})

        points = self.parse_xfoil_polar(polar_path)
        if not points:
            warnings.append("XFOIL did not produce parseable polar points.")
        if points and csv_path is not None:
            self.export_xfoil_points_to_csv(points, csv_path)
        if points and _expected_alpha_count(alpha_start, alpha_end, alpha_step) > len(points):
            warnings.append("Some requested alpha points may be missing due to non-convergence.")
        tables = {float(reynolds): points} if points else {}
        return XfoilRunResult(points, stdout, stderr, _unique(warnings), polar_path, csv_path, tables)

    @staticmethod
    def _build_script(
        source_lines: list[str],
        polar_filename: str,
        reynolds: float,
        mach: float,
        alpha_start: float,
        alpha_end: float,
        alpha_step: float,
        iter_limit: int,
        panels: int,
    ) -> str:
        """Build a tolerant XFOIL command script."""

        lines = [
            "PLOP",
            "G F",
            "",
            *source_lines,
            "PPAR",
            "N",
            f"{int(panels)}",
            "",
            "",
            "PANE",
            "OPER",
            f"VISC {float(reynolds):.8g}",
            f"MACH {float(mach):.8g}",
            f"ITER {int(iter_limit)}",
            "PACC",
            polar_filename,
            "",
            f"ASEQ {float(alpha_start):.8g} {float(alpha_end):.8g} {float(alpha_step):.8g}",
            "PACC",
            "",
            "QUIT",
            "",
        ]
        return "\n".join(lines)


def _parse_float_row(line: str) -> list[float]:
    """Parse a whitespace-separated numeric row."""

    parts = line.replace(",", " ").split()
    values: list[float] = []
    for part in parts:
        try:
            values.append(float(part))
        except ValueError:
            return []
    return values


def _expected_alpha_count(alpha_start: float, alpha_end: float, alpha_step: float) -> int:
    """Estimate requested alpha count."""

    if alpha_step == 0.0:
        return 0
    span = alpha_end - alpha_start
    if span * alpha_step < 0.0:
        return 0
    return int(abs(span / alpha_step)) + 1


def _unique(items: list[str]) -> list[str]:
    """Return warnings without duplicates."""

    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
