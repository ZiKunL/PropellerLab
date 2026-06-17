"""Blade-element and BEMT propeller calculations."""

from __future__ import annotations

import math
from dataclasses import replace

from .geometry import generate_pitch_geometry, validate_geometry
from .models import GeometryStation, PropellerInput, PropellerResult, StationResult
from .numerics import bisection_root, clamp, finite_or_default, is_finite_number, safe_div
from .polar import AirfoilPolar, GenericPolar


def calculate_propeller(
    inp: PropellerInput,
    polar: AirfoilPolar | None = None,
    geometry: list[GeometryStation] | None = None,
) -> PropellerResult:
    """Calculate integrated propeller performance."""

    polar_model = polar if polar is not None else GenericPolar()
    stations = geometry if geometry is not None else generate_pitch_geometry(inp)
    validate_geometry(stations)

    if inp.calculation_mode == "simple":
        station_results = calculate_simple(inp, polar_model, stations)
    elif inp.calculation_mode == "simple_induced":
        station_results = calculate_simple_induced(inp, polar_model, stations)
    elif inp.calculation_mode == "bemt_phi":
        station_results = calculate_bemt_phi(inp, polar_model, stations)
    else:
        raise ValueError(f"Unknown calculation_mode: {inp.calculation_mode}")
    return _integrate_result(inp, station_results)


def calculate_simple(
    inp: PropellerInput,
    polar: AirfoilPolar,
    geometry: list[GeometryStation],
) -> list[StationResult]:
    """Calculate stations without induced velocity."""

    geometry_data = _prepare_geometry(inp, geometry)
    results: list[StationResult] = []
    for station, r_m, dr_m in geometry_data:
        result = _station_from_velocity(inp, polar, station, r_m, dr_m, vi_mps=0.0, loss_factor=1.0)
        results.append(result)
    return results


def calculate_simple_induced(
    inp: PropellerInput,
    polar: AirfoilPolar,
    geometry: list[GeometryStation],
) -> list[StationResult]:
    """Calculate stations with a local axial induced-velocity iteration."""

    geometry_data = _prepare_geometry(inp, geometry)
    return [_induced_station(inp, polar, station, r_m, dr_m, "") for station, r_m, dr_m in geometry_data]


def calculate_bemt_phi(
    inp: PropellerInput,
    polar: AirfoilPolar,
    geometry: list[GeometryStation],
) -> list[StationResult]:
    """Calculate stations with a phi-based BEMT solve where possible."""

    geometry_data = _prepare_geometry(inp, geometry)
    if inp.v_inf <= 1e-6:
        return [
            _induced_station(
                inp,
                polar,
                station,
                r_m,
                dr_m,
                "Static condition: phi-BEMT fallback to induced blade-element station.",
            )
            for station, r_m, dr_m in geometry_data
        ]

    results: list[StationResult] = []
    for station, r_m, dr_m in geometry_data:
        try:
            results.append(_phi_station(inp, polar, station, r_m, dr_m))
        except Exception as exc:  # noqa: BLE001 - station fallback keeps the UI usable.
            results.append(_induced_station(inp, polar, station, r_m, dr_m, f"phi-BEMT fallback: {exc}"))
    return results


def prandtl_loss_factor(
    blades: int,
    radius_m: float,
    hub_radius_m: float,
    r_m: float,
    phi_rad: float,
    use_tip_loss: bool,
    use_hub_loss: bool,
) -> float:
    """Return combined Prandtl tip and hub loss factor."""

    sin_phi = max(abs(math.sin(phi_rad)), 1e-6)
    f_tip = blades * 0.5 * (radius_m - r_m) / max(r_m * sin_phi, 1e-30)
    f_root = blades * 0.5 * (r_m - hub_radius_m) / max(max(hub_radius_m, 1e-6) * sin_phi, 1e-30)
    f_tip = max(f_tip, 0.0)
    f_root = max(f_root, 0.0)
    tip = 1.0 if not use_tip_loss else (2.0 / math.pi) * math.acos(clamp(math.exp(-f_tip), 0.0, 1.0))
    root = 1.0 if not use_hub_loss else (2.0 / math.pi) * math.acos(clamp(math.exp(-f_root), 0.0, 1.0))
    return clamp(tip * root, 0.05, 1.0)


