"""Target-based propeller geometry optimization."""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass, replace

from .bemt import calculate_propeller
from .geometry import validate_geometry
from .models import GeometryStation, PropellerInput, PropellerResult
from .numerics import clamp, finite_or_default, is_finite_number, safe_div
from .polar import AirfoilPolar, GenericPolar, normalize_airfoil_id

ProgressCallback = Callable[[int, int, object], None]
StopCallback = Callable[[], bool]

LARGE_FITNESS = 1.0e9


@dataclass
class TargetOptimizationInput:
    """Input parameters for target optimization."""

    target_mode: str = "target_thrust_min_power"
    target_thrust_N: float = 1.0
    target_torque_Nm: float = 0.05
    torque_limit_Nm: float = 0.0
    power_limit_W: float = 0.0
    blades: int = 2
    diameter_m: float = 0.254
    diameter_min_m: float = 0.0
    diameter_max_m: float = 0.0
    hub_diameter_m: float = 0.035
    rpm: float = 8000.0
    v_inf: float = 0.0
    rho: float = 1.225
    mu: float = 1.81e-5
    sound_speed: float = 343.0
    elements: int = 40
    control_points: int = 6
    chord_min_ratio: float = 0.03
    chord_max_ratio: float = 0.18
    beta_min_deg: float = 2.0
    beta_max_deg: float = 45.0
    airfoil_ids: tuple[str, ...] = ()
    max_tip_mach: float = 0.75
    max_alpha_deg: float = 18.0
    max_stall_fraction: float = 0.35
    max_low_re_fraction: float = 0.50
    optimizer_method: str = "genetic_algorithm"
    population_size: int = 40
    generations: int = 40
    mutation_rate: float = 0.15
    crossover_rate: float = 0.75
    elitism_count: int = 2
    tournament_size: int = 3
    random_seed: int | None = 1
    smoothness_weight: float = 0.05
    power_weight: float = 0.10
    torque_weight: float = 2.0
    mach_weight: float = 10.0
    stall_weight: float = 5.0
    low_re_weight: float = 0.5
    geometry_weight: float = 0.5
    stop_tolerance: float = 1e-4
    stop_generations: int = 10


@dataclass
class OptimizationHistoryRow:
    """One optimizer history row."""

    generation: int
    evaluations: int
    best_diameter_m: float
    best_fitness: float
    best_thrust_N: float
    best_torque_Nm: float
    best_power_W: float
    best_eta: float
    best_ct: float
    best_cq: float
    best_cp: float
    target_error_fraction: float
    stall_fraction: float
    low_re_fraction: float
    max_mach: float


@dataclass
class CandidateEvaluation:
    """One optimized candidate evaluation."""

    genome: list[float]
    geometry: list[GeometryStation]
    analysis: PropellerResult | None
    fitness: float
    target_error_fraction: float
    penalties: dict[str, float]
    diagnostics: dict[str, float | str]
    warnings: list[str]


@dataclass
class TargetOptimizationResult:
    """Target optimization result."""

    input: TargetOptimizationInput
    best_diameter_m: float
    best_geometry: list[GeometryStation]
    best_analysis: PropellerResult
    best_fitness: float
    target_error_fraction: float
    history: list[OptimizationHistoryRow]
    evaluations: int
    warnings: list[str]
    diagnostics: dict[str, float | str]


def genome_length(opt_input: TargetOptimizationInput) -> int:
    """Return the optimizer genome length including diameter."""

    return max(int(opt_input.control_points), 2) * 2 + 1


def genome_diameter_m(genome: list[float], opt_input: TargetOptimizationInput) -> float:
    """Return the diameter encoded in a genome."""

    count = max(int(opt_input.control_points), 2)
    if len(genome) <= 2 * count:
        return _active_diameter_m(opt_input)
    diameter_min, diameter_max = _diameter_bounds(opt_input)
    return clamp(finite_or_default(genome[2 * count], _active_diameter_m(opt_input)), diameter_min, diameter_max)


def _active_diameter_m(opt_input: TargetOptimizationInput) -> float:
    """Return the fixed/reference diameter clamped to the optimization bounds."""

    diameter_min, diameter_max = _diameter_bounds(opt_input)
    return clamp(finite_or_default(opt_input.diameter_m, diameter_min), diameter_min, diameter_max)


def _diameter_bounds(opt_input: TargetOptimizationInput) -> tuple[float, float]:
    """Return valid diameter search bounds."""

    base = finite_or_default(opt_input.diameter_m, 0.254)
    if base <= 0.0:
        base = 0.254
    lower = finite_or_default(opt_input.diameter_min_m, 0.0)
    upper = finite_or_default(opt_input.diameter_max_m, 0.0)
    if lower <= 0.0 and upper <= 0.0:
        lower = base
        upper = base
    elif lower <= 0.0:
        lower = base
    elif upper <= 0.0:
        upper = base
    if upper < lower:
        lower, upper = upper, lower
    minimum_allowed = max(finite_or_default(opt_input.hub_diameter_m, 0.0) + 1e-6, 0.001)
    lower = max(lower, minimum_allowed)
    upper = max(upper, lower)
    return finite_or_default(lower), finite_or_default(upper)


