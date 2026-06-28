from app.core.constraints import EPS
from app.core.geometry import oriented_dims
from app.core.packer import solve
from app.models.schemas import Container, Item, SolveRequest


def _all_placements(sol):
    return [p for c in sol.containers for p in c.placements]


def test_container_payload_limit_leaves_overweight_unpacked():
    # 每件 20kg，容器载重上限 30kg → 只能装 1 件
    item = Item(id="a", length=50, width=50, height=50, weight=20, quantity=3)
    container = Container(
        id="c", inner_length=100, inner_width=100, inner_height=100,
        max_payload=30, quantity=1,
    )
    sol = solve(SolveRequest(items=[item], containers=[container]))
    assert len(_all_placements(sol)) == 1
    assert sol.unpacked == ["a", "a"]


def test_fragile_item_not_covered():
    # 50×50×100 容器只有一列；A 易碎(max_load_top=0)，B 无处可放只能落 A 上 → B 余货
    a = Item(id="A", length=50, width=50, height=50, weight=5, max_load_top=0)
    b = Item(id="B", length=50, width=50, height=50, weight=5)
    container = Container(
        id="c", inner_length=50, inner_width=50, inner_height=100,
        max_payload=10000, quantity=1,
    )
    sol = solve(SolveRequest(items=[a, b], containers=[container]))
    placed_ids = [p.item_id for p in _all_placements(sol)]
    assert placed_ids == ["A"]
    assert sol.unpacked == ["B"]


def test_max_load_top_limits_stacking():
    # base 底面 100×50 承重上限 15kg；两件 10kg 的 top 同压其上 → 第二件超限
    base = Item(id="base", length=100, width=50, height=50, weight=5, max_load_top=15)
    top = Item(id="top", length=50, width=50, height=50, weight=10, quantity=2)
    container = Container(
        id="c", inner_length=100, inner_width=50, inner_height=100,
        max_payload=10000, quantity=1,
    )
    sol = solve(SolveRequest(items=[base, top], containers=[container]))
    placed_ids = sorted(p.item_id for p in _all_placements(sol))
    assert placed_ids == ["base", "top"]  # base + 仅 1 个 top
    assert sol.unpacked == ["top"]


def test_no_floating_in_result():
    # 普通堆叠场景，校验结果里每个箱体都被支撑（地面或下方箱顶）
    item = Item(id="a", length=40, width=40, height=40, quantity=30)
    container = Container(
        id="c", inner_length=120, inner_width=120, inner_height=120,
        max_payload=100000, quantity=1,
    )
    sol = solve(SolveRequest(items=[item], containers=[container]))
    placements = _all_placements(sol)
    boxes = []
    for p in placements:
        dx, dy, dz = oriented_dims(40, 40, 40, p.orientation)
        boxes.append((p.x, p.y, p.z, dx, dy, dz))
    for x, y, z, dx, dy, dz in boxes:
        if z <= EPS:
            continue  # 地面
        # 必有某箱顶面 == z 且水平投影重叠
        supported = any(
            abs((bz + bdz) - z) <= EPS
            and max(0.0, min(x + dx, bx + bdx) - max(x, bx)) > EPS
            and max(0.0, min(y + dy, by + bdy) - max(y, by)) > EPS
            for bx, by, bz, bdx, bdy, bdz in boxes
            if (bx, by, bz, bdx, bdy, bdz) != (x, y, z, dx, dy, dz)
        )
        assert supported, f"box at z={z} is floating"
