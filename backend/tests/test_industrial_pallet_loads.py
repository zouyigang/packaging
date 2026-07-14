import pytest

from app.core.industrial import finalize_solution
from app.core.packer import solve
from app.models.schemas import (
    Container,
    Item,
    LoadedContainer,
    Pallet,
    PalletInstance,
    Placement,
    Solution,
    SolveRequest,
)


def _container():
    return Container(
        id="c",
        inner_length=3000,
        inner_width=2000,
        inner_height=2000,
        max_payload=10000,
        quantity=1,
        cog_limits={
            "x_min_ratio": 0.0,
            "x_max_ratio": 1.0,
            "y_min_ratio": 0.0,
            "y_max_ratio": 1.0,
            "z_max_ratio": 1.0,
        },
        max_floor_load_kg_m2=10000,
        acceleration_profile={
            "longitudinal_g": 0.8,
            "transverse_g": 0.5,
            "vertical_g": 0.2,
        },
        default_friction_coefficient=0.4,
    )


def _pallet(quantity=1, max_load=1000):
    return Pallet(
        id="p",
        length=1000,
        width=1000,
        deck_height=100,
        tare_weight=50,
        max_stack_height=1000,
        max_load=max_load,
        quantity=quantity,
    )


def _solve(items, pallets):
    return solve(SolveRequest(
        items=items,
        pallets=pallets,
        containers=[_container()],
        objective="safe_loading",
        validation_mode="industrial",
        pallet_policy="required",
    ))


def test_single_pallet_tare_is_included_in_mass_cog_and_floor_load():
    solution = _solve(
        [Item(id="a", length=500, width=500, height=200, weight=100, quantity=2)],
        [_pallet()],
    )

    loaded = solution.containers[0]
    assert len(loaded.pallet_instances) == 1
    assert loaded.pallet_instances[0].tare_weight == 50
    assert loaded.industrial_metrics["total_mass"] == pytest.approx(250)
    assert loaded.industrial_metrics["max_floor_load_kg_m2"] == pytest.approx(250)
    assert loaded.industrial_metrics["construction_total_mass"] == pytest.approx(250)
    assert loaded.industrial_metrics["construction_cog_z_ratio"] == pytest.approx(
        loaded.industrial_metrics["cog_z_ratio"]
    )
    pallet = loaded.pallet_instances[0]
    for placement in loaded.placements:
        assert placement.x >= pallet.x
        assert placement.y >= pallet.y
        assert placement.x + 500 <= pallet.x + pallet.length
        assert placement.y + 500 <= pallet.y + pallet.width


def test_multiple_pallets_each_transfer_tare_and_cargo_to_their_footprint():
    solution = _solve(
        [Item(id="a", length=500, width=500, height=200, weight=100, quantity=2)],
        [_pallet(quantity=2, max_load=100)],
    )

    loaded = solution.containers[0]
    assert len(loaded.pallet_instances) == 2
    assert loaded.industrial_metrics["total_mass"] == pytest.approx(300)
    assert loaded.industrial_metrics["max_floor_load_kg_m2"] == pytest.approx(150)


def test_mixed_pallet_uses_per_item_weight_plus_one_tare_weight():
    items = [
        Item(
            id="a", length=500, width=500, height=200, weight=100, quantity=1,
            stop_seq=2, pallet_group="ambient",
        ),
        Item(
            id="b", length=500, width=500, height=200, weight=50, quantity=1,
            stop_seq=2, pallet_group="ambient",
        ),
    ]
    pallet = _pallet()
    pallet.tare_weight = 20
    solution = _solve(items, [pallet])

    loaded = solution.containers[0]
    assert len(loaded.pallet_instances) == 1
    assert {placement.item_id for placement in loaded.placements} == {"a", "b"}
    assert loaded.industrial_metrics["total_mass"] == pytest.approx(170)
    assert loaded.industrial_metrics["construction_total_mass"] == pytest.approx(170)


def test_non_pallet_industrial_mass_is_unchanged():
    solution = solve(SolveRequest(
        items=[Item(id="a", length=500, width=500, height=200, weight=100, quantity=2)],
        containers=[_container()],
        objective="safe_loading",
        validation_mode="industrial",
        pallet_policy="avoid",
    ))

    loaded = solution.containers[0]
    assert loaded.pallet_instances == []
    assert loaded.industrial_metrics["total_mass"] == pytest.approx(200)


def test_final_validation_rejects_pallet_overhang():
    item = Item(id="a", length=600, width=500, height=200, weight=100, quantity=1)
    request = SolveRequest(items=[item], containers=[_container()], objective="safe_loading")
    solution = Solution(containers=[LoadedContainer(
        id="c",
        pallet_instances=[PalletInstance(
            id="p#1", pallet_type_id="p", x=0, y=0, z=0,
            length=1000, width=1000, deck_height=100, tare_weight=50,
        )],
        placements=[Placement(
            item_id="a", pallet_id="p#1", x=500, y=0, z=100,
            orientation="LWH", seq=1,
        )],
    )])

    finalize_solution(request, solution)

    assert solution.status == "infeasible"
    assert any(violation.code == "PALLET_OVERHANG" for violation in solution.violations)


def _stackable_item(quantity: int) -> Item:
    # 400 高、可无限堆叠：直接堆进 2000 高的容器能摞 5 层（2000mm 满柱）。
    # 上托盘则只能码到 100 台面 + 1000 限高，且托盘块封顶，900mm 柱高作废。
    return Item(
        id="s", name="s", length=500, width=500, height=400,
        weight=5, quantity=quantity, stackable=True,
    )


def test_auto_policy_declines_pallet_block_that_wastes_the_column():
    solution = solve(SolveRequest(
        items=[_stackable_item(24)],
        pallets=[_pallet(quantity=4, max_load=1000)],
        containers=[_container()],
        objective="delivery_sequence",
        pallet_policy="auto",
    ))

    assert not solution.unpacked
    palletized = [
        p for c in solution.containers for p in c.placements if p.pallet_id is not None
    ]
    assert palletized == []


def test_prefer_policy_still_palletizes_when_the_user_asks_for_it():
    solution = solve(SolveRequest(
        items=[_stackable_item(24)],
        pallets=[_pallet(quantity=4, max_load=1000)],
        containers=[_container()],
        objective="delivery_sequence",
        pallet_policy="prefer",
    ))

    palletized = [
        p for c in solution.containers for p in c.placements if p.pallet_id is not None
    ]
    assert palletized
