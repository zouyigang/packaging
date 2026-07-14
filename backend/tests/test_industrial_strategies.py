from app.core.industrial import finalize_solution
from app.core.objectives import resolve_objective
from app.core.packer import solve
from app.models.schemas import Container, Item, LoadedContainer, Pallet, Placement, Solution, SolveRequest


def _container(container_id="c", **updates):
    data = dict(
        id=container_id,
        inner_length=100,
        inner_width=100,
        inner_height=100,
        max_payload=1000,
        quantity=1,
    )
    data.update(updates)
    return Container(**data)


def test_canonical_strategy_aliases_are_resolved():
    assert resolve_objective("transport_cost") == ("cost_efficiency", "legacy_transport_cost")
    assert resolve_objective("max_utilization")[0] == "space_utilization"
    assert resolve_objective("load_stability")[0] == "safe_loading"
    assert resolve_objective("weight_balance")[0] == "safe_loading"
    assert resolve_objective("loading_efficiency")[0] == "delivery_sequence"
    assert resolve_objective("advanced_score")[0] == "custom"


def test_cost_and_space_choose_exact_fit_container():
    item = Item(id="a", length=50, width=50, height=50, weight=10, quantity=8)
    exact = _container("exact", use_cost=10)
    large = _container("large", inner_length=200, use_cost=100)

    cost = solve(SolveRequest(items=[item], containers=[large, exact], objective="cost_efficiency"))
    space = solve(SolveRequest(items=[item], containers=[large, exact], objective="space_utilization"))

    assert [loaded.id for loaded in cost.containers] == ["exact"]
    assert cost.cost_summary.total_cost == 10
    assert [loaded.id for loaded in space.containers] == ["exact"]


def test_must_load_and_priority_precede_volume():
    required = Item(id="required", length=50, width=50, height=50, quantity=1, must_load=True, priority=100)
    optional = Item(id="optional", length=50, width=50, height=50, quantity=2)
    container = _container(inner_length=50, inner_width=50, inner_height=50)

    solution = solve(SolveRequest(items=[optional, required], containers=[container], objective="space_utilization"))

    assert solution.containers[0].placements[0].item_id == "required"
    assert solution.status == "partial"


def test_unpacked_must_load_marks_solution_infeasible():
    item = Item(id="required", length=200, width=200, height=200, quantity=1, must_load=True)
    solution = solve(SolveRequest(items=[item], containers=[_container()], objective="cost_efficiency"))
    assert solution.status == "infeasible"
    assert any(v.code == "MUST_LOAD_UNPACKED" for v in solution.violations)


def test_industrial_mode_requires_equipment_parameters():
    item = Item(id="a", length=50, width=50, height=50, quantity=1)
    solution = solve(SolveRequest(
        items=[item], containers=[_container()], objective="safe_loading", validation_mode="industrial"
    ))
    assert solution.status == "infeasible"
    codes = {violation.code for violation in solution.violations}
    assert {"COG_LIMITS_REQUIRED", "FLOOR_LOAD_LIMIT_REQUIRED", "ACCELERATION_PROFILE_REQUIRED", "FRICTION_REQUIRED"} <= codes


def test_industrial_road_vehicle_curve_is_enforced():
    item = Item(id="a", length=50, width=50, height=50, weight=10, quantity=1)
    vehicle = _container(
        equipment_profile="road_vehicle",
        cog_limits={"x_min_ratio": 0, "x_max_ratio": 1, "y_min_ratio": 0, "y_max_ratio": 1, "z_max_ratio": 1},
        load_distribution_curve=[{"x_ratio": 0, "max_payload": 5}, {"x_ratio": 1, "max_payload": 5}],
        max_floor_load_kg_m2=100000,
        acceleration_profile={"longitudinal_g": 0.8, "transverse_g": 0.5, "vertical_g": 0.2},
        default_friction_coefficient=0.4,
    )
    solution = solve(SolveRequest(
        items=[item], containers=[vehicle], objective="safe_loading", validation_mode="industrial"
    ))
    assert solution.status == "infeasible"
    assert any(v.code == "LOAD_DISTRIBUTION_EXCEEDED" for v in solution.violations)


