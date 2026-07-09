"""单容器极点启发式放置 + 放置评分。

给定一件货品、当前已放置物体集合、极点集合，尝试为它找到一个
「能放下 + 满足约束 + 评分最优」的位置与朝向。

约束：不越界、不与已放置物体重叠（geometry）；朝向限制（此处枚举 allowed_rotations）；
支撑防悬空、堆叠承重（constraints，可选开启）。容器载重上限在 packer 层校验。
默认评分：靠底(z) → 靠里(y) → 靠左(x) 优先，利于堆叠稳定。
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Callable

from .constraints import (
    DEFAULT_SUPPORT_RATIO,
    PlacedItem,
    check_stack_load,
    check_support,
)
from .geometry import Box, boxes_overlap, oriented_dims
from .space import ExtremePointSet, Point

ScoreFn = Callable[[Box], tuple[float, ...]]
PointFn = Callable[[float, float, float], list[Point]]
HardConstraintFn = Callable[[Box], bool]
OverlapCandidatesFn = Callable[[Box], list[PlacedItem]]
OverlapCheckFn = Callable[[Box], bool]
CounterFn = Callable[[str, int], None]
MaxCounterFn = Callable[[str, int], None]
OrientedRotation = tuple[str, float, float, float]
Attempt = tuple[tuple[float, ...], int, Point, str, Box]


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
    overlap_candidates_fn: OverlapCandidatesFn | None = None,
    overlap_check_fn: OverlapCheckFn | None = None,
    oriented_rotations: list[OrientedRotation] | None = None,
    counter_fn: CounterFn | None = None,
    max_counter_fn: MaxCounterFn | None = None,
    filter_covered_points: bool = True,
) -> Candidate | None:
    """遍历极点 × 允许朝向，返回评分最优的可行放置；无解返回 None。

    placed 为已放置物体记录(PlacedItem)，用于重叠/支撑/承重校验。
    score_fn 由优化目标注入（见 objectives.py）；缺省用 z→y→x。
    enforce_constraints=True 时校验支撑(防悬空)与堆叠承重。
    """
    score = score_fn or _default_score
    best: Candidate | None = None
    orientations = oriented_rotations or [
        (orientation, *oriented_dims(length, width, height, orientation))
        for orientation in allowed_rotations
    ]
    raw_points = ep_set.points()
    if counter_fn is not None:
        counter_fn("candidate_points_raw", len(raw_points))
    if max_counter_fn is not None:
        max_counter_fn("candidate_points_raw_max", len(raw_points))
    points = _candidate_points(
        raw_points,
        inner_length,
        inner_width,
        inner_height,
        orientations,
        placed if filter_covered_points else None,
    )
    if counter_fn is not None:
        counter_fn("candidate_points_ready", len(points))
        counter_fn("candidate_points_pruned", max(0, len(raw_points) - len(points)))
    if max_counter_fn is not None:
        max_counter_fn("candidate_points_ready_max", len(points))

    def add_attempt(
        attempts: list[Attempt],
        index: int,
        point: Point,
        orientation: str,
        dx: float,
        dy: float,
        dz: float,
    ) -> None:
        px, py, pz = point
        if px + dx > inner_length + 1e-6 or py + dy > inner_width + 1e-6 or pz + dz > inner_height + 1e-6:
            return
        box: Box = (px, py, pz, dx, dy, dz)
        attempts.append((score(box), index, point, orientation, box))

    def build_attempt_heap(candidate_points: list[Point]) -> list[Attempt]:
        attempts: list[Attempt] = []
        index = 0
        for point in candidate_points:
            for orientation, dx, dy, dz in orientations:
                add_attempt(attempts, index, point, orientation, dx, dy, dz)
                index += 1
        heapq.heapify(attempts)
        if counter_fn is not None:
            counter_fn("candidate_boxes_scored", len(attempts))
        if max_counter_fn is not None:
            max_counter_fn("candidate_boxes_scored_max", len(attempts))
        return attempts

    def build_extra_attempt_heap(
        candidate_entries: list[tuple[Point, str, float, float, float]]
    ) -> list[Attempt]:
        attempts: list[Attempt] = []
        for index, (point, orientation, dx, dy, dz) in enumerate(candidate_entries):
            add_attempt(attempts, index, point, orientation, dx, dy, dz)
        heapq.heapify(attempts)
        if counter_fn is not None:
            counter_fn("candidate_boxes_scored", len(attempts))
        if max_counter_fn is not None:
            max_counter_fn("candidate_boxes_scored_max", len(attempts))
        return attempts

    checked_count = 0

    def try_candidate(attempt: Attempt) -> bool:
        nonlocal best, checked_count
        attempt_score, _index, point, orientation, box = attempt
        checked_count += 1
        if counter_fn is not None:
            counter_fn("candidate_boxes_checked")
        if overlap_check_fn is not None:
            if overlap_check_fn(box):
                return False
        else:
            overlap_candidates = overlap_candidates_fn(box) if overlap_candidates_fn is not None else placed
            if any(boxes_overlap(box, pi.box) for pi in overlap_candidates):
                return False
        if enforce_constraints:
            if not check_support(box, placed, min_support_ratio):
                return False
            if not check_stack_load(box, weight, placed):
                return False
        if hard_constraint_fn is not None and not hard_constraint_fn(box):
            return False
        if best is None or attempt_score < best.score:
            best = Candidate(point=point, orientation=orientation, box=box, score=attempt_score)
            return True
        return False

    def scan_attempts(attempts: list[Attempt]) -> int:
        skipped = 0
        while attempts:
            attempt = heapq.heappop(attempts)
            if best is not None and attempt[0] >= best.score:
                skipped += len(attempts) + 1
                break
            if try_candidate(attempt):
                skipped += len(attempts)
                break
        return skipped

    skipped_by_score = scan_attempts(build_attempt_heap(points))
    if counter_fn is not None and skipped_by_score:
        counter_fn("candidate_boxes_skipped_by_score", skipped_by_score)

    if best is None and extra_points_fn is not None:
        seen = set(points)
        extra_entries: list[tuple[Point, str, float, float, float]] = []
        for orientation, dx, dy, dz in orientations:
            for point in extra_points_fn(dx, dy, dz):
                if point in seen or not _point_in_bounds(point, inner_length, inner_width, inner_height):
                    continue
                seen.add(point)
                extra_entries.append((point, orientation, dx, dy, dz))
        extra_skipped_by_score = scan_attempts(build_extra_attempt_heap(extra_entries))
        if counter_fn is not None and extra_skipped_by_score:
            counter_fn("candidate_boxes_skipped_by_score", extra_skipped_by_score)
    if max_counter_fn is not None:
        max_counter_fn("candidate_boxes_checked_max", checked_count)
    return best


def _candidate_points(
    points: list[Point],
    inner_length: float,
    inner_width: float,
    inner_height: float,
    orientations: list[OrientedRotation],
    placed: list[PlacedItem] | None,
    eps: float = 1e-6,
) -> list[Point]:
    seen: set[Point] = set()
    candidates: list[Point] = []
    for point in points:
        if point in seen or not _point_in_bounds(point, inner_length, inner_width, inner_height, eps):
            continue
        if placed is not None and _point_covered(point, placed, eps):
            continue
        if not _any_orientation_fits(point, orientations, inner_length, inner_width, inner_height, eps):
            continue
        seen.add(point)
        candidates.append(point)
    return candidates


def _any_orientation_fits(
    point: Point,
    orientations: list[OrientedRotation],
    inner_length: float,
    inner_width: float,
    inner_height: float,
    eps: float = 1e-6,
) -> bool:
    x, y, z = point
    return any(
        x + dx <= inner_length + eps
        and y + dy <= inner_width + eps
        and z + dz <= inner_height + eps
        for _orientation, dx, dy, dz in orientations
    )


def _point_covered(point: Point, placed: list[PlacedItem], eps: float = 1e-6) -> bool:
    px, py, pz = point
    for item in placed:
        x, y, z, dx, dy, dz = item.box
        if (
            px >= x - eps
            and py >= y - eps
            and pz >= z - eps
            and px < x + dx - eps
            and py < y + dy - eps
            and pz < z + dz - eps
        ):
            return True
    return False


def _point_in_bounds(
    point: Point,
    inner_length: float,
    inner_width: float,
    inner_height: float,
    eps: float = 1e-6,
) -> bool:
    x, y, z = point
    return (
        x >= -eps
        and y >= -eps
        and z >= -eps
        and x <= inner_length + eps
        and y <= inner_width + eps
        and z <= inner_height + eps
    )
