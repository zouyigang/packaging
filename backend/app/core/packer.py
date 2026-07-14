"""编排器（M3：多容器循环 + 可插拔目标 + 直接装/码托盘决策）。

主流程：
  预处理（按数量展开为单件、大件先）→ 逐货品种类做「直接装 vs 码托盘」决策（由目标择优）
  → 生成待放置单元(placeable)：单件 或 托盘整块 → 多容器循环：按目标选容器开新箱 →
  极点启发式放置（记录坐标与 seq）→ 当前容器放不下的留到下一只 →
  容器用尽仍未放下的进入余货清单(unpacked)。

重量/朝向/堆叠/重心约束(M4) 在后续里程碑接入。
"""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass

from ..models.schemas import (
    Container,
    ConstraintViolation,
    Item,
    LoadedContainer,
    LoadingAccess,
    PalletInstance,
    PerformanceMetrics,
    Placement,
    Solution,
    SolveRequest,
)
from .constraints import (
    DEFAULT_COG_MAX_OFFSET_RATIO,
    DEFAULT_SUPPORT_RATIO,
    EPS,
    PlacedItem,
    can_accept_stack_load,
    commit_stack_load,
    support_links,
)
from .evaluator import evaluate_solution
from .extreme_point import OrientedRotation, find_placement
from .geometry import box_volume, oriented_dims
from .industrial import (
    _aligned_with_opening,
    _blocks_corridor,
    finalize_solution,
    prepare_request,
)
from .industrial_context import (
    IndustrialLoadContext,
    analyze_stack_clusters,
    stack_restraint_sufficient,
)
from .objectives import Objective, ScoreContext, delivery_group_keys, get_objective
from .performance import PerformanceTimer
from .palletizer import (
    build_mixed_pallet_load,
    build_pallet_load,
    pallet_load_efficiency,
    select_pallet,
)
from .space import ExtremePointSet

SPATIAL_BIN_SIZE = 500.0


def _expand(items: list[Item]) -> list[Item]:
    """把 quantity>1 的货品展开为多件 quantity=1 的实例，按体积降序（大件先放）。"""
    units: list[Item] = []
    for it in items:
        for _ in range(it.quantity):
            units.append(it.model_copy(update={"quantity": 1}))
    units.sort(key=lambda i: i.length * i.width * i.height, reverse=True)
    return units


def pack_units_into_container(
    units: list[Item], container: Container, objective: Objective
) -> tuple[LoadedContainer, list[Item]]:
    """把已展开的单件列表尽量装进单个容器。

    返回 (装载结果, 未能放入的剩余单件)。units 应已按放置优先级排好序。
    """
    raw_placeables = [_single_placeable(u) for u in units]
    unit_by_placeable_id = {id(p): u for p, u in zip(raw_placeables, units)}
    placeables = objective.order_placeables(raw_placeables)
    loaded, leftover_pl = _pack_placeables_into_container(placeables, container, objective)
    left_ids = {id(p) for p in leftover_pl}
    leftover_units = [unit_by_placeable_id[id(p)] for p in raw_placeables if id(p) in left_ids]
    return loaded, leftover_units


def pack_single_container(
    items: list[Item], container: Container, objective: str = "max_utilization"
) -> LoadedContainer:
    """单容器装载（M1 兼容入口）：展开后装进一个容器，返回装载结果。"""
    units = _expand(items)
    loaded, _leftover = pack_units_into_container(units, container, get_objective(objective))
    return loaded


@dataclass
class _Placeable:
    """容器装载循环的最小放置单元：一件货品，或一整块码好的托盘。

    单件：contents 为 None，朝向由放置时按目标自由选取。
    托盘块：contents 为块内各货品的相对放置；块固定不旋转（朝向恒为 'LWH'）。
    """

    item_id: str
    pallet_id: str | None
    pallet_deck_height: float
    pallet_tare_weight: float
    length: float
    width: float
    height: float
    allowed_rotations: list[str]
    volume: float
    oriented_rotations: list[OrientedRotation]
    weight: float
    customer_id: str
    order_id: str
    destination_id: str
    stop_seq: int
    must_load: bool
    priority: int
    pallet_group: str
    friction_coefficient: float | None
    stacking_type: str
    max_load_top: float | None  # 顶部可承重；托盘块为 None(此处不再向上堆叠)
    contents: list | None  # list[(item_id, x, y, z, orientation)] 相对块原点；None=单件
    content_dims: tuple[float, float, float] | None = None

    def item_ids(self) -> list[str]:
        if self.contents is None:
            return [self.item_id]
        return [c[0] for c in self.contents]

    def emit_with_boxes(
        self,
        px: float,
        py: float,
        pz: float,
        orientation: str,
        start_seq: int,
    ) -> list[tuple[Placement, tuple[float, float, float, float, float, float]]]:
        placements = self.emit(px, py, pz, orientation, start_seq)
        if self.contents is None:
            dx, dy, dz = oriented_dims(self.length, self.width, self.height, orientation)
            return [(placements[0], (px, py, pz, dx, dy, dz))]

        out: list[tuple[Placement, tuple[float, float, float, float, float, float]]] = []
        for placement, content in zip(placements, self.contents):
            _cid, ox, oy, oz, corient = content[:5]
            dims = tuple(content[5:8]) if len(content) >= 8 else self.content_dims
            if dims is None:
                out.append((placement, (placement.x, placement.y, placement.z, self.length, self.width, self.height)))
                continue
            dx, dy, dz = oriented_dims(*dims, corient)
            if orientation == "WLH":
                ox, oy = self.width - (oy + dy), ox
                dx, dy = dy, dx
            out.append((placement, (px + ox, py + oy, pz + oz, dx, dy, dz)))
        return out

    def emit(self, px: float, py: float, pz: float, orientation: str, start_seq: int) -> list[Placement]:
        if self.contents is None:
            return [
                Placement(
                    item_id=self.item_id,
                    pallet_id=None,
                    customer_id=self.customer_id,
                    order_id=self.order_id,
                    destination_id=self.destination_id,
                    stop_seq=self.stop_seq,
                    x=px,
                    y=py,
                    z=pz,
                    orientation=orientation,  # type: ignore[arg-type]
                    seq=start_seq + 1,
                )
            ]
        out: list[Placement] = []
        for i, content in enumerate(self.contents, start=1):
            cid, ox, oy, oz, corient = content[:5]
            customer_id = content[8] if len(content) >= 12 else self.customer_id
            order_id = content[9] if len(content) >= 12 else self.order_id
            destination_id = content[10] if len(content) >= 12 else self.destination_id
            stop_seq = content[11] if len(content) >= 12 else self.stop_seq
            if orientation == "WLH":
                dims = tuple(content[5:8]) if len(content) >= 8 else self.content_dims
                if dims is not None:
                    cdx, cdy, _cdz = oriented_dims(*dims, corient)
                    ox, oy = self.width - (oy + cdy), ox
                    corient = corient[1] + corient[0] + corient[2]
            out.append(
                Placement(
                    item_id=cid,
                    pallet_id=self.pallet_id,
                    customer_id=customer_id,
                    order_id=order_id,
                    destination_id=destination_id,
                    stop_seq=stop_seq,
                    x=px + ox,
                    y=py + oy,
                    z=pz + oz,
                    orientation=corient,  # type: ignore[arg-type]
                    seq=start_seq + i,
                )
            )
        return out


def _effective_stacking_type(item: Item) -> str:
    if not item.stackable and item.stacking_type == "stackable":
        return "not_stackable"
    return item.stacking_type


def _can_palletize_item(item: Item) -> bool:
    return item.stackable and _effective_stacking_type(item) in {"stackable", "same_item_only"}

def _placeable_volume(length: float, width: float, height: float) -> float:
    return length * width * height


def _oriented_rotations(
    length: float,
    width: float,
    height: float,
    allowed_rotations: list[str],
) -> list[OrientedRotation]:
    return [
        (orientation, *oriented_dims(length, width, height, orientation))
        for orientation in allowed_rotations
    ]


def _bounded_unique_values(values: list[float], upper: float, eps: float = 1e-6) -> list[float]:
    if upper < -eps:
        return []
    bounded: list[float] = []
    seen: set[float] = set()
    for value in values:
        if value < -eps or value > upper + eps:
            continue
        clamped = max(0.0, min(value, upper))
        if clamped in seen:
            continue
        seen.add(clamped)
        bounded.append(clamped)
    return bounded


def _z_key(value: float) -> float:
    return round(value, 6)


