"""遗传算法 / BRKGA 全局优化（M7，进阶后置项）。

思路（见 CLAUDE.md 第 6 节）：对「货品(待放置单元)的放置顺序」做全局搜索，
以现有极点启发式为解码器——每个个体是一组随机键(random keys)，按键排序得到放置顺序，
喂给 run_container_loop 解码成方案，再按当前优化目标算适应度，迭代进化。

BRKGA 精简版：精英保留 + 偏置交叉 + 随机突变个体。种群里植入一个「默认大块先」
个体，确保进化结果不劣于默认启发式（非退化保证）。

朝向选择仍交给启发式逐位择优（find_placement）；朝向基因留待后续扩展。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..models.schemas import Item, Solution, SolveRequest
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
    inherit_prob: float = 0.70  # 交叉时从精英父代继承基因的概率
    seed: int = 0


def _cargo_volume(item: Item) -> float:
    return item.length * item.width * item.height


def _make_fitness(objective_name: str, item_map: dict[str, Item]):
    """返回 solution → 适应度(越大越优) 的函数。"""

    def packed_volume(sol: Solution) -> float:
        return sum(
            _cargo_volume(item_map[p.item_id])
            for c in sol.containers
            for p in c.placements
            if p.item_id in item_map
        )

    if objective_name == "min_containers":
        # 容器数越少越好；同容器数下装得越多越好。
        def fitness(sol: Solution) -> float:
            return -len(sol.containers) * 1e18 + packed_volume(sol)
    else:
        # 利用率 / 稳定性 / 平衡：以装入货物总体积为主（装得多即利用率高）。
        def fitness(sol: Solution) -> float:
            return packed_volume(sol)

    return fitness


def solve_ga(request: SolveRequest, config: GAConfig | None = None) -> Solution:
    """用 BRKGA 搜索放置顺序，返回最优方案。"""
    cfg = config or GAConfig()
    objective = get_objective(request.objective)
    placeables: list[_Placeable] = _build_placeables(request, objective)
    containers = _expand_containers(request, objective)
    item_map = {i.id: i for i in request.items}
    fitness = _make_fitness(request.objective, item_map)

    m = len(placeables)
    if m == 0:
        return run_container_loop([], containers, objective)

    rng = np.random.default_rng(cfg.seed)
    pop = rng.random((cfg.population, m))
    # 植入「默认顺序」个体：键升序 → argsort 还原 placeables 现有(大块先)顺序。
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
        order = np.argsort(-scores)  # 适应度降序
        pop = pop[order]
        scores = scores[order]
        sols = [sols[i] for i in order]

        elites = pop[:n_elite]
        # 下一代：精英直传 + 突变体 + 偏置交叉
        children = [elites]
        children.append(rng.random((n_mutant, m)))  # 突变体
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
