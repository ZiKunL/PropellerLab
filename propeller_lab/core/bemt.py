"""Blade-element and BEMT propeller calculations."""

from __future__ import annotations

import math
from dataclasses import replace

from .geometry import generate_pitch_geometry, validate_geometry
from .models import GeometryStation, PropellerInput, PropellerResult, StationResult
from .numerics import (
    bisection_root,
    clamp,
    finite_or_default,
    is_finite_number,
    safe_div,
    solve_positive_bracketed_root,
)
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

    requested_mode = inp.calculation_mode
    actual_mode = select_solver(inp)
    extra_warnings: list[str] = []
    normalized_request = _normalize_mode(requested_mode)
    if normalized_request == "bemt_phi_forward" and actual_mode == "bemt_hover_dimensional":
        extra_warnings.append(
            "Low-speed condition: forward-flight phi-BEMT was replaced by dimensional low-speed BEMT."
        )

    if actual_mode == "simple":
        station_results = calculate_simple(inp, polar_model, stations)
    elif actual_mode == "simple_induced":
        station_results = calculate_simple_induced(inp, polar_model, stations)
    elif actual_mode == "bemt_phi_forward":
        station_results = calculate_bemt_phi_forward(inp, polar_model, stations)
    elif actual_mode == "bemt_hover_dimensional":
        station_results = calculate_bemt_hover_dimensional(inp, polar_model, stations)
    else:
        raise ValueError(f"Unknown calculation_mode: {inp.calculation_mode}")
    return _integrate_result(inp, station_results, requested_mode, actual_mode, extra_warnings)


def select_solver(inp: PropellerInput) -> str:
    """Select the actual solver mode for the requested input."""

    mode = _normalize_mode(inp.calculation_mode)
    if mode in ("simple", "simple_induced", "bemt_hover_dimensional"):
        return mode
    if mode == "auto":
        metrics = _advance_metrics(inp)
        if inp.v_inf < 0.5 or metrics["J"] < 0.05 or metrics["mu_adv"] < 0.03:
            return "bemt_hover_dimensional"
        return "bemt_phi_forward"
    if mode == "bemt_phi_forward":
        metrics = _advance_metrics(inp)
        if inp.v_inf < 0.5 or metrics["J"] < 0.05 or metrics["mu_adv"] < 0.03:
            return "bemt_hover_dimensional"
        return "bemt_phi_forward"
    raise ValueError(f"Unknown calculation_mode: {inp.calculation_mode}")


def _normalize_mode(mode: str) -> str:
    """Normalize old calculation mode names."""

    if mode == "bemt_phi":
        return "bemt_phi_forward"
    return mode


def _advance_metrics(inp: PropellerInput) -> dict[str, float]:
    """Return nondimensional advance metrics."""

    n_rev_s = inp.rpm / 60.0
    radius_m = inp.diameter_m / 2.0
    omega = 2.0 * math.pi * n_rev_s
    return {
        "J": safe_div(inp.v_inf, n_rev_s * inp.diameter_m),
        "mu_adv": safe_div(inp.v_inf, omega * radius_m),
    }


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
    """Backward-compatible alias for the forward-flight phi solver."""

    return calculate_bemt_phi_forward(inp, polar, geometry)


def calculate_bemt_phi_forward(
    inp: PropellerInput,
    polar: AirfoilPolar,
    geometry: list[GeometryStation],
) -> list[StationResult]:
    """Calculate stations with a forward-flight phi-based BEMT solve."""

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


def calculate_bemt_hover_dimensional(
    inp: PropellerInput,
    polar: AirfoilPolar,
    geometry: list[GeometryStation],
) -> list[StationResult]:
    """Calculate stations by solving dimensional axial induced velocity."""

    geometry_data = _prepare_geometry(inp, geometry)
    return [_hover_dimensional_station(inp, polar, station, r_m, dr_m) for station, r_m, dr_m in geometry_data]


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

    sin_phi = max(abs(math.sin(phi_rad)), 1e-4)
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
            warnings.append("Negative local thrust; induced velocity set to zero.")
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