def _prepare_geometry(
    inp: PropellerInput,
    geometry: list[GeometryStation],
) -> list[tuple[GeometryStation, float, float]]:
    """Convert nondimensional station geometry into radius and dr."""

    radius_m = inp.diameter_m / 2.0
    hub_radius_m = inp.hub_diameter_m / 2.0
    radii = [station.r_over_R * radius_m for station in geometry]
    if len(radii) == 1:
        lower = max(hub_radius_m, 0.0)
        upper = min(radius_m, radii[0] + max(radius_m - radii[0], 1e-6))
        return [(geometry[0], radii[0], max(upper - lower, 1e-9))]

    boundaries: list[float] = []
    first_spacing = radii[1] - radii[0]
    boundaries.append(max(hub_radius_m, radii[0] - 0.5 * first_spacing))
    for left, right in zip(radii, radii[1:]):
        boundaries.append(0.5 * (left + right))
    last_spacing = radii[-1] - radii[-2]
    boundaries.append(min(radius_m, radii[-1] + 0.5 * last_spacing))

    out: list[tuple[GeometryStation, float, float]] = []
    for i, station in enumerate(geometry):
        dr_m = max(boundaries[i + 1] - boundaries[i], 1e-9)
        out.append((station, radii[i], dr_m))
    return out


def _station_from_velocity(
    inp: PropellerInput,
    polar: AirfoilPolar,
    station: GeometryStation,
    r_m: float,
    dr_m: float,
    vi_mps: float,
    loss_factor: float,
    tangential_factor: float = 1.0,
) -> StationResult:
    """Calculate one station from local velocity components."""

    radius_m = inp.diameter_m / 2.0
    omega = 2.0 * math.pi * inp.rpm / 60.0
    chord_m = station.chord_over_R * radius_m
    beta_rad = math.radians(station.beta_deg)
    wa = inp.v_inf + vi_mps
    wt = omega * r_m * tangential_factor
    speed = math.hypot(wa, wt)
    phi_rad = math.atan2(wa, wt)
    alpha_deg = math.degrees(beta_rad - phi_rad)
    reynolds = safe_div(inp.rho * speed * chord_m, inp.mu)
    mach = safe_div(speed, inp.sound_speed)
    cl, cd, cm, polar_warnings = polar.lookup(alpha_deg, reynolds, mach)
    q = 0.5 * inp.rho * speed * speed
    dL_dr = q * chord_m * cl
    dD_dr = q * chord_m * cd
    dT_dr = inp.blades * loss_factor * (dL_dr * math.cos(phi_rad) - dD_dr * math.sin(phi_rad))
    dQ_dr = inp.blades * loss_factor * r_m * (dL_dr * math.sin(phi_rad) + dD_dr * math.cos(phi_rad))
    warnings = list(polar_warnings)
    if abs(alpha_deg) > 12.0:
        warnings.append("High angle of attack: possible stall.")
    if reynolds < 50000.0:
        warnings.append("Low Reynolds number.")
    if mach > 0.6:
        warnings.append("High Mach number.")
    if dT_dr < 0.0:
        warnings.append("Negative local thrust.")

    return _clean_station(
        StationResult(
            r_m=r_m,
            r_over_R=station.r_over_R,
            dr_m=dr_m,
            chord_m=chord_m,
            beta_deg=station.beta_deg,
            phi_deg=math.degrees(phi_rad),
            alpha_deg=alpha_deg,
            reynolds=reynolds,
            mach=mach,
            cl=cl,
            cd=cd,
            cm=cm,
            vi_mps=vi_mps,
            vt_mps=wt,
            tip_loss_F=loss_factor,
            dT_dr=dT_dr,
            dQ_dr=dQ_dr,
            dL_dr=dL_dr,
            dD_dr=dD_dr,
            warning="; ".join(_unique(warnings)),
        )
    )


def _induced_station(
    inp: PropellerInput,
    polar: AirfoilPolar,
    station: GeometryStation,
    r_m: float,
    dr_m: float,
    prefix_warning: str,
) -> StationResult:
    """Calculate one station with local axial induced velocity."""

    vi = 0.0
    warnings: list[str] = [prefix_warning] if prefix_warning else []
    result = _station_from_velocity(inp, polar, station, r_m, dr_m, vi, 1.0)
    for _ in range(30):
        result = _station_from_velocity(inp, polar, station, r_m, dr_m, vi, 1.0)
        annulus_area = max(2.0 * math.pi * r_m * dr_m, 1e-30)
        local_dT = result.dT_dr * dr_m
        if local_dT < 0.0:
            vi_new = 0.0
            warnings.append("Negative local thrust in induced-velocity iteration.")
        else:
            vi_new = math.sqrt(max(local_dT, 0.0) / max(2.0 * inp.rho * annulus_area, 1e-30))
        vi_new = clamp(vi_new, 0.0, 200.0)
        next_vi = clamp(0.7 * vi + 0.3 * vi_new, 0.0, 200.0)
        if abs(next_vi - vi) < 1e-4:
            vi = next_vi
            break
        vi = next_vi
    result = _station_from_velocity(inp, polar, station, r_m, dr_m, vi, 1.0)
    all_warnings = _unique(warnings + _split_warnings(result.warning))
    return replace(result, warning="; ".join(all_warnings))


