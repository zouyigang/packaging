"""safe_loading 安全优先择箱（容量换安全）的单元测试。

验证 `_score_safety_trials` 在「装完成本」之外把所需固定力折成成本当量一并最小化：
- 更大箱型把货铺开、压低固定力时，即便单箱更贵也会被选中；
- 但装不完（余货）的代价仍压过固定力，不会为省固定力把必装货物撂下。
端到端效果（1140 件 40GP+20GP 取代 3×20GP、成本 6080→5480、固定力不变）由
scripts/benchmark_solver.py 的 industrial_large_safe_loading_safety_first 门禁守住。
"""
from app.core.packer import _score_safety_trials, _SAFETY_RESTRAINT_COST_PER_KN
from app.models.schemas import (
    AccelerationProfile,
    Container,
    Item,
    LoadedContainer,
    Placement,
)


def _container(cid, length, cost):
    return Container(
        id=cid,
        inner_length=length,
        inner_width=2000,
        inner_height=3000,
        max_payload=30000,
        quantity=2,
        use_cost=cost,
        acceleration_profile=AccelerationProfile(longitudinal_g=0.8, transverse_g=0.5),
    )


SMALL = _container("small", 1000, 2000)   # 窄底：同样的货只能往上堆 → 固定力高
BIG = _container("big", 4000, 3400)       # 宽底：货能铺开 → 固定力低


def _item():
    return Item(id="a", length=800, width=800, height=400, weight=300, quantity=8)


ITEM_MAP = {"a": _item()}


def _tall_loaded(cid):
    # 8 件竖直码成一柱（高重心、大力臂）→ 高固定力。
    return LoadedContainer(id=cid, placements=[
        Placement(item_id="a", x=0, y=0, z=level * 400, orientation="LWH", seq=level + 1)
        for level in range(8)
    ])


def _flat_loaded(cid):
    # 8 件平铺成一层（无堆叠簇）→ 固定力为 0。
    return LoadedContainer(id=cid, placements=[
        Placement(item_id="a", x=col * 900, y=row * 900, z=0, orientation="LWH", seq=col + row + 1)
        for row in range(2) for col in range(4)
    ])


def _trial(container, loaded, remaining, index):
    placed = len(loaded.placements)
    return {
        "container": container,
        "index": index,
        "loaded": loaded,
        "remaining": remaining,
        "placed_count": placed,
        "priority_value": placed,
    }


def test_safety_scorer_prefers_lower_restraint_even_at_higher_cost():
    """大箱铺平（固定力≈0、更贵）应压过小箱码高（固定力高、更便宜）。"""
    small_tall = _trial(SMALL, _tall_loaded("small"), [], 0)   # 便宜但高固定力
    big_flat = _trial(BIG, _flat_loaded("big"), [], 1)         # 贵但零固定力
    scored = _score_safety_trials([small_tall, big_flat], [SMALL, BIG], ITEM_MAP)
    winner = max(scored, key=lambda t: t[0])
    assert winner[1] == 1  # big_flat 的 index

    # 反向健壮性：把固定力权重清零，则退回纯成本，便宜的小箱胜出。
    import app.core.packer as packer
    original = packer._SAFETY_RESTRAINT_COST_PER_KN
    try:
        packer._SAFETY_RESTRAINT_COST_PER_KN = 0.0
        scored0 = packer._score_safety_trials([small_tall, big_flat], [SMALL, BIG], ITEM_MAP)
        assert max(scored0, key=lambda t: t[0])[1] == 0  # small 更便宜
    finally:
        packer._SAFETY_RESTRAINT_COST_PER_KN = original


def test_safety_scorer_completion_beats_restraint():
    """装不完的低固定力方案不得胜过装完的方案——余货成本压过固定力收益。"""
    # 小箱平铺但只装 4 件（余 4 件），固定力 0；大箱平铺装完 8 件。
    half_flat = LoadedContainer(id="small", placements=[
        Placement(item_id="a", x=col * 900, y=0, z=0, orientation="LWH", seq=col + 1)
        for col in range(4)
    ])
    leftover = [object()] * 4  # 仅计数用；_score_safety_trials 只看数量与体积
    # 给余货对象补上 volume 属性（sum(pl.volume ...)）。
    class _PL:
        volume = 800 * 800 * 400
    small_partial = _trial(SMALL, half_flat, [_PL(), _PL(), _PL(), _PL()], 0)
    big_full = _trial(BIG, _flat_loaded("big"), [], 1)
    scored = _score_safety_trials([small_partial, big_full], [SMALL, BIG], ITEM_MAP)
    assert max(scored, key=lambda t: t[0])[1] == 1  # big_full 装完，胜出


def test_weight_constant_is_positive():
    assert _SAFETY_RESTRAINT_COST_PER_KN > 0
