from app.core.packer import solve
from app.core.geometry import oriented_dims
from app.models.schemas import Container, Item, Pallet, SolveRequest


def _item(qty, stackable=True):
    return Item(id="a", length=50, width=50, height=50, weight=10,
                quantity=qty, stackable=stackable)


def _pallet(qty):
    return Pallet(id="p", length=100, width=100, deck_height=10,
                  max_stack_height=200, max_load=1000, quantity=qty)


def _big_container(qty=1):
    return Container(id="c", inner_length=220, inner_width=220, inner_height=220,
                     max_payload=100000, quantity=qty)


def _pallet_ids(sol):
    return {p.pallet_id for c in sol.containers for p in c.placements}


def test_stability_palletizes():
    req = SolveRequest(
        items=[_item(32)], pallets=[_pallet(2)], containers=[_big_container()],
        objective="stability",
    )
    sol = solve(req)
    placements = [p for c in sol.containers for p in c.placements]
    assert len(placements) == 32
    assert all(p.pallet_id is not None for p in placements)
    assert _pallet_ids(sol) == {"p#2", "p#1"}  # 两只物理托盘各有独立 id
    assert sol.unpacked == []


def test_max_utilization_does_not_palletize():
    req = SolveRequest(
        items=[_item(32)], pallets=[_pallet(2)], containers=[_big_container()],
        objective="max_utilization",
    )
    sol = solve(req)
    placements = [p for c in sol.containers for p in c.placements]
    assert len(placements) == 32
    assert all(p.pallet_id is None for p in placements)


def test_unstackable_not_palletized():
    req = SolveRequest(
        items=[_item(8, stackable=False)], pallets=[_pallet(2)],
        containers=[_big_container()], objective="stability",
    )
    sol = solve(req)
    placements = [p for c in sol.containers for p in c.placements]
    assert all(p.pallet_id is None for p in placements)


def test_pallet_exhaustion_sends_remainder_direct():
    # 20 件，但只有 1 只托盘(可码 16) → 16 上托盘，4 件直接装
    req = SolveRequest(
        items=[_item(20)], pallets=[_pallet(1)], containers=[_big_container()],
        objective="stability",
    )
    sol = solve(req)
    placements = [p for c in sol.containers for p in c.placements]
    on_pallet = [p for p in placements if p.pallet_id is not None]
    direct = [p for p in placements if p.pallet_id is None]
    assert len(on_pallet) == 16
    assert len(direct) == 4
    assert sol.unpacked == []


def test_no_pallets_behaves_like_direct():
    req = SolveRequest(
        items=[_item(8)], containers=[_big_container()], objective="stability",
    )
    sol = solve(req)
    placements = [p for c in sol.containers for p in c.placements]
    assert len(placements) == 8
    assert all(p.pallet_id is None for p in placements)

def test_pallet_tare_weight_counts_against_container_payload():
    req = SolveRequest(
        items=[_item(16)],
        pallets=[_pallet(1).model_copy(update={"tare_weight": 50})],
        containers=[Container(id="c", inner_length=220, inner_width=220, inner_height=220, max_payload=200, quantity=1)],
        objective="stability",
    )
    sol = solve(req)
    assert sol.containers == []
    assert sol.unpacked == ["a"] * 16


def test_palletized_replay_never_shows_floating_items():
    item = _item(32)
    pallet = _pallet(2)
    req = SolveRequest(
        items=[item],
        pallets=[pallet],
        containers=[_big_container()],
        objective="stability",
    )

    sol = solve(req)
    placements = sorted(
        [p for c in sol.containers for p in c.placements],
        key=lambda p: p.seq,
    )
    seen_boxes = []
    by_pallet = {}
    for placement in placements:
        if placement.pallet_id:
            by_pallet.setdefault(placement.pallet_id, []).append(placement)

    for placement in placements:
        dx, dy, dz = oriented_dims(item.length, item.width, item.height, placement.orientation)
        box = (placement.x, placement.y, placement.z, dx, dy, dz)
        assert _fully_supported_in_replay(box, placement.pallet_id, by_pallet, pallet, seen_boxes)
        seen_boxes.append(box)


