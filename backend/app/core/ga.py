"""Genetic algorithm / BRKGA optimizer.

The chromosome is a random-key ordering of placeables. The packing loop remains
responsible for decoding each ordered individual into a concrete solution.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..models.schemas import Container, Item, Solution, SolveRequest
from .geometry import oriented_dims
from .objectives import get_objective
from .packer import (
    _Placeable,
    _build_placeables,
    _expand_containers,
    run_container_loop,
)


@dataclass
class GAConfig:
    population: int = 40
    generations: int = 40
    elite_frac: float = 0.25
    mutant_frac: float = 0.20
    inherit_prob: float = 0.70
    seed: int = 0


def _cargo_volume(item: Item) -> float:
    return item.length * item.width * item.height


def _make_fitness(
    objective_name: str,
    item_map: dict[str, Item],
    container_map: dict[str, Container],
):
    """Return a solution fitness function. Higher is better."""

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

    if objective_name in {"min_containers", "transport_cost"}:
        def fitness(sol: Solution) -> float:
            return -len(sol.containers) * 1e18 + packed_volume(sol)
    elif objective_name in {"center_of_gravity", "weight_balance"}:
        def fitness(sol: Solution) -> float:
            return packed_volume(sol) * 1e6 - cog_penalty(sol)
    else:
        def fitness(sol: Solution) -> float:
            return packed_volume(sol)

    return fitness


def solve_ga(request: SolveRequest, config: GAConfig | None = None) -> Solution:
    """Search placeable order with BRKGA and return the best decoded solution."""
    cfg = config or GAConfig()
    objective = get_objective(request.objective)
    placeables: list[_Placeable] = _build_placeables(request, objective)
    containers = _expand_containers(request, objective)
    item_map = {i.id: i for i in request.items}
    container_map = {c.id: c for c in request.containers}
    fitness = _make_fitness(request.objective, item_map, container_map)

    m = len(placeables)
    if m == 0:
        return run_container_loop([], containers, objective)

    rng = np.random.default_rng(cfg.seed)
    pop = rng.random((cfg.population, m))
    pop[0] = np.linspace(0.0, 1.0, m)

    n_elite = max(1, int(cfg.population * cfg.elite_frac))
    n_mutant = max(1, int(cfg.population * cfg.mutant_frac))

    def decode(keys: np.ndarray) -> Solution:
        order = np.argsort(keys, kind="stable")
        ordered = [placeables[i] for i in order]
        return run_container_loop(ordered, containers, objective)

    def evaluate(population: np.ndarray) -> tuple[list[Solution], np.ndarray]:
        sols = [decode(ind) for ind in population]
        scores = np.array([fitness(s) for s in sols])
        return sols, scores

    sols, scores = evaluate(pop)
    best_idx = int(np.argmax(scores))
    best_sol, best_score = sols[best_idx], scores[best_idx]

    for _ in range(cfg.generations):
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
        gen_best = int(np.argmax(scores))
        if scores[gen_best] > best_score:
            best_sol, best_score = sols[gen_best], scores[gen_best]

    return best_sol
