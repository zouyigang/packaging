"""Genetic algorithm / BRKGA optimizer.

The chromosome is a random-key ordering of placeables. The packing loop remains
responsible for decoding each ordered individual into a concrete solution.
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from collections import Counter
from dataclasses import dataclass, replace
from os import cpu_count

import numpy as np

from ..models.schemas import Container, Item, PerformanceMetrics, Solution, SolutionAlternative, SolveRequest
from .evaluator import evaluate_solution
from .industrial import finalize_solution, prepare_request
from .industrial_context import analyze_stack_clusters
from .geometry import oriented_dims
from .objectives import AdvancedScoreWeights, get_objective, resolve_objective
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
_GA_WORKER_OBSERVE_INDUSTRIAL = False

# 实验开关（默认关）：safe_loading 策略在工业模式 + GA 路径下，把「堆垛簇所需
# 固定力（纵+横 kN）」作为罚项并入 GA fitness。权重乘子，0 = 关（等于旧基线）。
# 经 1140 件多种子实验：开启后同容器数下横向固定力/危险簇稳定下降、纵向固定力
# 多数种子大幅下降但有方差，故落为环境变量 opt-in（如 GA_SAFE_RESTRAINT_WEIGHT=20），
# 默认不改变任何既有行为。详见 docs/ga-industrial-restraint-experiment.md。
_SAFE_LOADING_RESTRAINT_WEIGHT = float(os.environ.get("GA_SAFE_RESTRAINT_WEIGHT", "0.0"))


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
    observe_industrial: bool,
) -> None:
    global _GA_WORKER_PLACEABLES, _GA_WORKER_CONTAINERS, _GA_WORKER_OBJECTIVE, _GA_WORKER_OBSERVE_INDUSTRIAL
    _GA_WORKER_PLACEABLES = placeables
    _GA_WORKER_CONTAINERS = containers
    _GA_WORKER_OBJECTIVE = objective
    _GA_WORKER_OBSERVE_INDUSTRIAL = observe_industrial


def _decode_ga_order_worker(
    signature: tuple[int, ...],
) -> tuple[tuple[int, ...], Solution, dict[str, float], dict[str, int]]:
    if _GA_WORKER_PLACEABLES is None or _GA_WORKER_CONTAINERS is None or _GA_WORKER_OBJECTIVE is None:
        raise RuntimeError("GA worker is not initialized")
    timer = PerformanceTimer()
    ordered, containers = _decode_signature(signature, _GA_WORKER_PLACEABLES, _GA_WORKER_CONTAINERS)
    solution = run_container_loop(
        ordered,
        containers,
        _GA_WORKER_OBJECTIVE,
        timer,
        observe_industrial=_GA_WORKER_OBSERVE_INDUSTRIAL,
    )
    return signature, solution, timer.stages_ms, timer.counters


def _decode_signature(
    signature: tuple[int, ...],
    placeables: list[_Placeable],
    containers: list[Container],
) -> tuple[list[_Placeable], list[Container]]:
    m = len(placeables)
    n = len(containers)
    order = signature[:m]
    rotation_choices = signature[m:2 * m]
    container_order = signature[2 * m:2 * m + n]
    ordered: list[_Placeable] = []
    for source_index in order:
        placeable = placeables[source_index]
        rotations = list(placeable.oriented_rotations)
        if rotations:
            offset = rotation_choices[source_index] % len(rotations)
            rotations = rotations[offset:] + rotations[:offset]
            placeable = replace(
                placeable,
                oriented_rotations=rotations,
                allowed_rotations=[rotation[0] for rotation in rotations],
            )
        ordered.append(placeable)
    ordered_containers = [containers[index] for index in container_order]
    return ordered, ordered_containers


def _cargo_volume(item: Item) -> float:
    return item.length * item.width * item.height


def _make_fitness(
    objective_name: str,
    item_map: dict[str, Item],
    container_map: dict[str, Container],
    advanced_weights: AdvancedScoreWeights | None = None,
    pallet_map: dict | None = None,
    industrial: bool = False,
):
    """Return a solution fitness function. Higher is better."""
    total_cargo_volume = sum(_cargo_volume(item) * item.quantity for item in item_map.values()) or 1.0
    total_units = sum(item.quantity for item in item_map.values()) or 1
    total_must = sum(item.quantity for item in item_map.values() if item.must_load)
    total_priority = sum((item.priority + 1) * item.quantity for item in item_map.values()) or 1
    canonical, _profile = resolve_objective(objective_name)

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

    def restraint_penalty(sol: Solution) -> float:
        """堆垛簇所需固定力（纵向 + 横向 kN）之和，越小越安全。

        复刻 finalize_solution 的簇载荷构建（含托盘实例），逐容器调用纯函数
        analyze_stack_clusters 现算。容器未配运输加速度时该函数返回 0，
        故仅在工业模式且配了加速度的容器上非零。
        """
        total_kn = 0.0
        for loaded in sol.containers:
            container = container_map.get(loaded.id)
            if container is None or container.acceleration_profile is None:
                continue
            cluster_loads: list[tuple[tuple[float, float, float, float, float, float], float]] = []
            for pallet_instance in getattr(loaded, "pallet_instances", ()) or ():
                cluster_loads.append((
                    (
                        pallet_instance.x,
                        pallet_instance.y,
                        pallet_instance.z,
                        pallet_instance.length,
                        pallet_instance.width,
                        pallet_instance.deck_height,
                    ),
                    pallet_instance.tare_weight,
                ))
            for p in loaded.placements:
                item = item_map.get(p.item_id)
                if item is None:
                    continue
                dx, dy, dz = oriented_dims(item.length, item.width, item.height, p.orientation)
                mass = item.weight if item.weight > 0 else dx * dy * dz
                cluster_loads.append(((p.x, p.y, p.z, dx, dy, dz), mass))
            cluster = analyze_stack_clusters(container, cluster_loads)
            total_kn += (
                cluster.required_longitudinal_restraint_kn
                + cluster.required_transverse_restraint_kn
            )
        return total_kn

    def pallet_ratio(sol: Solution) -> float:
        placements = [p for loaded in sol.containers for p in loaded.placements]
        if not placements:
            return 0.0
        return sum(1 for p in placements if p.pallet_id is not None) / len(placements)

    def unpacked_volume(sol: Solution) -> float:
        return sum(_cargo_volume(item_map[item_id]) for item_id in sol.unpacked if item_id in item_map)

    def common_score(sol: Solution) -> float:
        unpacked = Counter(sol.unpacked)
        missing_must = sum(count for item_id, count in unpacked.items() if item_id in item_map and item_map[item_id].must_load)
        loaded_units = total_units - len(sol.unpacked)
        loaded_priority = total_priority - sum(
            (item_map[item_id].priority + 1) * count
            for item_id, count in unpacked.items()
            if item_id in item_map
        )
        must_quality = 1.0 if total_must == 0 else max(0.0, (total_must - missing_must) / total_must)
        return must_quality * 1e12 + (loaded_priority / total_priority) * 1e9 + (loaded_units / total_units) * 1e6

    def solution_cost(sol: Solution) -> float:
        cost = 0.0
        for loaded in sol.containers:
            container = container_map.get(loaded.id)
            cost += container.use_cost if container is not None and container.use_cost is not None else 1.0
        if pallet_map:
            pallet_ids = {
                placement.pallet_id
                for loaded in sol.containers
                for placement in loaded.placements
                if placement.pallet_id
            }
            for pallet_id in pallet_ids:
                pallet = pallet_map.get(str(pallet_id).split("#", 1)[0])
                if pallet is not None and pallet.handling_cost is not None:
                    cost += pallet.handling_cost
        return cost

    def utilization(sol: Solution) -> float:
        used_capacity = sum(
            container_map[loaded.id].inner_length * container_map[loaded.id].inner_width * container_map[loaded.id].inner_height
            for loaded in sol.containers if loaded.id in container_map
        )
        return packed_volume(sol) / used_capacity if used_capacity > 0 else 0.0

    if canonical == "cost_efficiency":
        def fitness(sol: Solution) -> float:
            return common_score(sol) - solution_cost(sol) * 1e3 + utilization(sol)
    elif canonical == "space_utilization":
        def fitness(sol: Solution) -> float:
            return common_score(sol) + utilization(sol) * 1e3 - len(sol.containers)
    elif canonical == "safe_loading":
        apply_restraint = industrial and _SAFE_LOADING_RESTRAINT_WEIGHT > 0.0

        def fitness(sol: Solution) -> float:
            stability_quality = 1.0 - min(stability_penalty(sol), 1.0)
            balance_quality = 1.0 - min(cog_penalty(sol) / max(len(sol.containers), 1), 1.0)
            score = common_score(sol) + min(stability_quality, balance_quality) * 700.0 + 0.5 * (stability_quality + balance_quality) * 300.0
            # 实验：把堆垛簇所需固定力并入 fitness，引导 GA 主动降低固定力/危险簇。
            # 罚项落在细粒度层（远小于 common_score 的 1e6+），不会翻转必装/装载量排序。
            if apply_restraint:
                score -= _SAFE_LOADING_RESTRAINT_WEIGHT * restraint_penalty(sol)
            return score
    elif canonical == "delivery_sequence":
        def fitness(sol: Solution) -> float:
            return common_score(sol) + (1.0 - min(loading_penalty(sol), 1.0)) * 1e3
    elif canonical == "custom":
        weights = advanced_weights or AdvancedScoreWeights()

        def fitness(sol: Solution) -> float:
            utilization = packed_volume(sol) / total_cargo_volume
            stability_quality = 1.0 - min(stability_penalty(sol), 1.0)
            balance_quality = 1.0 - min(cog_penalty(sol) / max(len(sol.containers), 1), 1.0)
            loading_quality = 1.0 - min(loading_penalty(sol), 1.0)
            pallet_quality = pallet_ratio(sol)
            missing = unpacked_volume(sol) / total_cargo_volume
            weighted = (
                weights.cost_efficiency * (1.0 / (1.0 + solution_cost(sol)))
                + weights.space_utilization * utilization
                + weights.stability * stability_quality
                + weights.balance * balance_quality
                + weights.loading_position * loading_quality
            )
            return common_score(sol) + 1e3 * (weighted - 2.0 * missing - 0.02 * len(sol.containers))
    else:
        def fitness(sol: Solution) -> float:
            return common_score(sol) + packed_volume(sol) / total_cargo_volume

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
    initial_violations: list | None = None,
) -> Solution:
    ranked: list[tuple[Solution, float]] = []
    for sol, fitness_score in candidates.values():
        industrial_metrics = finalize_solution(request, sol, initial_violations)
        sol.evaluation = evaluate_solution(request, sol)
        sol.evaluation.metrics.update({key: round(value, 4) for key, value in industrial_metrics.items()})
        sol.alternatives = []
        ranked.append((sol, fitness_score))

    ranked.sort(
        key=lambda pair: (
            {"infeasible": 0, "partial": 1, "feasible": 2}.get(pair[0].status, 0),
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
                status=sol.status,
                violations=[violation.model_copy(deep=True) for violation in sol.violations],
                cost_summary=sol.cost_summary.model_copy(deep=True) if sol.cost_summary is not None else None,
            )
        )
    return primary


def solve_ga(request: SolveRequest, config: GAConfig | None = None) -> Solution:
    """Search placeable order with BRKGA and return the best decoded solution."""
    timer = PerformanceTimer()
    request, initial_violations = prepare_request(request)
    cfg = config or GAConfig()
    with timer.stage("prepare_objective"):
        objective = get_objective(
            request.objective, request.advanced_weights, request.safety_priority
        )
    with timer.stage("build_placeables"):
        placeables: list[_Placeable] = _build_placeables(request, objective)
    with timer.stage("expand_containers"):
        containers = _expand_containers(request, objective)
    with timer.stage("prepare_fitness"):
        item_map = {i.id: i for i in request.items}
        container_map = {c.id: c for c in request.containers}
        pallet_map = {p.id: p for p in request.pallets}
        fitness = _make_fitness(
            request.objective,
            item_map,
            container_map,
            getattr(objective, "weights", None),
            pallet_map,
            industrial=request.validation_mode == "industrial",
        )

    m = len(placeables)
    if m == 0:
        with timer.stage("container_loop"):
            solution = run_container_loop(
                [], containers, objective, timer,
                observe_industrial=request.validation_mode == "industrial",
            )
        with timer.stage("evaluator"):
            industrial_metrics = finalize_solution(request, solution, initial_violations)
            solution.evaluation = evaluate_solution(request, solution)
            solution.evaluation.metrics.update({key: round(value, 4) for key, value in industrial_metrics.items()})
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
    n_containers = len(containers)
    gene_count = 2 * m + n_containers
    pop = rng.random((cfg.population, gene_count))
    pop[0, :m] = np.linspace(0.0, 1.0, m)
    pop[0, m:2 * m] = 0.0
    if n_containers:
        pop[0, 2 * m:] = np.linspace(0.0, 1.0, n_containers)

    n_elite = max(1, int(cfg.population * cfg.elite_frac))
    n_mutant = max(1, int(cfg.population * cfg.mutant_frac))
    decode_cache: dict[tuple[int, ...], tuple[Solution, float]] = {}
    executor: ProcessPoolExecutor | None = None

    def decode(signature: tuple[int, ...]) -> Solution:
        ordered, ordered_containers = _decode_signature(signature, placeables, containers)
        return run_container_loop(
            ordered,
            ordered_containers,
            objective,
            timer,
            observe_industrial=request.validation_mode == "industrial",
        )

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
            item_order = tuple(int(i) for i in np.argsort(ind[:m], kind="stable"))
            rotation_choices = tuple(
                min(int(ind[m + i] * max(len(placeables[i].oriented_rotations), 1)), max(len(placeables[i].oriented_rotations) - 1, 0))
                for i in range(m)
            )
            container_order = tuple(int(i) for i in np.argsort(ind[2 * m:], kind="stable"))
            order = item_order + rotation_choices + container_order
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
                initargs=(
                    placeables,
                    containers,
                    objective,
                    request.validation_mode == "industrial",
                ),
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
                children.append(rng.random((n_mutant, gene_count)))
                n_cross = cfg.population - n_elite - n_mutant
                if n_cross > 0:
                    elite_parents = elites[rng.integers(0, n_elite, n_cross)]
                    non_elite_parents = pop[rng.integers(n_elite, cfg.population, n_cross)]
                    mask = rng.random((n_cross, gene_count)) < cfg.inherit_prob
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
        solution = _rank_ga_candidates(request, candidates, candidate_limit, cfg.seed, initial_violations)
    solution.performance = PerformanceMetrics(
        runtime_ms=round(timer.runtime_ms, 3),
        stages_ms=timer.rounded_stages(),
        counters=timer.counters,
    )
    return solution
