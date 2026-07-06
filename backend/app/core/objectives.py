"""可插拔优化目标（策略模式）。

目标函数影响两处决策（均不改动引擎核心，运行时按名注入）：
  1. 放置评分 placement_score：在极点启发式里，对候选放置位置打分（返回元组，越小越优）。
  2. 容器开箱顺序 order_containers：多容器循环里决定优先用哪种容器。

新增目标只需继承 Objective 并注册到 _REGISTRY。
目标名与 schemas.Objective 字面量保持一致：
  max_utilization / min_containers / stability / balanced
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..models.schemas import Container
from .geometry import Box

ScoreFn = Callable[[Box], tuple[float, ...]]


@dataclass
class ScoreContext:
    """放置评分的上下文：容器尺寸 + 当前容器内已放货物的累计质量与加权坐标。

    供「重心居中」等需要全局信息的目标使用；packer 每放一件就更新累计量。
    质量优先用重量(weight)；重量为 0 时用体积兜底（见 packer）。
    """

    inner_length: float
    inner_width: float
    inner_height: float = 0.0
    loading_access_sides: tuple[str, ...] = ("x_max",)
    unit_w: float = 0.0   # 当前待放件的质量（放置前由 packer 设好）
    total_w: float = 0.0  # 已放货物累计质量
    sum_wx: float = 0.0   # Σ 质量 × 中心x
    sum_wy: float = 0.0   # Σ 质量 × 中心y
    current_stop_seq: int = 1
    current_customer_id: str = ""
    current_order_id: str = ""
    min_stop_seq: int = 1
    max_stop_seq: int = 1
    delivery_groups: dict[tuple[str, int, str], tuple[float, float, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class AdvancedScoreWeights:
    space_utilization: float = 0.35
    stability: float = 0.25
    palletization: float = 0.15
    balance: float = 0.15
    loading_position: float = 0.10


class Objective:
    """目标基类。默认策略：放置靠底→靠里→靠左；容器顺序不变。"""

    name: str = "base"

    def placement_score(self, box: Box) -> tuple[float, ...]:
        x, y, z, *_ = box
        return (z, y, x)

    def make_scorer(self, ctx: ScoreContext) -> ScoreFn:
        """返回放置评分函数。默认忽略上下文，等同 placement_score。

        需要全局信息的目标（如重心居中）覆写此方法，闭包捕获 ctx。
        """
        return self.placement_score

    def order_containers(self, containers: list[Container]) -> list[Container]:
        return list(containers)

    def order_placeables(self, placeables: list[Any]) -> list[Any]:
        return sorted(placeables, key=lambda p: p.length * p.width * p.height, reverse=True)

    def should_palletize(self, load_efficiency: float, count_per_pallet: int) -> bool:
        """是否对某货品采用「先码托盘再装」。

        默认 False：单件直接装容器在体积上总是更省（托盘有台面高 + 码放空隙开销），
        故体积/数量类目标不码托盘。托盘的收益主要在搬运与稳定性，见各子类覆写。
        load_efficiency = 货物体积 / 满托盘包围盒体积；count_per_pallet = 单托盘可码件数。
        """
        return False


class MaxUtilization(Objective):
    """最大空间利用率：紧贴底/里/左塞满；优先开大容器以容纳更多。"""

    name = "max_utilization"

    def order_containers(self, containers: list[Container]) -> list[Container]:
        return sorted(containers, key=_volume, reverse=True)


class MinContainers(Objective):
    """最少容器数：优先开最大的容器，尽量把货塞进少数箱子。"""

    name = "min_containers"

    def order_containers(self, containers: list[Container]) -> list[Container]:
        return sorted(containers, key=_volume, reverse=True)


class Stability(Objective):
    """稳定性优先：重心尽量低，且优先大底面着地。"""

    name = "stability"

    def placement_score(self, box: Box) -> tuple[float, ...]:
        x, y, z, dx, dy, dz = box
        # z 最低优先（低重心）；同高时底面积大者优先（-面积 → 越大越靠前）；再靠里/靠左。
        return (z, -(dx * dy), y, x)

    def should_palletize(self, load_efficiency: float, count_per_pallet: int) -> bool:
        # 稳定性优先：把多件松散货物码成整托盘块更稳（降低重心、抗位移）。
        return count_per_pallet >= 2


class Balanced(Objective):
    """显式加权综合评分：空间紧凑、稳定、重心均衡、装卸位置与托盘化收益。"""

    name = "balanced"

    def __init__(self, weights: AdvancedScoreWeights | None = None):
        self.weights = weights or AdvancedScoreWeights()

    def make_scorer(self, ctx: ScoreContext) -> ScoreFn:
        length = ctx.inner_length or 1.0
        width = ctx.inner_width or 1.0
        height = ctx.inner_height or 1.0
        footprint = length * width or 1.0
        weights = self.weights

        def score(box: Box) -> tuple[float, ...]:
            x, y, z, dx, dy, dz = box
            space_score = _space_compaction_score(box, length, width, height)
            stability_score = _stability_score(box, footprint, height)
            balance_score = _balance_score(ctx, box, length, width)
            loading_score = _loading_position_score(ctx, box)

            weighted = (
                weights.space_utilization * space_score
                + weights.stability * stability_score
                + weights.balance * balance_score
                + weights.loading_position * loading_score
            )
            return (weighted, z / height, x / length, y / width)

        return score

    def placement_score(self, box: Box) -> tuple[float, ...]:
        x, y, z, dx, dy, dz = box
        volume = max(dx * dy * dz, 1.0)
        area = max(dx * dy, 1.0)
        compactness = z + y + x
        stability = z + dz / area
        return (0.6 * compactness + 0.4 * stability, z, -volume)

    def should_palletize(self, load_efficiency: float, count_per_pallet: int) -> bool:
        if count_per_pallet < 2:
            return False
        count_score = min(count_per_pallet / 8.0, 1.0)
        pallet_score = 0.65 * load_efficiency + 0.35 * count_score
        return pallet_score >= 0.40 + self.weights.palletization


class CenterOfGravity(Objective):
    """重心居中：每放一件都选「放下后整体重心最接近容器水平中心」的位置。

    评分主项为放置后重心到容器水平中心(长x、宽y)的偏移；次项为低 z（重心也尽量低）。
    适合在装不满时仍让负载左右/前后均衡、避免堆在一个角而偏心。
    注：极点法的候选点从角落生长，故无法做到完美居中，但相比靠角策略能显著减小偏心。
    """

    name = "center_of_gravity"

    def make_scorer(self, ctx: ScoreContext) -> ScoreFn:
        cx = ctx.inner_length / 2.0
        cy = ctx.inner_width / 2.0
        length = ctx.inner_length or 1.0
        width = ctx.inner_width or 1.0
        height = ctx.inner_height or 1.0

        def score(box: Box) -> tuple[float, ...]:
            x, y, z, dx, dy, _dz = box
            bx = x + dx / 2.0
            by = y + dy / 2.0
            m = ctx.unit_w if ctx.unit_w > 0 else dx * dy * _dz
            nw = ctx.total_w + m  # m>0 恒成立，nw>0
            gx = (ctx.sum_wx + m * bx) / nw
            gy = (ctx.sum_wy + m * by) / nw
            norm_x = abs(gx - cx) / length
            norm_y = abs(gy - cy) / width
            height_penalty = 0.60 * (z / height)
            compactness_penalty = 0.08 * ((x + dx) / length + (y + dy) / width)
            return (
                max(norm_x, norm_y) + height_penalty + compactness_penalty,
                norm_x + norm_y + height_penalty + compactness_penalty,
                z,
                x,
                y,
            )

        return score


def _space_compaction_score(box: Box, length: float, width: float, height: float) -> float:
    x, y, z, dx, dy, dz = box
    top = (z + dz) / height
    front = (x + dx) / length
    side = (y + dy) / width
    low = z / height
    return 0.45 * top + 0.25 * front + 0.20 * side + 0.10 * low


def _stability_score(box: Box, footprint: float, height: float) -> float:
    _x, _y, z, dx, dy, dz = box
    base_ratio = min((dx * dy) / footprint, 1.0)
    center_height = (z + dz / 2.0) / height
    slenderness = dz / max(dx, dy, 1.0)
    return 0.50 * center_height + 0.35 * (1.0 - base_ratio) + 0.15 * min(slenderness, 1.0)


def _balance_score(ctx: ScoreContext, box: Box, length: float, width: float) -> float:
    x, y, z, dx, dy, dz = box
    mass = ctx.unit_w if ctx.unit_w > 0 else dx * dy * dz
    total = ctx.total_w + mass
    if total <= 0:
        return 0.0
    gx = (ctx.sum_wx + mass * (x + dx / 2.0)) / total
    gy = (ctx.sum_wy + mass * (y + dy / 2.0)) / total
    norm_x = abs(gx - length / 2.0) / length
    norm_y = abs(gy - width / 2.0) / width
    return max(norm_x, norm_y) + norm_x + norm_y


def _loading_position_score(ctx: ScoreContext, box: Box) -> float:
    sides = ctx.loading_access_sides or ("x_max",)
    nearest_depth = min(_normalized_access_depth(box, side, ctx) for side in sides)
    if ctx.max_stop_seq > ctx.min_stop_seq:
        stop_pos = (ctx.current_stop_seq - ctx.min_stop_seq) / (ctx.max_stop_seq - ctx.min_stop_seq)
        return abs(nearest_depth - stop_pos) + _delivery_cluster_score(ctx, box)
    return 1.0 - nearest_depth


class LoadingEfficiency(Objective):
    """Loading efficiency with stop sequencing and soft customer/order clustering."""

    name = "loading_efficiency"

    def order_placeables(self, placeables: list[Any]) -> list[Any]:
        return sorted(
            placeables,
            key=lambda p: (
                -max(1, int(getattr(p, "stop_seq", 1) or 1)),
                getattr(p, "destination_id", "") or "",
                getattr(p, "customer_id", "") or "",
                getattr(p, "order_id", "") or "",
                -(p.length * p.width * p.height),
            ),
        )

    def make_scorer(self, ctx: ScoreContext) -> ScoreFn:
        sides = ctx.loading_access_sides or ("x_max",)
        single_side = sides[0] if len(sides) == 1 else None
        length = ctx.inner_length or 1.0
        width = ctx.inner_width or 1.0
        height = ctx.inner_height or 1.0
        has_delivery_stops = ctx.max_stop_seq > ctx.min_stop_seq

        def delivery_score(box: Box) -> tuple[float, float]:
            nearest_depth = min(_normalized_access_depth(box, side, ctx) for side in sides)
            if has_delivery_stops:
                stop_pos = (ctx.current_stop_seq - ctx.min_stop_seq) / (ctx.max_stop_seq - ctx.min_stop_seq)
                station_score = abs(nearest_depth - stop_pos)
            else:
                station_score = 0.0
            return (station_score, _delivery_cluster_score(ctx, box))

        def score(box: Box) -> tuple[float, ...]:
            x, y, z, dx, dy, dz = box
            area = dx * dy
            cx = abs((x + dx / 2.0) - ctx.inner_length / 2.0) / length
            cy = abs((y + dy / 2.0) - ctx.inner_width / 2.0) / width
            station_score, cluster_score = delivery_score(box)

            if single_side in {"x_min", "x_max"}:
                depth = _access_depth(box, single_side, ctx) / length
                lateral = cy
                if has_delivery_stops:
                    return (station_score, cluster_score, lateral, z, x, y, -area)
                return (z, -depth, lateral, cluster_score, x, y, -area)

            if single_side in {"y_min", "y_max"}:
                depth = _access_depth(box, single_side, ctx) / width
                if has_delivery_stops:
                    return (station_score, cluster_score, cx, z, x, y, -area)
                return (z, depth, cx, cluster_score, x, y, -area)

            if single_side == "z_max":
                top_depth = _access_depth(box, "z_max", ctx) / height
                if has_delivery_stops:
                    return (station_score, cluster_score, cx + cy, z, top_depth, -area, x, y)
                return (z, cx + cy, top_depth, cluster_score, -area, x, y)

            nearest = min(_normalized_access_depth(box, side, ctx) for side in sides)
            nearest_side = min(sides, key=lambda side: _normalized_access_depth(box, side, ctx))
            if has_delivery_stops:
                return (station_score, cluster_score, _side_rank(nearest_side), cx + cy, z, x, y, -area)
            return (z, nearest, _side_rank(nearest_side), cx + cy, cluster_score, x, y, -area)

        return score

    def placement_score(self, box: Box) -> tuple[float, ...]:
        x, y, z, dx, dy, _dz = box
        return (z, x, y, -(dx * dy))

    def should_palletize(self, load_efficiency: float, count_per_pallet: int) -> bool:
        return count_per_pallet >= 2 and load_efficiency >= 0.45


def delivery_group_keys(stop_seq: int, customer_id: str, order_id: str) -> list[tuple[str, int, str]]:
    keys: list[tuple[str, int, str]] = []
    if customer_id:
        keys.append(("customer", stop_seq, customer_id))
    if order_id:
        keys.append(("order", stop_seq, order_id))
    return keys


def _delivery_cluster_score(ctx: ScoreContext, box: Box) -> float:
    keys = delivery_group_keys(ctx.current_stop_seq, ctx.current_customer_id, ctx.current_order_id)
    if not keys:
        return 0.0
    x, y, _z, dx, dy, _dz = box
    bx = x + dx / 2.0
    by = y + dy / 2.0
    denom_x = ctx.inner_length or 1.0
    denom_y = ctx.inner_width or 1.0
    scores: list[float] = []
    for key in keys:
        group = ctx.delivery_groups.get(key)
        if not group:
            continue
        count, sum_x, sum_y = group
        if count <= 0:
            continue
        gx = sum_x / count
        gy = sum_y / count
        scores.append(abs(bx - gx) / denom_x + abs(by - gy) / denom_y)
    return min(scores) if scores else 0.0


def _access_depth(box: Box, side: str, ctx: ScoreContext) -> float:
    x, y, z, dx, dy, dz = box
    if side == "x_min":
        return x
    if side == "x_max":
        return ctx.inner_length - (x + dx)
    if side == "y_min":
        return y
    if side == "y_max":
        return ctx.inner_width - (y + dy)
    if side == "z_max":
        return ctx.inner_height - (z + dz)
    return 0.0


def _normalized_access_depth(box: Box, side: str, ctx: ScoreContext) -> float:
    if side in {"x_min", "x_max"}:
        denom = ctx.inner_length or 1.0
    elif side in {"y_min", "y_max"}:
        denom = ctx.inner_width or 1.0
    else:
        denom = ctx.inner_height or 1.0
    return _access_depth(box, side, ctx) / denom


def _side_rank(side: str) -> int:
    order = {"x_max": 0, "x_min": 1, "y_min": 2, "y_max": 3, "z_max": 4}
    return order.get(side, 99)

def _volume(c: Container) -> float:
    return c.inner_length * c.inner_width * c.inner_height


transport_cost = MaxUtilization()
min_containers = MinContainers()
load_stability = Stability()
advanced_score = Balanced()
weight_balance = CenterOfGravity()
loading_efficiency = LoadingEfficiency()
multi_customer_delivery = loading_efficiency

_REGISTRY: dict[str, Objective] = {
    "transport_cost": transport_cost,
    "max_utilization": transport_cost,
    "min_containers": min_containers,
    "load_stability": load_stability,
    "stability": load_stability,
    "advanced_score": advanced_score,
    "balanced": advanced_score,
    "weight_balance": weight_balance,
    "center_of_gravity": weight_balance,
    "loading_efficiency": loading_efficiency,
    "multi_customer_delivery": multi_customer_delivery,
}

def get_objective(name: str, advanced_weights: Any | None = None) -> Objective:
    if name in {"advanced_score", "balanced"} and advanced_weights is not None:
        return Balanced(_coerce_advanced_weights(advanced_weights))
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"未知优化目标: {name!r}，可选: {sorted(_REGISTRY)}") from exc


def _coerce_advanced_weights(value: Any) -> AdvancedScoreWeights:
    if isinstance(value, AdvancedScoreWeights):
        return value
    if hasattr(value, "model_dump"):
        data = value.model_dump()
    else:
        data = dict(value)
    defaults = AdvancedScoreWeights()
    return AdvancedScoreWeights(
        space_utilization=float(data.get("space_utilization", defaults.space_utilization)),
        stability=float(data.get("stability", defaults.stability)),
        palletization=float(data.get("palletization", defaults.palletization)),
        balance=float(data.get("balance", defaults.balance)),
        loading_position=float(data.get("loading_position", defaults.loading_position)),
    )