def _representative_diameters(opt_input: TargetOptimizationInput) -> list[float]:
    """Return diameter values that cover the optimization range."""

    lower, upper = _diameter_bounds(opt_input)
    middle = 0.5 * (lower + upper)
    out: list[float] = []
    for value in (lower, middle, upper):
        if all(abs(value - existing) > 1e-9 for existing in out):
            out.append(value)
    return out


def _input_with_diameter(opt_input: TargetOptimizationInput, diameter_m: float) -> TargetOptimizationInput:
    """Return an optimization input copy using one candidate diameter."""

    return replace(opt_input, diameter_m=diameter_m)


def make_control_radii(opt_input: TargetOptimizationInput, diameter_m: float | None = None) -> list[float]:
    """Return control point r/R positions."""

    count = max(int(opt_input.control_points), 2)
    diameter = _active_diameter_m(opt_input) if diameter_m is None else diameter_m
    radius = max(diameter / 2.0, 1e-9)
    start = max(safe_div(opt_input.hub_diameter_m / 2.0, radius), 0.20)
    end = 0.98
    if start >= end:
        start = max(0.05, end - 0.2)
    return [finite_or_default(start + i * (end - start) / (count - 1)) for i in range(count)]


def random_genome(opt_input: TargetOptimizationInput, rng: random.Random) -> list[float]:
    """Return a random finite genome."""

    count = max(int(opt_input.control_points), 2)
    diameter_min, diameter_max = _diameter_bounds(opt_input)
    chords = [
        rng.uniform(opt_input.chord_min_ratio, opt_input.chord_max_ratio)
        for _ in range(count)
    ]
    betas = [
        rng.uniform(opt_input.beta_min_deg, opt_input.beta_max_deg)
        for _ in range(count)
    ]
    diameter = rng.uniform(diameter_min, diameter_max)
    return repair_genome(chords + betas + [diameter], opt_input)


def genome_to_geometry(
    genome: list[float],
    opt_input: TargetOptimizationInput,
) -> list[GeometryStation]:
    """Convert a genome to blade geometry stations."""

    clean = repair_genome(genome, opt_input)
    count = max(int(opt_input.control_points), 2)
    diameter = genome_diameter_m(clean, opt_input)
    chord_values = clean[:count]
    beta_values = clean[count : 2 * count]
    control_r = make_control_radii(opt_input, diameter)
    start = control_r[0]
    end = control_r[-1]
    elements = max(int(opt_input.elements), 3)
    geometry: list[GeometryStation] = []
    for idx in range(elements):
        r_over_R = start + (idx + 0.5) * (end - start) / elements
        chord = interpolate_control_points(r_over_R, control_r, chord_values)
        beta = interpolate_control_points(r_over_R, control_r, beta_values)
        geometry.append(
            GeometryStation(
                r_over_R=finite_or_default(r_over_R),
                chord_over_R=finite_or_default(clamp(chord, opt_input.chord_min_ratio, opt_input.chord_max_ratio)),
                beta_deg=finite_or_default(clamp(beta, opt_input.beta_min_deg, opt_input.beta_max_deg)),
                airfoil_id=_airfoil_id_for_radius(r_over_R, opt_input, diameter),
            )
        )
    geometry = smooth_geometry(geometry, strength=0.15)
    validate_geometry(geometry)
    return geometry


def estimate_optimization_reynolds_range(opt_input: TargetOptimizationInput) -> dict[str, float]:
    """Estimate Reynolds bounds from the target optimization search range."""

    omega = 2.0 * math.pi * opt_input.rpm / 60.0
    elements = max(int(opt_input.elements), 3)
    values: list[float] = []
    for diameter in _representative_diameters(opt_input):
        radius_m = max(diameter / 2.0, 1e-9)
        control = make_control_radii(opt_input, diameter)
        start = control[0]
        end = control[-1]
        for idx in range(elements):
            r_over_R = start + (idx + 0.5) * (end - start) / elements
            r_m = r_over_R * radius_m
            speed = math.hypot(opt_input.v_inf, omega * r_m)
            for chord_ratio in (opt_input.chord_min_ratio, opt_input.chord_max_ratio):
                chord_m = max(chord_ratio, 1e-9) * radius_m
                reynolds = safe_div(opt_input.rho * speed * chord_m, opt_input.mu)
                if is_finite_number(reynolds) and reynolds > 0.0:
                    values.append(reynolds)
    if not values:
        raise ValueError("Could not estimate Reynolds range from target optimization bounds.")
    return {
        "re_min": finite_or_default(min(values)),
        "re_max": finite_or_default(max(values)),
    }