def _phi_station(
    inp: PropellerInput,
    polar: AirfoilPolar,
    station: GeometryStation,
    r_m: float,
    dr_m: float,
) -> StationResult:
    """Solve one station with phi as the unknown."""

    radius_m = inp.diameter_m / 2.0
    hub_radius_m = inp.hub_diameter_m / 2.0
    omega = 2.0 * math.pi * inp.rpm / 60.0
    chord_m = station.chord_over_R * radius_m
    sigma = safe_div(inp.blades * chord_m, 2.0 * math.pi * r_m)
    if omega <= 0.0 or sigma <= 0.0:
        raise ValueError("invalid omega or solidity")

    def residual(phi_rad: float) -> float:
        beta_rad = math.radians(station.beta_deg)
        alpha_deg = math.degrees(beta_rad - phi_rad)
        speed_guess = math.hypot(inp.v_inf, omega * r_m)
        reynolds = safe_div(inp.rho * speed_guess * chord_m, inp.mu)
        mach = safe_div(speed_guess, inp.sound_speed)
        cl, cd, _cm, _warnings = polar.lookup(alpha_deg, reynolds, mach)
        cn = cl * math.cos(phi_rad) - cd * math.sin(phi_rad)
        ct = cl * math.sin(phi_rad) + cd * math.cos(phi_rad)
        if abs(cn) < 1e-8 or abs(ct) < 1e-8:
            raise ValueError("small force coefficient")
        f_loss = prandtl_loss_factor(
            inp.blades,
            radius_m,
            hub_radius_m,
            r_m,
            phi_rad,
            inp.use_tip_loss,
            inp.use_hub_loss,
        )
        if f_loss < 0.05:
            raise ValueError("small loss factor")
        a_den = 4.0 * f_loss * (math.sin(phi_rad) ** 2) / (sigma * cn) - 1.0
        ap_den = 4.0 * f_loss * math.sin(phi_rad) * math.cos(phi_rad) / (sigma * ct) + 1.0
        if abs(a_den) < 1e-8 or abs(ap_den) < 1e-8:
            raise ValueError("singular induction factor")
        a = 1.0 / a_den
        a_prime = 1.0 / ap_den
        if not is_finite_number(a) or not is_finite_number(a_prime) or abs(1.0 - a_prime) < 1e-8:
            raise ValueError("invalid induction factor")
        value = math.tan(phi_rad) - inp.v_inf * (1.0 + a) / max(omega * r_m * (1.0 - a_prime), 1e-30)
        if not is_finite_number(value):
            raise ValueError("invalid residual")
        return value

    bracket = _find_phi_bracket(residual)
    if bracket is None:
        raise ValueError("no phi root found")
    phi_rad = bisection_root(residual, bracket[0], bracket[1], tol=1e-7, max_iter=100)

    beta_rad = math.radians(station.beta_deg)
    alpha_deg = math.degrees(beta_rad - phi_rad)
    speed_guess = math.hypot(inp.v_inf, omega * r_m)
    reynolds_guess = safe_div(inp.rho * speed_guess * chord_m, inp.mu)
    mach_guess = safe_div(speed_guess, inp.sound_speed)
    cl, cd, _cm, _warnings = polar.lookup(alpha_deg, reynolds_guess, mach_guess)
    cn = cl * math.cos(phi_rad) - cd * math.sin(phi_rad)
    ct = cl * math.sin(phi_rad) + cd * math.cos(phi_rad)
    if abs(cn) < 1e-8 or abs(ct) < 1e-8:
        raise ValueError("small force coefficient")
    loss = prandtl_loss_factor(
        inp.blades,
        radius_m,
        hub_radius_m,
        r_m,
        phi_rad,
        inp.use_tip_loss,
        inp.use_hub_loss,
    )
    a = 1.0 / (4.0 * loss * (math.sin(phi_rad) ** 2) / (sigma * cn) - 1.0)
    a_prime = 1.0 / (4.0 * loss * math.sin(phi_rad) * math.cos(phi_rad) / (sigma * ct) + 1.0)
    if not is_finite_number(a) or not is_finite_number(a_prime):
        raise ValueError("invalid induction factor")
    vi = max(inp.v_inf * a, 0.0)
    tangential_factor = clamp(1.0 - a_prime, 0.05, 2.0)
    result = _station_from_velocity(inp, polar, station, r_m, dr_m, vi, loss, tangential_factor)
    return result


