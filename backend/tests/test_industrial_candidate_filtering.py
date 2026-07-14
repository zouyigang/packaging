from app.core.industrial_context import IndustrialLoadMetrics
from app.core.packer import _cog_can_reach_limits, _single_placeable, solve
from app.models.schemas import Container, Item, Pallet, SolveRequest


def _container(container_id="c", **updates):
    data = dict(
        id=container_id,
        inner_length=1000,
        inner_width=1000,
        inner_height=1000,
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
    data.update(updates)
    return Container(**data)


def _request(item, containers, **updates):
    data = dict(
        items=[item],
        containers=containers,
        objective="safe_loading",
        validation_mode="industrial",
        pallet_policy="avoid",
    )
    data.update(updates)
    return SolveRequest(**data)


def test_cog_rejection_uses_an_alternative_balanced_position():
    item = Item(id="a", length=50, width=100, height=100, weight=10, quantity=1)
    container = _container(
        inner_length=200,
        inner_width=100,
        inner_height=100,
        cog_limits={
            "x_min_ratio": 0.45,
            "x_max_ratio": 0.55,
            "y_min_ratio": 0.0,
            "y_max_ratio": 1.0,
            "z_max_ratio": 1.0,
        },
    )

    solution = solve(_request(item, [container]))

    assert solution.status == "feasible"
    assert solution.containers[0].industrial_metrics["cog_x_ratio"] == 0.5
    assert solution.performance.counters["industrial_preview_cog_exceeded"] > 0


def test_floor_load_rejection_falls_through_to_next_container():
    item = Item(id="a", length=100, width=100, height=100, weight=100, quantity=1)
    weak = _container("weak", max_floor_load_kg_m2=5000)
    strong = _container("strong", max_floor_load_kg_m2=20000)

    solution = solve(_request(item, [weak, strong]))

    assert solution.status == "feasible"
    assert [loaded.id for loaded in solution.containers] == ["strong"]
    assert solution.performance.counters["industrial_preview_floor_load_exceeded"] > 0
    assert not any(v.severity == "error" for v in solution.violations)


def test_no_feasible_floor_candidate_returns_specific_error():
    item = Item(id="a", length=100, width=100, height=100, weight=100, quantity=1)
    solution = solve(_request(item, [_container(max_floor_load_kg_m2=5000)]))

    assert solution.status == "infeasible"
    assert solution.unpacked == ["a"]
    assert any(v.code == "FLOOR_LOAD_EXCEEDED" for v in solution.violations)


def test_pallet_transaction_preview_includes_tare_and_full_footprint():
    item = Item(id="a", length=500, width=500, height=200, weight=100, quantity=1)
    pallet = Pallet(
        id="p",
        length=1000,
        width=1000,
        deck_height=100,
        tare_weight=50,
        max_stack_height=1000,
        max_load=1000,
        quantity=1,
    )
    container = _container(max_floor_load_kg_m2=140)
    solution = solve(_request(
        item,
        [container],
        pallets=[pallet],
        pallet_policy="required",
    ))

    assert solution.status == "infeasible"
    assert solution.unpacked == ["a"]
    assert any(v.code == "FLOOR_LOAD_EXCEEDED" for v in solution.violations)


def test_cog_reachability_keeps_a_temporary_offset_that_remaining_mass_can_correct():
    container = _container(use_cost=1, cog_limits={
        "x_min_ratio": 0.45,
        "x_max_ratio": 0.55,
        "y_min_ratio": 0.45,
        "y_max_ratio": 0.55,
        "z_max_ratio": 1.0,
    })
    current = IndustrialLoadMetrics(
        total_mass=100,
        cog_x_ratio=0.1,
        cog_y_ratio=0.1,
        cog_z_ratio=0.1,
    )
    remaining = [_single_placeable(Item(
        id="balance", length=100, width=100, height=100, weight=1000, quantity=1,
    ))]

    assert _cog_can_reach_limits(current, remaining, container) is True


def test_cog_reachability_rejects_final_offset_when_no_correcting_mass_remains():
    container = _container(cog_limits={
        "x_min_ratio": 0.45,
        "x_max_ratio": 0.55,
        "y_min_ratio": 0.45,
        "y_max_ratio": 0.55,
        "z_max_ratio": 1.0,
    })
    current = IndustrialLoadMetrics(
        total_mass=100,
        cog_x_ratio=0.1,
        cog_y_ratio=0.1,
        cog_z_ratio=0.1,
    )

    assert _cog_can_reach_limits(current, [], container) is False


def test_second_pass_accepts_tall_light_load_when_later_heavy_load_can_lower_final_cog():
    items = [
        Item(
            id="tall", length=500, width=500, height=800, weight=100, quantity=1,
            allowed_rotations=["LWH"],
        ),
        Item(
            id="low-heavy", length=500, width=500, height=100, weight=1000, quantity=1,
            allowed_rotations=["LWH"],
        ),
    ]
    container = _container(use_cost=1, cog_limits={
        "x_min_ratio": 0.0,
        "x_max_ratio": 1.0,
        "y_min_ratio": 0.0,
        "y_max_ratio": 1.0,
        "z_max_ratio": 0.30,
    })
    solution = solve(SolveRequest(
        items=items,
        containers=[container],
        objective="cost_efficiency",
        validation_mode="industrial",
        pallet_policy="avoid",
    ))

    assert solution.status == "feasible"
    assert solution.unpacked == []
    assert solution.containers[0].industrial_metrics["cog_z_ratio"] <= 0.30
    assert solution.performance.counters["industrial_cog_recovery_passes"] > 0
    assert solution.performance.counters["industrial_preview_cog_recoverable"] > 0
