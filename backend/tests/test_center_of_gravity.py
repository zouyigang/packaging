from app.core.geometry import oriented_dims
from app.core.objectives import CenterOfGravity, get_objective
from app.core.packer import solve
from app.models.schemas import Container, Item, SolveRequest


def _cog_offset(sol, item_map, container):
    """整体水平重心到容器中心的 |dx|+|dy| 偏移。"""
    cx, cy = container.inner_length / 2, container.inner_width / 2
    tw = sx = sy = 0.0
    for c in sol.containers:
        for p in c.placements:
            it = item_map[p.item_id]
            dx, dy, dz = oriented_dims(it.length, it.width, it.height, p.orientation)
            m = it.weight if it.weight > 0 else dx * dy * dz
            tw += m
            sx += m * (p.x + dx / 2)
            sy += m * (p.y + dy / 2)
    return abs(sx / tw - cx) + abs(sy / tw - cy)


def test_registered():
    assert isinstance(get_objective("center_of_gravity"), CenterOfGravity)


def test_partial_fill_more_centered_than_max_utilization():
    # 部分装载：重心居中应比靠角的最大利用率重心更靠近容器中心
    item = Item(id="a", length=600, width=400, height=400, weight=20, quantity=24)
    container = Container(id="c", inner_length=5900, inner_width=2350, inner_height=2390,
                         max_payload=28000, quantity=1)
    item_map = {item.id: item}

    base = solve(SolveRequest(items=[item], containers=[container], objective="max_utilization"))
    cog = solve(SolveRequest(items=[item], containers=[container], objective="center_of_gravity"))

    off_base = _cog_offset(base, item_map, container)
    off_cog = _cog_offset(cog, item_map, container)
    assert off_cog < off_base


def test_all_items_still_placed():
    item = Item(id="a", length=50, width=50, height=50, quantity=8)
    container = Container(id="c", inner_length=100, inner_width=100, inner_height=100,
                         max_payload=10000, quantity=1)
    sol = solve(SolveRequest(items=[item], containers=[container], objective="center_of_gravity"))
    assert len(sol.containers[0].placements) == 8
    assert sol.unpacked == []


def test_deterministic():
    item = Item(id="a", length=400, width=300, height=300, weight=5, quantity=15)
    container = Container(id="c", inner_length=2000, inner_width=1200, inner_height=1200,
                         max_payload=10000, quantity=1)
    req = SolveRequest(items=[item], containers=[container], objective="center_of_gravity")
    s1 = solve(req)
    s2 = solve(req)
    c1 = [(p.x, p.y, p.z, p.seq) for c in s1.containers for p in c.placements]
    c2 = [(p.x, p.y, p.z, p.seq) for c in s2.containers for p in c.placements]
    assert c1 == c2
