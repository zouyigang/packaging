"""码托盘逻辑与「直接装 vs 码托盘」决策（M3）。

托盘是算法的可选手段（见 CLAUDE.md 决策 1）：对每件/每批货品，由当前优化目标
决定是「直接装进容器」还是「先码到托盘再作为整块装箱」，按目标择优——不写死流程。

机制：把托盘当成一个迷你容器（footprint = pallet.length×width，限高 max_stack_height，
限重 max_load），用同一套极点启发式把同种货品尽量码上去，形成一个刚性块；
该块随后作为一个整体放进容器（M3 暂固定不旋转，朝向优化留待后续）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models.schemas import Item, Pallet
from .constraints import PlacedItem, commit_stack_load
from .extreme_point import find_placement
from .objectives import Objective
from .space import ExtremePointSet

# 托盘上单件货物的相对放置：item_id, x, y, z(含台面高), orientation
Content = tuple[str, float, float, float, str]


@dataclass
class PalletLoad:
    pallet_id: str            # 物理托盘实例 id（如 "p#1"）
    footprint_l: float        # 块在 x 方向占用（= 托盘长）
    footprint_w: float        # 块在 y 方向占用（= 托盘宽）
    total_height: float       # 台面高 + 码放高
    total_weight: float       # cargo weight + pallet tare weight
    contents: list[Content] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.contents)

    def bounding_volume(self) -> float:
        return self.footprint_l * self.footprint_w * self.total_height


def fits_on_pallet(item: Item, pallet: Pallet) -> bool:
    """item 在某朝向下底面能放进托盘 footprint 且高度不超过 max_stack_height。"""
    dims = (item.length, item.width, item.height)
    # 任意两维作底面、第三维作高，能否塞进 footprint 且不超限高。
    pairs = [(0, 1, 2), (0, 2, 1), (1, 2, 0)]
    for a, b, h in pairs:
        base = (dims[a], dims[b])
        if (
            min(base) <= min(pallet.length, pallet.width)
            and max(base) <= max(pallet.length, pallet.width)
            and dims[h] <= pallet.max_stack_height
        ):
            return True
    return False


def build_pallet_load(
    item: Item,
    pallet: Pallet,
    objective: Objective,
    instance_id: str,
    limit: int | None = None,
) -> PalletLoad:
    """把尽量多的同种 item 码到一个托盘上；limit 限制本托盘最多码几件（用于最后一只半满托盘）。"""
    ep = ExtremePointSet()
    placed: list[PlacedItem] = []
    contents: list[Content] = []
    cargo_weight = 0.0
    stack_height = 0.0

    while True:
        if limit is not None and len(contents) >= limit:
            break
        if cargo_weight + item.weight > pallet.max_load + 1e-9:
            break
        cand = find_placement(
            item.length,
            item.width,
            item.height,
            item.allowed_rotations,
            ep,
            placed,
            pallet.length,
            pallet.width,
            pallet.max_stack_height,
            score_fn=objective.placement_score,
            weight=item.weight,
        )
        if cand is None:
            break
        x, y, z, _dx, _dy, dz = cand.box
        contents.append((item.id, x, y, z + pallet.deck_height, cand.orientation))
        commit_stack_load(cand.box, item.weight, placed)
        placed.append(PlacedItem(
            box=cand.box, weight=item.weight,
            max_load_top=item.max_load_top, item_id=item.id,
        ))
        ep.remove(cand.point)
        ep.add_from_placement(cand.box)
        cargo_weight += item.weight
        stack_height = max(stack_height, z + dz)

    return PalletLoad(
        pallet_id=instance_id,
        footprint_l=pallet.length,
        footprint_w=pallet.width,
        total_height=pallet.deck_height + stack_height,
        total_weight=cargo_weight + pallet.tare_weight,
        contents=contents,
    )


def pallet_load_efficiency(load: PalletLoad, item: Item) -> float:
    """满托盘填充率 = 货物总体积 / 托盘块包围盒体积。"""
    bounding = load.bounding_volume()
    if bounding <= 0:
        return 0.0
    cargo = load.count * item.length * item.width * item.height
    return cargo / bounding


def select_pallet(item: Item, pallets: list[Pallet], objective: Objective) -> Pallet | None:
    """从有余量的托盘类型里挑「单托盘可码件数最多」的一种；都放不下返回 None。"""
    best: Pallet | None = None
    best_count = 0
    for p in pallets:
        if p.quantity <= 0 or not fits_on_pallet(item, p):
            continue
        sample = build_pallet_load(item, p, objective, instance_id=f"{p.id}#probe")
        if sample.count > best_count:
            best, best_count = p, sample.count
    return best
