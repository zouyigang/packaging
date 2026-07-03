"""约束校验（M4）。

引擎逐条校验的物理约束（几何越界/重叠在 geometry.py，朝向在 find_placement 内枚举）：
  - 支撑（防悬空）：箱体底面须落在地面或下方箱顶，支撑面积比例 ≥ 阈值。
  - 堆叠承重：压在某箱顶部的重量（按接触面积分摊）不得超过其 max_load_top；
    易碎品 max_load_top=0 → 顶部不可压；None → 无限制。
  - 容器载重上限在 packer 层按累计重量校验（见 packer）。
  - 整体重心「尽量低且居中」属软目标，由 objectives 的放置评分体现，不在此做硬约束。

直接分摊的简化：仅把新箱重量分摊给「直接支撑它的下方箱」，不向更下层传递
（传递式承重留待后续）。对单一支撑柱因此不限高，但能正确限制「多箱共压一箱」。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .geometry import Box

EPS = 1e-6
DEFAULT_SUPPORT_RATIO = 1.0  # Require full base support for non-ground loads.
DEFAULT_COG_MAX_OFFSET_RATIO = 0.25  # Max normalized COG offset per horizontal axis.


@dataclass
class PlacedItem:
    """已放置物体的运行期记录：几何 + 承重状态。"""

    box: Box
    weight: float
    max_load_top: Optional[float]  # None=无限制, 0=易碎
    item_id: str
    stacking_type: str = "stackable"
    carried: float = 0.0  # 已压在其顶部的累计重量


def _base_area(box: Box) -> float:
    return box[3] * box[4]


def _contact_area(box: Box, other: Box) -> float:
    """box 底面与 other 顶面在同一高度时的水平重叠面积（否则 0）。"""
    x, y, z, dx, dy, _dz = box
    bx, by, bz, bdx, bdy, bdz = other
    if abs((bz + bdz) - z) > EPS:  # other 顶面不在 box 底面高度
        return 0.0
    ox = max(0.0, min(x + dx, bx + bdx) - max(x, bx))
    oy = max(0.0, min(y + dy, by + bdy) - max(y, by))
    return ox * oy


def supporters(box: Box, placed: list[PlacedItem]) -> list[tuple[PlacedItem, float]]:
    """返回直接支撑 box 的 (下方箱, 接触面积) 列表；box 在地面则返回空。"""
    if box[2] <= EPS:
        return []
    out: list[tuple[PlacedItem, float]] = []
    for pi in placed:
        area = _contact_area(box, pi.box)
        if area > EPS:
            out.append((pi, area))
    return out


def check_support(box: Box, placed: list[PlacedItem],
                  min_support_ratio: float = DEFAULT_SUPPORT_RATIO) -> bool:
    """箱体是否被充分支撑（地面或下方箱顶接触面积比例达标）。"""
    if box[2] <= EPS:  # 贴地
        return True
    total = sum(area for _pi, area in supporters(box, placed))
    return total / _base_area(box) >= min_support_ratio - EPS


def check_stack_load(box: Box, weight: float, placed: list[PlacedItem]) -> bool:
    """新箱(重 weight)压在支撑箱上，按接触面积分摊后不得超各支撑箱 max_load_top。"""
    sups = supporters(box, placed)
    total_area = sum(a for _pi, a in sups)
    if total_area <= EPS:
        return True  # 地面承重，无上限
    for pi, area in sups:
        if pi.max_load_top is None:
            continue  # 无限制
        share = weight * (area / total_area)
        if pi.carried + share > pi.max_load_top + EPS:
            return False
    return True


def check_stacking_type(
    box: Box,
    item_id: str,
    stacking_type: str,
    placed: list[PlacedItem],
) -> bool:
    """Validate vertical stacking compatibility with direct supporters."""
    sups = supporters(box, placed)
    if box[2] <= EPS:
        return stacking_type != "top_only"
    if not sups:
        return False
    for supporter, _area in sups:
        if not _can_be_supported_by(stacking_type, item_id, supporter):
            return False
        if not _can_support(supporter.stacking_type, supporter.item_id, item_id):
            return False
    return True


def _can_be_supported_by(stacking_type: str, item_id: str, supporter: PlacedItem) -> bool:
    if stacking_type == "not_stackable":
        return False
    if stacking_type == "same_item_only":
        return supporter.item_id == item_id
    if stacking_type == "support_only":
        return False
    return True


def _can_support(stacking_type: str, supporter_id: str, item_id: str) -> bool:
    if stacking_type == "not_stackable":
        return False
    if stacking_type == "same_item_only":
        return supporter_id == item_id
    if stacking_type == "top_only":
        return False
    return True


def check_heavy_low(box: Box, weight: float, placed: list[PlacedItem]) -> bool:
    """Reject placing a heavier item directly on top of lighter support items."""
    if box[2] <= EPS:
        return True
    return all(weight <= pi.weight + EPS for pi, _area in supporters(box, placed))


def check_cog_within_limits(
    box: Box,
    weight: float,
    placed: list[PlacedItem],
    inner_length: float,
    inner_width: float,
    max_offset_ratio: float = DEFAULT_COG_MAX_OFFSET_RATIO,
) -> bool:
    """Keep the running horizontal center of gravity within container limits."""
    x, y, _z, dx, dy, dz = box
    mass = weight if weight > 0 else dx * dy * dz
    total_w = mass
    sum_wx = mass * (x + dx / 2.0)
    sum_wy = mass * (y + dy / 2.0)
    for pi in placed:
        px, py, _pz, pdx, pdy, pdz = pi.box
        pmass = pi.weight if pi.weight > 0 else pdx * pdy * pdz
        total_w += pmass
        sum_wx += pmass * (px + pdx / 2.0)
        sum_wy += pmass * (py + pdy / 2.0)
    if total_w <= EPS:
        return True
    gx = sum_wx / total_w
    gy = sum_wy / total_w
    norm_x = abs(gx - inner_length / 2.0) / inner_length
    norm_y = abs(gy - inner_width / 2.0) / inner_width
    return norm_x <= max_offset_ratio + EPS and norm_y <= max_offset_ratio + EPS

def commit_stack_load(box: Box, weight: float, placed: list[PlacedItem]) -> None:
    """放置已确认后，把新箱重量按接触面积累加到各支撑箱的 carried。"""
    sups = supporters(box, placed)
    total_area = sum(a for _pi, a in sups)
    if total_area <= EPS:
        return
    for pi, area in sups:
        pi.carried += weight * (area / total_area)