def _hover_dimensional_station(
    inp: PropellerInput,
    polar: AirfoilPolar,
    station: GeometryStation,
    r_m: float,
    dr_m: float,
) -> StationResult:
    """Solve dimensional vi for one low-speed station."""

    radius_m = inp.diameter_m / 2.0
    omega = 2.0 * math.pi * inp.rpm / 60.0
    initial_hi = max(1.0, 0.10 * omega * radius_m)
    max_hi = min(200.0, 0.80 * omega * radius_m)
    if max_hi <= 0.0:
        return _induced_station(
            inp,
            polar,
            station,
            r_m,
            dr_m,
            "Dimensional low-speed vi solve failed; used relaxed induced fallback.",
        )
    if initial_hi >= max_hi:
        initial_hi = max(max_hi * 0.5, 1e-6)

    def residual(vi_mps: float) -> float:
        data = _hover_dimensional_values(inp, polar, station, r_m, dr_m, vi_mps)
        return data["dT_be_dr"] - data["dT_mom_dr"]

    try:
        vi = solve_positive_bracketed_root(
            residual,
            0.0,
            initial_hi,
            max_hi,
            tol=1e-6,
            max_iter=100,
        )
        return _hover_station_from_vi(inp, polar, station, r_m, dr_m, vi, "")
    except Exception:  # noqa: BLE001 - station fallback keeps the solver robust.
        return _induced_station(
            inp,
            polar,
            station,
            r_m,
            dr_m,
            "Dimensional low-speed vi solve failed; used relaxed induced fallback.",
        )


def _hover_station_from_vi(
    inp: PropellerInput,
    polar: AirfoilPolar,
    station: GeometryStation,
    r_m: float,
    dr_m: float,
    vi_mps: float,
    prefix_warning: str,
) -> StationResult:
    """Build a station result from a solved low-speed vi value."""

    data = _hover_dimensional_values(inp, polar, station, r_m, dr_m, vi_mps)
    warnings = [prefix_warning] if prefix_warning else []
    warnings.extend(data["warnings"])
    if abs(data["alpha_deg"]) > 12.0:
        warnings.append("High angle of attack: possible stall.")
    if data["reynolds"] < 50000.0:
        warnings.append("Low Reynolds number.")
    if data["mach"] > 0.6:
        warnings.append("High Mach number.")
    if data["dT_be_dr"] < 0.0:
        warnings.append("Negative local thrust.")
    return _clean_station(
        StationResult(
            r_m=r_m,
            r_over_R=station.r_over_R,
            dr_m=dr_m,
            chord_m=data["chord_m"],
            beta_deg=station.beta_deg,
            phi_deg=data["phi_deg"],
            alpha_deg=data["alpha_deg"],
            reynolds=data["reynolds"],
            mach=data["mach"],
            cl=data["cl"],
            cd=data["cd"],
            cm=data["cm"],
            vi_mps=vi_mps,
            vt_mps=data["vt_mps"],
            tip_loss_F=data["loss_factor"],
            dT_dr=data["dT_be_dr"],
            dQ_dr=data["dQ_be_dr"],
            dL_dr=data["dL_dr"],
            dD_dr=data["dD_dr"],
            warning="; ".join(_unique(warnings)),
        )
    )


