"""极点（Extreme Point）集合的维护。

极点启发式的核心数据结构：候选放置点的集合。从原点 (0,0,0) 开始；
每放下一个箱子，就在其三条出边方向投影生成新的候选点。
（M1 采用 Crainic 等人极点法的简化版：仅沿坐标轴正向投影三个角点。）
"""
from __future__ import annotations

from .geometry import Box

Point = tuple[float, float, float]


class ExtremePointSet:
    def __init__(self) -> None:
        self._points: list[Point] = [(0.0, 0.0, 0.0)]

    def points(self) -> list[Point]:
        """返回按 (z, y, x) 升序排列的极点（靠底/靠里/靠左优先）。"""
        return sorted(self._points, key=lambda p: (p[2], p[1], p[0]))

    def remove(self, point: Point) -> None:
        if point in self._points:
            self._points.remove(point)

    def add_from_placement(self, box: Box, eps: float = 1e-6) -> None:
        """根据刚放下的 box 生成新极点并并入集合（去重）。"""
        x, y, z, dx, dy, dz = box
        candidates = [
            (x + dx, y, z),  # 沿 x 正向
            (x, y + dy, z),  # 沿 y 正向
            (x, y, z + dz),  # 沿 z 正向（堆叠）
        ]
        for c in candidates:
            if not self._contains(c, eps):
                self._points.append(c)

    def prune_covered(self, box: Box, eps: float = 1e-6) -> int:
        """删除最小角已经落入 box 占用空间内的极点。"""
        before = len(self._points)
        self._points = [point for point in self._points if not _point_starts_inside_box(point, box, eps)]
        return before - len(self._points)

    def _contains(self, point: Point, eps: float) -> bool:
        return any(
            abs(point[0] - p[0]) <= eps
            and abs(point[1] - p[1]) <= eps
            and abs(point[2] - p[2]) <= eps
            for p in self._points
        )


def _point_starts_inside_box(point: Point, box: Box, eps: float = 1e-6) -> bool:
    px, py, pz = point
    x, y, z, dx, dy, dz = box
    return (
        px >= x - eps
        and py >= y - eps
        and pz >= z - eps
        and px < x + dx - eps
        and py < y + dy - eps
        and pz < z + dz - eps
    )
