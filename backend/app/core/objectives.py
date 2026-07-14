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

# 托盘块封顶（max_load_top=0），码不满的柱高就是永久损失。装卸效率类目标最多容忍
# 损失 15% 柱高来换「整块叉运」的收益，超过就散装。
MIN_PALLET_COLUMN_EFFICIENCY = 0.85


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
    sum_wz: float = 0.0   # Σ 质量 × 中心z
    current_stop_seq: int = 1
    current_customer_id: str = ""
    current_order_id: str = ""
    min_stop_seq: int = 1
    max_stop_seq: int = 1
    delivery_groups: dict[tuple[str, int, str], tuple[float, float, float]] = field(default_factory=dict)
    # 每换一件待放件、或每次并入新放置更新 delivery_groups，都要 +1；配送簇质心据此失效重算。
    epoch: int = 0
    _cluster_cache: tuple[int, tuple[tuple[float, float], ...]] | None = field(
        default=None, repr=False, compare=False
    )

    def cluster_targets(self) -> tuple[tuple[float, float], ...]:
        """当前待放件所属客户/订单簇的质心，按 epoch 缓存。

        质心在一整次 find_placement 里恒定，而评分函数要对上千个候选箱各调一次，
        故必须缓存，否则每个候选箱都要重建组键、查字典、重算均值。
        """
        cached = self._cluster_cache
        if cached is not None and cached[0] == self.epoch:
            return cached[1]
        targets: list[tuple[float, float]] = []
        for key in delivery_group_keys(
            self.current_stop_seq, self.current_customer_id, self.current_order_id
        ):
            group = self.delivery_groups.get(key)
            if not group:
                continue
            count, sum_x, sum_y = group
            if count <= 0:
                continue
            targets.append((sum_x / count, sum_y / count))
        resolved = tuple(targets)
        self._cluster_cache = (self.epoch, resolved)
        return resolved


