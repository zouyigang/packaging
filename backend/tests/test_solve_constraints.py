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
    assert placed_ids == ["base"]
    assert sol.unpacked == ["top", "top"]


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


def test_heavier_item_not_stacked_on_lighter_support():
    light = Item(id="light", length=100, width=100, height=50, weight=5, max_load_top=100)
    heavy = Item(id="heavy", length=100, width=100, height=50, weight=20)
    container = Container(
        id="c", inner_length=100, inner_width=100, inner_height=100,
        max_payload=10000, quantity=1,
    )

    sol = solve(SolveRequest(items=[light, heavy], containers=[container]))

    placed_ids = [p.item_id for p in _all_placements(sol)]
    assert placed_ids == ["light"]
    assert sol.unpacked == ["heavy"]


def test_cog_limit_applies_to_max_utilization_strategy():
    item = Item(id="a", length=600, width=400, height=400, weight=20, quantity=1)
    container = Container(
        id="c", inner_length=5900, inner_width=2350, inner_height=2390,
        max_payload=28000, quantity=1,
    )

    sol = solve(SolveRequest(items=[item], containers=[container], objective="max_utilization"))

    [p] = _all_placements(sol)
    dx, dy, _dz = oriented_dims(item.length, item.width, item.height, p.orientation)
    gx = p.x + dx / 2
    gy = p.y + dy / 2
    assert abs(gx - container.inner_length / 2) / container.inner_length <= 0.25
    assert abs(gy - container.inner_width / 2) / container.inner_width <= 0.25


def test_not_stackable_item_cannot_support_other_items():
    base = Item(
        id="base",
        length=50,
        width=50,
        height=50,
        weight=5,
        stacking_type="not_stackable",
    )
    top = Item(id="top", length=50, width=50, height=50, weight=5)
    container = Container(
        id="c", inner_length=50, inner_width=50, inner_height=100,
        max_payload=10000, quantity=1,
    )

    sol = solve(SolveRequest(items=[base, top], containers=[container]))

    assert [p.item_id for p in _all_placements(sol)] == ["base"]
    assert sol.unpacked == ["top"]


def test_same_item_only_rejects_different_item_stacked_above():
    base = Item(
        id="A",
        length=50,
        width=50,
        height=50,
        weight=5,
        stacking_type="same_item_only",
    )
    top = Item(id="B", length=50, width=50, height=50, weight=5)
    container = Container(
        id="c", inner_length=50, inner_width=50, inner_height=100,
        max_payload=10000, quantity=1,
    )

    sol = solve(SolveRequest(items=[base, top], containers=[container]))

    assert [p.item_id for p in _all_placements(sol)] == ["A"]
    assert sol.unpacked == ["B"]


def test_same_item_only_allows_same_item_stacking():
    item = Item(
        id="A",
        length=50,
        width=50,
        height=50,
        weight=5,
        quantity=2,
        stacking_type="same_item_only",
    )
    container = Container(
        id="c", inner_length=50, inner_width=50, inner_height=100,
        max_payload=10000, quantity=1,
    )

    sol = solve(SolveRequest(items=[item], containers=[container]))

    assert [p.item_id for p in _all_placements(sol)] == ["A", "A"]
    assert sol.unpacked == []


def test_support_only_item_cannot_be_placed_on_another_item():
    base = Item(id="base", length=50, width=50, height=50, weight=5)
    upper = Item(
        id="support-only",
        length=50,
        width=50,
        height=50,
        weight=5,
        stacking_type="support_only",
    )
    container = Container(
        id="c", inner_length=50, inner_width=50, inner_height=100,
        max_payload=10000, quantity=1,
    )

    sol = solve(SolveRequest(items=[base, upper], containers=[container]))

    assert [p.item_id for p in _all_placements(sol)] == ["base"]
    assert sol.unpacked == ["support-only"]


def test_top_only_item_can_be_stacked_but_cannot_support_more_items():
    base = Item(id="base", length=50, width=50, height=50, weight=5)
    top_only = Item(
        id="top-only",
        length=50,
        width=50,
        height=50,
        weight=5,
        stacking_type="top_only",
    )
    cap = Item(id="cap", length=50, width=50, height=50, weight=5)
    container = Container(
        id="c", inner_length=50, inner_width=50, inner_height=150,
        max_payload=10000, quantity=1,
    )

    sol = solve(SolveRequest(items=[base, top_only, cap], containers=[container]))

    assert [p.item_id for p in _all_placements(sol)] == ["base", "top-only"]
    assert sol.unpacked == ["cap"]


def test_top_load_is_zero_for_items_that_cannot_support_upper_loads():
    independent = Item(
        id="independent",
        length=50,
        width=50,
        height=50,
        stacking_type="not_stackable",
        max_load_top=100,
    )
    top_only = Item(
        id="top-only",
        length=50,
        width=50,
        height=50,
        stacking_type="top_only",
        max_load_top=100,
    )
    support_only = Item(
        id="support-only",
        length=50,
        width=50,
        height=50,
        stacking_type="support_only",
        max_load_top=100,
    )

    assert independent.max_load_top == 0
    assert top_only.max_load_top == 0
    assert support_only.max_load_top == 100
