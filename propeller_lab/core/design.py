"""Early propeller twist design helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .bemt import calculate_propeller
from .geometry import generate_pitch_geometry, validate_geometry
from .models import GeometryStation, PropellerInput, PropellerResult, StationResult
from .numerics import clamp, finite_or_default, is_finite_number, safe_div
from .polar import AirfoilPolar, GenericPolar


@dataclass
class DesignInput:
    """Input parameters for twist design."""

    rpm: float
    v_inf: float
    rho: float
    mu: float
    sound_speed: float
    target_type: str = "none"
    target_value: float = 0.0
    objective: str = "max_ld"
    chord_mode: str = "keep_current"
    alpha_min_deg: float = -4.0
    alpha_max_deg: float = 12.0
    alpha_step_deg: float = 0.25
    stall_margin_deg: float = 2.0
    max_cl_fraction: float = 0.85
    fixed_alpha_deg: float = 5.0
    beta_min_deg: float = 0.0
    beta_max_deg: float = 60.0
    max_tip_mach: float = 0.75
    target_tolerance: float = 0.02
    max_iterations: int = 30
    allow_beta_offset: bool = True


@dataclass
class DesignStationResult:
    """Designed station values."""

    r_over_R: float
    r_m: float
    chord_over_R: float
    chord_m: float
    phi_deg: float
    alpha_design_deg: float
    beta_deg: float
    reynolds: float
    mach: float
    cl: float
    cd: float
    cm: float
    ld: float
    objective_value: float
    warning: str = ""


@dataclass
class DesignResult:
    """Complete twist design result."""

    design_input: DesignInput
    geometry: list[GeometryStation]
    stations: list[DesignStationResult]
    analysis_result: PropellerResult | None
    warnings: list[str]
    diagnostics: dict[str, float | str]


def find_alpha_max_ld(
    polar: AirfoilPolar,
    reynolds: float,
    mach: float,
    alpha_min_deg: float = -4.0,
    alpha_max_deg: float = 12.0,
    alpha_step_deg: float = 0.25,
    stall_margin_deg: float = 2.0,
    max_cl_fraction: float = 0.85,
) -> dict[str, float | list[str]]:
    """Find the scanned alpha with the best positive Cl/Cd."""

    records: list[dict[str, float | list[str]]] = []
    warnings: list[str] = []
    for alpha in _alpha_values(alpha_min_deg, alpha_max_deg, alpha_step_deg):
        cl, cd, cm, polar_warnings = polar.lookup(alpha, reynolds, mach)
        warnings.extend(polar_warnings)
        if not all(is_finite_number(value) for value in (cl, cd, cm)):
            continue
        if cd <= 1e-6 or cl <= 0.0:
            continue
        ld = cl / cd
        if not is_finite_number(ld):
            continue
        records.append(
            {
                "alpha_deg": finite_or_default(alpha),
                "cl": finite_or_default(cl),
                "cd": finite_or_default(cd),
                "cm": finite_or_default(cm),
                "ld": finite_or_default(ld),
                "objective_value": finite_or_default(ld),
                "warnings": list(polar_warnings),
            }
        )
    if not records:
        return _fallback_alpha_result(polar, reynolds, mach, "Could not find max Cl/Cd alpha; used fallback alpha.")

    cl_max = max(float(record["cl"]) for record in records)
    alpha_limit = alpha_max_deg - max(stall_margin_deg, 0.0)
    cl_limit = max_cl_fraction * cl_max if cl_max > 0.0 and max_cl_fraction > 0.0 else cl_max
    candidates = [
        record
        for record in records
        if float(record["alpha_deg"]) <= alpha_limit and float(record["cl"]) <= cl_limit
    ]
    if not candidates:
        candidates = [record for record in records if float(record["alpha_deg"]) <= alpha_limit]
    if not candidates:
        candidates = [record for record in records if float(record["cl"]) <= cl_limit]
    if not candidates:
        candidates = records
    best = max(candidates, key=lambda record: float(record["objective_value"]))
    return _clean_alpha_result(best, warnings)


def find_alpha_for_local_efficiency(
    polar: AirfoilPolar,
    reynolds: float,
    mach: float,
    phi_rad: float,
    alpha_min_deg: float = -4.0,
    alpha_max_deg: float = 12.0,
    alpha_step_deg: float = 0.25,
) -> dict[str, float | list[str]]:
    """Find alpha maximizing a local thrust-to-torque coefficient ratio."""

    records: list[dict[str, float | list[str]]] = []
    warnings: list[str] = []
    sin_phi = math.sin(phi_rad)
    cos_phi = math.cos(phi_rad)
    for alpha in _alpha_values(alpha_min_deg, alpha_max_deg, alpha_step_deg):
        cl, cd, cm, polar_warnings = polar.lookup(alpha, reynolds, mach)
        warnings.extend(polar_warnings)
        if not all(is_finite_number(value) for value in (cl, cd, cm)):
            continue
        numerator = cl * cos_phi - cd * sin_phi
        denominator = cl * sin_phi + cd * cos_phi
        if denominator <= 1e-8 or numerator <= 0.0 or cd <= 1e-6:
            continue
        objective = numerator / denominator
        ld = cl / cd
        if not all(is_finite_number(value) for value in (objective, ld)):
            continue
        records.append(
            {
                "alpha_deg": finite_or_default(alpha),
                "cl": finite_or_default(cl),
                "cd": finite_or_default(cd),
                "cm": finite_or_default(cm),
                "ld": finite_or_default(ld),
                "objective_value": finite_or_default(objective),
                "warnings": list(polar_warnings),
            }
        )
    if not records:
        result = find_alpha_max_ld(polar, reynolds, mach, alpha_min_deg, alpha_max_deg, alpha_step_deg)
        result["warnings"] = _unique(
            list(result.get("warnings", [])) + ["Local efficiency objective had no valid point; used max Cl/Cd."]
        )
        return result
    best = max(records, key=lambda record: float(record["objective_value"]))
    return _clean_alpha_result(best, warnings)


def find_alpha_design(
    polar: AirfoilPolar,
    reynolds: float,
    mach: float,
    phi_rad: float,
    design_input: DesignInput,
) -> dict[str, float | list[str]]:
    """Dispatch the alpha design objective."""

    if design_input.objective == "fixed_alpha":
        alpha = clamp(design_input.fixed_alpha_deg, -90.0, 90.0)
        cl, cd, cm, warnings = polar.lookup(alpha, reynolds, mach)
        ld = safe_div(cl, cd)
        return {
            "alpha_deg": finite_or_default(alpha),
            "cl": finite_or_default(cl),
            "cd": finite_or_default(cd),
            "cm": finite_or_default(cm),
            "ld": finite_or_default(ld),
            "objective_value": finite_or_default(ld),
            "warnings": _unique(warnings),
        }
    if design_input.objective == "max_local_efficiency":
        return find_alpha_for_local_efficiency(
            polar,
            reynolds,
            mach,
            phi_rad,
            design_input.alpha_min_deg,
            design_input.alpha_max_deg,
            design_input.alpha_step_deg,
        )
    return find_alpha_max_ld(
        polar,
        reynolds,
        mach,
        design_input.alpha_min_deg,
        design_input.alpha_max_deg,
        design_input.alpha_step_deg,
        design_input.stall_margin_deg,
        design_input.max_cl_fraction,
    )


def estimate_inflow_for_design(
    prop_input: PropellerInput,
    station: GeometryStation,
    polar: AirfoilPolar,
    base_analysis_result: PropellerResult | None = None,
) -> dict[str, float | list[str]]:
    """Estimate local inflow state for one design station."""

    del polar
    warnings: list[str] = []
    if base_analysis_result is not None and base_analysis_result.stations:
        nearest = min(base_analysis_result.stations, key=lambda item: abs(item.r_over_R - station.r_over_R))
        phi_deg = clamp(nearest.phi_deg, 0.5, 80.0)
        return {
            "phi_rad": finite_or_default(math.radians(phi_deg)),
            "reynolds": finite_or_default(nearest.reynolds),
            "mach": finite_or_default(nearest.mach),
            "vi_mps": finite_or_default(nearest.vi_mps),
            "vt_mps": finite_or_default(nearest.vt_mps),
            "warnings": _split_warnings(nearest.warning),
        }

    radius_m = prop_input.diameter_m / 2.0
    r_m = station.r_over_R * radius_m
    chord_m = station.chord_over_R * radius_m
    omega = 2.0 * math.pi * prop_input.rpm / 60.0
    wa = prop_input.v_inf
    wt = omega * r_m
    speed = math.hypot(wa, wt)
    phi = math.radians(clamp(math.degrees(math.atan2(wa, wt)), 0.5, 80.0))
    reynolds = safe_div(prop_input.rho * speed * chord_m, prop_input.mu)
    mach = safe_div(speed, prop_input.sound_speed)
    if prop_input.v_inf <= 0.0:
        warnings.append("Static design used kinematic fallback inflow estimate.")
    return {
        "phi_rad": finite_or_default(phi),
        "reynolds": finite_or_default(reynolds),
        "mach": finite_or_default(mach),
        "vi_mps": 0.0,
        "vt_mps": finite_or_default(wt),
        "warnings": warnings,
    }


def design_twist_for_alpha_objective(
    prop_input: PropellerInput,
    design_input: DesignInput,
    polar: AirfoilPolar | None = None,
    base_geometry: list[GeometryStation] | None = None,
) -> DesignResult:
    """Design twist from local inflow and an alpha objective."""

    polar_model = polar if polar is not None else GenericPolar()
    geometry = clone_geometry(base_geometry) if base_geometry is not None else generate_pitch_geometry(prop_input)
    validate_geometry(geometry)
    analysis_input = _analysis_input(prop_input, design_input)
    warnings: list[str] = []
    try:
        base_analysis = calculate_propeller(analysis_input, polar=polar_model, geometry=geometry)
        warnings.extend(base_analysis.warnings)
    except Exception as exc:  # noqa: BLE001 - design should remain usable.
        base_analysis = None
        warnings.append(f"Base geometry analysis failed during design: {exc}")

    design_stations = _build_design_stations(
        analysis_input,
        design_input,
        polar_model,
        geometry,
        base_analysis,
        beta_offset_deg=0.0,
    )
    designed_geometry = geometry_from_design_stations(design_stations)
    designed_geometry = smooth_beta_distribution(
        designed_geometry,
        beta_min_deg=design_input.beta_min_deg,
        beta_max_deg=design_input.beta_max_deg,
    )
    design_stations = _replace_station_betas(design_stations, designed_geometry)
    analysis_result = _analyze_design_geometry(analysis_input, polar_model, designed_geometry, warnings)
    warnings.extend(_station_warning_list(design_stations))
    diagnostics = _design_diagnostics(design_input, design_stations, analysis_result)
    return _clean_design_result(DesignResult(design_input, designed_geometry, design_stations, analysis_result, _unique(warnings), diagnostics))


def design_twist_with_target(
    prop_input: PropellerInput,
    design_input: DesignInput,
    polar: AirfoilPolar | None = None,
    base_geometry: list[GeometryStation] | None = None,
) -> DesignResult:
    """Design twist and optionally match a thrust or power target with beta offset."""

    if design_input.target_type == "none" or not design_input.allow_beta_offset or design_input.target_value <= 0.0:
        return design_twist_for_alpha_objective(prop_input, design_input, polar, base_geometry)

    polar_model = polar if polar is not None else GenericPolar()
    base_result = design_twist_for_alpha_objective(prop_input, design_input, polar_model, base_geometry)
    analysis_input = _analysis_input(prop_input, design_input)
    base_geometry_for_offset = clone_geometry(base_result.geometry)
    target = design_input.target_value

    def evaluate(offset: float) -> tuple[float, DesignResult]:
        geometry = apply_beta_offset(base_geometry_for_offset, offset, design_input.beta_min_deg, design_input.beta_max_deg)
        analysis_result = _analyze_design_geometry(analysis_input, polar_model, geometry, [])
        value = _target_metric(analysis_result, design_input.target_type)
        error = safe_div(value - target, target)
        stations = _stations_from_geometry_and_analysis(base_result.stations, geometry, analysis_result)
        diagnostics = _design_diagnostics(design_input, stations, analysis_result)
        diagnostics["target_error_fraction"] = finite_or_default(error)
        result = DesignResult(
            design_input=design_input,
            geometry=geometry,
            stations=stations,
            analysis_result=analysis_result,
            warnings=list(base_result.warnings),
            diagnostics=diagnostics,
        )
        return error, _clean_design_result(result)

    samples: list[tuple[float, float, DesignResult]] = []
    for offset in (-10.0, -5.0, 0.0, 5.0, 10.0, 15.0):
        error, result = evaluate(offset)
        samples.append((offset, error, result))
    best = min(samples, key=lambda item: abs(item[1]))
    bracket: tuple[float, float] | None = None
    for left, right in zip(samples, samples[1:]):
        if left[1] == 0.0 or left[1] * right[1] <= 0.0:
            bracket = (left[0], right[0])
            break
    if bracket is None:
        result = best[2]
        result.warnings = _unique(result.warnings + ["Target could not be bracketed by beta offset; returned best effort design."])
        return result

    lo, hi = bracket
    lo_error, lo_result = evaluate(lo)
    hi_error, hi_result = evaluate(hi)
    best_result = lo_result if abs(lo_error) <= abs(hi_error) else hi_result
    for _ in range(max(design_input.max_iterations, 1)):
        mid = 0.5 * (lo + hi)
        mid_error, mid_result = evaluate(mid)
        best_error = float(best_result.diagnostics.get("target_error_fraction", 1e9))
        if abs(mid_error) < abs(best_error):
            best_result = mid_result
        if abs(mid_error) <= design_input.target_tolerance:
            best_result = mid_result
            break
        if lo_error * mid_error <= 0.0:
            hi = mid
            hi_error = mid_error
        else:
            lo = mid
            lo_error = mid_error
    return best_result


def smooth_beta_distribution(
    geometry: list[GeometryStation],
    smoothing_strength: float = 0.25,
    beta_min_deg: float = 0.0,
    beta_max_deg: float = 60.0,
) -> list[GeometryStation]:
    """Smooth interior beta values while preserving endpoints."""

    if len(geometry) < 3:
        return [
            GeometryStation(st.r_over_R, st.chord_over_R, clamp(st.beta_deg, beta_min_deg, beta_max_deg), st.airfoil_id)
            for st in geometry
        ]
    out = clone_geometry(geometry)
    strength = clamp(smoothing_strength, 0.0, 1.0)
    for _ in range(2):
        previous = clone_geometry(out)
        for idx in range(1, len(out) - 1):
            neighbor_avg = 0.5 * (previous[idx - 1].beta_deg + previous[idx + 1].beta_deg)
            beta = (1.0 - strength) * previous[idx].beta_deg + strength * neighbor_avg
            out[idx].beta_deg = clamp(beta, beta_min_deg, beta_max_deg)
    out[0].beta_deg = clamp(geometry[0].beta_deg, beta_min_deg, beta_max_deg)
    out[-1].beta_deg = clamp(geometry[-1].beta_deg, beta_min_deg, beta_max_deg)
    return out


def apply_beta_offset(
    geometry: list[GeometryStation],
    offset_deg: float,
    beta_min_deg: float,
    beta_max_deg: float,
) -> list[GeometryStation]:
    """Return a geometry copy with a global beta offset."""

    return [
        GeometryStation(
            r_over_R=station.r_over_R,
            chord_over_R=station.chord_over_R,
            beta_deg=finite_or_default(clamp(station.beta_deg + offset_deg, beta_min_deg, beta_max_deg)),
            airfoil_id=station.airfoil_id,
        )
        for station in geometry
    ]


def clone_geometry(geometry: list[GeometryStation]) -> list[GeometryStation]:
    """Return a deep enough geometry copy."""

    return [
        GeometryStation(station.r_over_R, station.chord_over_R, station.beta_deg, station.airfoil_id)
        for station in geometry
    ]


def geometry_from_design_stations(stations: list[DesignStationResult]) -> list[GeometryStation]:
    """Build GeometryStation objects from design station rows."""

    return [
        GeometryStation(
            r_over_R=station.r_over_R,
            chord_over_R=station.chord_over_R,
            beta_deg=station.beta_deg,
            airfoil_id="designed",
        )
        for station in stations
    ]


def _build_design_stations(
    prop_input: PropellerInput,
    design_input: DesignInput,
    polar: AirfoilPolar,
    geometry: list[GeometryStation],
    base_analysis_result: PropellerResult | None,
    beta_offset_deg: float,
) -> list[DesignStationResult]:
    """Build station rows for a beta-offset design."""

    radius_m = prop_input.diameter_m / 2.0
    rows: list[DesignStationResult] = []
    for station in geometry:
        inflow = estimate_inflow_for_design(prop_input, station, polar, base_analysis_result)
        phi_rad = float(inflow["phi_rad"])
        reynolds = float(inflow["reynolds"])
        mach = float(inflow["mach"])
        alpha_result = find_alpha_design(polar, reynolds, mach, phi_rad, design_input)
        alpha_design = float(alpha_result["alpha_deg"])
        warning_parts = list(inflow.get("warnings", [])) + list(alpha_result.get("warnings", []))
        if station.r_over_R < 0.25:
            warning_parts.append("Root region uses smoothed transition; 2D airfoil optimum is not reliable near hub.")
            alpha_design = min(alpha_design, design_input.fixed_alpha_deg)
        beta = math.degrees(phi_rad) + alpha_design + beta_offset_deg
        beta = clamp(beta, design_input.beta_min_deg, design_input.beta_max_deg)
        if mach > design_input.max_tip_mach:
            warning_parts.append("Local Mach exceeds design limit.")
        if reynolds < 50000.0:
            warning_parts.append("Low Reynolds number in design station.")
        if _near_alpha_boundary(alpha_design, design_input):
            warning_parts.append("Selected alpha is near polar/design alpha boundary; extend polar range.")
        chord_over_R = _design_chord(station, geometry, design_input)
        chord_m = chord_over_R * radius_m
        rows.append(
            DesignStationResult(
                r_over_R=finite_or_default(station.r_over_R),
                r_m=finite_or_default(station.r_over_R * radius_m),
                chord_over_R=finite_or_default(chord_over_R),
                chord_m=finite_or_default(chord_m),
                phi_deg=finite_or_default(math.degrees(phi_rad)),
                alpha_design_deg=finite_or_default(alpha_design),
                beta_deg=finite_or_default(beta),
                reynolds=finite_or_default(reynolds),
                mach=finite_or_default(mach),
                cl=finite_or_default(float(alpha_result["cl"])),
                cd=finite_or_default(float(alpha_result["cd"])),
                cm=finite_or_default(float(alpha_result["cm"])),
                ld=finite_or_default(float(alpha_result["ld"])),
                objective_value=finite_or_default(float(alpha_result["objective_value"])),
                warning="; ".join(_unique(warning_parts)),
            )
        )
    return rows


def _replace_station_betas(
    rows: list[DesignStationResult],
    geometry: list[GeometryStation],
) -> list[DesignStationResult]:
    """Copy smoothed beta values back into station rows."""

    return [replace(row, beta_deg=geometry[idx].beta_deg) for idx, row in enumerate(rows)]


def _stations_from_geometry_and_analysis(
    base_rows: list[DesignStationResult],
    geometry: list[GeometryStation],
    analysis_result: PropellerResult | None,
) -> list[DesignStationResult]:
    """Refresh beta and analysis-derived values after beta offset."""

    out: list[DesignStationResult] = []
    analysis_stations = analysis_result.stations if analysis_result is not None else []
    for idx, row in enumerate(base_rows):
        geometry_station = geometry[idx]
        if analysis_stations:
            nearest = min(analysis_stations, key=lambda item: abs(item.r_over_R - row.r_over_R))
            out.append(
                replace(
                    row,
                    beta_deg=geometry_station.beta_deg,
                    phi_deg=nearest.phi_deg,
                    reynolds=nearest.reynolds,
                    mach=nearest.mach,
                    cl=nearest.cl,
                    cd=nearest.cd,
                    cm=nearest.cm,
                    ld=safe_div(nearest.cl, nearest.cd),
                    warning="; ".join(_unique(_split_warnings(row.warning) + _split_warnings(nearest.warning))),
                )
            )
        else:
            out.append(replace(row, beta_deg=geometry_station.beta_deg))
    return out


def _analysis_input(prop_input: PropellerInput, design_input: DesignInput) -> PropellerInput:
    """Return a propeller input for the requested design condition."""

    return replace(
        prop_input,
        rpm=design_input.rpm,
        v_inf=design_input.v_inf,
        rho=design_input.rho,
        mu=design_input.mu,
        sound_speed=design_input.sound_speed,
        calculation_mode="auto",
    )


def _analyze_design_geometry(
    prop_input: PropellerInput,
    polar: AirfoilPolar,
    geometry: list[GeometryStation],
    warnings: list[str],
) -> PropellerResult | None:
    """Analyze a designed geometry and collect warnings on failure."""

    try:
        return calculate_propeller(prop_input, polar=polar, geometry=geometry)
    except Exception as exc:  # noqa: BLE001 - design result can carry warnings.
        warnings.append(f"Designed geometry analysis failed: {exc}")
        return None


def _design_diagnostics(
    design_input: DesignInput,
    stations: list[DesignStationResult],
    analysis_result: PropellerResult | None,
) -> dict[str, float | str]:
    """Return design diagnostics."""

    thrust = analysis_result.thrust_N if analysis_result is not None else 0.0
    torque = analysis_result.torque_Nm if analysis_result is not None else 0.0
    power = analysis_result.power_W if analysis_result is not None else 0.0
    eta = analysis_result.eta if analysis_result is not None else 0.0
    ct = analysis_result.ct if analysis_result is not None else 0.0
    cp = analysis_result.cp if analysis_result is not None else 0.0
    diagnostics: dict[str, float | str] = {
        "objective": design_input.objective,
        "target_type": design_input.target_type,
        "requested_rpm": finite_or_default(design_input.rpm),
        "requested_v_inf": finite_or_default(design_input.v_inf),
        "predicted_thrust_N": finite_or_default(thrust),
        "predicted_torque_Nm": finite_or_default(torque),
        "predicted_power_W": finite_or_default(power),
        "predicted_eta": finite_or_default(eta),
        "predicted_CT": finite_or_default(ct),
        "predicted_CP": finite_or_default(cp),
        "max_beta_deg": finite_or_default(max((st.beta_deg for st in stations), default=0.0)),
        "min_beta_deg": finite_or_default(min((st.beta_deg for st in stations), default=0.0)),
        "max_alpha_design_deg": finite_or_default(max((st.alpha_design_deg for st in stations), default=0.0)),
        "min_alpha_design_deg": finite_or_default(min((st.alpha_design_deg for st in stations), default=0.0)),
        "max_mach": finite_or_default(max((st.mach for st in stations), default=0.0)),
        "max_reynolds": finite_or_default(max((st.reynolds for st in stations), default=0.0)),
        "min_reynolds": finite_or_default(min((st.reynolds for st in stations), default=0.0)),
        "stations_with_warnings": finite_or_default(sum(1 for st in stations if st.warning)),
    }
    if design_input.target_type != "none" and design_input.target_value > 0.0:
        metric = thrust if design_input.target_type == "thrust" else power
        diagnostics["target_error_fraction"] = finite_or_default(safe_div(metric - design_input.target_value, design_input.target_value))
    else:
        diagnostics["target_error_fraction"] = 0.0
    return diagnostics


def _target_metric(analysis_result: PropellerResult | None, target_type: str) -> float:
    """Return thrust or power from an analysis result."""

    if analysis_result is None:
        return 0.0
    if target_type == "power":
        return finite_or_default(analysis_result.power_W)
    return finite_or_default(analysis_result.thrust_N)


def _design_chord(
    station: GeometryStation,
    geometry: list[GeometryStation],
    design_input: DesignInput,
) -> float:
    """Return chord/R for a design station."""

    if design_input.chord_mode != "linear" or len(geometry) < 2:
        return station.chord_over_R
    first = geometry[0]
    last = geometry[-1]
    t = safe_div(station.r_over_R - first.r_over_R, last.r_over_R - first.r_over_R)
    return finite_or_default(first.chord_over_R + t * (last.chord_over_R - first.chord_over_R))


def _near_alpha_boundary(alpha_deg: float, design_input: DesignInput) -> bool:
    """Return True when alpha is near the scan limits."""

    margin = max(abs(design_input.alpha_step_deg), 0.25)
    return alpha_deg <= design_input.alpha_min_deg + margin or alpha_deg >= design_input.alpha_max_deg - margin


def _alpha_values(alpha_min_deg: float, alpha_max_deg: float, alpha_step_deg: float) -> list[float]:
    """Return inclusive alpha scan values."""

    lo = min(alpha_min_deg, alpha_max_deg)
    hi = max(alpha_min_deg, alpha_max_deg)
    step = max(abs(alpha_step_deg), 1e-6)
    values: list[float] = []
    alpha = lo
    guard = 0
    while alpha <= hi + 1e-9 and guard < 10000:
        values.append(finite_or_default(alpha))
        alpha += step
        guard += 1
    if not values or abs(values[-1] - hi) > 1e-9:
        values.append(hi)
    return values


def _fallback_alpha_result(
    polar: AirfoilPolar,
    reynolds: float,
    mach: float,
    warning: str,
) -> dict[str, float | list[str]]:
    """Return a finite fallback alpha result."""

    alpha = 4.0
    cl, cd, cm, warnings = polar.lookup(alpha, reynolds, mach)
    ld = safe_div(cl, cd)
    return {
        "alpha_deg": alpha,
        "cl": finite_or_default(cl),
        "cd": finite_or_default(cd, 0.01),
        "cm": finite_or_default(cm),
        "ld": finite_or_default(ld),
        "objective_value": finite_or_default(ld),
        "warnings": _unique(warnings + [warning]),
    }


def _clean_alpha_result(
    record: dict[str, float | list[str]],
    extra_warnings: list[str],
) -> dict[str, float | list[str]]:
    """Return alpha result with finite numeric fields."""

    return {
        "alpha_deg": finite_or_default(float(record["alpha_deg"])),
        "cl": finite_or_default(float(record["cl"])),
        "cd": finite_or_default(float(record["cd"])),
        "cm": finite_or_default(float(record["cm"])),
        "ld": finite_or_default(float(record["ld"])),
        "objective_value": finite_or_default(float(record["objective_value"])),
        "warnings": _unique(extra_warnings + list(record.get("warnings", []))),
    }


def _clean_design_result(result: DesignResult) -> DesignResult:
    """Replace invalid numeric design values with finite defaults."""

    clean_stations = [
        DesignStationResult(
            r_over_R=finite_or_default(st.r_over_R),
            r_m=finite_or_default(st.r_m),
            chord_over_R=finite_or_default(st.chord_over_R),
            chord_m=finite_or_default(st.chord_m),
            phi_deg=finite_or_default(st.phi_deg),
            alpha_design_deg=finite_or_default(st.alpha_design_deg),
            beta_deg=finite_or_default(st.beta_deg),
            reynolds=finite_or_default(st.reynolds),
            mach=finite_or_default(st.mach),
            cl=finite_or_default(st.cl),
            cd=finite_or_default(st.cd),
            cm=finite_or_default(st.cm),
            ld=finite_or_default(st.ld),
            objective_value=finite_or_default(st.objective_value),
            warning=st.warning,
        )
        for st in result.stations
    ]
    clean_geometry = [
        GeometryStation(
            r_over_R=finite_or_default(st.r_over_R),
            chord_over_R=finite_or_default(st.chord_over_R),
            beta_deg=finite_or_default(st.beta_deg),
            airfoil_id=st.airfoil_id,
        )
        for st in result.geometry
    ]
    clean_diagnostics = {
        key: finite_or_default(value) if isinstance(value, float) else value
        for key, value in result.diagnostics.items()
    }
    return DesignResult(
        design_input=result.design_input,
        geometry=clean_geometry,
        stations=clean_stations,
        analysis_result=result.analysis_result,
        warnings=_unique(result.warnings),
        diagnostics=clean_diagnostics,
    )


def _station_warning_list(stations: list[DesignStationResult]) -> list[str]:
    """Collect warnings from design stations."""

    warnings: list[str] = []
    for station in stations:
        warnings.extend(_split_warnings(station.warning))
    return _unique(warnings)


def _split_warnings(text: object) -> list[str]:
    """Split semicolon-separated warnings."""

    return [part.strip() for part in str(text or "").split(";") if part.strip()]


def _unique(items: list[str]) -> list[str]:
    """Return strings without duplicates."""

    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