def _hover_dimensional_values(
    inp: PropellerInput,
    polar: AirfoilPolar,
    station: GeometryStation,
    r_m: float,
    dr_m: float,
    vi_mps: float,
) -> dict[str, float | list[str]]:
    """Return local low-speed BEMT values for a candidate vi."""

    del dr_m
    radius_m = inp.diameter_m / 2.0
    hub_radius_m = inp.hub_diameter_m / 2.0
    omega = 2.0 * math.pi * inp.rpm / 60.0
    chord_m = station.chord_over_R * radius_m
    beta_rad = math.radians(station.beta_deg)
    wa = inp.v_inf + vi_mps
    wt = omega * r_m
    speed = math.hypot(wa, wt)
    phi_rad = math.atan2(wa, wt)
    alpha_deg = math.degrees(beta_rad - phi_rad)
    reynolds = safe_div(inp.rho * speed * chord_m, inp.mu)
    mach = safe_div(speed, inp.sound_speed)
    cl, cd, cm, polar_warnings = polar.lookup(alpha_deg, reynolds, mach)
    q = 0.5 * inp.rho * speed * speed
    dL_dr = q * chord_m * cl
    dD_dr = q * chord_m * cd
    dT_be_dr = inp.blades * (dL_dr * math.cos(phi_rad) - dD_dr * math.sin(phi_rad))
    dQ_be_dr = inp.blades * r_m * (dL_dr * math.sin(phi_rad) + dD_dr * math.cos(phi_rad))
    loss_factor = prandtl_loss_factor(
        inp.blades,
        radius_m,
        hub_radius_m,
        r_m,
        phi_rad,
        inp.use_tip_loss,
        inp.use_hub_loss,
    )
    dT_mom_dr = 4.0 * math.pi * inp.rho * loss_factor * r_m * vi_mps * (inp.v_inf + vi_mps)
    values: dict[str, float | list[str]] = {
        "chord_m": finite_or_default(chord_m),
        "phi_deg": finite_or_default(math.degrees(phi_rad)),
        "alpha_deg": finite_or_default(alpha_deg),
        "reynolds": finite_or_default(reynolds),
        "mach": finite_or_default(mach),
        "cl": finite_or_default(cl),
        "cd": finite_or_default(cd),
        "cm": finite_or_default(cm),
        "vt_mps": finite_or_default(wt),
        "loss_factor": finite_or_default(loss_factor, 1.0),
        "dL_dr": finite_or_default(dL_dr),
        "dD_dr": finite_or_default(dD_dr),
        "dT_be_dr": finite_or_default(dT_be_dr),
        "dQ_be_dr": finite_or_default(dQ_be_dr),
        "dT_mom_dr": finite_or_default(dT_mom_dr),
        "warnings": polar_warnings,
    }
    for key, value in values.items():
        if key != "warnings" and not is_finite_number(value):
            raise ValueError("Invalid low-speed station value.")
    return values


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
        if (
            not is_finite_number(a)
            or not is_finite_number(a_prime)
            or abs(a) > 2.0
            or abs(a_prime) > 2.0
            or abs(1.0 - a_prime) < 1e-8
        ):
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
    if not is_finite_number(a) or not is_finite_number(a_prime) or abs(a) > 2.0 or abs(a_prime) > 2.0:
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


def _integrate_result(
    inp: PropellerInput,
    stations: list[StationResult],
    requested_mode: str,
    actual_mode: str,
    extra_warnings: list[str] | None = None,
) -> PropellerResult:
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
    warnings.extend(extra_warnings or [])
    for station in stations:
        warnings.extend(_split_warnings(station.warning))
    if thrust < 0.0:
        warnings.append("Negative total thrust.")
    if power < 0.0:
        warnings.append("Negative shaft power.")
    clean_stations = [_clean_station(st) for st in stations]
    return PropellerResult(
        input=inp,
        thrust_N=finite_or_default(thrust),
        torque_Nm=finite_or_default(torque),
        power_W=finite_or_default(power),
        eta=finite_or_default(eta),
        ct=finite_or_default(ct),
        cq=finite_or_default(cq),
        cp=finite_or_default(cp),
        stations=clean_stations,
        warnings=_unique(warnings),
        diagnostics=_diagnostics(inp, clean_stations, requested_mode, actual_mode),
    )


def _diagnostics(
    inp: PropellerInput,
    stations: list[StationResult],
    requested_mode: str,
    actual_mode: str,
) -> dict[str, float | str]:
    """Return summary diagnostics for solver selection and station health."""

    metrics = _advance_metrics(inp)
    count = max(len(stations), 1)
    fallback_count = sum(
        1
        for station in stations
        if "fallback" in station.warning.lower() or "vi solve failed" in station.warning.lower()
    )
    return {
        "requested_mode": requested_mode,
        "actual_mode": actual_mode,
        "J": finite_or_default(metrics["J"]),
        "mu_adv": finite_or_default(metrics["mu_adv"]),
        "max_alpha_deg": finite_or_default(max((abs(st.alpha_deg) for st in stations), default=0.0)),
        "stall_station_fraction": finite_or_default(
            sum(1 for st in stations if abs(st.alpha_deg) > 12.0) / count
        ),
        "low_re_station_fraction": finite_or_default(
            sum(1 for st in stations if st.reynolds < 50000.0) / count
        ),
        "negative_thrust_station_fraction": finite_or_default(
            sum(1 for st in stations if st.dT_dr < 0.0) / count
        ),
        "max_vi_mps": finite_or_default(max((st.vi_mps for st in stations), default=0.0)),
        "solver_fallback_fraction": finite_or_default(fallback_count / count),
    }


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