def interpolate_control_points(x: float, xs: list[float], ys: list[float]) -> float:
    """Linearly interpolate one value from control points."""

    if not xs or not ys or len(xs) != len(ys):
        return 0.0
    if x <= xs[0]:
        return finite_or_default(ys[0])
    if x >= xs[-1]:
        return finite_or_default(ys[-1])
    for left_index in range(len(xs) - 1):
        x0 = xs[left_index]
        x1 = xs[left_index + 1]
        if x0 <= x <= x1:
            t = safe_div(x - x0, x1 - x0)
            return finite_or_default(ys[left_index] + t * (ys[left_index + 1] - ys[left_index]))
    return finite_or_default(ys[-1])


def smooth_geometry(geometry: list[GeometryStation], strength: float = 0.15) -> list[GeometryStation]:
    """Lightly smooth interior chord and beta values."""

    if len(geometry) < 3:
        return [GeometryStation(st.r_over_R, st.chord_over_R, st.beta_deg, st.airfoil_id) for st in geometry]
    amount = clamp(strength, 0.0, 1.0)
    out = [GeometryStation(st.r_over_R, st.chord_over_R, st.beta_deg, st.airfoil_id) for st in geometry]
    src = [GeometryStation(st.r_over_R, st.chord_over_R, st.beta_deg, st.airfoil_id) for st in out]
    for idx in range(1, len(out) - 1):
        chord_avg = 0.5 * (src[idx - 1].chord_over_R + src[idx + 1].chord_over_R)
        beta_avg = 0.5 * (src[idx - 1].beta_deg + src[idx + 1].beta_deg)
        out[idx].chord_over_R = finite_or_default((1.0 - amount) * src[idx].chord_over_R + amount * chord_avg)
        out[idx].beta_deg = finite_or_default((1.0 - amount) * src[idx].beta_deg + amount * beta_avg)
    return out


def clamp_genome(genome: list[float], opt_input: TargetOptimizationInput) -> list[float]:
    """Clamp a genome to input bounds."""

    count = max(int(opt_input.control_points), 2)
    gene_count = genome_length(opt_input)
    values = list(genome[:gene_count])
    while len(values) < 2 * count:
        values.append(0.0)
    if len(values) < gene_count:
        values.append(_active_diameter_m(opt_input))
    diameter_min, diameter_max = _diameter_bounds(opt_input)
    chords = [clamp(finite_or_default(value, opt_input.chord_min_ratio), opt_input.chord_min_ratio, opt_input.chord_max_ratio) for value in values[:count]]
    betas = [clamp(finite_or_default(value, opt_input.beta_min_deg), opt_input.beta_min_deg, opt_input.beta_max_deg) for value in values[count:]]
    diameter = clamp(finite_or_default(values[2 * count], _active_diameter_m(opt_input)), diameter_min, diameter_max)
    return chords + betas[:count] + [diameter]


def repair_genome(genome: list[float], opt_input: TargetOptimizationInput) -> list[float]:
    """Clamp and lightly repair a genome."""

    clean = clamp_genome(genome, opt_input)
    count = max(int(opt_input.control_points), 2)
    chords = clean[:count]
    betas = clean[count:]
    if chords[-1] > chords[0] * 1.35:
        chords[-1] = chords[0] * 1.35
    for idx in range(1, count):
        max_step = max(opt_input.chord_max_ratio - opt_input.chord_min_ratio, 1e-9) * 0.75
        chords[idx] = clamp(chords[idx], chords[idx - 1] - max_step, chords[idx - 1] + max_step)
    return clamp_genome(chords + betas[:count] + [genome_diameter_m(clean, opt_input)], opt_input)


def evaluate_candidate(
    genome: list[float],
    opt_input: TargetOptimizationInput,
    polar: AirfoilPolar | None = None,
) -> CandidateEvaluation:
    """Evaluate one candidate using the existing propeller solver."""

    polar_model = polar if polar is not None else GenericPolar()
    clean = repair_genome(genome, opt_input)
    diameter = genome_diameter_m(clean, opt_input)
    candidate_input = _input_with_diameter(opt_input, diameter)
    try:
        geometry = genome_to_geometry(clean, candidate_input)
        prop_input = _propeller_input_from_optimizer(candidate_input)
        analysis = calculate_propeller(prop_input, polar=polar_model, geometry=geometry)
        diagnostics = _analysis_diagnostics(analysis, candidate_input, geometry)
        diagnostics["diameter_m"] = diameter
        fitness, target_error, penalties, warnings = compute_fitness(analysis, candidate_input, geometry, diagnostics)
        warnings.extend(analysis.warnings)
        return _clean_evaluation(
            CandidateEvaluation(clean, geometry, analysis, fitness, target_error, penalties, diagnostics, _unique(warnings))
        )
    except Exception as exc:  # noqa: BLE001 - optimizer keeps running on bad candidates.
        geometry = _fallback_geometry(opt_input)
        diagnostics = {"error": str(exc)}
        return CandidateEvaluation(
            genome=clean,
            geometry=geometry,
            analysis=None,
            fitness=LARGE_FITNESS,
            target_error_fraction=1.0,
            penalties={"invalid": LARGE_FITNESS},
            diagnostics=diagnostics,
            warnings=[f"Candidate evaluation failed: {exc}"],
        )


