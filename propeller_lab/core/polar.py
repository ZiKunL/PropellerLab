"""Airfoil polar models and CSV import/export."""

from __future__ import annotations

import csv
import math
from pathlib import Path

from .models import PolarPoint
from .numerics import clamp, finite_or_default, lin_interp


class AirfoilPolar:
    """Base interface for airfoil polar lookup."""

    def lookup(
        self,
        alpha_deg: float,
        reynolds: float | None = None,
        mach: float | None = None,
    ) -> tuple[float, float, float, list[str]]:
        """Return cl, cd, cm, warnings for the requested state."""

        raise NotImplementedError


class GenericPolar(AirfoilPolar):
    """Simple analytic polar for early engineering estimates."""

    def __init__(
        self,
        alpha0_deg: float = -2.0,
        cl_min: float = -1.1,
        cl_max: float = 1.25,
        cd0: float = 0.012,
        k: float = 0.018,
        cm: float = -0.04,
    ) -> None:
        self.alpha0_deg = alpha0_deg
        self.cl_min = cl_min
        self.cl_max = cl_max
        self.cd0 = cd0
        self.k = k
        self.cm = cm

    def lookup(
        self,
        alpha_deg: float,
        reynolds: float | None = None,
        mach: float | None = None,
    ) -> tuple[float, float, float, list[str]]:
        """Return a clamped lift curve and parabolic drag polar."""

        warnings: list[str] = []
        alpha_rad = math.radians(alpha_deg)
        alpha0_rad = math.radians(self.alpha0_deg)
        cl = 2.0 * math.pi * (alpha_rad - alpha0_rad)
        cl = clamp(cl, self.cl_min, self.cl_max)
        cd = self.cd0 + self.k * cl * cl
        if abs(alpha_deg) > 12.0:
            cd += 0.08 * ((abs(alpha_deg) - 12.0) / 10.0) ** 2
            warnings.append("Possible stall.")
        if abs(alpha_deg) > 15.0:
            excess = abs(alpha_deg) - 15.0
            cl *= max(0.35, 1.0 - 0.025 * excess)
            cd += 0.15 * (excess / 10.0) ** 2 + 0.01 * excess
        if reynolds is not None and reynolds < 50000.0:
            warnings.append("Low Reynolds number: polar accuracy may be poor.")
        if mach is not None and mach > 0.6:
            warnings.append("High Mach number: compressibility effects may be important.")
        return (
            finite_or_default(cl),
            finite_or_default(cd),
            finite_or_default(self.cm),
            warnings,
        )


class TablePolar(AirfoilPolar):
    """CSV-backed polar with alpha interpolation."""

    def __init__(self, points: list[PolarPoint]) -> None:
        if not points:
            raise ValueError("TablePolar requires at least one point.")
        self.points = sorted(points, key=lambda p: p.alpha_deg)

    @classmethod
    def from_csv(cls, path: str | Path) -> "TablePolar":
        """Load a polar table from CSV."""

        csv_path = Path(path)
        points: list[PolarPoint] = []
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise ValueError("CSV file has no header.")
            for row in reader:
                normalized = {str(k).strip().lower(): v for k, v in row.items() if k is not None}
                try:
                    alpha = float(normalized["alpha_deg"])
                    cl = float(normalized["cl"])
                    cd = float(normalized["cd"])
                    cm = _optional_float(normalized.get("cm"), 0.0)
                    cdp = _optional_float(normalized.get("cdp"), None)
                    xtr_top = _optional_float(normalized.get("xtr_top"), None)
                    xtr_bottom = _optional_float(normalized.get("xtr_bottom"), None)
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid polar CSV row: {row}") from exc
                points.append(
                    PolarPoint(
                        alpha_deg=alpha,
                        cl=cl,
                        cd=cd,
                        cm=cm if cm is not None else 0.0,
                        cdp=cdp,
                        xtr_top=xtr_top,
                        xtr_bottom=xtr_bottom,
                    )
                )
        return cls(points)

    def to_csv(self, path: str | Path) -> None:
        """Write the polar table to CSV."""

        csv_path = Path(path)
        has_xfoil = any(
            p.cdp is not None or p.xtr_top is not None or p.xtr_bottom is not None
            for p in self.points
        )
        fieldnames = (
            ["alpha_deg", "cl", "cd", "cdp", "cm", "xtr_top", "xtr_bottom"]
            if has_xfoil
            else ["alpha_deg", "cl", "cd", "cm"]
        )
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for point in self.points:
                row: dict[str, float | str] = {
                    "alpha_deg": point.alpha_deg,
                    "cl": point.cl,
                    "cd": point.cd,
                    "cm": point.cm,
                }
                if has_xfoil:
                    row["cdp"] = "" if point.cdp is None else point.cdp
                    row["xtr_top"] = "" if point.xtr_top is None else point.xtr_top
                    row["xtr_bottom"] = "" if point.xtr_bottom is None else point.xtr_bottom
                writer.writerow(row)

    def lookup(
        self,
        alpha_deg: float,
        reynolds: float | None = None,
        mach: float | None = None,
    ) -> tuple[float, float, float, list[str]]:
        """Return cl, cd, cm by alpha interpolation."""

        del reynolds, mach
        warnings: list[str] = []
        for point in self.points:
            if abs(alpha_deg - point.alpha_deg) <= 1e-12:
                return point.cl, point.cd, point.cm, warnings
        first = self.points[0]
        last = self.points[-1]
        if alpha_deg <= first.alpha_deg:
            if alpha_deg < first.alpha_deg:
                warnings.append("Alpha below polar range; using lower boundary.")
            return first.cl, first.cd, first.cm, warnings
        if alpha_deg >= last.alpha_deg:
            if alpha_deg > last.alpha_deg:
                warnings.append("Alpha above polar range; using upper boundary.")
            return last.cl, last.cd, last.cm, warnings

        for left, right in zip(self.points, self.points[1:]):
            if left.alpha_deg <= alpha_deg <= right.alpha_deg:
                cl = lin_interp(alpha_deg, left.alpha_deg, right.alpha_deg, left.cl, right.cl)
                cd = lin_interp(alpha_deg, left.alpha_deg, right.alpha_deg, left.cd, right.cd)
                cm = lin_interp(alpha_deg, left.alpha_deg, right.alpha_deg, left.cm, right.cm)
                return cl, cd, cm, warnings
        return last.cl, last.cd, last.cm, warnings


