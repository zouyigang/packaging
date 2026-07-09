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
    Item,
    LoadedContainer,
    LoadingAccess,
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
    check_heavy_low_from_supporters,
    check_stack_load_from_supporters,
    check_stacking_type_from_supporters,
    check_support_from_supporters,
    commit_stack_load,
    supporters_from_candidates,
)
from .evaluator import evaluate_solution
from .extreme_point import OrientedRotation, find_placement
from .geometry import box_volume, oriented_dims
from .objectives import Objective, ScoreContext, delivery_group_keys, get_objective
from .performance import PerformanceTimer
from .palletizer import (
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

        if self.content_dims is None:
            return [(placement, (px, py, pz, self.length, self.width, self.height)) for placement in placements]
        out: list[tuple[Placement, tuple[float, float, float, float, float, float]]] = []
        for placement, (_cid, ox, oy, oz, corient) in zip(placements, self.contents):
            dx, dy, dz = oriented_dims(*self.content_dims, corient)
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
        for i, (cid, ox, oy, oz, corient) in enumerate(self.contents, start=1):
            out.append(
                Placement(
                    item_id=cid,
                    pallet_id=self.pallet_id,
                    customer_id=self.customer_id,
                    order_id=self.order_id,
                    destination_id=self.destination_id,
                    stop_seq=self.stop_seq,
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


def _single_placeable(item: Item) -> _Placeable:
    volume = _placeable_volume(item.length, item.width, item.height)
    return _Placeable(
        item_id=item.id,
        pallet_id=None,
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
        stacking_type=_effective_stacking_type(item),
        max_load_top=item.max_load_top,
        contents=None,
        content_dims=None,
    )


def _composite_placeable(load, item: Item) -> _Placeable:
    allowed_rotations = ["LWH"]
    volume = _placeable_volume(load.footprint_l, load.footprint_w, load.total_height)
    return _Placeable(
        item_id=load.contents[0][0],
        pallet_id=load.pallet_id,
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
        stacking_type="not_stackable",
        max_load_top=0,
        contents=load.contents,
        content_dims=(item.length, item.width, item.height),
    )


def _build_placeables(request: SolveRequest, objective: Objective) -> list[_Placeable]:
    """逐货品种类做「直接装 vs 码托盘」决策，产出待放置单元列表。"""
    pallets = [p.model_copy() for p in request.pallets]  # 复制以便扣减可用数量
    placeables: list[_Placeable] = []

    for item in request.items:
        remaining = item.quantity
        pallet = select_pallet(item, pallets, objective) if (_can_palletize_item(item) and pallets) else None

        if pallet is not None:
            sample = build_pallet_load(item, pallet, objective, instance_id=f"{pallet.id}#probe")
            eff = pallet_load_efficiency(sample, item)
            if sample.count > 0 and objective.should_palletize(eff, sample.count):
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


def _pack_placeables_into_container(
    placeables: list[_Placeable],
    container: Container,
    objective: Objective,
    timer: PerformanceTimer | None = None,
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
    support_layers: dict[float, list[PlacedItem]] = {}
    overlap_grid_layers: dict[tuple[float, float], dict[tuple[int, int], list[PlacedItem]]] = {}

    # 评分上下文（含累计重心信息），供重心居中等目标使用；默认目标忽略它。
    ctx = ScoreContext(inner_length=container.inner_length, inner_width=container.inner_width, inner_height=container.inner_height)
    ctx.loading_access_sides = tuple(access.side for access in _effective_loading_accesses(container))
    if placeables:
        stops = [max(1, int(pl.stop_seq or 1)) for pl in placeables]
        ctx.min_stop_seq = min(stops)
        ctx.max_stop_seq = max(stops)
    scorer = objective.make_scorer(ctx)

    for pl in placeables:
        # 容器载重上限：累计重量不得超过 max_payload（重者放不下，留待后续容器）。
        if container.max_payload and used_weight + pl.weight > container.max_payload + 1e-6:
            leftover.append(pl)
            continue
        ctx.unit_w = pl.weight
        ctx.current_stop_seq = max(1, int(pl.stop_seq or 1))
        ctx.current_customer_id = pl.customer_id
        ctx.current_order_id = pl.order_id

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

        def hard_constraints(box) -> bool:
            if not _check_cog_with_context(
                ctx,
                pl,
                box,
                pl.weight,
                container.inner_length,
                container.inner_width,
            ):
                if timer is not None:
                    timer.count("cog_constraint_rejections")
                return False
            x, y, _z, dx, dy, _dz = box
            x2 = x + dx
            y2 = y + dy
            support_candidates: list[PlacedItem] = []
            for item in support_layers.get(_z_key(box[2]), []):
                ix, iy, _iz, idx, idy, _idz = item.box
                if x2 > ix + EPS and ix + idx > x + EPS and y2 > iy + EPS and iy + idy > y + EPS:
                    support_candidates.append(item)
            if timer is not None:
                timer.count("support_candidate_items", len(support_candidates))
            sups = supporters_from_candidates(box, support_candidates)
            return (
                check_support_from_supporters(box, sups, DEFAULT_SUPPORT_RATIO)
                and check_stack_load_from_supporters(pl.weight, sups)
                and check_stacking_type_from_supporters(box, pl.item_id, pl.stacking_type, sups)
                and check_heavy_low_from_supporters(box, pl.weight, sups)
            )

        def overlaps_existing(box) -> bool:
            x, y, z, dx, dy, dz = box
            x2 = x + dx
            y2 = y + dy
            z_top = z + dz
            bx_first = int(x // SPATIAL_BIN_SIZE)
            bx_last = int((x2 - EPS) // SPATIAL_BIN_SIZE)
            by_first = int(y // SPATIAL_BIN_SIZE)
            by_last = int((y2 - EPS) // SPATIAL_BIN_SIZE)
            needs_seen = bx_first != bx_last or by_first != by_last
            scanned = 0
            seen: set[int] | None = set() if needs_seen else None
            for (low, high), grid in overlap_grid_layers.items():
                if low < z_top - EPS and high > z + EPS:
                    for bx in range(bx_first, bx_last + 1):
                        for by in range(by_first, by_last + 1):
                            for item in grid.get((bx, by), []):
                                if seen is not None:
                                    item_key = id(item)
                                    if item_key in seen:
                                        continue
                                    seen.add(item_key)
                                scanned += 1
                                ix, iy, _iz, idx, idy, _idz = item.box
                                if x2 > ix + EPS and ix + idx > x + EPS and y2 > iy + EPS and iy + idy > y + EPS:
                                    if timer is not None:
                                        timer.count("overlap_scan_items", scanned)
                                        timer.count("overlap_candidate_items")
                                    return True
            if timer is not None:
                timer.count("overlap_scan_items", scanned)
            return False

        if timer is not None:
            timer.count("find_placement_calls")
        with timer.stage("find_placement") if timer is not None else nullcontext():
            cand = find_placement(
                pl.length,
                pl.width,
                pl.height,
                pl.allowed_rotations,
                ep_set,
                placed_items,
                container.inner_length,
                container.inner_width,
                container.inner_height,
                score_fn=scorer,
                weight=pl.weight,
                enforce_constraints=False,
                extra_points_fn=balance_points,
                hard_constraint_fn=hard_constraints,
                overlap_check_fn=overlaps_existing,
                oriented_rotations=pl.oriented_rotations,
                counter_fn=timer.count if timer is not None else None,
                max_counter_fn=timer.count_max if timer is not None else None,
                filter_covered_points=False,
            )
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
        support_layers.setdefault(_z_key(top_z), []).append(placed_item)
        overlap_key = (_z_key(cand.box[2]), _z_key(top_z))
        _add_to_spatial_grid(overlap_grid_layers.setdefault(overlap_key, {}), placed_item)
        used_volume += pl.volume
        used_weight += pl.weight

        # 更新重心累计（质量：重量优先，无重量用体积兜底；用所选 box 的中心）。
        bdx, bdy, bdz = cand.box[3], cand.box[4], cand.box[5]
        mass = pl.weight if pl.weight > 0 else pl.volume
        ctx.total_w += mass
        center_x = px + bdx / 2.0
        center_y = py + bdy / 2.0
        ctx.sum_wx += mass * center_x
        ctx.sum_wy += mass * center_y
        _update_delivery_groups(ctx, pl, center_x, center_y)

    container_volume = (
        container.inner_length * container.inner_width * container.inner_height
    )
    loaded.volume_utilization = used_volume / container_volume if container_volume else 0.0
    loaded.weight_utilization = (
        used_weight / container.max_payload if container.max_payload else 0.0
    )
    if objective.name == "center_of_gravity":
        _center_loaded_container(loaded, placement_boxes, balance_boxes, container)
    _resequence_inside_to_outside(
        loaded, placement_boxes, container, objective.name in {"loading_efficiency", "multi_customer_delivery"}
    )
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
    for index, (placement, box) in enumerate(placement_boxes):
        x, y, z, dx, dy, dz = box
        placement_boxes[index] = (placement, (x + shift_x, y + shift_y, z, dx, dy, dz))


def _clamp_shift(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _update_delivery_groups(ctx: ScoreContext, pl: _Placeable, center_x: float, center_y: float) -> None:
    for key in delivery_group_keys(max(1, int(pl.stop_seq or 1)), pl.customer_id, pl.order_id):
        count, sum_x, sum_y = ctx.delivery_groups.get(key, (0.0, 0.0, 0.0))
        ctx.delivery_groups[key] = (count + 1.0, sum_x + center_x, sum_y + center_y)


def _resequence_inside_to_outside(
    loaded: LoadedContainer,
    placement_boxes: list[tuple[Placement, tuple[float, float, float, float, float, float]]],
    container: Container,
    use_stop_priority: bool = False,
) -> None:
    """Assign loading seq from container inside to door while honoring support deps."""
    records = list(placement_boxes)
    deps: list[set[int]] = [set() for _ in records]

    for i, (_p, box) in enumerate(records):
        x, y, z, dx, dy, _dz = box
        if z <= EPS:
            continue
        for j, (_below_p, below) in enumerate(records):
            if i == j:
                continue
            bx, by, bz, bdx, bdy, bdz = below
            if abs((bz + bdz) - z) > EPS:
                continue
            ox = max(0.0, min(x + dx, bx + bdx) - max(x, bx))
            oy = max(0.0, min(y + dy, by + bdy) - max(y, by))
            if ox * oy > EPS:
                deps[i].add(j)

    remaining = set(range(len(records)))
    emitted: list[int] = []
    while remaining:
        ready = [i for i in remaining if deps[i].issubset(emitted)]
        if not ready:
            ready = list(remaining)
        ready.sort(key=lambda i: _loading_priority(records[i], container, use_stop_priority))
        chosen = ready[0]
        remaining.remove(chosen)
        emitted.append(chosen)

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
) -> Solution:
    """按给定顺序把 placeables 逐只开箱装载（GA 解码器复用此函数）。

    placeables 的先后即放置优先级；调用方负责排序。
    """
    remaining = list(placeables)
    solution = Solution()
    for container in containers:
        if not remaining:
            break
        if timer is not None:
            timer.count("containers_attempted")
        with timer.stage("single_container_loading") if timer is not None else nullcontext():
            loaded, remaining = _pack_placeables_into_container(remaining, container, objective, timer)
        if loaded.placements:
            solution.containers.append(loaded)

    # 容器用尽仍剩下的（含托盘块内各件）进入余货清单。
    unpacked: list[str] = []
    for pl in remaining:
        unpacked.extend(pl.item_ids())
    solution.unpacked = unpacked
    return solution


def solve(request: SolveRequest) -> Solution:
    """多容器求解主循环：决策码托盘 → 自动开箱直到货品装完或容器用尽。"""
    timer = PerformanceTimer()
    with timer.stage("prepare_objective"):
        objective = get_objective(request.objective, request.advanced_weights)
    with timer.stage("build_placeables"):
        placeables = _build_placeables(request, objective)  # 已按大块先排序
    with timer.stage("expand_containers"):
        containers = _expand_containers(request, objective)
    with timer.stage("container_loop"):
        solution = run_container_loop(placeables, containers, objective, timer)
    with timer.stage("evaluator"):
        solution.evaluation = evaluate_solution(request, solution)
    solution.performance = PerformanceMetrics(
        runtime_ms=round(timer.runtime_ms, 3),
        stages_ms=timer.rounded_stages(),
        counters=timer.counters,
    )
    return solution