def compute_fitness(
    analysis: PropellerResult,
    opt_input: TargetOptimizationInput,
    geometry: list[GeometryStation],
    diagnostics: dict[str, float | str],
) -> tuple[float, float, dict[str, float], list[str]]:
    """Compute finite lower-is-better fitness."""

    del geometry
    warnings: list[str] = []
    thrust = finite_or_default(analysis.thrust_N)
    torque = finite_or_default(analysis.torque_Nm)
    power = finite_or_default(analysis.power_W)
    penalties: dict[str, float] = {}
    target_mode = opt_input.target_mode

    if target_mode in ("target_thrust_min_power", "target_thrust_torque_limited", "match_thrust"):
        target_error = abs(thrust - opt_input.target_thrust_N) / max(abs(opt_input.target_thrust_N), 1e-9)
    elif target_mode in ("target_torque_max_thrust", "match_torque"):
        target_error = abs(torque - opt_input.target_torque_Nm) / max(abs(opt_input.target_torque_Nm), 1e-9)
    else:
        target_error = abs(thrust - opt_input.target_thrust_N) / max(abs(opt_input.target_thrust_N), 1e-9)

    fitness = target_error * target_error
    if target_mode == "target_thrust_min_power":
        normalized_power = power / max(abs(opt_input.target_thrust_N * max(opt_input.v_inf, 1.0)), 1.0)
        penalties["power"] = opt_input.power_weight * max(normalized_power, 0.0)
    elif target_mode == "target_thrust_torque_limited":
        limit = opt_input.torque_limit_Nm
        excess = safe_div(torque - limit, limit) if limit > 0.0 and torque > limit else 0.0
        penalties["torque_limit"] = opt_input.torque_weight * excess * excess
    elif target_mode == "target_torque_max_thrust":
        limit = max(opt_input.target_torque_Nm, 1e-9)
        excess = safe_div(torque - limit, limit) if torque > limit else 0.0
        penalties["torque_limit"] = opt_input.torque_weight * 5.0 * excess * excess
        penalties["thrust_reward"] = safe_div(1.0, max(thrust, 0.0) + 1e-3)
        if thrust <= 0.0:
            penalties["nonpositive_thrust"] = 100.0
    elif target_mode == "match_torque":
        warnings.append("Torque matching alone is a load target, not an efficiency objective.")
        penalties["power"] = 0.25 * opt_input.power_weight * max(power, 0.0) / 100.0
    elif target_mode == "match_thrust":
        penalties["power"] = 0.5 * opt_input.power_weight * max(power, 0.0) / 100.0

    if opt_input.power_limit_W > 0.0 and power > opt_input.power_limit_W:
        excess = safe_div(power - opt_input.power_limit_W, opt_input.power_limit_W)
        penalties["power_limit"] = opt_input.power_weight * 5.0 * excess * excess

    max_mach = float(diagnostics.get("max_mach", 0.0))
    stall_fraction = float(diagnostics.get("stall_fraction", 0.0))
    low_re_fraction = float(diagnostics.get("low_re_fraction", 0.0))
    negative_fraction = float(diagnostics.get("negative_thrust_fraction", 0.0))
    smoothness = float(diagnostics.get("geometry_smoothness", 0.0))
    if max_mach > opt_input.max_tip_mach:
        penalties["mach"] = opt_input.mach_weight * (safe_div(max_mach - opt_input.max_tip_mach, opt_input.max_tip_mach) ** 2)
    penalties["stall"] = opt_input.stall_weight * max(stall_fraction - opt_input.max_stall_fraction, 0.0) ** 2
    penalties["low_re"] = opt_input.low_re_weight * max(low_re_fraction - opt_input.max_low_re_fraction, 0.0) ** 2
    penalties["negative_thrust"] = 5.0 * negative_fraction * negative_fraction
    penalties["smoothness"] = opt_input.smoothness_weight * smoothness
    penalties["geometry"] = opt_input.geometry_weight * float(diagnostics.get("geometry_penalty", 0.0))

    total = fitness + sum(value for value in penalties.values() if value > 0.0)
    return finite_or_default(total, LARGE_FITNESS), finite_or_default(target_error), _clean_penalties(penalties), warnings


