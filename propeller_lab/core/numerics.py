"""Small numerical helpers without SciPy."""

from __future__ import annotations

import math
from collections.abc import Callable


def clamp(x: float, lo: float, hi: float) -> float:
    """Return x limited to the inclusive range [lo, hi]."""

    if lo > hi:
        lo, hi = hi, lo
    return max(lo, min(hi, x))


def safe_div(a: float, b: float, default: float = 0.0) -> float:
    """Divide a by b and return default when the result is invalid."""

    if not is_finite_number(a) or not is_finite_number(b) or abs(b) < 1e-30:
        return default
    value = a / b
    return finite_or_default(value, default)


def is_finite_number(x: object) -> bool:
    """Return True if x is a finite int or float."""

    return isinstance(x, (int, float)) and math.isfinite(float(x))


def finite_or_default(x: float, default: float = 0.0) -> float:
    """Return x as a float if finite, otherwise default."""

    if is_finite_number(x):
        return float(x)
    return float(default)


def lin_interp(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    """Linearly interpolate y at x between two points."""

    if not all(is_finite_number(v) for v in (x, x0, x1, y0, y1)):
        return finite_or_default(y0)
    if abs(x1 - x0) < 1e-30:
        return finite_or_default(y0)
    t = (x - x0) / (x1 - x0)
    return finite_or_default(y0 + t * (y1 - y0))


def bisection_root(
    func: Callable[[float], float],
    lo: float,
    hi: float,
    tol: float = 1e-7,
    max_iter: int = 100,
) -> float:
    """Find a bracketed root with bisection."""

    if lo >= hi:
        raise ValueError("Bisection requires lo < hi.")
    f_lo = func(lo)
    f_hi = func(hi)
    if not is_finite_number(f_lo) or not is_finite_number(f_hi):
        raise ValueError("Bisection endpoint function value is not finite.")
    if f_lo == 0.0:
        return lo
    if f_hi == 0.0:
        return hi
    if f_lo * f_hi > 0.0:
        raise ValueError("Bisection interval does not bracket a root.")

    a = lo
    b = hi
    fa = float(f_lo)
    for _ in range(max_iter):
        mid = 0.5 * (a + b)
        fm = func(mid)
        if not is_finite_number(fm):
            raise ValueError("Bisection function value is not finite.")
        fm = float(fm)
        if abs(fm) <= tol or 0.5 * abs(b - a) <= tol:
            return mid
        if fa * fm <= 0.0:
            b = mid
        else:
            a = mid
            fa = fm
    return 0.5 * (a + b)


def solve_positive_bracketed_root(
    func: Callable[[float], float],
    lo: float,
    initial_hi: float,
    max_hi: float,
    tol: float = 1e-7,
    max_iter: int = 100,
) -> float:
    """Find a positive root by expanding the upper bracket."""

    if lo < 0.0:
        raise ValueError("Positive root solve requires lo >= 0.")
    if initial_hi <= lo:
        raise ValueError("Positive root solve requires initial_hi > lo.")
    if max_hi <= lo:
        raise ValueError("Positive root solve requires max_hi > lo.")

    f_lo = func(lo)
    if not is_finite_number(f_lo):
        raise ValueError("Root lower function value is not finite.")
    if f_lo == 0.0:
        return lo

    hi = initial_hi
    last_error: ValueError | None = None
    while hi <= max_hi + 1e-12:
        f_hi = func(hi)
        if not is_finite_number(f_hi):
            last_error = ValueError("Root upper function value is not finite.")
        elif f_lo * f_hi <= 0.0:
            return finite_or_default(bisection_root(func, lo, hi, tol=tol, max_iter=max_iter))
        hi *= 2.0

    hi = max_hi
    f_hi = func(hi)
    if is_finite_number(f_hi) and f_lo * f_hi <= 0.0:
        return finite_or_default(bisection_root(func, lo, hi, tol=tol, max_iter=max_iter))
    if last_error is not None:
        raise last_error
    raise ValueError("No positive root bracket was found.")