class MultiRePolar(AirfoilPolar):
    """Multiple TablePolar objects interpolated across Reynolds number."""

    def __init__(self) -> None:
        self.tables: dict[float, TablePolar] = {}

    def add_table(self, reynolds: float, table_polar: TablePolar) -> None:
        """Add a table for one Reynolds number."""

        if reynolds <= 0.0:
            raise ValueError("Reynolds number must be positive.")
        self.tables[float(reynolds)] = table_polar

    def lookup(
        self,
        alpha_deg: float,
        reynolds: float | None = None,
        mach: float | None = None,
    ) -> tuple[float, float, float, list[str]]:
        """Lookup by alpha and Reynolds number."""

        if not self.tables:
            raise ValueError("MultiRePolar has no tables.")
        re_value = 0.0 if reynolds is None else float(reynolds)
        keys = sorted(self.tables)
        warnings: list[str] = []
        if re_value <= keys[0]:
            cl, cd, cm, w = self.tables[keys[0]].lookup(alpha_deg, re_value, mach)
            warnings.extend(w)
            if re_value < keys[0]:
                warnings.append("Reynolds below table range; using nearest table.")
            return cl, cd, cm, _unique(warnings)
        if re_value >= keys[-1]:
            cl, cd, cm, w = self.tables[keys[-1]].lookup(alpha_deg, re_value, mach)
            warnings.extend(w)
            if re_value > keys[-1]:
                warnings.append("Reynolds above table range; using nearest table.")
            return cl, cd, cm, _unique(warnings)

        for lo, hi in zip(keys, keys[1:]):
            if lo <= re_value <= hi:
                cl0, cd0, cm0, w0 = self.tables[lo].lookup(alpha_deg, lo, mach)
                cl1, cd1, cm1, w1 = self.tables[hi].lookup(alpha_deg, hi, mach)
                cl = lin_interp(re_value, lo, hi, cl0, cl1)
                cd = lin_interp(re_value, lo, hi, cd0, cd1)
                cm = lin_interp(re_value, lo, hi, cm0, cm1)
                warnings.extend(w0)
                warnings.extend(w1)
                return cl, cd, cm, _unique(warnings)
        cl, cd, cm, w = self.tables[keys[-1]].lookup(alpha_deg, re_value, mach)
        return cl, cd, cm, _unique(w)


def _optional_float(value: object, default: float | None) -> float | None:
    """Parse an optional float field."""

    if value is None:
        return default
    text = str(value).strip()
    if text == "":
        return default
    return float(text)


def _unique(items: list[str]) -> list[str]:
    """Return items with duplicates removed while preserving order."""

    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