def run_random_search(
    opt_input: TargetOptimizationInput,
    polar: AirfoilPolar | None = None,
    progress_callback: ProgressCallback | None = None,
    stop_callback: StopCallback | None = None,
    base_geometry: list[GeometryStation] | None = None,
) -> TargetOptimizationResult:
    """Run random search optimization."""

    rng = random.Random(opt_input.random_seed)
    best: CandidateEvaluation | None = None
    history: list[OptimizationHistoryRow] = []
    evaluations = 0
    stopped = False
    for generation in range(max(opt_input.generations, 1)):
        genomes = [random_genome(opt_input, rng) for _ in range(max(opt_input.population_size, 1))]
        if generation == 0 and base_geometry is not None:
            genomes[0] = geometry_to_genome(base_geometry, opt_input)
        for genome in genomes:
            if stop_callback is not None and stop_callback():
                stopped = True
                break
            candidate = evaluate_candidate(genome, opt_input, polar)
            evaluations += 1
            best = _best_candidate(best, candidate)
        if best is not None:
            history.append(_history_row(generation, evaluations, best))
            if progress_callback is not None:
                progress_callback(generation + 1, max(opt_input.generations, 1), best)
        if stopped:
            break
    return _result_from_best(opt_input, best, history, evaluations, stopped)


def run_genetic_algorithm(
    opt_input: TargetOptimizationInput,
    polar: AirfoilPolar | None = None,
    progress_callback: ProgressCallback | None = None,
    stop_callback: StopCallback | None = None,
    base_geometry: list[GeometryStation] | None = None,
) -> TargetOptimizationResult:
    """Run a small genetic algorithm."""

    rng = random.Random(opt_input.random_seed)
    pop_size = max(opt_input.population_size, 2)
    population = [random_genome(opt_input, rng) for _ in range(pop_size)]
    if base_geometry is not None:
        population[0] = geometry_to_genome(base_geometry, opt_input)
    best: CandidateEvaluation | None = None
    history: list[OptimizationHistoryRow] = []
    evaluations = 0
    stagnant = 0
    last_best = LARGE_FITNESS
    stopped = False

    for generation in range(max(opt_input.generations, 1)):
        evaluated: list[CandidateEvaluation] = []
        for genome in population:
            if stop_callback is not None and stop_callback():
                stopped = True
                break
            candidate = evaluate_candidate(genome, opt_input, polar)
            evaluated.append(candidate)
            evaluations += 1
            best = _best_candidate(best, candidate)
        if not evaluated:
            break
        evaluated.sort(key=lambda item: item.fitness)
        best_generation = evaluated[0]
        history.append(_history_row(generation, evaluations, best_generation if best is None else best))
        if progress_callback is not None:
            progress_callback(generation + 1, max(opt_input.generations, 1), best if best is not None else best_generation)
        if best is not None and abs(last_best - best.fitness) <= opt_input.stop_tolerance:
            stagnant += 1
        else:
            stagnant = 0
        last_best = best.fitness if best is not None else last_best
        if stopped or stagnant >= max(opt_input.stop_generations, 1):
            break
        population = _next_population(evaluated, opt_input, rng)
    return _result_from_best(opt_input, best, history, evaluations, stopped)


def run_ga_local_refine(
    opt_input: TargetOptimizationInput,
    polar: AirfoilPolar | None = None,
    progress_callback: ProgressCallback | None = None,
    stop_callback: StopCallback | None = None,
    base_geometry: list[GeometryStation] | None = None,
) -> TargetOptimizationResult:
    """Run GA followed by a compact coordinate refinement."""

    count = max(int(opt_input.control_points), 2)
    result = run_genetic_algorithm(opt_input, polar, progress_callback, stop_callback, base_geometry)
    best_genome = geometry_to_genome(result.best_geometry, opt_input)
    if len(best_genome) >= genome_length(opt_input):
        best_genome[-1] = result.best_diameter_m
        best_genome = repair_genome(best_genome, opt_input)
    best_eval = evaluate_candidate(best_genome, opt_input, polar)
    evaluations = result.evaluations + 1
    step = 0.08
    for _pass in range(2):
        improved = False
        for idx in range(len(best_genome)):
            if stop_callback is not None and stop_callback():
                return _result_from_best(
                    opt_input,
                    best_eval,
                    result.history,
                    evaluations,
                    stopped=True,
                )
            for sign in (-1.0, 1.0):
                trial = list(best_genome)
                if idx < count:
                    scale = opt_input.chord_max_ratio - opt_input.chord_min_ratio
                elif idx < count * 2:
                    scale = opt_input.beta_max_deg - opt_input.beta_min_deg
                else:
                    diameter_min, diameter_max = _diameter_bounds(opt_input)
                    scale = diameter_max - diameter_min
                trial[idx] += sign * step * max(scale, 1e-9)
                trial = repair_genome(trial, opt_input)
                candidate = evaluate_candidate(trial, opt_input, polar)
                evaluations += 1
                if candidate.fitness < best_eval.fitness:
                    best_eval = candidate
                    best_genome = trial
                    improved = True
        step *= 0.5
        if not improved:
            break
    history = list(result.history)
    history.append(_history_row(len(history), evaluations, best_eval))
    return _result_from_best(opt_input, best_eval, history, evaluations, stopped=False)