def test_valid_industrial_vehicle_returns_load_and_securing_metrics():
    item = Item(id="a", length=100, width=100, height=100, weight=10, quantity=1)
    vehicle = _container(
        equipment_profile="road_vehicle",
        cog_limits={"x_min_ratio": 0, "x_max_ratio": 1, "y_min_ratio": 0, "y_max_ratio": 1, "z_max_ratio": 1},
        load_distribution_curve=[{"x_ratio": 0, "max_payload": 1000}, {"x_ratio": 1, "max_payload": 1000}],
        max_floor_load_kg_m2=2000,
        acceleration_profile={"longitudinal_g": 0.8, "transverse_g": 0.5, "vertical_g": 0.2},
        default_friction_coefficient=0.4,
    )
    solution = solve(SolveRequest(
        items=[item], containers=[vehicle], objective="safe_loading", validation_mode="industrial"
    ))
    assert solution.status == "feasible"
    metrics = solution.containers[0].industrial_metrics
    assert metrics["max_floor_load_kg_m2"] == 1000
    assert metrics["required_securement_kn"] > 0
    assert "tip_stability_margin" in metrics


def test_floor_load_excess_is_hard_industrial_violation():
    item = Item(id="a", length=100, width=100, height=100, weight=100, quantity=1)
    container = _container(
        cog_limits={"x_min_ratio": 0, "x_max_ratio": 1, "y_min_ratio": 0, "y_max_ratio": 1, "z_max_ratio": 1},
        max_floor_load_kg_m2=5000,
        acceleration_profile={"longitudinal_g": 0.8, "transverse_g": 0.5, "vertical_g": 0.2},
        default_friction_coefficient=0.4,
    )
    solution = solve(SolveRequest(
        items=[item], containers=[container], objective="safe_loading", validation_mode="industrial"
    ))
    assert solution.status == "infeasible"
    assert any(v.code == "FLOOR_LOAD_EXCEEDED" for v in solution.violations)


def test_standard_cost_fallback_is_reported_but_remains_feasible():
    item = Item(id="a", length=50, width=50, height=50, quantity=1)
    solution = solve(SolveRequest(items=[item], containers=[_container()], objective="cost_efficiency"))
    assert solution.status == "feasible"
    assert solution.cost_summary.estimated is True
    assert any(v.code == "COST_DATA_MISSING" for v in solution.violations)


def test_compatible_same_stop_items_can_share_mixed_pallet():
    items = [
        Item(id="a", length=50, width=50, height=50, quantity=2, stop_seq=2, pallet_group="ambient"),
        Item(id="b", length=50, width=50, height=50, quantity=2, stop_seq=2, pallet_group="ambient"),
    ]
    pallet = Pallet(
        id="p", length=100, width=100, deck_height=10,
        max_stack_height=100, max_load=1000, quantity=1,
    )
    solution = solve(SolveRequest(
        items=items,
        pallets=[pallet],
        containers=[_container(inner_height=150)],
        objective="safe_loading",
        pallet_policy="prefer",
    ))
    placements = solution.containers[0].placements
    assert {placement.item_id for placement in placements} == {"a", "b"}
    assert len({placement.pallet_id for placement in placements}) == 1
    assert placements[0].pallet_id is not None


def test_delivery_strategy_reports_blocked_early_stop():
    item_a = Item(id="early", length=50, width=100, height=100, stop_seq=1)
    item_b = Item(id="late", length=50, width=100, height=100, stop_seq=2)
    container = _container(inner_length=100, loading_accesses=[{"side": "x_max"}])
    solution = Solution(containers=[LoadedContainer(id="c", placements=[
        Placement(item_id="early", x=0, y=0, z=0, orientation="LWH", seq=1, stop_seq=1),
        Placement(item_id="late", x=50, y=0, z=0, orientation="LWH", seq=2, stop_seq=2),
    ])])
    request = SolveRequest(items=[item_a, item_b], containers=[container], objective="delivery_sequence")
    finalize_solution(request, solution)
    assert solution.status == "infeasible"
    assert any(v.code == "DELIVERY_PATH_BLOCKED" for v in solution.violations)