def _spatial_bin_range(start: float, end: float, bin_size: float = SPATIAL_BIN_SIZE) -> range:
    first = int(max(0.0, start) // bin_size)
    last = int(max(0.0, end - EPS) // bin_size)
    return range(first, last + 1)


def _add_to_spatial_grid(
    grid: dict[tuple[int, int], list[PlacedItem]],
    item: PlacedItem,
    bin_size: float = SPATIAL_BIN_SIZE,
) -> None:
    x, y, _z, dx, dy, _dz = item.box
    for bx in _spatial_bin_range(x, x + dx, bin_size):
        for by in _spatial_bin_range(y, y + dy, bin_size):
            grid.setdefault((bx, by), []).append(item)


def _check_cog_with_context(
    ctx: ScoreContext,
    pl: _Placeable,
    box: tuple[float, float, float, float, float, float],
    weight: float,
    inner_length: float,
    inner_width: float,
    max_offset_ratio: float = DEFAULT_COG_MAX_OFFSET_RATIO,
) -> bool:
    x, y, _z, dx, dy, _dz = box
    mass = weight if weight > 0 else pl.volume
    total_w = ctx.total_w + mass
    if total_w <= EPS:
        return True
    gx = (ctx.sum_wx + mass * (x + dx / 2.0)) / total_w
    gy = (ctx.sum_wy + mass * (y + dy / 2.0)) / total_w
    norm_x = abs(gx - inner_length / 2.0) / inner_length
    norm_y = abs(gy - inner_width / 2.0) / inner_width
    return norm_x <= max_offset_ratio + EPS and norm_y <= max_offset_ratio + EPS


def _check_configured_cog_limits(
    ctx: ScoreContext,
    pl: _Placeable,
    box: tuple[float, float, float, float, float, float],
    container: Container,
) -> bool:
    limits = container.cog_limits
    if limits is None:
        return True
    x, y, z, dx, dy, dz = box
    mass = pl.weight if pl.weight > 0 else pl.volume
    total_w = ctx.total_w + mass
    if total_w <= EPS:
        return True
    gx = (ctx.sum_wx + mass * (x + dx / 2.0)) / total_w / container.inner_length
    gy = (ctx.sum_wy + mass * (y + dy / 2.0)) / total_w / container.inner_width
    gz = (ctx.sum_wz + mass * (z + dz / 2.0)) / total_w / container.inner_height
    if limits is not None and not (
        limits.x_min_ratio - EPS <= gx <= limits.x_max_ratio + EPS
        and limits.y_min_ratio - EPS <= gy <= limits.y_max_ratio + EPS
        and gz <= limits.z_max_ratio + EPS
    ):
        return False
    return True


def _allowed_payload_at_x(container: Container, x_ratio: float) -> float | None:
    curve = container.load_distribution_curve
    if not curve:
        return None
    if x_ratio < curve[0].x_ratio - EPS or x_ratio > curve[-1].x_ratio + EPS:
        return 0.0
    for left, right in zip(curve, curve[1:]):
        if left.x_ratio - EPS <= x_ratio <= right.x_ratio + EPS:
            span = right.x_ratio - left.x_ratio
            if span <= EPS:
                return min(left.max_payload, right.max_payload)
            fraction = (x_ratio - left.x_ratio) / span
            return left.max_payload + fraction * (right.max_payload - left.max_payload)
    return curve[-1].max_payload


def _floor_load_ok(
    box: tuple[float, float, float, float, float, float],
    added_weight: float,
    supporters_with_area: list[tuple[PlacedItem, float]],
    container: Container,
) -> bool:
    limit = container.max_floor_load_kg_m2
    if limit is None:
        return True
    if box[2] <= EPS:
        area_m2 = box[3] * box[4] / 1_000_000.0
        return area_m2 > EPS and added_weight / area_m2 <= limit + EPS
    total_area = sum(area for _supporter, area in supporters_with_area)
    if total_area <= EPS:
        return False

    additions: dict[int, tuple[PlacedItem, float]] = {}

    def propagate(item: PlacedItem, load: float) -> None:
        if not item.supported_by:
            current = additions.get(id(item), (item, 0.0))[1]
            additions[id(item)] = (item, current + load)
            return
        for below, fraction in item.supported_by:
            propagate(below, load * fraction)

    for supporter, area in supporters_with_area:
        propagate(supporter, added_weight * area / total_area)
    for ground, extra in additions.values():
        area_m2 = ground.box[3] * ground.box[4] / 1_000_000.0
        if area_m2 <= EPS or (ground.weight + ground.carried + extra) / area_m2 > limit + EPS:
            return False
    return True


def _check_support_constraints_fast(
    box: tuple[float, float, float, float, float, float],
    pl: _Placeable,
    sups: list[tuple[PlacedItem, float]],
    min_support_ratio: float = DEFAULT_SUPPORT_RATIO,
    current_stop_seq: int | None = None,
) -> bool:
    if box[2] <= EPS:
        return pl.stacking_type != "top_only"
    if not sups:
        return False

    total_area = 0.0
    for _supporter, area in sups:
        total_area += area
    if total_area <= EPS or total_area / (box[3] * box[4]) < min_support_ratio - EPS:
        return False

    for supporter, area in sups:
        if current_stop_seq is not None and supporter.stop_seq < current_stop_seq:
            return False
        if pl.stacking_type == "same_item_only" and supporter.item_id != pl.item_id:
            return False
        supporter_type = supporter.stacking_type
        if supporter_type == "not_stackable" or supporter_type == "top_only":
            return False
        if supporter_type == "same_item_only" and supporter.item_id != pl.item_id:
            return False
        share = pl.weight * (area / total_area)
        if not can_accept_stack_load(supporter, share):
            return False
    return True


def _center_of_gravity_scorer(
    ctx: ScoreContext,
    pl: _Placeable,
    container: Container,
):
    cx = container.inner_length / 2.0
    cy = container.inner_width / 2.0
    inv_length = 1.0 / (container.inner_length or 1.0)
    inv_width = 1.0 / (container.inner_width or 1.0)
    inv_height = 1.0 / (container.inner_height or 1.0)
    unit_weight = pl.weight
    total_w = ctx.total_w
    sum_wx = ctx.sum_wx
    sum_wy = ctx.sum_wy

    def score(box: tuple[float, float, float, float, float, float]) -> tuple[float, ...]:
        x, y, z, dx, dy, dz = box
        bx = x + dx / 2.0
        by = y + dy / 2.0
        mass = unit_weight if unit_weight > 0 else dx * dy * dz
        next_total = total_w + mass
        norm_x = abs(((sum_wx + mass * bx) / next_total) - cx) * inv_length
        norm_y = abs(((sum_wy + mass * by) / next_total) - cy) * inv_width
        height_penalty = 0.60 * z * inv_height
        compactness_penalty = 0.08 * ((x + dx) * inv_length + (y + dy) * inv_width)
        return (
            max(norm_x, norm_y) + height_penalty + compactness_penalty,
            norm_x + norm_y + height_penalty + compactness_penalty,
            z,
            x,
            y,
        )

    return score


def _single_placeable(item: Item) -> _Placeable:
    volume = _placeable_volume(item.length, item.width, item.height)
    return _Placeable(
        item_id=item.id,
        pallet_id=None,
        pallet_deck_height=0.0,
        pallet_tare_weight=0.0,
        length=item.length,
        width=item.width,
        height=item.height,
        allowed_rotations=item.allowed_rotations,
        volume=volume,
        oriented_rotations=_oriented_rotations(
            item.length,
            item.width,
            item.height,
            item.allowed_rotations,
        ),
        weight=item.weight,
        customer_id=item.customer_id,
        order_id=item.order_id,
        destination_id=item.destination_id,
        stop_seq=item.stop_seq,
        must_load=item.must_load,
        priority=item.priority,
        pallet_group=item.pallet_group,
        friction_coefficient=item.friction_coefficient,
        stacking_type=_effective_stacking_type(item),
        max_load_top=item.max_load_top,
        contents=None,
        content_dims=None,
    )


def _composite_placeable(load, item: Item) -> _Placeable:
    allowed_rotations = ["LWH", "WLH"]
    volume = _placeable_volume(load.footprint_l, load.footprint_w, load.total_height)
    return _Placeable(
        item_id=load.contents[0][0],
        pallet_id=load.pallet_id,
        pallet_deck_height=load.deck_height,
        pallet_tare_weight=load.tare_weight,
        length=load.footprint_l,
        width=load.footprint_w,
        height=load.total_height,
        allowed_rotations=allowed_rotations,  # 托盘块 M3 固定朝向
        volume=volume,
        oriented_rotations=_oriented_rotations(
            load.footprint_l,
            load.footprint_w,
            load.total_height,
            allowed_rotations,
        ),
        weight=load.total_weight,
        customer_id=item.customer_id,
        order_id=item.order_id,
        destination_id=item.destination_id,
        stop_seq=item.stop_seq,
        must_load=item.must_load,
        priority=item.priority,
        pallet_group=item.pallet_group,
        friction_coefficient=item.friction_coefficient,
        stacking_type="not_stackable",
        max_load_top=0,
        contents=load.contents,
        content_dims=(item.length, item.width, item.height),
    )


def _mixed_composite_placeable(load) -> _Placeable:
    first = load.contents[0]
    must_load = any(bool(content[12]) for content in load.contents if len(content) >= 14)
    priority = max((int(content[13]) for content in load.contents if len(content) >= 14), default=0)
    return _Placeable(
        item_id=first[0],
        pallet_id=load.pallet_id,
        pallet_deck_height=load.deck_height,
        pallet_tare_weight=load.tare_weight,
        length=load.footprint_l,
        width=load.footprint_w,
        height=load.total_height,
        allowed_rotations=["LWH", "WLH"],
        volume=_placeable_volume(load.footprint_l, load.footprint_w, load.total_height),
        oriented_rotations=_oriented_rotations(
            load.footprint_l, load.footprint_w, load.total_height, ["LWH", "WLH"]
        ),
        weight=load.total_weight,
        customer_id=first[8] if len(first) >= 12 else "",
        order_id=first[9] if len(first) >= 12 else "",
        destination_id=first[10] if len(first) >= 12 else "",
        stop_seq=int(first[11]) if len(first) >= 12 else 1,
        must_load=must_load,
        priority=priority,
        pallet_group="mixed",
        friction_coefficient=None,
        stacking_type="not_stackable",
        max_load_top=0,
        contents=load.contents,
        content_dims=None,
    )


def _min_upright_height(item: Item) -> float:
    """该货品在允许朝向里能取到的最小竖直边——直接堆叠时的层高。"""
    heights = [
        oriented_dims(item.length, item.width, item.height, rotation)[2]
        for rotation in item.allowed_rotations
    ]
    return min(heights) if heights else item.height


def _pallet_column_efficiency(load, item: Item, container_height: float) -> float:
    """托盘净码高 / 同货直接堆叠可达净高。

    托盘块封顶（max_load_top=0），谁也压不上去，所以它脚下那根柱子从 max_stack_height
    到容器顶的余高是永久损失。这里把两种方案在同一块地板上能摞到的货物净高作比：
    <1 表示托盘块比散装浪费柱高，1 表示不吃亏（或直接堆也堆不上去）。
    每层的水平填充率两边相同，故在比值里约掉，不必入账。
    """
    stack_height = max(load.total_height - load.deck_height, 0.0)
    layer_height = _min_upright_height(item)
    if container_height <= 0 or stack_height <= 0 or layer_height <= 0:
        return 1.0
    direct_height = int(container_height / layer_height) * layer_height
    if direct_height <= 0:  # 散装堆不进容器，托盘不吃亏
        return 1.0
    return min(stack_height / direct_height, 1.0)


def _build_placeables(request: SolveRequest, objective: Objective) -> list[_Placeable]:
    """逐货品种类做「直接装 vs 码托盘」决策，产出待放置单元列表。"""
    pallets = [p.model_copy() for p in request.pallets]  # 复制以便扣减可用数量
    placeables: list[_Placeable] = []
    remaining_counts = {item.id: item.quantity for item in request.items}
    # 最高的可用容器 = 散装堆叠能争取到的最大柱高，据此衡量托盘块废掉多少柱子。
    tallest_container = max(
        (c.inner_height for c in request.containers if c.quantity > 0), default=0.0
    )

    def use_pallet(load, item: Item) -> bool:
        if request.pallet_policy == "avoid":
            return False
        if load.count <= 0:
            return False
        if request.pallet_policy == "required":
            return True
        if request.pallet_policy == "prefer":
            return load.count >= 2
        return objective.should_palletize(
            pallet_load_efficiency(load, item),
            load.count,
            _pallet_column_efficiency(load, item, tallest_container),
        )

    # Compatible mixed-SKU groups are palletized before the legacy per-SKU pass.
    if request.pallet_policy != "avoid" and pallets:
        groups: dict[tuple[int, str], list[Item]] = {}
        for item in request.items:
            if item.pallet_group and _can_palletize_item(item):
                groups.setdefault((item.stop_seq, item.pallet_group), []).append(item)
        for _group_key, group_items in groups.items():
            if len({item.id for item in group_items}) < 2:
                continue
            while True:
                units = [
                    item.model_copy(update={"quantity": 1})
                    for item in group_items
                    for _ in range(remaining_counts[item.id])
                ]
                if len(units) < 2:
                    break
                best = None
                for pallet in pallets:
                    if pallet.quantity <= 0:
                        continue
                    sample = build_mixed_pallet_load(units, pallet, objective, f"{pallet.id}#probe")
                    if best is None or sample.count > best[0].count:
                        best = (sample, pallet)
                if best is None or best[0].count < 2 or not use_pallet(best[0], group_items[0]):
                    break
                _sample, pallet = best
                load = build_mixed_pallet_load(
                    units, pallet, objective, f"{pallet.id}#{pallet.quantity}"
                )
                if load.count < 2:
                    break
                placeables.append(_mixed_composite_placeable(load))
                for content in load.contents:
                    remaining_counts[content[0]] -= 1
                pallet.quantity -= 1

    for item in request.items:
        remaining = remaining_counts[item.id]
        pallet = select_pallet(item, pallets, objective) if (
            request.pallet_policy != "avoid" and _can_palletize_item(item) and pallets
        ) else None

        if pallet is not None:
            sample = build_pallet_load(item, pallet, objective, instance_id=f"{pallet.id}#probe")
            eff = pallet_load_efficiency(sample, item)
            if sample.count > 0 and use_pallet(sample, item):
                # 码托盘：消耗托盘数量，逐只装满（最后一只可能半满），剩余转直接装。
                while remaining > 0 and pallet.quantity > 0:
                    instance_id = f"{pallet.id}#{pallet.quantity}"
                    load = build_pallet_load(
                        item, pallet, objective, instance_id=instance_id, limit=remaining
                    )
                    if load.count == 0:
                        break
                    placeables.append(_composite_placeable(load, item))
                    remaining -= load.count
                    pallet.quantity -= 1

        for _ in range(remaining):
            placeables.append(_single_placeable(item))

    # 大块先放，利于稳定与填充。
    return objective.order_placeables(placeables)


def _observe_industrial_candidate(
    context: IndustrialLoadContext | None,
    box,
    orientation: str,
    placeable: _Placeable,
    container: Container,
    timer: PerformanceTimer | None,
    rejection_codes: set[str],
    remaining_placeables: list[_Placeable],
    allow_recoverable_cog: bool,
    delivery_tracker=None,
) -> bool:
    """Preview and enforce configured industrial feasibility constraints."""
    if context is None:
        return True
    candidate_loads = _industrial_candidate_loads(placeable, box, orientation)
    metrics = context.preview_batch(candidate_loads)
    if timer is not None:
        timer.count("industrial_preview_calls")
    allowed = True
    limits = container.cog_limits
    # 多站点顺序配送的全载重心检查由逐站点跟踪器统一处理（含可达区间），
    # 避免逐候选的严格全载检查大量拒绝按站点聚集的临时偏心布局。
    if limits is not None and delivery_tracker is None:
        current_inside = (
            limits.x_min_ratio - EPS <= metrics.cog_x_ratio <= limits.x_max_ratio + EPS
            and limits.y_min_ratio - EPS <= metrics.cog_y_ratio <= limits.y_max_ratio + EPS
            and metrics.cog_z_ratio <= limits.z_max_ratio + EPS
        )
        if not current_inside and timer is not None:
            timer.count("industrial_preview_cog_temporarily_outside")
        reachable_possible = (
            _cog_can_reach_limits(metrics, remaining_placeables, container)
            if allow_recoverable_cog else False
        )
        reachable = allow_recoverable_cog and reachable_possible
        if not current_inside and not reachable:
            allowed = False
            rejection_codes.add("COG_OUT_OF_RANGE")
            if timer is not None:
                timer.count("industrial_preview_cog_exceeded")
                timer.count("industrial_preview_cog_unreachable" if allow_recoverable_cog else "industrial_preview_cog_strict_rejection")
        elif not current_inside and timer is not None:
            timer.count("industrial_preview_cog_recoverable")
    if delivery_tracker is not None and not delivery_tracker.candidate_ok(
        _normalized_stop(placeable), candidate_loads, timer, rejection_codes
    ):
        allowed = False
    if (
        container.max_floor_load_kg_m2 is not None
        and metrics.max_floor_load_kg_m2 > container.max_floor_load_kg_m2 + EPS
    ):
        allowed = False
        rejection_codes.add("FLOOR_LOAD_EXCEEDED")
        if timer is not None:
            timer.count("industrial_preview_floor_load_exceeded")
    if metrics.load_distribution_margin < -EPS:
        allowed = False
        rejection_codes.add("LOAD_DISTRIBUTION_EXCEEDED")
        if timer is not None:
            timer.count("industrial_preview_distribution_exceeded")
    if metrics.tip_stability_margin < -EPS and timer is not None:
        timer.count("industrial_preview_tip_risk")
    if container.restraint_mode != "unverified":
        stack_metrics = analyze_stack_clusters(
            container,
            [(record.box, record.mass) for record in context.records]
            + [(candidate_box, mass) for candidate_box, mass, _friction in candidate_loads],
        )
        if stack_restraint_sufficient(container, stack_metrics) is False:
            allowed = False
            rejection_codes.add("STACK_CLUSTER_RESTRAINT_INSUFFICIENT")
            if timer is not None:
                timer.count("industrial_preview_stack_restraint_exceeded")
    if not allowed and timer is not None:
        timer.count("industrial_constraint_rejections")
    return allowed


def _cog_can_reach_limits(metrics, remaining_placeables: list[_Placeable], container: Container) -> bool:
    limits = container.cog_limits
    if limits is None:
        return True
    remaining_mass = 0.0
    min_x_moment = 0.0
    max_x_moment = 0.0
    min_y_moment = 0.0
    max_y_moment = 0.0
    min_z_moment = 0.0
    for placeable in remaining_placeables:
        mass = placeable.weight if placeable.weight > 0 else placeable.volume
        if mass <= EPS:
            continue
        rotations = placeable.oriented_rotations or [
            ("LWH", placeable.length, placeable.width, placeable.height)
        ]
        min_dx = min(rotation[1] for rotation in rotations)
        min_dy = min(rotation[2] for rotation in rotations)
        min_dz = min(rotation[3] for rotation in rotations)
        remaining_mass += mass
        min_x_moment += mass * min_dx / 2.0
        max_x_moment += mass * max(min_dx / 2.0, container.inner_length - min_dx / 2.0)
        min_y_moment += mass * min_dy / 2.0
        max_y_moment += mass * max(min_dy / 2.0, container.inner_width - min_dy / 2.0)
        min_z_moment += mass * min_dz / 2.0

    total_mass = metrics.total_mass + remaining_mass
    if total_mass <= EPS:
        return True
    current_x_moment = metrics.cog_x_ratio * metrics.total_mass * container.inner_length
    current_y_moment = metrics.cog_y_ratio * metrics.total_mass * container.inner_width
    current_z_moment = metrics.cog_z_ratio * metrics.total_mass * container.inner_height
    min_x_ratio = (current_x_moment + min_x_moment) / total_mass / container.inner_length
    max_x_ratio = (current_x_moment + max_x_moment) / total_mass / container.inner_length
    min_y_ratio = (current_y_moment + min_y_moment) / total_mass / container.inner_width
    max_y_ratio = (current_y_moment + max_y_moment) / total_mass / container.inner_width
    min_z_ratio = (current_z_moment + min_z_moment) / total_mass / container.inner_height
    return (
        max_x_ratio >= limits.x_min_ratio - EPS
        and min_x_ratio <= limits.x_max_ratio + EPS
        and max_y_ratio >= limits.y_min_ratio - EPS
        and min_y_ratio <= limits.y_max_ratio + EPS
        and min_z_ratio <= limits.z_max_ratio + EPS
    )


def _industrial_candidate_loads(
    placeable: _Placeable,
    box,
    orientation: str,
) -> list[tuple[tuple[float, float, float, float, float, float], float, float | None]]:
    if placeable.pallet_id is None:
        return [(box, placeable.weight, placeable.friction_coefficient)]
    loads = [(
        (box[0], box[1], box[2], box[3], box[4], placeable.pallet_deck_height),
        placeable.pallet_tare_weight,
        None,
    )]
    emitted = placeable.emit_with_boxes(box[0], box[1], box[2], orientation, start_seq=0)
    for (_placement, content_box), content in zip(emitted, placeable.contents or []):
        friction = content[14] if len(content) >= 15 else placeable.friction_coefficient
        content_weight = content[15] if len(content) >= 16 else 0.0
        loads.append((content_box, content_weight, friction))
    return loads


def _normalized_stop(placeable: _Placeable) -> int:
    return max(1, int(placeable.stop_seq or 1))




def _delivery_corridor_ok(
    box: tuple[float, float, float, float, float, float],
    stop: int,
    container: Container,
    accesses: list[LoadingAccess],
    exit_state: list[tuple[PlacedItem, set[int]]],
) -> bool:
    """构造阶段的直线卸货通道检查（与最终 `DELIVERY_PATH_BLOCKED` 校验同口径）。

    候选自身必须存在一个对齐入口，且通道上没有更晚卸货的已放置货物（同站货物
    可先行移除，不算永久阻挡）；同时候选不能堵死任何已放置的更早卸货货物的
    最后一条畅通出口。
    """
    self_clear = False
    for access in accesses:
        if not _aligned_with_opening(box, access, container):
            continue
        blocked = False
        for placed, _clear in exit_state:
            if (
                max(1, int(placed.stop_seq or 1)) > stop
                and _blocks_corridor(box, placed.box, access.side)
            ):
                blocked = True
                break
        if not blocked:
            self_clear = True
            break
    if not self_clear:
        return False
    for placed, clear in exit_state:
        if max(1, int(placed.stop_seq or 1)) >= stop or not clear:
            continue
        if all(
            _blocks_corridor(placed.box, box, accesses[index].side)
            for index in clear
        ):
            return False
    return True


class _DeliveryStopCogTracker:
    """顺序配送逐站点载荷跟踪。

    为每个「卸完站点 ≤ t 之后」的剩余载荷状态分别维护质量矩与重心可达区间：
    候选放置必须让每个受影响的卸货后状态要么立即处于设备重心范围内，要么可由
    「尚未放置且比该站更晚卸货」的货物修正回范围内。直接用全体剩余货物做恢复
    判断会掩盖卸货后的偏心（产生 POST_DROP_COG_OUT_OF_RANGE），故按站点过滤。
    质量口径与增量工业上下文一致（已放置/候选用实际重量），可达界与
    `_cog_can_reach_limits` 一致（剩余货物无重量时用体积兜底）。
    """

    def __init__(self, container: Container, placeables: list[_Placeable]):
        self.container = container
        stops = sorted({_normalized_stop(pl) for pl in placeables})
        # 状态 t=0 为全载（未卸任何站）；t=stop 为卸完 stop ≤ t 后的剩余载荷；
        # 最后一站卸完为空载，无需检查。全载检查同样由本跟踪器以「范围内或
        # 可修正」判定，替代逐候选的严格全载检查（修正池耗尽时自动收紧为严格）。
        self.check_stops: list[int] = [0] + stops[:-1] if stops else []
        self.committed: dict[int, list[float]] = {}
        self._per_stop_remaining: dict[int, list[float]] = {}
        self.pool: dict[int, list[float]] = {}
        for pl in placeables:
            self._add_remaining(pl, 1.0)

    def _add_remaining(self, pl: _Placeable, sign: float) -> None:
        mass = pl.weight if pl.weight > 0 else pl.volume
        if mass <= EPS:
            return
        rotations = pl.oriented_rotations or [
            ("LWH", pl.length, pl.width, pl.height)
        ]
        min_dx = min(rotation[1] for rotation in rotations)
        min_dy = min(rotation[2] for rotation in rotations)
        min_dz = min(rotation[3] for rotation in rotations)
        length = self.container.inner_length
        width = self.container.inner_width
        agg = self._per_stop_remaining.setdefault(_normalized_stop(pl), [0.0] * 6)
        agg[0] += sign * mass
        agg[1] += sign * mass * min_dx / 2.0
        agg[2] += sign * mass * max(min_dx / 2.0, length - min_dx / 2.0)
        agg[3] += sign * mass * min_dy / 2.0
        agg[4] += sign * mass * max(min_dy / 2.0, width - min_dy / 2.0)
        agg[5] += sign * mass * min_dz / 2.0

    def advance(self, pl: _Placeable) -> None:
        """当前货品出队：从剩余池扣除自身，并重算各状态的可达界聚合。"""
        self._add_remaining(pl, -1.0)
        pool: dict[int, list[float]] = {}
        for t in self.check_stops:
            acc = [0.0] * 6
            for stop, agg in self._per_stop_remaining.items():
                if stop > t:
                    for i in range(6):
                        acc[i] += agg[i]
            pool[t] = acc
        self.pool = pool

    def commit_loads(
        self,
        stop: int,
        loads: list[tuple[tuple[float, float, float, float, float, float], float, float | None]],
    ) -> None:
        acc = self.committed.setdefault(stop, [0.0, 0.0, 0.0, 0.0])
        for box, mass, _friction in loads:
            if mass <= 0:
                continue
            acc[0] += mass
            acc[1] += mass * (box[0] + box[3] / 2.0)
            acc[2] += mass * (box[1] + box[4] / 2.0)
            acc[3] += mass * (box[2] + box[5] / 2.0)

    def candidate_ok(
        self,
        candidate_stop: int,
        candidate_loads: list[tuple[tuple[float, float, float, float, float, float], float, float | None]],
        timer: PerformanceTimer | None,
        rejection_codes: set[str],
    ) -> bool:
        limits = self.container.cog_limits
        if limits is None or not self.check_stops:
            return True
        cand_mass = 0.0
        cand_mx = 0.0
        cand_my = 0.0
        cand_mz = 0.0
        for box, mass, _friction in candidate_loads:
            if mass <= 0:
                continue
            cand_mass += mass
            cand_mx += mass * (box[0] + box[3] / 2.0)
            cand_my += mass * (box[1] + box[4] / 2.0)
            cand_mz += mass * (box[2] + box[5] / 2.0)
        length = self.container.inner_length
        width = self.container.inner_width
        height = self.container.inner_height
        for t in self.check_stops:
            if candidate_stop <= t:
                break  # 候选货品在状态 t 之前已卸下；更晚的状态同理不受影响。
            mass = cand_mass
            mx = cand_mx
            my = cand_my
            mz = cand_mz
            for stop, acc in self.committed.items():
                if stop > t:
                    mass += acc[0]
                    mx += acc[1]
                    my += acc[2]
                    mz += acc[3]
            if mass <= EPS:
                continue
            gx = mx / mass / length
            gy = my / mass / width
            gz = mz / mass / height
            if (
                limits.x_min_ratio - EPS <= gx <= limits.x_max_ratio + EPS
                and limits.y_min_ratio - EPS <= gy <= limits.y_max_ratio + EPS
                and gz <= limits.z_max_ratio + EPS
            ):
                continue
            full_load_state = t == 0
            if full_load_state and timer is not None:
                timer.count("industrial_preview_cog_temporarily_outside")
            pool = self.pool.get(t)
            reachable = False
            if pool is not None and pool[0] > EPS:
                total = mass + pool[0]
                min_x_ratio = (mx + pool[1]) / total / length
                max_x_ratio = (mx + pool[2]) / total / length
                min_y_ratio = (my + pool[3]) / total / width
                max_y_ratio = (my + pool[4]) / total / width
                min_z_ratio = (mz + pool[5]) / total / height
                reachable = (
                    max_x_ratio >= limits.x_min_ratio - EPS
                    and min_x_ratio <= limits.x_max_ratio + EPS
                    and max_y_ratio >= limits.y_min_ratio - EPS
                    and min_y_ratio <= limits.y_max_ratio + EPS
                    and min_z_ratio <= limits.z_max_ratio + EPS
                )
            if reachable:
                if timer is not None:
                    timer.count(
                        "industrial_preview_cog_recoverable"
                        if full_load_state
                        else "industrial_preview_post_drop_cog_recoverable"
                    )
                continue
            rejection_codes.add(
                "COG_OUT_OF_RANGE" if full_load_state else "POST_DROP_COG_OUT_OF_RANGE"
            )
            if timer is not None:
                timer.count(
                    "industrial_preview_cog_exceeded"
                    if full_load_state
                    else "industrial_preview_post_drop_cog_exceeded"
                )
            return False
        return True


def _pack_placeables_into_container(
    placeables: list[_Placeable],
    container: Container,
    objective: Objective,
    timer: PerformanceTimer | None = None,
    observe_industrial: bool = False,
) -> tuple[LoadedContainer, list[_Placeable]]:
    loaded = LoadedContainer(id=container.id)
    ep_set = ExtremePointSet()
    placed_items: list[PlacedItem] = []
    leftover: list[_Placeable] = []
    placement_boxes: list[tuple[Placement, tuple[float, float, float, float, float, float]]] = []
    balance_boxes: list[tuple[tuple[float, float, float, float, float, float], float]] = []
    seq = 0
    used_volume = 0.0
    used_weight = 0.0
    top_z_levels: list[float] = [0.0]
    top_z_seen: set[float] = {0.0}
    support_grid_layers: dict[float, dict[tuple[int, int], list[PlacedItem]]] = {}
    overlap_layer_lookup: dict[tuple[float, float], dict[tuple[int, int], list[PlacedItem]]] = {}
    overlap_grid_layers: list[tuple[float, float, dict[tuple[int, int], list[PlacedItem]]]] = []
    overlap_scan_items_total = 0
    overlap_candidate_items_total = 0
    support_scan_items_total = 0
    support_candidate_items_total = 0
    industrial_context = IndustrialLoadContext(container) if observe_industrial else None
    industrial_rejection_codes: set[str] = set()
    allow_recoverable_cog = False
    delivery_tracker = None
    if (
        industrial_context is not None
        and objective.name == "delivery_sequence"
        and container.cog_limits is not None
    ):
        tracker = _DeliveryStopCogTracker(container, placeables)
        if tracker.check_stops:
            delivery_tracker = tracker
    is_delivery = objective.name == "delivery_sequence"
    # 工业模式顺序配送：直线卸货通道前置到构造过程（标准模式仍只做事后诊断）。
    delivery_path_filter = industrial_context is not None and is_delivery
    delivery_accesses = _effective_loading_accesses(container) if is_delivery else []
    # 每个已放置单元当前仍畅通的出口下标集合（只计更晚卸货的永久阻挡者）。
    delivery_exit_state: list[tuple[PlacedItem, set[int]]] = []

    # 评分上下文（含累计重心信息），供重心居中等目标使用；默认目标忽略它。
    ctx = ScoreContext(inner_length=container.inner_length, inner_width=container.inner_width, inner_height=container.inner_height)
    ctx.loading_access_sides = tuple(access.side for access in _effective_loading_accesses(container))
    if placeables:
        stops = [max(1, int(pl.stop_seq or 1)) for pl in placeables]
        ctx.min_stop_seq = min(stops)
        ctx.max_stop_seq = max(stops)
    scorer = objective.make_scorer(ctx)
    point_score_fn = (lambda point: (point[2], point[1], point[0])) if objective.name in {
        "max_utilization", "min_containers", "cost_efficiency", "space_utilization"
    } else None

    for placeable_index, pl in enumerate(placeables):
        remaining_placeables = placeables[placeable_index + 1:]
        if delivery_tracker is not None:
            delivery_tracker.advance(pl)
        item_industrial_rejection_codes: set[str] = set()
        # 容器载重上限：累计重量不得超过 max_payload（重者放不下，留待后续容器）。
        if container.max_payload and used_weight + pl.weight > container.max_payload + 1e-6:
            leftover.append(pl)
            continue
        ctx.unit_w = pl.weight
        ctx.current_stop_seq = max(1, int(pl.stop_seq or 1))
        ctx.current_customer_id = pl.customer_id
        ctx.current_order_id = pl.order_id
        ctx.epoch += 1  # 换件 → 配送簇质心缓存失效
        placement_scorer = _center_of_gravity_scorer(ctx, pl, container) if objective.name == "center_of_gravity" else scorer
        current_stop_value = _normalized_stop(pl)

        def corridor_ok(box) -> bool:
            if not delivery_path_filter:
                return True
            ok = _delivery_corridor_ok(
                box, current_stop_value, container, delivery_accesses, delivery_exit_state
            )
            if not ok:
                item_industrial_rejection_codes.add("DELIVERY_PATH_BLOCKED")
                if timer is not None:
                    timer.count("delivery_corridor_rejections")
            return ok

        def balance_points(dx: float, dy: float, dz: float) -> list[tuple[float, float, float]]:
            mass = pl.weight if pl.weight > 0 else pl.volume
            if mass <= 0:
                return []
            total = ctx.total_w + mass
            bx = (container.inner_length / 2.0 * total - ctx.sum_wx) / mass
            by = (container.inner_width / 2.0 * total - ctx.sum_wy) / mass
            ideal_x = bx - dx / 2.0
            ideal_y = by - dy / 2.0
            max_x_offset = DEFAULT_COG_MAX_OFFSET_RATIO * container.inner_length
            max_y_offset = DEFAULT_COG_MAX_OFFSET_RATIO * container.inner_width
            low_bx = ((container.inner_length / 2.0 - max_x_offset) * total - ctx.sum_wx) / mass
            high_bx = ((container.inner_length / 2.0 + max_x_offset) * total - ctx.sum_wx) / mass
            low_by = ((container.inner_width / 2.0 - max_y_offset) * total - ctx.sum_wy) / mass
            high_by = ((container.inner_width / 2.0 + max_y_offset) * total - ctx.sum_wy) / mass
            xs = [
                ideal_x,
                max(0.0, min(ideal_x, container.inner_length - dx)),
                low_bx - dx / 2.0,
                high_bx - dx / 2.0,
            ]
            ys = [
                ideal_y,
                max(0.0, min(ideal_y, container.inner_width - dy)),
                low_by - dy / 2.0,
                high_by - dy / 2.0,
            ]
            xs.extend([0.0, container.inner_length - dx])
            ys.extend([0.0, container.inner_width - dy])
            xs = _bounded_unique_values(xs, container.inner_length - dx)
            ys = _bounded_unique_values(ys, container.inner_width - dy)
            zs = _bounded_unique_values(top_z_levels, container.inner_height - dz)

            points: list[tuple[float, float, float]] = []
            seen: set[tuple[float, float, float]] = set()
            for x in xs:
                for y in ys:
                    for z in zs:
                        point = (x, y, z)
                        if point in seen:
                            continue
                        seen.add(point)
                        points.append(point)
            if timer is not None:
                timer.count("balance_fallback_calls")
                timer.count("balance_fallback_points", len(points))
            return points

        def hard_constraints(box, orientation: str) -> bool:
            nonlocal support_scan_items_total, support_candidate_items_total
            if not any(
                _box_fits_access_aperture(box, access, container)
                for access in _effective_loading_accesses(container)
            ):
                if timer is not None:
                    timer.count("door_aperture_rejections")
                return False
            cog_ok = True if industrial_context is not None else _check_configured_cog_limits(ctx, pl, box, container)
            if objective.name == "center_of_gravity" and container.cog_limits is None:
                cog_ok = _check_cog_with_context(
                    ctx, pl, box, pl.weight, container.inner_length, container.inner_width
                )
            if not cog_ok:
                if timer is not None:
                    timer.count("cog_constraint_rejections")
                return False
            x, y, _z, dx, dy, _dz = box
            x2 = x + dx
            y2 = y + dy
            if _z <= EPS:
                valid = pl.stacking_type != "top_only"
                if valid:
                    valid = corridor_ok(box) and _observe_industrial_candidate(
                        industrial_context, box, orientation, pl, container, timer,
                        item_industrial_rejection_codes,
                        remaining_placeables,
                        allow_recoverable_cog,
                        delivery_tracker,
                    )
                return valid
            if pl.stacking_type in {"not_stackable", "support_only"}:
                return False
            sups: list[tuple[PlacedItem, float]] = []
            support_scanned = 0
            grid = support_grid_layers.get(_z_key(box[2]))
            if grid is None:
                return False
            bx_first = int(x // SPATIAL_BIN_SIZE)
            bx_last = int((x2 - EPS) // SPATIAL_BIN_SIZE)
            by_first = int(y // SPATIAL_BIN_SIZE)
            by_last = int((y2 - EPS) // SPATIAL_BIN_SIZE)
            needs_seen = bx_first != bx_last or by_first != by_last
            seen: set[int] | None = set() if needs_seen else None
            for bx in range(bx_first, bx_last + 1):
                for by in range(by_first, by_last + 1):
                    for item in grid.get((bx, by), []):
                        if seen is not None:
                            item_key = id(item)
                            if item_key in seen:
                                continue
                            seen.add(item_key)
                        support_scanned += 1
                        ix, iy, _iz, idx, idy, _idz = item.box
                        if x2 > ix + EPS and ix + idx > x + EPS and y2 > iy + EPS and iy + idy > y + EPS:
                            area = (min(x2, ix + idx) - max(x, ix)) * (min(y2, iy + idy) - max(y, iy))
                            if area > EPS:
                                sups.append((item, area))
            support_scan_items_total += support_scanned
            support_candidate_items_total += len(sups)
            delivery_stop = pl.stop_seq if objective.name in {
                "loading_efficiency", "multi_customer_delivery", "delivery_sequence"
            } else None
            valid = _check_support_constraints_fast(box, pl, sups, current_stop_seq=delivery_stop)
            if valid:
                valid = corridor_ok(box) and _observe_industrial_candidate(
                    industrial_context, box, orientation, pl, container, timer,
                    item_industrial_rejection_codes,
                    remaining_placeables,
                    allow_recoverable_cog,
                    delivery_tracker,
                )
            return valid

        def overlaps_existing(box) -> bool:
            # 求解热点：生产规模上每次求解要调 10^6 次，故把 EPS / 分箱尺寸绑成闭包局部量，
            # 并且不做跨分箱去重——一有重叠就返回，重复看到同一个物体不影响结果，而
            # 实测去重集几乎去不掉任何重复（723 万次 add 对 682 万个待扫物体），纯属开销。
            # 支撑扫描不能照搬：那里重复会把同一件的支撑面积算两遍。
            nonlocal overlap_scan_items_total, overlap_candidate_items_total
            x, y, z, dx, dy, dz = box
            x2 = x + dx
            y2 = y + dy
            z_top = z + dz
            x_eps = x + EPS
            y_eps = y + EPS
            bx_first = int(x // SPATIAL_BIN_SIZE)
            bx_last = int((x2 - EPS) // SPATIAL_BIN_SIZE)
            by_first = int(y // SPATIAL_BIN_SIZE)
            by_last = int((y2 - EPS) // SPATIAL_BIN_SIZE)
            # 分箱键一次算好：原先每个 z 层都要重建两个 range，而绝大多数箱子只落在
            # 单个分箱里，白白付了 range 的构造开销。
            if bx_first == bx_last and by_first == by_last:
                bin_keys = ((bx_first, by_first),)
            else:
                bin_keys = [
                    (bx, by)
                    for bx in range(bx_first, bx_last + 1)
                    for by in range(by_first, by_last + 1)
                ]
            scanned = 0
            for low, high, grid in overlap_grid_layers:
                if low >= z_top - EPS:
                    break
                if high <= z + EPS:
                    continue
                for key in bin_keys:
                    for item in grid.get(key, ()):
                        scanned += 1
                        ix, iy, _iz, idx, idy, _idz = item.box
                        if x2 > ix + EPS and ix + idx > x_eps and y2 > iy + EPS and iy + idy > y_eps:
                            overlap_scan_items_total += scanned
                            overlap_candidate_items_total += 1
                            return True
            overlap_scan_items_total += scanned
            return False

        def find_candidate():
            return find_placement(
                pl.length,
                pl.width,
                pl.height,
                pl.allowed_rotations,
                ep_set,
                placed_items,
                container.inner_length,
                container.inner_width,
                container.inner_height,
                score_fn=placement_scorer,
                weight=pl.weight,
                enforce_constraints=False,
                extra_points_fn=balance_points,
                hard_constraint_fn=hard_constraints,
                overlap_check_fn=overlaps_existing,
                oriented_rotations=pl.oriented_rotations,
                counter_fn=timer.count if timer is not None else None,
                max_counter_fn=timer.count_max if timer is not None else None,
                filter_covered_points=False,
                point_score_fn=point_score_fn,
                always_scan_extra_points=objective.name in {
                    "loading_efficiency", "multi_customer_delivery", "delivery_sequence"
                },
            )
        if timer is not None:
            timer.count("find_placement_calls")
        with timer.stage("find_placement") if timer is not None else nullcontext():
            cand = find_candidate()
            if (
                cand is None
                and industrial_context is not None
                and remaining_placeables
                and "COG_OUT_OF_RANGE" in item_industrial_rejection_codes
            ):
                allow_recoverable_cog = True
                if timer is not None:
                    timer.count("industrial_cog_recovery_passes")
                    timer.count("find_placement_calls")
                cand = find_candidate()
                allow_recoverable_cog = False
        industrial_rejection_codes.update(item_industrial_rejection_codes)
        if cand is None:
            leftover.append(pl)
            continue
        px, py, pz, *_ = cand.box
        emitted_with_boxes = pl.emit_with_boxes(px, py, pz, cand.orientation, start_seq=seq)
        emitted = [placement for placement, _box in emitted_with_boxes]
        loaded.placements.extend(emitted)
        placement_boxes.extend(emitted_with_boxes)
        balance_boxes.append((cand.box, pl.weight))
        seq += len(emitted)
        commit_stack_load(cand.box, pl.weight, placed_items)
        placed_item = PlacedItem(
            box=cand.box, weight=pl.weight,
            max_load_top=pl.max_load_top, item_id=pl.item_id,
            stacking_type=pl.stacking_type,
            stop_seq=pl.stop_seq,
            supported_by=support_links(cand.box, placed_items),
        )
        placed_items.append(placed_item)
        ep_set.remove(cand.point)
        if timer is not None:
            timer.count("candidate_points_pruned_covered", ep_set.prune_covered(cand.box))
        else:
            ep_set.prune_covered(cand.box)
        ep_set.add_from_placement(cand.box)
        top_z = cand.box[2] + cand.box[5]
        if top_z not in top_z_seen:
            top_z_seen.add(top_z)
            top_z_levels.append(top_z)
        _add_to_spatial_grid(support_grid_layers.setdefault(_z_key(top_z), {}), placed_item)
        overlap_key = (_z_key(cand.box[2]), _z_key(top_z))
        overlap_grid = overlap_layer_lookup.get(overlap_key)
        if overlap_grid is None:
            overlap_grid = {}
            overlap_layer_lookup[overlap_key] = overlap_grid
            insert_at = len(overlap_grid_layers)
            while insert_at > 0 and overlap_grid_layers[insert_at - 1][0] > overlap_key[0]:
                insert_at -= 1
            overlap_grid_layers.insert(insert_at, (overlap_key[0], overlap_key[1], overlap_grid))
        _add_to_spatial_grid(overlap_grid, placed_item)
        used_volume += pl.volume
        used_weight += pl.weight
        if industrial_context is not None:
            if pl.pallet_id is None:
                industrial_context.commit(cand.box, pl.weight, pl.friction_coefficient)
            else:
                pallet_box = (
                    cand.box[0], cand.box[1], cand.box[2],
                    cand.box[3], cand.box[4], pl.pallet_deck_height,
                )
                industrial_context.commit(pallet_box, pl.pallet_tare_weight)
                for (_placement, content_box), content in zip(emitted_with_boxes, pl.contents or []):
                    friction = content[14] if len(content) >= 15 else pl.friction_coefficient
                    content_weight = content[15] if len(content) >= 16 else 0.0
                    industrial_context.commit(content_box, content_weight, friction)
            if timer is not None:
                timer.count("industrial_commits")
            if delivery_tracker is not None:
                delivery_tracker.commit_loads(
                    _normalized_stop(pl),
                    _industrial_candidate_loads(pl, cand.box, cand.orientation),
                )
        if delivery_path_filter:
            new_clear = {
                index
                for index, access in enumerate(delivery_accesses)
                if _aligned_with_opening(cand.box, access, container)
                and not any(
                    max(1, int(placed.stop_seq or 1)) > current_stop_value
                    and _blocks_corridor(cand.box, placed.box, access.side)
                    for placed, _clear in delivery_exit_state
                )
            }
            for placed, clear in delivery_exit_state:
                if clear and max(1, int(placed.stop_seq or 1)) < current_stop_value:
                    blocked_indexes = {
                        index for index in clear
                        if _blocks_corridor(placed.box, cand.box, delivery_accesses[index].side)
                    }
                    if blocked_indexes:
                        clear.difference_update(blocked_indexes)
            delivery_exit_state.append((placed_item, new_clear))
        if pl.pallet_id is not None:
            loaded.pallet_instances.append(PalletInstance(
                id=pl.pallet_id,
                pallet_type_id=pl.pallet_id.split("#", 1)[0],
                x=cand.box[0],
                y=cand.box[1],
                z=cand.box[2],
                length=cand.box[3],
                width=cand.box[4],
                deck_height=pl.pallet_deck_height,
                tare_weight=pl.pallet_tare_weight,
                stop_seq=max(1, int(pl.stop_seq or 1)),
                orientation=cand.orientation,
            ))

        # 更新重心累计（质量：重量优先，无重量用体积兜底；用所选 box 的中心）。
        bdx, bdy, bdz = cand.box[3], cand.box[4], cand.box[5]
        mass = pl.weight if pl.weight > 0 else pl.volume
        ctx.total_w += mass
        center_x = px + bdx / 2.0
        center_y = py + bdy / 2.0
        ctx.sum_wx += mass * center_x
        ctx.sum_wy += mass * center_y
        ctx.sum_wz += mass * (pz + bdz / 2.0)
        _update_delivery_groups(ctx, pl, center_x, center_y)

    container_volume = (
        container.inner_length * container.inner_width * container.inner_height
    )
    loaded.volume_utilization = used_volume / container_volume if container_volume else 0.0
    loaded.weight_utilization = (
        used_weight / container.max_payload if container.max_payload else 0.0
    )
    if objective.name in {"center_of_gravity", "safe_loading"}:
        _center_loaded_container(loaded, placement_boxes, balance_boxes, container)
    if industrial_context is not None:
        construction_metrics = industrial_context.metrics().as_dict()
        loaded.industrial_metrics.update({
            f"construction_{key}": value for key, value in construction_metrics.items()
        })
        loaded.industrial_rejection_codes = sorted(industrial_rejection_codes)
    _resequence_inside_to_outside(
        loaded, placement_boxes, container, objective.name in {
            "loading_efficiency", "multi_customer_delivery", "delivery_sequence"
        }
    )
    if timer is not None:
        timer.count("overlap_scan_items", overlap_scan_items_total)
        timer.count("overlap_candidate_items", overlap_candidate_items_total)
        timer.count("support_scan_items", support_scan_items_total)
        timer.count("support_candidate_items", support_candidate_items_total)
    return loaded, leftover


def _center_loaded_container(
    loaded: LoadedContainer,
    placement_boxes: list[tuple[Placement, tuple[float, float, float, float, float, float]]],
    balance_boxes: list[tuple[tuple[float, float, float, float, float, float], float]],
    container: Container,
) -> None:
    if not balance_boxes:
        return
    min_x = min(box[0] for box, _mass in balance_boxes)
    min_y = min(box[1] for box, _mass in balance_boxes)
    max_x = max(box[0] + box[3] for box, _mass in balance_boxes)
    max_y = max(box[1] + box[4] for box, _mass in balance_boxes)
    total_mass = sum(mass if mass > 0 else box_volume(box) for box, mass in balance_boxes)
    if total_mass <= 0:
        return
    gx = sum((mass if mass > 0 else box_volume(box)) * (box[0] + box[3] / 2.0) for box, mass in balance_boxes) / total_mass
    gy = sum((mass if mass > 0 else box_volume(box)) * (box[1] + box[4] / 2.0) for box, mass in balance_boxes) / total_mass
    shift_x = _clamp_shift(container.inner_length / 2.0 - gx, -min_x, container.inner_length - max_x)
    shift_y = _clamp_shift(container.inner_width / 2.0 - gy, -min_y, container.inner_width - max_y)
    if abs(shift_x) <= EPS and abs(shift_y) <= EPS:
        return
    for placement in loaded.placements:
        placement.x += shift_x
        placement.y += shift_y
    for pallet in loaded.pallet_instances:
        pallet.x += shift_x
        pallet.y += shift_y
    for index, (placement, box) in enumerate(placement_boxes):
        x, y, z, dx, dy, dz = box
        placement_boxes[index] = (placement, (x + shift_x, y + shift_y, z, dx, dy, dz))


def _clamp_shift(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _update_delivery_groups(ctx: ScoreContext, pl: _Placeable, center_x: float, center_y: float) -> None:
    for key in delivery_group_keys(max(1, int(pl.stop_seq or 1)), pl.customer_id, pl.order_id):
        count, sum_x, sum_y = ctx.delivery_groups.get(key, (0.0, 0.0, 0.0))
        ctx.delivery_groups[key] = (count + 1.0, sum_x + center_x, sum_y + center_y)
        ctx.epoch += 1  # 质心已移动 → 缓存失效


def _resequence_inside_to_outside(
    loaded: LoadedContainer,
    placement_boxes: list[tuple[Placement, tuple[float, float, float, float, float, float]]],
    container: Container,
    use_stop_priority: bool = False,
) -> None:
    """Assign loading seq from container inside to door while honoring support deps."""
    records = list(placement_boxes)
    deps: list[set[int]] = [set() for _ in records]
    top_grids: dict[float, dict[tuple[int, int], list[int]]] = {}

    for index, (_placement, box) in enumerate(records):
        x, y, z, dx, dy, dz = box
        grid = top_grids.setdefault(_z_key(z + dz), {})
        for bx in _spatial_bin_range(x, x + dx):
            for by in _spatial_bin_range(y, y + dy):
                grid.setdefault((bx, by), []).append(index)

    for i, (_p, box) in enumerate(records):
        x, y, z, dx, dy, _dz = box
        if z <= EPS:
            continue
        grid = top_grids.get(_z_key(z))
        if grid is None:
            continue
        seen: set[int] = set()
        for bx_key in _spatial_bin_range(x, x + dx):
            for by_key in _spatial_bin_range(y, y + dy):
                for j in grid.get((bx_key, by_key), []):
                    if i == j or j in seen:
                        continue
                    seen.add(j)
                    _below_p, below = records[j]
                    bx, by, _bz, bdx, bdy, _bdz = below
                    ox = max(0.0, min(x + dx, bx + bdx) - max(x, bx))
                    oy = max(0.0, min(y + dy, by + bdy) - max(y, by))
                    if ox * oy > EPS:
                        deps[i].add(j)

    remaining = set(range(len(records)))
    emitted: list[int] = []
    emitted_set: set[int] = set()
    while remaining:
        ready = [i for i in remaining if deps[i].issubset(emitted_set)]
        if not ready:
            ready = list(remaining)
        ready.sort(key=lambda i: _loading_priority(records[i], container, use_stop_priority))
        chosen = ready[0]
        remaining.remove(chosen)
        emitted.append(chosen)
        emitted_set.add(chosen)

    ordered = [records[i][0] for i in emitted]
    for seq, placement in enumerate(ordered, start=1):
        placement.seq = seq
    loaded.placements = ordered


def _loading_priority(
    record: tuple[Placement, tuple[float, float, float, float, float, float]],
    container: Container,
    use_stop_priority: bool = False,
) -> tuple[float, ...]:
    placement, box = record
    x, y, z, dx, dy, dz = box
    accesses = _effective_loading_accesses(container)
    sides = tuple(access.side for access in accesses)
    single_side = sides[0] if len(sides) == 1 else None

    stop_priority = -max(1, int(getattr(placement, "stop_seq", 1) or 1)) if use_stop_priority else 0

    if single_side in {"x_min", "x_max"}:
        return (stop_priority, -_access_depth(box, accesses[0], container), z, y, x, 0.0, placement.seq)

    if single_side in {"y_min", "y_max"}:
        center_x = abs((x + dx / 2.0) - container.inner_length / 2.0)
        return (stop_priority, _access_depth(box, accesses[0], container), z, center_x, x, y, placement.seq)

    if single_side == "z_max":
        center = (
            abs((x + dx / 2.0) - container.inner_length / 2.0)
            + abs((y + dy / 2.0) - container.inner_width / 2.0)
        )
        return (stop_priority, z, center, -(dx * dy), x, y, placement.seq)

    nearest = min(accesses, key=lambda access: _access_depth(box, access, container))
    partition = _access_rank(nearest.side)
    return (stop_priority, partition, _access_depth(box, nearest, container), z, x, y, placement.seq)


def _effective_loading_accesses(container: Container) -> list[LoadingAccess]:
    if container.loading_accesses:
        return container.loading_accesses
    if container.door_width is not None or container.door_height is not None:
        return [
            LoadingAccess(
                side="x_max",
                door_width=container.door_width,
                door_height=container.door_height,
            )
        ]
    return [LoadingAccess(side="x_max")]


def _box_fits_access_aperture(
    box: tuple[float, float, float, float, float, float],
    access: LoadingAccess,
    container: Container,
) -> bool:
    """Check oriented cross-section dimensions against an access opening."""
    _x, _y, _z, dx, dy, dz = box
    if access.side in {"x_min", "x_max"}:
        available_u = _access_opening_width(access, container.inner_width)
        available_v = access.door_height if access.door_height is not None else container.inner_height
        return dy <= available_u + EPS and dz <= available_v + EPS
    if access.side in {"y_min", "y_max"}:
        available_u = _access_opening_width(access, container.inner_length)
        available_v = access.door_height if access.door_height is not None else container.inner_height
        return dx <= available_u + EPS and dz <= available_v + EPS
    available_u = _access_opening_width(access, container.inner_length)
    available_v = access.door_height if access.door_height is not None else container.inner_width
    return dx <= available_u + EPS and dy <= available_v + EPS


def _access_opening_width(access: LoadingAccess, full_span: float) -> float:
    if access.opening_start is not None and access.opening_end is not None:
        return max(0.0, access.opening_end - access.opening_start)
    if access.door_width is not None:
        return access.door_width
    return full_span


def _box_aligned_with_access(
    box: tuple[float, float, float, float, float, float],
    access: LoadingAccess,
    container: Container,
) -> bool:
    x, y, z, dx, dy, dz = box
    if access.side in {"x_min", "x_max"}:
        low, high = _access_span(access, container.inner_width)
        height = access.door_height if access.door_height is not None else container.inner_height
        return y >= low - EPS and y + dy <= high + EPS and z + dz <= height + EPS
    if access.side in {"y_min", "y_max"}:
        low, high = _access_span(access, container.inner_length)
        height = access.door_height if access.door_height is not None else container.inner_height
        return x >= low - EPS and x + dx <= high + EPS and z + dz <= height + EPS
    low, high = _access_span(access, container.inner_length)
    y_span = access.door_height if access.door_height is not None else container.inner_width
    y_low = (container.inner_width - y_span) / 2.0
    return x >= low - EPS and x + dx <= high + EPS and y >= y_low - EPS and y + dy <= y_low + y_span + EPS


def _access_span(access: LoadingAccess, full_span: float) -> tuple[float, float]:
    if access.opening_start is not None and access.opening_end is not None:
        return access.opening_start, access.opening_end
    width = access.door_width if access.door_width is not None else full_span
    low = max(0.0, (full_span - width) / 2.0)
    return low, min(full_span, low + width)


def _box_path_clear(
    box: tuple[float, float, float, float, float, float],
    side: str,
    placed_items: list[PlacedItem],
) -> bool:
    x, y, z, dx, dy, dz = box
    for placed in placed_items:
        ox, oy, oz, odx, ody, odz = placed.box
        if side in {"x_min", "x_max"}:
            cross = _ranges_overlap(y, y + dy, oy, oy + ody) and _ranges_overlap(z, z + dz, oz, oz + odz)
            if cross and ((side == "x_min" and ox < x - EPS) or (side == "x_max" and ox + odx > x + dx + EPS)):
                return False
        elif side in {"y_min", "y_max"}:
            cross = _ranges_overlap(x, x + dx, ox, ox + odx) and _ranges_overlap(z, z + dz, oz, oz + odz)
            if cross and ((side == "y_min" and oy < y - EPS) or (side == "y_max" and oy + ody > y + dy + EPS)):
                return False
        else:
            cross = _ranges_overlap(x, x + dx, ox, ox + odx) and _ranges_overlap(y, y + dy, oy, oy + ody)
            if cross and oz + odz > z + dz + EPS:
                return False
    return True


def _ranges_overlap(a1: float, a2: float, b1: float, b2: float) -> bool:
    return min(a2, b2) - max(a1, b1) > EPS



def _access_rank(side: str) -> int:
    order = {"x_max": 0, "x_min": 1, "y_min": 2, "y_max": 3, "z_max": 4}
    return order.get(side, 99)

def _loading_depth(
    box: tuple[float, float, float, float, float, float],
    container: Container,
) -> float:
    depths = [_access_depth(box, access, container) for access in _effective_loading_accesses(container)]
    return min(depths) if depths else 0.0


def _access_depth(
    box: tuple[float, float, float, float, float, float],
    access: LoadingAccess,
    container: Container,
) -> float:
    x, y, z, dx, dy, dz = box
    if access.side == "x_min":
        return x
    if access.side == "x_max":
        return container.inner_length - (x + dx)
    if access.side == "y_min":
        return y
    if access.side == "y_max":
        return container.inner_width - (y + dy)
    if access.side == "z_max":
        return container.inner_height - (z + dz)
    return 0.0


def _expand_containers(request: SolveRequest, objective: Objective) -> list[Container]:
    """按目标排定容器开箱优先级，并展开各容器类型的可用数量。"""
    available: list[Container] = []
    for ct in objective.order_containers(request.containers):
        available.extend(ct for _ in range(ct.quantity))
    return available


def run_container_loop(
    placeables: list[_Placeable],
    containers: list[Container],
    objective: Objective,
    timer: PerformanceTimer | None = None,
    observe_industrial: bool = False,
) -> Solution:
    """按给定顺序把 placeables 逐只开箱装载（GA 解码器复用此函数）。

    placeables 的先后即放置优先级；调用方负责排序。
    """
    remaining = list(placeables)
    solution = Solution()
    industrial_rejection_codes: set[str] = set()
    available = list(containers)
    while available and remaining:
        if objective.name in {"cost_efficiency", "space_utilization"}:
            trials: list[tuple[tuple[float, ...], int, LoadedContainer, list[_Placeable]]] = []
            seen_types: set[tuple] = set()
            for index, candidate_container in enumerate(available):
                signature = (
                    candidate_container.id,
                    candidate_container.inner_length,
                    candidate_container.inner_width,
                    candidate_container.inner_height,
                    candidate_container.max_payload,
                    candidate_container.use_cost,
                )
                if signature in seen_types:
                    continue
                seen_types.add(signature)
                if timer is not None:
                    timer.count("containers_attempted")
                with timer.stage("single_container_loading") if timer is not None else nullcontext():
                    trial_loaded, trial_remaining = _pack_placeables_into_container(
                        remaining, candidate_container, objective, timer, observe_industrial
                    )
                placed_count = len(remaining) - len(trial_remaining)
                leftover_ids = {id(pl) for pl in trial_remaining}
                priority_value = sum(
                    (1000 if pl.must_load else 0) + pl.priority + 1
                    for pl in remaining
                    if id(pl) not in leftover_ids
                )
                if objective.name == "cost_efficiency":
                    cost = candidate_container.use_cost if candidate_container.use_cost is not None else 1.0
                    key = (priority_value / max(cost, EPS), placed_count / max(cost, EPS), trial_loaded.volume_utilization)
                else:
                    key = (trial_loaded.volume_utilization, priority_value, placed_count)
                trials.append((key, index, trial_loaded, trial_remaining))
            if not trials:
                break
            _key, selected_index, loaded, next_remaining = max(trials, key=lambda trial: trial[0])
            industrial_rejection_codes.update(loaded.industrial_rejection_codes)
            available.pop(selected_index)
            if loaded.placements:
                solution.containers.append(loaded)
                remaining = next_remaining
            continue

        container = available.pop(0)
        if timer is not None:
            timer.count("containers_attempted")
        with timer.stage("single_container_loading") if timer is not None else nullcontext():
            loaded, remaining = _pack_placeables_into_container(
                remaining, container, objective, timer, observe_industrial
            )
        industrial_rejection_codes.update(loaded.industrial_rejection_codes)
        if loaded.placements:
            solution.containers.append(loaded)

    # 容器用尽仍剩下的（含托盘块内各件）进入余货清单。
    unpacked: list[str] = []
    for pl in remaining:
        unpacked.extend(pl.item_ids())
    solution.unpacked = unpacked
    if unpacked and industrial_rejection_codes:
        messages = {
            "COG_OUT_OF_RANGE": "工业候选的载荷重心超出设备允许范围。",
            "FLOOR_LOAD_EXCEEDED": "工业候选超过设备地板载荷限制。",
            "LOAD_DISTRIBUTION_EXCEEDED": "工业候选超过设备纵向载荷分布曲线。",
            "STACK_CLUSTER_RESTRAINT_INSUFFICIENT": "工业候选形成的堆垛簇超过设备可用固定能力。",
            "POST_DROP_COG_OUT_OF_RANGE": "工业候选在某站点卸货后的剩余载荷重心超出设备允许范围，且无更晚卸货货物可修正。",
            "DELIVERY_PATH_BLOCKED": "工业候选没有无需倒货的直线卸货路径，或会堵死更早卸货货物的出口。",
        }
        solution.violations.extend(
            ConstraintViolation(code=code, severity="error", message=messages[code])
            for code in sorted(industrial_rejection_codes)
        )
    return solution


def solve(request: SolveRequest) -> Solution:
    """多容器求解主循环：决策码托盘 → 自动开箱直到货品装完或容器用尽。"""
    timer = PerformanceTimer()
    request, initial_violations = prepare_request(request)
    with timer.stage("prepare_objective"):
        objective = get_objective(
            request.objective, request.advanced_weights, request.safety_priority
        )
    with timer.stage("build_placeables"):
        placeables = _build_placeables(request, objective)  # 已按大块先排序
    with timer.stage("expand_containers"):
        containers = _expand_containers(request, objective)
    with timer.stage("container_loop"):
        solution = run_container_loop(
            placeables,
            containers,
            objective,
            timer,
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