def run_target_optimization(
    opt_input: TargetOptimizationInput,
    polar: AirfoilPolar | None = None,
    progress_callback: ProgressCallback | None = None,
    stop_callback: StopCallback | None = None,
    base_geometry: list[GeometryStation] | None = None,
) -> TargetOptimizationResult:
    """Dispatch target optimization method."""

    if opt_input.optimizer_method == "random_search":
        return run_random_search(opt_input, polar, progress_callback, stop_callback, base_geometry)
    if opt_input.optimizer_method == "ga_local_refine":
        return run_ga_local_refine(opt_input, polar, progress_callback, stop_callback, base_geometry)
    return run_genetic_algorithm(opt_input, polar, progress_callback, stop_callback, base_geometry)


def geometry_to_genome(geometry: list[GeometryStation], opt_input: TargetOptimizationInput) -> list[float]:
    """Convert geometry to a control-point genome by sampling."""

    if not geometry:
        return random_genome(opt_input, random.Random(opt_input.random_seed))
    sorted_geometry = sorted(geometry, key=lambda item: item.r_over_R)
    xs = [station.r_over_R for station in sorted_geometry]
    chords = [station.chord_over_R for station in sorted_geometry]
    betas = [station.beta_deg for station in sorted_geometry]
    control = make_control_radii(opt_input)
    genome = [interpolate_control_points(r, xs, chords) for r in control]
    genome.extend(interpolate_control_points(r, xs, betas) for r in control)
    genome.append(_active_diameter_m(opt_input))
    return repair_genome(genome, opt_input)


def _propeller_input_from_optimizer(opt_input: TargetOptimizationInput) -> PropellerInput:
    """Build PropellerInput from optimizer input."""

    return PropellerInput(
        blades=max(int(opt_input.blades), 1),
        diameter_m=opt_input.diameter_m,
        hub_diameter_m=opt_input.hub_diameter_m,
        rpm=opt_input.rpm,
        v_inf=opt_input.v_inf,
        rho=opt_input.rho,
        mu=opt_input.mu,
        sound_speed=opt_input.sound_speed,
        elements=max(int(opt_input.elements), 3),
        calculation_mode="auto",
        polar_mode="generic",
    )


def _analysis_diagnostics(
    analysis: PropellerResult,
    opt_input: TargetOptimizationInput,
    geometry: list[GeometryStation],
) -> dict[str, float | str]:
    """Return candidate diagnostics."""

    stations = analysis.stations
    count = max(len(stations), 1)
    stall_count = sum(1 for station in stations if abs(station.alpha_deg) > opt_input.max_alpha_deg)
    low_re_count = sum(1 for station in stations if station.reynolds < 50000.0)
    negative_count = sum(1 for station in stations if station.dT_dr < 0.0)
    return {
        "thrust_N": finite_or_default(analysis.thrust_N),
        "torque_Nm": finite_or_default(analysis.torque_Nm),
        "power_W": finite_or_default(analysis.power_W),
        "eta": finite_or_default(analysis.eta),
        "ct": finite_or_default(analysis.ct),
        "cq": finite_or_default(analysis.cq),
        "cp": finite_or_default(analysis.cp),
        "max_alpha_deg": finite_or_default(max((abs(st.alpha_deg) for st in stations), default=0.0)),
        "stall_fraction": finite_or_default(stall_count / count),
        "low_re_fraction": finite_or_default(low_re_count / count),
        "negative_thrust_fraction": finite_or_default(negative_count / count),
        "max_mach": finite_or_default(max((st.mach for st in stations), default=0.0)),
        "max_vi_mps": finite_or_default(max((st.vi_mps for st in stations), default=0.0)),
        "geometry_smoothness": finite_or_default(_geometry_smoothness(geometry)),
        "geometry_penalty": finite_or_default(_geometry_penalty(geometry)),
    }


def _geometry_smoothness(geometry: list[GeometryStation]) -> float:
    """Return second-difference smoothness metric."""

    if len(geometry) < 3:
        return 0.0
    total = 0.0
    for idx in range(1, len(geometry) - 1):
        chord_second = geometry[idx - 1].chord_over_R - 2.0 * geometry[idx].chord_over_R + geometry[idx + 1].chord_over_R
        beta_second = geometry[idx - 1].beta_deg - 2.0 * geometry[idx].beta_deg + geometry[idx + 1].beta_deg
        total += chord_second * chord_second * 100.0 + beta_second * beta_second / 100.0
    return finite_or_default(total / max(len(geometry) - 2, 1))


