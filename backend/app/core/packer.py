"""编排器（M3：多容器循环 + 可插拔目标 + 直接装/码托盘决策）。

主流程：
  预处理（按数量展开为单件、大件先）→ 逐货品种类做「直接装 vs 码托盘」决策（由目标择优）
  → 生成待放置单元(placeable)：单件 或 托盘整块 → 多容器循环：按目标选容器开新箱 →
  极点启发式放置（记录坐标与 seq）→ 当前容器放不下的留到下一只 →
  容器用尽仍未放下的进入余货清单(unpacked)。

重量/朝向/堆叠/重心约束(M4) 在后续里程碑接入。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models.schemas import (
    Container,
    Item,
    LoadedContainer,
    LoadingAccess,
    Placement,
    Solution,
    SolveRequest,
)
from .constraints import (
    DEFAULT_COG_MAX_OFFSET_RATIO,
    EPS,
    PlacedItem,
    check_cog_within_limits,
    check_heavy_low,
    check_stacking_type,
    commit_stack_load,
)
from .extreme_point import find_placement
from .geometry import box_volume
from .objectives import Objective, ScoreContext, delivery_group_keys, get_objective
from .palletizer import (
    build_pallet_load,
    pallet_load_efficiency,
    select_pallet,
)
from .space import ExtremePointSet


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
    weight: float
    customer_id: str
    order_id: str
    destination_id: str
    stop_seq: int
    stacking_type: str
    max_load_top: float | None  # 顶部可承重；托盘块为 None(此处不再向上堆叠)
    contents: list | None  # list[(item_id, x, y, z, orientation)] 相对块原点；None=单件

    def item_ids(self) -> list[str]:
        if self.contents is None:
            return [self.item_id]
        return [c[0] for c in self.contents]

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

def _single_placeable(item: Item) -> _Placeable:
    return _Placeable(
        item_id=item.id,
        pallet_id=None,
        length=item.length,
        width=item.width,
        height=item.height,
        allowed_rotations=item.allowed_rotations,
        weight=item.weight,
        customer_id=item.customer_id,
        order_id=item.order_id,
        destination_id=item.destination_id,
        stop_seq=item.stop_seq,
        stacking_type=_effective_stacking_type(item),
        max_load_top=item.max_load_top,
        contents=None,
    )


def _composite_placeable(load, item: Item) -> _Placeable:
    return _Placeable(
        item_id=load.contents[0][0],
        pallet_id=load.pallet_id,
        length=load.footprint_l,
        width=load.footprint_w,
        height=load.total_height,
        allowed_rotations=["LWH"],  # 托盘块 M3 固定朝向
        weight=load.total_weight,
        customer_id=item.customer_id,
        order_id=item.order_id,
        destination_id=item.destination_id,
        stop_seq=item.stop_seq,
        stacking_type="stackable",
        max_load_top=None,
        contents=load.contents,
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
    placeables: list[_Placeable], container: Container, objective: Objective
) -> tuple[LoadedContainer, list[_Placeable]]:
    loaded = LoadedContainer(id=container.id)
    ep_set = ExtremePointSet()
    placed_items: list[PlacedItem] = []
    leftover: list[_Placeable] = []
    placement_boxes: list[tuple[Placement, tuple[float, float, float, float, float, float]]] = []
    seq = 0
    used_volume = 0.0
    used_weight = 0.0

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
            mass = pl.weight if pl.weight > 0 else dx * dy * dz
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
            zs = [0.0]
            zs.extend(pi.box[2] + pi.box[5] for pi in placed_items)

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
            return points

        def hard_constraints(box) -> bool:
            return (
                check_stacking_type(box, pl.item_id, pl.stacking_type, placed_items)
                and check_heavy_low(box, pl.weight, placed_items)
                and check_cog_within_limits(
                    box,
                    pl.weight,
                    placed_items,
                    container.inner_length,
                    container.inner_width,
                )
            )

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
            extra_points_fn=balance_points,
            hard_constraint_fn=hard_constraints,
        )
        if cand is None:
            leftover.append(pl)
            continue
        px, py, pz, *_ = cand.box
        emitted = pl.emit(px, py, pz, cand.orientation, start_seq=seq)
        loaded.placements.extend(emitted)
        placement_boxes.extend((p, cand.box) for p in emitted)
        seq += len(emitted)
        commit_stack_load(cand.box, pl.weight, placed_items)
        placed_items.append(PlacedItem(
            box=cand.box, weight=pl.weight,
            max_load_top=pl.max_load_top, item_id=pl.item_id,
            stacking_type=pl.stacking_type,
        ))
        ep_set.remove(cand.point)
        ep_set.add_from_placement(cand.box)
        used_volume += box_volume(cand.box)
        used_weight += pl.weight

        # 更新重心累计（质量：重量优先，无重量用体积兜底；用所选 box 的中心）。
        bdx, bdy, bdz = cand.box[3], cand.box[4], cand.box[5]
        mass = pl.weight if pl.weight > 0 else bdx * bdy * bdz
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
    _resequence_inside_to_outside(
        loaded, placement_boxes, container, objective.name in {"loading_efficiency", "multi_customer_delivery"}
    )
    return loaded, leftover


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
    placeables: list[_Placeable], containers: list[Container], objective: Objective
) -> Solution:
    """按给定顺序把 placeables 逐只开箱装载（GA 解码器复用此函数）。

    placeables 的先后即放置优先级；调用方负责排序。
    """
    remaining = list(placeables)
    solution = Solution()
    for container in containers:
        if not remaining:
            break
        loaded, remaining = _pack_placeables_into_container(remaining, container, objective)
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
    objective = get_objective(request.objective)
    placeables = _build_placeables(request, objective)  # 已按大块先排序
    containers = _expand_containers(request, objective)
    return run_container_loop(placeables, containers, objective)
