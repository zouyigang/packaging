"""Genetic algorithm / BRKGA optimizer.

The chromosome is a random-key ordering of placeables. The packing loop remains
responsible for decoding each ordered individual into a concrete solution.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from os import cpu_count

import numpy as np

from ..models.schemas import Container, Item, PerformanceMetrics, Solution, SolutionAlternative, SolveRequest
from .evaluator import evaluate_solution
from .geometry import oriented_dims
from .objectives import AdvancedScoreWeights, get_objective
from .packer import (
    _Placeable,
    _build_placeables,
    _expand_containers,
    run_container_loop,
)
from .performance import PerformanceTimer

_GA_WORKER_PLACEABLES: list[_Placeable] | None = None
_GA_WORKER_CONTAINERS: list[Container] | None = None
_GA_WORKER_OBJECTIVE: object | None = None


@dataclass
class GAConfig:
    population: int = 40
    generations: int = 40
    elite_frac: float = 0.25
    mutant_frac: float = 0.20
    inherit_prob: float = 0.70
    seed: int = 0
    early_stop_rounds: int | None = None
    parallel_workers: int = 0
    parallel_min_population: int = 24

    @classmethod
    def for_speed(cls, speed: str, seed: int = 0) -> "GAConfig":
        if speed == "fast":
            return cls(
                population=16,
                generations=12,
                seed=seed,
                early_stop_rounds=4,
                parallel_workers=_default_parallel_workers(),
                parallel_min_population=8,
            )
        if speed == "fine":
            return cls(
                population=64,
                generations=60,
                seed=seed,
                early_stop_rounds=12,
                parallel_workers=_default_parallel_workers(),
            )
        return cls(
            population=32,
            generations=30,
            seed=seed,
            early_stop_rounds=8,
            parallel_workers=_default_parallel_workers(),
        )


def _default_parallel_workers() -> int:
    cores = cpu_count() or 1
    return max(0, min(cores - 1, 4))


def _init_ga_decode_worker(
    placeables: list[_Placeable],
    containers: list[Container],
    objective: object,
) -> None:
    global _GA_WORKER_PLACEABLES, _GA_WORKER_CONTAINERS, _GA_WORKER_OBJECTIVE
    _GA_WORKER_PLACEABLES = placeables
    _GA_WORKER_CONTAINERS = containers
    _GA_WORKER_OBJECTIVE = objective


def _decode_ga_order_worker(
    order: tuple[int, ...],
) -> tuple[tuple[int, ...], Solution, dict[str, float], dict[str, int]]:
    if _GA_WORKER_PLACEABLES is None or _GA_WORKER_CONTAINERS is None or _GA_WORKER_OBJECTIVE is None:
        raise RuntimeError("GA worker is not initialized")
    timer = PerformanceTimer()
    ordered = [_GA_WORKER_PLACEABLES[i] for i in order]
    solution = run_container_loop(ordered, _GA_WORKER_CONTAINERS, _GA_WORKER_OBJECTIVE, timer)
    return order, solution, timer.stages_ms, timer.counters


def _cargo_volume(item: Item) -> float:
    return item.length * item.width * item.height


def _make_fitness(
    objective_name: str,
    item_map: dict[str, Item],
    container_map: dict[str, Container],
    advanced_weights: AdvancedScoreWeights | None = None,
):
    """Return a solution fitness function. Higher is better."""
    total_cargo_volume = sum(_cargo_volume(item) * item.quantity for item in item_map.values()) or 1.0

    def packed_volume(sol: Solution) -> float:
        return sum(
            _cargo_volume(item_map[p.item_id])
            for c in sol.containers
            for p in c.placements
            if p.item_id in item_map
        )

    def cog_penalty(sol: Solution) -> float:
        penalty = 0.0
        for loaded in sol.containers:
            container = container_map.get(loaded.id)
            if container is None:
                continue
            total_w = sum_wx = sum_wy = 0.0
            for p in loaded.placements:
                item = item_map.get(p.item_id)
                if item is None:
                    continue
                dx, dy, dz = oriented_dims(item.length, item.width, item.height, p.orientation)
                mass = item.weight if item.weight > 0 else dx * dy * dz
                total_w += mass
                sum_wx += mass * (p.x + dx / 2.0)
                sum_wy += mass * (p.y + dy / 2.0)
            if total_w <= 0:
                continue
            gx = sum_wx / total_w
            gy = sum_wy / total_w
            norm_x = abs(gx - container.inner_length / 2.0) / container.inner_length
            norm_y = abs(gy - container.inner_width / 2.0) / container.inner_width
            penalty += max(norm_x, norm_y) + norm_x + norm_y
        return penalty

    def stability_penalty(sol: Solution) -> float:
        total_mass = weighted_penalty = 0.0
        for loaded in sol.containers:
            container = container_map.get(loaded.id)
            if container is None:
                continue
            for p in loaded.placements:
                item = item_map.get(p.item_id)
                if item is None:
                    continue
                dx, dy, dz = oriented_dims(item.length, item.width, item.height, p.orientation)
                mass = item.weight if item.weight > 0 else dx * dy * dz
                center_height = (p.z + dz / 2.0) / container.inner_height
                slenderness = min(dz / max(dx, dy, 1.0), 1.0)
                weighted_penalty += mass * (0.75 * center_height + 0.25 * slenderness)
                total_mass += mass
        return weighted_penalty / total_mass if total_mass else 0.0

    def loading_penalty(sol: Solution) -> float:
        placements = [p for loaded in sol.containers for p in loaded.placements]
        if not placements:
            return 1.0
        min_stop = min(max(1, int(p.stop_seq or 1)) for p in placements)
        max_stop = max(max(1, int(p.stop_seq or 1)) for p in placements)
        has_stops = max_stop > min_stop
        penalty = 0.0
        count = 0
        for loaded in sol.containers:
            container = container_map.get(loaded.id)
            if container is None:
                continue
            sides = tuple(access.side for access in container.loading_accesses) or ("x_max",)
            for p in loaded.placements:
                item = item_map.get(p.item_id)
                if item is None:
                    continue
                dx, dy, dz = oriented_dims(item.length, item.width, item.height, p.orientation)
                box = (p.x, p.y, p.z, dx, dy, dz)
                nearest_depth = min(_normalized_loading_depth(box, side, container) for side in sides)
                if has_stops:
                    stop_pos = (max(1, int(p.stop_seq or 1)) - min_stop) / (max_stop - min_stop)
                    penalty += abs(nearest_depth - stop_pos)
                else:
                    penalty += 1.0 - nearest_depth
                count += 1
        return penalty / count if count else 1.0

    def pallet_ratio(sol: Solution) -> float:
        placements = [p for loaded in sol.containers for p in loaded.placements]
        if not placements:
            return 0.0
        return sum(1 for p in placements if p.pallet_id is not None) / len(placements)

    def unpacked_volume(sol: Solution) -> float:
        return sum(_cargo_volume(item_map[item_id]) for item_id in sol.unpacked if item_id in item_map)

    if objective_name in {"min_containers", "transport_cost"}:
        def fitness(sol: Solution) -> float:
            return -len(sol.containers) * 1e18 + packed_volume(sol)
    elif objective_name in {"center_of_gravity", "weight_balance"}:
        def fitness(sol: Solution) -> float:
            return packed_volume(sol) * 1e6 - cog_penalty(sol)
    elif objective_name in {"advanced_score", "balanced"}:
        weights = advanced_weights or AdvancedScoreWeights()

        def fitness(sol: Solution) -> float:
            utilization = packed_volume(sol) / total_cargo_volume
            stability_quality = 1.0 - min(stability_penalty(sol), 1.0)
            balance_quality = 1.0 - min(cog_penalty(sol) / max(len(sol.containers), 1), 1.0)
            loading_quality = 1.0 - min(loading_penalty(sol), 1.0)
            pallet_quality = pallet_ratio(sol)
            missing = unpacked_volume(sol) / total_cargo_volume
            weighted = (
                weights.space_utilization * utilization
                + weights.stability * stability_quality
                + weights.balance * balance_quality
                + weights.loading_position * loading_quality
                + weights.palletization * pallet_quality
            )
            return weighted - 2.0 * missing - 0.02 * len(sol.containers)
    else:
        def fitness(sol: Solution) -> float:
            return packed_volume(sol)

    return fitness


def _normalized_loading_depth(
    box: tuple[float, float, float, float, float, float],
    side: str,
    container: Container,
) -> float:
    x, y, z, dx, dy, dz = box
    if side == "x_min":
        return x / container.inner_length
    if side == "x_max":
        return (container.inner_length - (x + dx)) / container.inner_length
    if side == "y_min":
        return y / container.inner_width
    if side == "y_max":
        return (container.inner_width - (y + dy)) / container.inner_width
    if side == "z_max":
        return (container.inner_height - (z + dz)) / container.inner_height
    return 0.0


def _solution_signature(sol: Solution) -> tuple:
    containers = []
    for container_index, loaded in enumerate(sol.containers):
        placements = tuple(
            (
                p.seq,
                p.item_id,
                p.pallet_id or "",
                p.customer_id or "",
                p.order_id or "",
                p.destination_id or "",
                p.stop_seq,
                round(p.x, 6),
                round(p.y, 6),
                round(p.z, 6),
                p.orientation,
            )
            for p in loaded.placements
        )
        containers.append((container_index, loaded.id, placements))
    return (tuple(containers), tuple(sol.unpacked))


def _rank_ga_candidates(
    request: SolveRequest,
    candidates: dict[tuple, tuple[Solution, float]],
    limit: int,
    seed: int,
) -> Solution:
    ranked: list[tuple[Solution, float]] = []
    for sol, fitness_score in candidates.values():
        sol.evaluation = evaluate_solution(request, sol)
        sol.alternatives = []
        ranked.append((sol, fitness_score))

    ranked.sort(
        key=lambda pair: (
            pair[0].evaluation.score if pair[0].evaluation is not None else 0.0,
            pair[1],
        ),
        reverse=True,
    )

    primary = ranked[0][0].model_copy(deep=True)
    primary.alternatives = []
    for rank, (sol, _fitness_score) in enumerate(ranked[1:limit], start=2):
        evaluation = sol.evaluation
        primary.alternatives.append(
            SolutionAlternative(
                rank=rank,
                seed=seed,
                score=evaluation.score if evaluation is not None else 0.0,
                grade=evaluation.grade if evaluation is not None else "D",
                containers=[c.model_copy(deep=True) for c in sol.containers],
                unpacked=list(sol.unpacked),
                evaluation=evaluation.model_copy(deep=True) if evaluation is not None else None,
            )
        )
    return primary


def solve_ga(request: SolveRequest, config: GAConfig | None = None) -> Solution:
    """Search placeable order with BRKGA and return the best decoded solution."""
    timer = PerformanceTimer()
    cfg = config or GAConfig()
    with timer.stage("prepare_objective"):
        objective = get_objective(request.objective, request.advanced_weights)
    with timer.stage("build_placeables"):
        placeables: list[_Placeable] = _build_placeables(request, objective)
    with timer.stage("expand_containers"):
        containers = _expand_containers(request, objective)
    with timer.stage("prepare_fitness"):
        item_map = {i.id: i for i in request.items}
        container_map = {c.id: c for c in request.containers}
        fitness = _make_fitness(request.objective, item_map, container_map, getattr(objective, "weights", None))

    m = len(placeables)
    if m == 0:
        with timer.stage("container_loop"):
            solution = run_container_loop([], containers, objective, timer)
        with timer.stage("evaluator"):
            solution.evaluation = evaluate_solution(request, solution)
        solution.performance = PerformanceMetrics(
            runtime_ms=round(timer.runtime_ms, 3),
            stages_ms=timer.rounded_stages(),
            counters=timer.counters,
        )
        return solution

    candidate_limit = max(1, min(request.candidate_count, 8))
    candidates: dict[tuple, tuple[Solution, float]] = {}
    parallel_workers = cfg.parallel_workers if cfg.population >= cfg.parallel_min_population else 0
    parallel_workers = min(parallel_workers, cfg.population)

    rng = np.random.default_rng(cfg.seed)
    pop = rng.random((cfg.population, m))
    pop[0] = np.linspace(0.0, 1.0, m)

    n_elite = max(1, int(cfg.population * cfg.elite_frac))
    n_mutant = max(1, int(cfg.population * cfg.mutant_frac))
    decode_cache: dict[tuple[int, ...], tuple[Solution, float]] = {}
    executor: ProcessPoolExecutor | None = None

    def decode(order: tuple[int, ...]) -> Solution:
        ordered = [placeables[i] for i in order]
        return run_container_loop(ordered, containers, objective, timer)

    def decode_misses(orders: list[tuple[int, ...]]) -> None:
        if executor is None:
            for order in orders:
                sol = decode(order)
                score = float(fitness(sol))
                decode_cache[order] = (sol, score)
            return
        timer.count("ga_parallel_batches")
        timer.count("ga_parallel_tasks", len(orders))
        chunksize = max(1, len(orders) // (parallel_workers * 2))
        for order, sol, stages_ms, counters in executor.map(_decode_ga_order_worker, orders, chunksize=chunksize):
            timer.merge(stages_ms, counters)
            score = float(fitness(sol))
            decode_cache[order] = (sol, score)

    def evaluate(population: np.ndarray) -> tuple[list[Solution], np.ndarray]:
        orders: list[tuple[int, ...]] = []
        missing_orders: list[tuple[int, ...]] = []
        missing_seen: set[tuple[int, ...]] = set()
        for ind in population:
            order = tuple(int(i) for i in np.argsort(ind, kind="stable"))
            orders.append(order)
            if order not in decode_cache and order not in missing_seen:
                timer.count("ga_decode_cache_misses")
                missing_orders.append(order)
                missing_seen.add(order)
        if missing_orders:
            decode_misses(missing_orders)

        sols: list[Solution] = []
        scores: list[float] = []
        for order in orders:
            cached = decode_cache[order]
            if order not in missing_seen:
                timer.count("ga_decode_cache_hits")
            sol, score = cached
            sols.append(sol)
            scores.append(score)
        return sols, np.array(scores)

    def remember(solutions: list[Solution], fitness_scores: np.ndarray) -> None:
        for sol, score in zip(solutions, fitness_scores):
            signature = _solution_signature(sol)
            current = candidates.get(signature)
            if current is None or score > current[1]:
                candidates[signature] = (sol, float(score))

    try:
        if parallel_workers > 1:
            timer.count("ga_parallel_workers", parallel_workers)
            executor = ProcessPoolExecutor(
                max_workers=parallel_workers,
                initializer=_init_ga_decode_worker,
                initargs=(placeables, containers, objective),
            )

        with timer.stage("ga_initial_population"):
            sols, scores = evaluate(pop)
        remember(sols, scores)
        best_score = float(np.max(scores))
        stale_generations = 0
        completed_generations = 0

        for generation in range(cfg.generations):
            with timer.stage(f"ga_generation_{generation + 1}"):
                order = np.argsort(-scores)
                pop = pop[order]
                scores = scores[order]
                sols = [sols[i] for i in order]

                elites = pop[:n_elite]
                children = [elites]
                children.append(rng.random((n_mutant, m)))
                n_cross = cfg.population - n_elite - n_mutant
                if n_cross > 0:
                    elite_parents = elites[rng.integers(0, n_elite, n_cross)]
                    non_elite_parents = pop[rng.integers(n_elite, cfg.population, n_cross)]
                    mask = rng.random((n_cross, m)) < cfg.inherit_prob
                    crossed = np.where(mask, elite_parents, non_elite_parents)
                    children.append(crossed)
                pop = np.vstack(children)

                sols, scores = evaluate(pop)
            remember(sols, scores)
            completed_generations = generation + 1
            generation_best = float(np.max(scores))
            if generation_best > best_score + 1e-9:
                best_score = generation_best
                stale_generations = 0
            else:
                stale_generations += 1
            if cfg.early_stop_rounds is not None and stale_generations >= cfg.early_stop_rounds:
                timer.count("ga_early_stopped")
                break
    finally:
        if executor is not None:
            executor.shutdown()
    timer.count("ga_generations_completed", completed_generations)

    with timer.stage("rank_candidates"):
        solution = _rank_ga_candidates(request, candidates, candidate_limit, cfg.seed)
    solution.performance = PerformanceMetrics(
        runtime_ms=round(timer.runtime_ms, 3),
        stages_ms=timer.rounded_stages(),
        counters=timer.counters,
    )
    return solution