def _geometry_penalty(geometry: list[GeometryStation]) -> float:
    """Return simple geometry plausibility penalty."""

    penalty = 0.0
    for left, right in zip(geometry, geometry[1:]):
        if right.chord_over_R > left.chord_over_R * 1.5:
            penalty += (right.chord_over_R - left.chord_over_R) ** 2 * 100.0
        if abs(right.beta_deg - left.beta_deg) > 12.0:
            penalty += ((abs(right.beta_deg - left.beta_deg) - 12.0) / 12.0) ** 2
    return finite_or_default(penalty)


def _next_population(
    evaluated: list[CandidateEvaluation],
    opt_input: TargetOptimizationInput,
    rng: random.Random,
) -> list[list[float]]:
    """Create next GA population."""

    pop_size = max(opt_input.population_size, 2)
    elite_count = clamp(int(opt_input.elitism_count), 0, pop_size)
    next_pop = [list(item.genome) for item in evaluated[:elite_count]]
    while len(next_pop) < pop_size:
        parent_a = _tournament(evaluated, opt_input, rng).genome
        parent_b = _tournament(evaluated, opt_input, rng).genome
        if rng.random() < opt_input.crossover_rate:
            child = _blend_crossover(parent_a, parent_b, rng)
        else:
            child = list(parent_a)
        child = _mutate(child, opt_input, rng)
        next_pop.append(repair_genome(child, opt_input))
    return next_pop


def _tournament(
    evaluated: list[CandidateEvaluation],
    opt_input: TargetOptimizationInput,
    rng: random.Random,
) -> CandidateEvaluation:
    """Tournament selection."""

    size = max(int(opt_input.tournament_size), 1)
    candidates = [rng.choice(evaluated) for _ in range(size)]
    return min(candidates, key=lambda item: item.fitness)


def _blend_crossover(parent_a: list[float], parent_b: list[float], rng: random.Random) -> list[float]:
    """Blend crossover."""

    child: list[float] = []
    for a, b in zip(parent_a, parent_b):
        weight = rng.random()
        child.append(weight * a + (1.0 - weight) * b)
    return child


def _mutate(
    genome: list[float],
    opt_input: TargetOptimizationInput,
    rng: random.Random,
) -> list[float]:
    """Mutate one genome."""

    count = max(opt_input.control_points, 2)
    out = list(genome)
    diameter_min, diameter_max = _diameter_bounds(opt_input)
    chord_sigma = 0.15 * max(opt_input.chord_max_ratio - opt_input.chord_min_ratio, 1e-9)
    beta_sigma = 0.12 * max(opt_input.beta_max_deg - opt_input.beta_min_deg, 1e-9)
    diameter_sigma = 0.10 * max(diameter_max - diameter_min, 1e-9)
    for idx, value in enumerate(out):
        if rng.random() <= opt_input.mutation_rate:
            if idx < count:
                sigma = chord_sigma
            elif idx < 2 * count:
                sigma = beta_sigma
            else:
                sigma = diameter_sigma
            out[idx] = value + rng.gauss(0.0, sigma)
    return out


def _best_candidate(
    current: CandidateEvaluation | None,
    candidate: CandidateEvaluation,
) -> CandidateEvaluation:
    """Return lower-fitness candidate."""

    if current is None or candidate.fitness < current.fitness:
        return candidate
    return current


def _history_row(generation: int, evaluations: int, best: CandidateEvaluation) -> OptimizationHistoryRow:
    """Build a history row."""

    analysis = best.analysis
    return OptimizationHistoryRow(
        generation=int(generation),
        evaluations=int(evaluations),
        best_diameter_m=finite_or_default(float(best.diagnostics.get("diameter_m", 0.0))),
        best_fitness=finite_or_default(best.fitness, LARGE_FITNESS),
        best_thrust_N=finite_or_default(analysis.thrust_N if analysis is not None else 0.0),
        best_torque_Nm=finite_or_default(analysis.torque_Nm if analysis is not None else 0.0),
        best_power_W=finite_or_default(analysis.power_W if analysis is not None else 0.0),
        best_eta=finite_or_default(analysis.eta if analysis is not None else 0.0),
        best_ct=finite_or_default(analysis.ct if analysis is not None else 0.0),
        best_cq=finite_or_default(analysis.cq if analysis is not None else 0.0),
        best_cp=finite_or_default(analysis.cp if analysis is not None else 0.0),
        target_error_fraction=finite_or_default(best.target_error_fraction),
        stall_fraction=finite_or_default(float(best.diagnostics.get("stall_fraction", 0.0))),
        low_re_fraction=finite_or_default(float(best.diagnostics.get("low_re_fraction", 0.0))),
        max_mach=finite_or_default(float(best.diagnostics.get("max_mach", 0.0))),
    )