def test_default_stability_sample_replay_never_shows_floating_items():
    items = [
        Item(
            id="box-A",
            length=600,
            width=400,
            height=400,
            weight=20,
            quantity=8,
            allowed_rotations=["LWH", "WLH"],
            stackable=False,
            stacking_type="not_stackable",
            max_load_top=0,
            customer_id="甲",
            stop_seq=1,
        ),
        Item(
            id="box-B",
            length=400,
            width=300,
            height=300,
            weight=8,
            quantity=120,
            allowed_rotations=["LWH", "WLH", "LHW", "HLW", "WHL", "HWL"],
            stackable=True,
            stacking_type="stackable",
            max_load_top=None,
            customer_id="甲",
            stop_seq=1,
        ),
        Item(
            id="box-C",
            length=500,
            width=400,
            height=230,
            weight=10,
            quantity=300,
            allowed_rotations=["LWH", "WLH", "LHW", "HLW"],
            stackable=True,
            stacking_type="stackable",
            max_load_top=None,
            customer_id="乙",
            stop_seq=2,
        ),
        Item(
            id="box-D",
            length=300,
            width=200,
            height=200,
            weight=1,
            quantity=10,
            allowed_rotations=["LWH", "WLH", "LHW", "HLW", "WHL", "HWL"],
            stackable=True,
            stacking_type="top_only",
            max_load_top=None,
            customer_id="乙",
            stop_seq=2,
        ),
    ]
    pallet = Pallet(
        id="plt",
        length=1200,
        width=1000,
        tare_weight=10,
        deck_height=150,
        max_stack_height=1500,
        max_load=1000,
        quantity=4,
    )
    req = SolveRequest(
        items=items,
        pallets=[pallet],
        containers=[
            Container(
                id="cntr",
                inner_length=5900,
                inner_width=2350,
                inner_height=2390,
                max_payload=28000,
                quantity=2,
            )
        ],
        objective="stability",
    )

    sol = solve(req)
    assert sum(len(container.placements) for container in sol.containers) == 438
    _assert_replay_fully_supported(sol, {item.id: item for item in items}, {"plt": pallet})


def _assert_replay_fully_supported(sol, item_map, pallet_map):
    for loaded in sol.containers:
        placements = sorted(loaded.placements, key=lambda p: p.seq)
        by_pallet = {}
        for placement in placements:
            if placement.pallet_id:
                by_pallet.setdefault(placement.pallet_id, []).append(placement)
        seen_boxes = []
        for placement in placements:
            item = item_map[placement.item_id]
            dx, dy, dz = oriented_dims(item.length, item.width, item.height, placement.orientation)
            box = (placement.x, placement.y, placement.z, dx, dy, dz)
            pallet = pallet_map.get(placement.pallet_id.split("#")[0]) if placement.pallet_id else None
            assert _fully_supported_in_replay(box, placement.pallet_id, by_pallet, pallet, seen_boxes)
            seen_boxes.append(box)


def _fully_supported_in_replay(box, pallet_id, by_pallet, pallet, seen_boxes, eps=1e-6):
    x, y, z, dx, dy, _dz = box
    if z <= eps:
        return True
    support_area = 0.0
    if pallet_id and pallet is not None and abs(z - pallet.deck_height) <= eps:
        pallet_items = by_pallet[pallet_id]
        deck_x = min(p.x for p in pallet_items)
        deck_y = min(p.y for p in pallet_items)
        support_area += _overlap_area(x, y, dx, dy, deck_x, deck_y, pallet.length, pallet.width)
    for bx, by, bz, bdx, bdy, bdz in seen_boxes:
        if abs((bz + bdz) - z) > eps:
            continue
        support_area += _overlap_area(x, y, dx, dy, bx, by, bdx, bdy)
    return support_area >= dx * dy - eps


def _overlap_area(x, y, dx, dy, bx, by, bdx, bdy):
    ox = max(0.0, min(x + dx, bx + bdx) - max(x, bx))
    oy = max(0.0, min(y + dy, by + bdy) - max(y, by))
    return ox * oy
