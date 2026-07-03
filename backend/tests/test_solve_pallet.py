from app.core.packer import solve
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