def _result_from_best(
    opt_input: TargetOptimizationInput,
    best: CandidateEvaluation | None,
    history: list[OptimizationHistoryRow],
    evaluations: int,
    stopped: bool,
) -> TargetOptimizationResult:
    """Build result from best candidate."""

    if best is None or best.analysis is None:
        fallback = evaluate_candidate(random_genome(opt_input, random.Random(opt_input.random_seed)), opt_input, None)
        best = fallback
    if best.analysis is None:
        prop_input = _propeller_input_from_optimizer(opt_input)
        geometry = _fallback_geometry(opt_input)
        analysis = calculate_propeller(prop_input, polar=GenericPolar(), geometry=geometry)
        best = CandidateEvaluation([], geometry, analysis, LARGE_FITNESS, 1.0, {"invalid": LARGE_FITNESS}, {"diameter_m": opt_input.diameter_m}, ["Fallback result used."])
    warnings = list(best.warnings)
    best_diameter = genome_diameter_m(best.genome, opt_input)
    if best_diameter <= 0.0:
        best_diameter = finite_or_default(float(best.diagnostics.get("diameter_m", opt_input.diameter_m)), opt_input.diameter_m)
    if stopped:
        warnings.append("Optimization stopped by user.")
    if opt_input.target_mode == "match_torque":
        warnings.append("Torque matching alone is a load target, not an efficiency objective.")
    if best.target_error_fraction > 0.25:
        warnings.append(
            "Best result remains far from the requested target; "
            "the target may be infeasible with the current bounds, RPM, diameter, polar data, or limits."
        )
    if opt_input.power_limit_W > 0.0 and best.analysis.power_W > opt_input.power_limit_W:
        warnings.append("Best result exceeds the requested power limit.")
    return TargetOptimizationResult(
        input=opt_input,
        best_diameter_m=best_diameter,
        best_geometry=best.geometry,
        best_analysis=best.analysis,
        best_fitness=finite_or_default(best.fitness, LARGE_FITNESS),
        target_error_fraction=finite_or_default(best.target_error_fraction),
        history=history or [_history_row(0, evaluations, best)],
        evaluations=int(evaluations),
        warnings=_unique(warnings),
        diagnostics=_clean_diagnostics(best.diagnostics),
    )


def _fallback_geometry(opt_input: TargetOptimizationInput) -> list[GeometryStation]:
    """Return a simple finite fallback geometry."""

    count = max(opt_input.control_points, 2)
    chord = 0.5 * (opt_input.chord_min_ratio + opt_input.chord_max_ratio)
    beta = 0.5 * (opt_input.beta_min_deg + opt_input.beta_max_deg)
    genome = [chord] * count + [beta] * count
    return genome_to_geometry(genome, opt_input)


def _airfoil_id_for_radius(
    r_over_R: float,
    opt_input: TargetOptimizationInput,
    diameter_m: float | None = None,
) -> str:
    """Return the root-to-tip airfoil id for one radius."""

    airfoils = [normalize_airfoil_id(item) for item in opt_input.airfoil_ids if normalize_airfoil_id(item)]
    if not airfoils:
        return "active"
    if len(airfoils) == 1:
        return airfoils[0]
    control = make_control_radii(opt_input, diameter_m)
    span = max(control[-1] - control[0], 1e-9)
    fraction = clamp((r_over_R - control[0]) / span, 0.0, 0.999999)
    index = min(int(fraction * len(airfoils)), len(airfoils) - 1)
    return airfoils[index]


def _clean_evaluation(candidate: CandidateEvaluation) -> CandidateEvaluation:
    """Return finite candidate fields."""

    return CandidateEvaluation(
        genome=[finite_or_default(value) for value in candidate.genome],
        geometry=candidate.geometry,
        analysis=candidate.analysis,
        fitness=finite_or_default(candidate.fitness, LARGE_FITNESS),
        target_error_fraction=finite_or_default(candidate.target_error_fraction),
        penalties=_clean_penalties(candidate.penalties),
        diagnostics=_clean_diagnostics(candidate.diagnostics),
        warnings=_unique(candidate.warnings),
    )


def _clean_penalties(penalties: dict[str, float]) -> dict[str, float]:
    """Return finite penalties."""

    return {key: finite_or_default(value) for key, value in penalties.items()}


def _clean_diagnostics(diagnostics: dict[str, float | str]) -> dict[str, float | str]:
    """Return finite diagnostics."""

    return {
        key: finite_or_default(value) if isinstance(value, float) else value
        for key, value in diagnostics.items()
    }


def _unique(items: list[str]) -> list[str]:
    """Return strings without duplicates."""

    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
