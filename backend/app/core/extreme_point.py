"""单容器极点启发式放置 + 放置评分。

给定一件货品、当前已放置物体集合、极点集合，尝试为它找到一个
「能放下 + 满足约束 + 评分最优」的位置与朝向。

约束：不越界、不与已放置物体重叠（geometry）；朝向限制（此处枚举 allowed_rotations）；
支撑防悬空、堆叠承重（constraints，可选开启）。容器载重上限在 packer 层校验。
默认评分：靠底(z) → 靠里(y) → 靠左(x) 优先，利于堆叠稳定。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .constraints import (
    DEFAULT_SUPPORT_RATIO,
    PlacedItem,
    check_stack_load,
    check_support,
)
from .geometry import Box, box_within, boxes_overlap, oriented_dims
from .space import ExtremePointSet, Point

ScoreFn = Callable[[Box], tuple[float, ...]]
PointFn = Callable[[float, float, float], list[Point]]
HardConstraintFn = Callable[[Box], bool]


@dataclass(frozen=True)
class Candidate:
    point: Point
    orientation: str
    box: Box
    score: tuple[float, ...]  # 越小越优


def _default_score(box: Box) -> tuple[float, ...]:
    x, y, z, *_ = box
    return (z, y, x)


def find_placement(
    length: float,
    width: float,
    height: float,
    allowed_rotations: list[str],
    ep_set: ExtremePointSet,
    placed: list[PlacedItem],
    inner_length: float,
    inner_width: float,
    inner_height: float,
    score_fn: ScoreFn | None = None,
    weight: float = 0.0,
    enforce_constraints: bool = True,
    min_support_ratio: float = DEFAULT_SUPPORT_RATIO,
    extra_points_fn: PointFn | None = None,
    hard_constraint_fn: HardConstraintFn | None = None,
) -> Candidate | None:
    """遍历极点 × 允许朝向，返回评分最优的可行放置；无解返回 None。

    placed 为已放置物体记录(PlacedItem)，用于重叠/支撑/承重校验。
    score_fn 由优化目标注入（见 objectives.py）；缺省用 z→y→x。
    enforce_constraints=True 时校验支撑(防悬空)与堆叠承重。
    """
    score = score_fn or _default_score
    best: Candidate | None = None

    def try_candidate(point: Point, orientation: str, dx: float, dy: float, dz: float) -> None:
        nonlocal best
        px, py, pz = point
        box: Box = (px, py, pz, dx, dy, dz)
        if not box_within(box, inner_length, inner_width, inner_height):
            return
        if any(boxes_overlap(box, pi.box) for pi in placed):
            return
        if enforce_constraints:
            if not check_support(box, placed, min_support_ratio):
                return
            if not check_stack_load(box, weight, placed):
                return
            if hard_constraint_fn is not None and not hard_constraint_fn(box):
                return
        s = score(box)
        if best is None or s < best.score:
            best = Candidate(point=point, orientation=orientation, box=box, score=s)

    for point in ep_set.points():
        for orientation in allowed_rotations:
            dx, dy, dz = oriented_dims(length, width, height, orientation)
            try_candidate(point, orientation, dx, dy, dz)

    if best is None and extra_points_fn is not None:
        seen = set(ep_set.points())
        for orientation in allowed_rotations:
            dx, dy, dz = oriented_dims(length, width, height, orientation)
            for point in extra_points_fn(dx, dy, dz):
                if point in seen:
                    continue
                seen.add(point)
                try_candidate(point, orientation, dx, dy, dz)
    return best
