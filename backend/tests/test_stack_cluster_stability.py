import pytest

from app.core.industrial_context import analyze_stack_clusters
from app.core.industrial import finalize_solution
from app.core.packer import solve
from app.models.schemas import Container, Item, LoadedContainer, Placement, Solution, SolveRequest


def _container():
    return Container(
        id="c",
        inner_length=2000,
        inner_width=2000,
        inner_height=2000,
        max_payload=10000,
        quantity=1,
        acceleration_profile={
            "longitudinal_g": 0.8,
            "transverse_g": 0.5,
            "vertical_g": 0.2,
        },
    )


def test_tall_narrow_column_is_a_risky_stack_cluster():
    loads = [((0, 0, level * 100, 100, 100, 100), 100) for level in range(4)]

    metrics = analyze_stack_clusters(_container(), loads)

    assert metrics.cluster_count == 1
    assert metrics.risky_cluster_count == 1
    assert metrics.min_tip_stability_margin < 0
    assert metrics.max_slenderness_ratio == pytest.approx(4.0)
    assert metrics.required_longitudinal_restraint_kn > 0
    assert metrics.required_transverse_restraint_kn > 0


def test_heavy_wide_base_can_stabilize_a_short_upper_stack():
    loads = [
        ((0, 0, 0, 400, 400, 100), 1000),
        ((150, 150, 100, 100, 100, 100), 10),
        ((150, 150, 200, 100, 100, 100), 10),
    ]

    metrics = analyze_stack_clusters(_container(), loads)

    assert metrics.cluster_count == 1
    assert metrics.risky_cluster_count == 0
    assert metrics.min_tip_stability_margin > 0


def test_independent_columns_are_analyzed_as_separate_clusters():
    loads = [
        ((0, 0, 0, 100, 100, 100), 100),
        ((0, 0, 100, 100, 100, 100), 100),
        ((500, 0, 0, 100, 100, 100), 100),
        ((500, 0, 100, 100, 100, 100), 100),
    ]

    metrics = analyze_stack_clusters(_container(), loads)

    assert metrics.cluster_count == 2
    assert metrics.risky_cluster_count == 2


def test_pallet_base_and_cargo_form_one_supported_cluster():
    loads = [
        ((0, 0, 0, 1200, 1000, 150), 20),
        ((100, 100, 150, 500, 400, 200), 100),
        ((100, 100, 350, 500, 400, 200), 100),
    ]

    metrics = analyze_stack_clusters(_container(), loads)

    assert metrics.cluster_count == 1
    assert metrics.max_slenderness_ratio == pytest.approx(0.55)


@pytest.mark.parametrize(
    "objective",
    ["cost_efficiency", "space_utilization", "safe_loading", "delivery_sequence"],
)
def test_stack_cluster_metric_is_common_to_every_production_strategy(objective):
    item = Item(id="a", length=100, width=100, height=100, weight=100, quantity=4)
    request = SolveRequest(items=[item], containers=[_container()], objective=objective)
    solution = Solution(containers=[LoadedContainer(id="c", placements=[
        Placement(item_id="a", x=0, y=0, z=level * 100, orientation="LWH", seq=level + 1)
        for level in range(4)
    ])])

    metrics = finalize_solution(request, solution)

    assert metrics["risky_stack_cluster_count"] == 1
    assert metrics["stack_cluster_tip_margin"] < 0
    assert solution.containers[0].industrial_metrics["stack_cluster_count"] == 1
    assert any(v.code == "STACK_CLUSTER_TIPPING_RISK" for v in solution.violations)


def _column_request(objective, restraint_mode, longitudinal=None, transverse=None):
    container = Container(
        id="column",
        inner_length=100,
        inner_width=100,
        inner_height=400,
        max_payload=10000,
        quantity=1,
        use_cost=1,
        cog_limits={
            "x_min_ratio": 0.0,
            "x_max_ratio": 1.0,
            "y_min_ratio": 0.0,
            "y_max_ratio": 1.0,
            "z_max_ratio": 1.0,
        },
        max_floor_load_kg_m2=100000,
        acceleration_profile={
            "longitudinal_g": 0.8,
            "transverse_g": 0.5,
            "vertical_g": 0.2,
        },
        default_friction_coefficient=0.4,
        restraint_mode=restraint_mode,
        longitudinal_restraint_capacity_kn=longitudinal,
        transverse_restraint_capacity_kn=transverse,
    )
    item = Item(
        id="a", length=100, width=100, height=100, weight=100, quantity=4,
        allowed_rotations=["LWH"],
    )
    return SolveRequest(
        items=[item], containers=[container], objective=objective,
        validation_mode="industrial", pallet_policy="avoid",
    )


@pytest.mark.parametrize(
    "objective",
    ["cost_efficiency", "space_utilization", "safe_loading", "delivery_sequence"],
)
def test_explicit_no_restraint_rejects_risky_cluster_for_every_strategy(objective):
    solution = solve(_column_request(objective, "none"))

    assert solution.status == "infeasible"
    assert solution.unpacked
    assert any(v.code == "STACK_CLUSTER_RESTRAINT_INSUFFICIENT" for v in solution.violations)


@pytest.mark.parametrize(
    "objective",
    ["cost_efficiency", "space_utilization", "safe_loading", "delivery_sequence"],
)
def test_rated_restraint_allows_cluster_when_both_direction_capacities_are_sufficient(objective):
    solution = solve(_column_request(objective, "rated", longitudinal=3.0, transverse=2.0))

    assert solution.status == "feasible"
    assert solution.unpacked == []
    assert solution.containers[0].industrial_metrics["required_stack_longitudinal_restraint_kn"] <= 3.0
    assert solution.containers[0].industrial_metrics["required_stack_transverse_restraint_kn"] <= 2.0
    assert not any(v.code == "STACK_CLUSTER_RESTRAINT_INSUFFICIENT" for v in solution.violations)


def test_unverified_restraint_keeps_solution_feasible_but_reports_warning():
    solution = solve(_column_request("safe_loading", "unverified"))

    assert solution.status == "feasible"
    assert any(v.code == "STACK_RESTRAINT_UNVERIFIED" for v in solution.violations)
    assert any(v.code == "STACK_CLUSTER_TIPPING_RISK" for v in solution.violations)


def test_sufficient_rated_restraint_is_accepted_after_partial_delivery():
    request = _column_request("delivery_sequence", "rated", longitudinal=3.0, transverse=2.0)
    request.items[0].quantity = 2
    request.items.append(Item(
        id="b", length=100, width=100, height=100, weight=100, quantity=2,
        allowed_rotations=["LWH"], stop_seq=2,
    ))
    solution = Solution(containers=[LoadedContainer(id="column", placements=[
        Placement(item_id="b", x=0, y=0, z=0, orientation="LWH", seq=1, stop_seq=2),
        Placement(item_id="b", x=0, y=0, z=100, orientation="LWH", seq=2, stop_seq=2),
        Placement(item_id="a", x=0, y=0, z=200, orientation="LWH", seq=3, stop_seq=1),
        Placement(item_id="a", x=0, y=0, z=300, orientation="LWH", seq=4, stop_seq=1),
    ])])

    finalize_solution(request, solution)

    assert not any(
        v.code == "POST_DROP_STACK_CLUSTER_RESTRAINT_INSUFFICIENT"
        for v in solution.violations
    )