@dataclass(frozen=True)
class AdvancedScoreWeights:
    cost_efficiency: float = 0.15
    space_utilization: float = 0.35
    stability: float = 0.25
    palletization: float = 0.0
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
        return sorted(
            placeables,
            key=lambda p: (
                -int(bool(getattr(p, "must_load", False))),
                -int(getattr(p, "priority", 0) or 0),
                -(p.length * p.width * p.height),
            ),
        )

    def should_palletize(
        self,
        load_efficiency: float,
        count_per_pallet: int,
        column_efficiency: float = 1.0,
    ) -> bool:
        """是否对某货品采用「先码托盘再装」。

        默认 False：单件直接装容器在体积上总是更省（托盘有台面高 + 码放空隙开销），
        故体积/数量类目标不码托盘。托盘的收益主要在搬运与稳定性，见各子类覆写。
        load_efficiency = 货物体积 / 满托盘包围盒体积；count_per_pallet = 单托盘可码件数；
        column_efficiency = 托盘净码高 / 同货直接堆叠可达净高（托盘块封顶，不足 1 的部分
        是被它永久废掉的柱高，见 packer._pallet_column_efficiency）。
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


class CostEfficiency(MinContainers):
    """Minimize declared activation cost after mandatory completion goals."""

    name = "cost_efficiency"

    def order_containers(self, containers: list[Container]) -> list[Container]:
        def key(container: Container) -> tuple[float, float, float]:
            volume = max(_volume(container), 1.0)
            cost = container.use_cost
            if cost is None:
                return (1.0 / volume, 1.0, -volume)
            return (cost / volume, cost, -volume)

        return sorted(containers, key=key)


class SpaceUtilization(Objective):
    """Prefer the smallest available capacity that can be filled well."""

    name = "space_utilization"

    def order_containers(self, containers: list[Container]) -> list[Container]:
        return sorted(containers, key=_volume)


class Stability(Objective):
    """稳定性优先：重心尽量低，且优先大底面着地。"""

    name = "stability"

    def placement_score(self, box: Box) -> tuple[float, ...]:
        x, y, z, dx, dy, dz = box
        # z 最低优先（低重心）；同高时底面积大者优先（-面积 → 越大越靠前）；再靠里/靠左。
        return (z, -(dx * dy), y, x)

    def should_palletize(
        self,
        load_efficiency: float,
        count_per_pallet: int,
        column_efficiency: float = 1.0,
    ) -> bool:
        # 稳定性优先：把多件松散货物码成整托盘块更稳（降低重心、抗位移），
        # 为此甘愿付出被托盘块废掉的那部分柱高，故不看 column_efficiency。
        return count_per_pallet >= 2


class SafeLoading(Stability):
    """Combine local stack stability with global horizontal load balance."""

    name = "safe_loading"

    def __init__(self, safety_priority: bool = False):
        self.safety_priority = safety_priority

    def make_scorer(self, ctx: ScoreContext) -> ScoreFn:
        # Keep the local search stable and compact; whole-load balance is
        # corrected by the safe-loading centering pass after construction.
        return self.placement_score

    def order_placeables(self, placeables: list[Any]) -> list[Any]:
        if not self.safety_priority:
            return super().order_placeables(placeables)
        # 安全优先：扁平件先落位。堆垛簇的倾覆裕量与所需固定力由「重心高 / 底面半宽」
        # 决定，先把矮胖件铺开、把细高件留到最后，能显著压低细长比与固定力需求。
        # 这会改变装填顺序、从而降低密度——容器数可能上升，是用户明确选择的交换。
        return sorted(
            placeables,
            key=lambda p: (
                -int(bool(getattr(p, "must_load", False))),
                -int(getattr(p, "priority", 0) or 0),
                _flatness(p),
                -(p.length * p.width * p.height),
            ),
        )


def _flatness(placeable: Any) -> float:
    """最小边 / √(底面积)：越小越扁平，堆起来重心越低、底面相对越宽。"""
    short, mid, long_ = sorted((placeable.length, placeable.width, placeable.height))
    base_area = mid * long_
    if base_area <= 0:
        return 0.0
    return short / base_area ** 0.5


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

    def should_palletize(
        self,
        load_efficiency: float,
        count_per_pallet: int,
        column_efficiency: float = 1.0,
    ) -> bool:
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
                -int(bool(getattr(p, "must_load", False))),
                -int(getattr(p, "priority", 0) or 0),
                getattr(p, "destination_id", "") or "",
                getattr(p, "customer_id", "") or "",
                getattr(p, "order_id", "") or "",
                -(p.length * p.width * p.height),
            ),
        )

    def make_scorer(self, ctx: ScoreContext) -> ScoreFn:
        # 评分函数在每次 find_placement 里要对上千个候选箱各调一次（生产规模上是 10^6 量级），
        # 因此入口面分派、居中分母、簇质心这些「一件货之内恒定」的量全部提到构造期，
        # 按入口配置返回特化的闭包。数值与展开前逐位一致。
        sides = ctx.loading_access_sides or ("x_max",)
        single_side = sides[0] if len(sides) == 1 else None
        length = ctx.inner_length or 1.0
        width = ctx.inner_width or 1.0
        has_delivery_stops = ctx.max_stop_seq > ctx.min_stop_seq
        half_length = ctx.inner_length / 2.0
        half_width = ctx.inner_width / 2.0
        stop_span = (ctx.max_stop_seq - ctx.min_stop_seq) or 1
        min_stop = ctx.min_stop_seq

        def stop_pos() -> float:
            return (ctx.current_stop_seq - min_stop) / stop_span

        cluster = _delivery_cluster_score

        if single_side is not None:
            # 单入口时「该面的深度」就是「最近入口深度」，两者不必各算一遍。
            depth_of = _normalized_depth_fn(single_side, ctx)

            if single_side in {"x_min", "x_max"}:
                if has_delivery_stops:
                    def score(box: Box) -> tuple[float, ...]:
                        x, y, z, dx, dy, _dz = box
                        station = abs(depth_of(box) - stop_pos())
                        cy = abs((y + dy / 2.0) - half_width) / width
                        return (station, cluster(ctx, box), cy, z, x, y, -(dx * dy))
                    return score

                # 端门整箱同站时没有卸货顺序可优化：横向居中会把货堆到宽度中线、
                # 把两侧压成放不下货的窄条，故改用靠墙贴角键做紧凑填充。同一站点
                # 内部的卸货顺序由求解器自定，无需保留居中语义。顶开与侧门的居中
                # 是有意的取货可达性设计（见 test_packer 对应用例），保持不变。
                def score(box: Box) -> tuple[float, ...]:
                    x, y, z, dx, dy, _dz = box
                    return (z, y, -depth_of(box), cluster(ctx, box), x, -(dx * dy))
                return score

            if single_side in {"y_min", "y_max"}:
                if has_delivery_stops:
                    def score(box: Box) -> tuple[float, ...]:
                        x, y, z, dx, dy, _dz = box
                        station = abs(depth_of(box) - stop_pos())
                        cx = abs((x + dx / 2.0) - half_length) / length
                        return (station, cluster(ctx, box), cx, z, x, y, -(dx * dy))
                    return score

                def score(box: Box) -> tuple[float, ...]:
                    x, y, z, dx, dy, _dz = box
                    cx = abs((x + dx / 2.0) - half_length) / length
                    return (z, depth_of(box), cx, cluster(ctx, box), x, y, -(dx * dy))
                return score

            if single_side == "z_max":
                if has_delivery_stops:
                    def score(box: Box) -> tuple[float, ...]:
                        x, y, z, dx, dy, _dz = box
                        station = abs(depth_of(box) - stop_pos())
                        cx = abs((x + dx / 2.0) - half_length) / length
                        cy = abs((y + dy / 2.0) - half_width) / width
                        return (
                            station, cluster(ctx, box), cx + cy, z,
                            depth_of(box), -(dx * dy), x, y,
                        )
                    return score

                def score(box: Box) -> tuple[float, ...]:
                    x, y, z, dx, dy, _dz = box
                    cx = abs((x + dx / 2.0) - half_length) / length
                    cy = abs((y + dy / 2.0) - half_width) / width
                    return (
                        z, cx + cy, depth_of(box), cluster(ctx, box),
                        -(dx * dy), x, y,
                    )
                return score

        ranked_sides = [(_normalized_depth_fn(side, ctx), _side_rank(side)) for side in sides]

        def score(box: Box) -> tuple[float, ...]:
            x, y, z, dx, dy, _dz = box
            # min(sides, key=...) 取首个最小者，这里保持同样的先到先得语义。
            nearest, nearest_rank = min(
                ((depth(box), rank) for depth, rank in ranked_sides),
                key=lambda pair: pair[0],
            )
            cx = abs((x + dx / 2.0) - half_length) / length
            cy = abs((y + dy / 2.0) - half_width) / width
            area = dx * dy
            if has_delivery_stops:
                station = abs(nearest - stop_pos())
                return (station, cluster(ctx, box), nearest_rank, cx + cy, z, x, y, -area)
            return (z, nearest, nearest_rank, cx + cy, cluster(ctx, box), x, y, -area)

        return score

    def placement_score(self, box: Box) -> tuple[float, ...]:
        x, y, z, dx, dy, _dz = box
        return (z, x, y, -(dx * dy))

    def should_palletize(
        self,
        load_efficiency: float,
        count_per_pallet: int,
        column_efficiency: float = 1.0,
    ) -> bool:
        # 托盘块封顶：它脚下那根柱子只能码到 max_stack_height，余高全部作废。装卸效率类
        # 目标愿意为「一次叉走一整块」付出一点柱高，但代价过大时宁可散装堆到容器顶。
        return (
            count_per_pallet >= 2
            and load_efficiency >= 0.45
            and column_efficiency >= MIN_PALLET_COLUMN_EFFICIENCY
        )


class DeliverySequence(LoadingEfficiency):
    name = "delivery_sequence"


class Custom(Balanced):
    name = "custom"


def delivery_group_keys(stop_seq: int, customer_id: str, order_id: str) -> list[tuple[str, int, str]]:
    keys: list[tuple[str, int, str]] = []
    if customer_id:
        keys.append(("customer", stop_seq, customer_id))
    if order_id:
        keys.append(("order", stop_seq, order_id))
    return keys


def _delivery_cluster_score(ctx: ScoreContext, box: Box) -> float:
    targets = ctx.cluster_targets()
    if not targets:
        return 0.0
    x, y, _z, dx, dy, _dz = box
    bx = x + dx / 2.0
    by = y + dy / 2.0
    denom_x = ctx.inner_length or 1.0
    denom_y = ctx.inner_width or 1.0
    if len(targets) == 1:  # 绝大多数货只属于一个客户/订单簇，别为它起生成器
        gx, gy = targets[0]
        return abs(bx - gx) / denom_x + abs(by - gy) / denom_y
    return min(
        abs(bx - gx) / denom_x + abs(by - gy) / denom_y for gx, gy in targets
    )


def _normalized_depth_fn(side: str, ctx: ScoreContext) -> Callable[[Box], float]:
    """把 _normalized_access_depth 的入口面分派提前到构造期。

    评分函数每个候选箱都要算一次入口深度；原实现每次都要跑一遍字符串比较链，
    在 10^6 量级的候选上是可观的开销。
    """
    length = ctx.inner_length or 1.0
    width = ctx.inner_width or 1.0
    height = ctx.inner_height or 1.0
    inner_length = ctx.inner_length
    inner_width = ctx.inner_width
    inner_height = ctx.inner_height
    if side == "x_min":
        return lambda box: box[0] / length
    if side == "x_max":
        return lambda box: (inner_length - (box[0] + box[3])) / length
    if side == "y_min":
        return lambda box: box[1] / width
    if side == "y_max":
        return lambda box: (inner_width - (box[1] + box[4])) / width
    if side == "z_max":
        return lambda box: (inner_height - (box[2] + box[5])) / height
    return lambda box: 0.0


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
advanced_score = Balanced(AdvancedScoreWeights(cost_efficiency=0.0, palletization=0.15))
weight_balance = CenterOfGravity()
loading_efficiency = LoadingEfficiency()
multi_customer_delivery = loading_efficiency
cost_efficiency = CostEfficiency()
space_utilization = SpaceUtilization()
safe_loading = SafeLoading()
delivery_sequence = DeliverySequence()
custom = Custom()

_REGISTRY: dict[str, Objective] = {
    "cost_efficiency": cost_efficiency,
    "space_utilization": space_utilization,
    "safe_loading": safe_loading,
    "delivery_sequence": delivery_sequence,
    "custom": custom,
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

_CANONICAL_OBJECTIVES: dict[str, tuple[str, str]] = {
    "cost_efficiency": ("cost_efficiency", "default"),
    "transport_cost": ("cost_efficiency", "legacy_transport_cost"),
    "min_containers": ("cost_efficiency", "legacy_min_containers"),
    "space_utilization": ("space_utilization", "default"),
    "max_utilization": ("space_utilization", "legacy_max_utilization"),
    "safe_loading": ("safe_loading", "balanced_safety"),
    "load_stability": ("safe_loading", "legacy_stability"),
    "stability": ("safe_loading", "legacy_stability"),
    "weight_balance": ("safe_loading", "legacy_balance"),
    "center_of_gravity": ("safe_loading", "legacy_balance"),
    "delivery_sequence": ("delivery_sequence", "default"),
    "loading_efficiency": ("delivery_sequence", "legacy_loading"),
    "multi_customer_delivery": ("delivery_sequence", "legacy_loading"),
    "custom": ("custom", "default"),
    "advanced_score": ("custom", "legacy_advanced"),
    "balanced": ("custom", "legacy_advanced"),
}


def resolve_objective(name: str) -> tuple[str, str]:
    try:
        return _CANONICAL_OBJECTIVES[name]
    except KeyError as exc:
        raise ValueError(f"未知优化目标: {name!r}，可选: {sorted(_REGISTRY)}") from exc

def get_objective(
    name: str,
    advanced_weights: Any | None = None,
    safety_priority: bool = False,
) -> Objective:
    if name in {"advanced_score", "balanced", "custom"} and advanced_weights is not None:
        return Custom(_coerce_advanced_weights(advanced_weights)) if name == "custom" else Balanced(_coerce_advanced_weights(advanced_weights))
    try:
        objective = _REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"未知优化目标: {name!r}，可选: {sorted(_REGISTRY)}") from exc
    # 注册表存的是单例；安全优先要换一套放置顺序，故另建实例，不污染共享单例。
    if safety_priority and isinstance(objective, SafeLoading):
        return SafeLoading(safety_priority=True)
    return objective


def _coerce_advanced_weights(value: Any) -> AdvancedScoreWeights:
    if isinstance(value, AdvancedScoreWeights):
        return value
    if hasattr(value, "model_dump"):
        data = value.model_dump()
    else:
        data = dict(value)
    defaults = AdvancedScoreWeights()
    return AdvancedScoreWeights(
        cost_efficiency=float(data.get("cost_efficiency", defaults.cost_efficiency)),
        space_utilization=float(data.get("space_utilization", defaults.space_utilization)),
        stability=float(data.get("stability", defaults.stability)),
        palletization=float(data.get("palletization", defaults.palletization)),
        balance=float(data.get("balance", defaults.balance)),
        loading_position=float(data.get("loading_position", defaults.loading_position)),
    )