def _find_phi_bracket(residual: object) -> tuple[float, float] | None:
    """Scan phi from 1 deg to 89 deg for a sign change."""

    func = residual  # Helps type checkers with callable objects.
    samples = [math.radians(1.0 + i * (88.0 / 88.0)) for i in range(89)]
    previous_phi: float | None = None
    previous_value: float | None = None
    for phi in samples:
        try:
            value = func(phi)  # type: ignore[misc]
        except Exception:
            previous_phi = None
            previous_value = None
            continue
        if not is_finite_number(value):
            previous_phi = None
            previous_value = None
            continue
        if previous_phi is not None and previous_value is not None:
            if previous_value == 0.0:
                return previous_phi, phi
            if previous_value * value <= 0.0:
                return previous_phi, phi
        previous_phi = phi
        previous_value = float(value)
    return None


def _integrate_result(inp: PropellerInput, stations: list[StationResult]) -> PropellerResult:
    """Integrate station loads and calculate propeller coefficients."""

    omega = 2.0 * math.pi * inp.rpm / 60.0
    thrust = sum(st.dT_dr * st.dr_m for st in stations)
    torque = sum(st.dQ_dr * st.dr_m for st in stations)
    power = omega * torque
    n_rev_s = inp.rpm / 60.0
    diameter = inp.diameter_m
    ct = safe_div(thrust, inp.rho * n_rev_s**2 * diameter**4)
    cq = safe_div(torque, inp.rho * n_rev_s**2 * diameter**5)
    cp = safe_div(power, inp.rho * n_rev_s**3 * diameter**5)
    eta = safe_div(thrust * inp.v_inf, power) if power > 0.0 and inp.v_inf > 0.0 else 0.0
    warnings: list[str] = []
    for station in stations:
        warnings.extend(_split_warnings(station.warning))
    if thrust < 0.0:
        warnings.append("Negative total thrust.")
    if power < 0.0:
        warnings.append("Negative shaft power.")
    return PropellerResult(
        input=inp,
        thrust_N=finite_or_default(thrust),
        torque_Nm=finite_or_default(torque),
        power_W=finite_or_default(power),
        eta=finite_or_default(eta),
        ct=finite_or_default(ct),
        cq=finite_or_default(cq),
        cp=finite_or_default(cp),
        stations=[_clean_station(st) for st in stations],
        warnings=_unique(warnings),
    )


def _clean_station(station: StationResult) -> StationResult:
    """Replace invalid station numeric values with zero."""

    return StationResult(
        r_m=finite_or_default(station.r_m),
        r_over_R=finite_or_default(station.r_over_R),
        dr_m=finite_or_default(station.dr_m),
        chord_m=finite_or_default(station.chord_m),
        beta_deg=finite_or_default(station.beta_deg),
        phi_deg=finite_or_default(station.phi_deg),
        alpha_deg=finite_or_default(station.alpha_deg),
        reynolds=finite_or_default(station.reynolds),
        mach=finite_or_default(station.mach),
        cl=finite_or_default(station.cl),
        cd=finite_or_default(station.cd),
        cm=finite_or_default(station.cm),
        vi_mps=finite_or_default(station.vi_mps),
        vt_mps=finite_or_default(station.vt_mps),
        tip_loss_F=finite_or_default(station.tip_loss_F, 1.0),
        dT_dr=finite_or_default(station.dT_dr),
        dQ_dr=finite_or_default(station.dQ_dr),
        dL_dr=finite_or_default(station.dL_dr),
        dD_dr=finite_or_default(station.dD_dr),
        warning=station.warning,
    )


def _split_warnings(text: str) -> list[str]:
    """Split a semicolon-separated warning string."""

    return [part.strip() for part in text.split(";") if part.strip()]


def _unique(items: list[str]) -> list[str]:
    """Return warning strings without duplicates."""

    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
