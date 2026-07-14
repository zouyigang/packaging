import pytest

from app.core.ga import GAConfig, solve_ga
from app.core.packer import solve
from app.models.schemas import Container, Item, SolveRequest
from scripts.benchmark_solver import (
    INDUSTRIAL_STRATEGIES,
    QUALITY_BASELINES,
    QUALITY_TOLERANCES,
    _check_quality_gate,
    _frontend_industrial_request,
    _industrial_strategy_request,
    _quality_summary,
    _solution_signature,
)


def _run_strategy(strategy: str):
    request = _industrial_strategy_request(strategy)
    solution = solve(request)
    return request, solution, _quality_summary(request, solution)


def test_industrial_strategy_baseline_is_complete_and_deterministic():
    for strategy in INDUSTRIAL_STRATEGIES:
        request = _industrial_strategy_request(strategy)
        first = solve(request)
        second = solve(request)

        assert first.status == "feasible"
        assert len(first.unpacked) == 0
        assert sum(len(loaded.placements) for loaded in first.containers) == sum(
            item.quantity for item in request.items
        )
        assert _solution_signature(first) == _solution_signature(second)


def test_safe_and_delivery_strategies_improve_their_primary_baseline_metric():
    _cost_request, cost, cost_summary = _run_strategy("cost_efficiency")
    _safe_request, safe, safe_summary = _run_strategy("safe_loading")
    _delivery_request, delivery, delivery_summary = _run_strategy("delivery_sequence")

    assert min(safe_summary["stability_score"], safe_summary["balance_score"]) >= min(
        cost_summary["stability_score"], cost_summary["balance_score"]
    )
    assert delivery_summary["loading_score"] > cost_summary["loading_score"]
    assert _solution_signature(safe) != _solution_signature(cost)
    assert _solution_signature(delivery) != _solution_signature(cost)


def test_industrial_observation_is_enabled_without_changing_final_metrics():
    request = _industrial_strategy_request("cost_efficiency")
    solution = solve(request)
    counters = solution.performance.counters

    assert counters["industrial_preview_calls"] > 0
    assert counters["industrial_commits"] == sum(len(loaded.placements) for loaded in solution.containers)
    for loaded in solution.containers:
        metrics = loaded.industrial_metrics
        assert metrics["construction_cog_x_ratio"] == pytest.approx(metrics["cog_x_ratio"])
        assert metrics["construction_cog_y_ratio"] == pytest.approx(metrics["cog_y_ratio"])
        assert metrics["construction_cog_z_ratio"] == pytest.approx(metrics["cog_z_ratio"])
        assert metrics["construction_max_floor_load_kg_m2"] == pytest.approx(metrics["max_floor_load_kg_m2"])


def test_standard_mode_does_not_pay_for_industrial_candidate_observation():
    solution = solve(SolveRequest(
        items=[Item(id="a", length=50, width=50, height=50, weight=10, quantity=2)],
        containers=[Container(
            id="c", inner_length=100, inner_width=100, inner_height=100,
            max_payload=1000, quantity=1,
        )],
        objective="cost_efficiency",
    ))

    assert not any(key.startswith("industrial_preview") for key in solution.performance.counters)
    assert "industrial_commits" not in solution.performance.counters


def test_ga_decoder_preserves_industrial_observation_mode():
    request = _industrial_strategy_request("safe_loading")
    request.use_ga = True
    request.candidate_count = 1

    solution = solve_ga(request, GAConfig(population=4, generations=1, parallel_workers=0))

    assert solution.performance.counters["industrial_preview_calls"] > 0
    assert solution.performance.counters["industrial_commits"] > 0


def test_large_industrial_benchmark_matches_frontend_scale_and_has_required_equipment_data():
    request = _frontend_industrial_request("safe_loading")

    assert sum(item.quantity for item in request.items) == 1140
    assert request.validation_mode == "industrial"
    assert request.pallet_policy == "auto"
    assert all(pallet.handling_cost is not None for pallet in request.pallets)
    assert all(container.use_cost is not None for container in request.containers)
    assert all(container.cog_limits is not None for container in request.containers)
    assert all(len(container.load_distribution_curve) >= 2 for container in request.containers)
    assert all(container.max_floor_load_kg_m2 is not None for container in request.containers)
    assert all(container.acceleration_profile is not None for container in request.containers)
    assert all(container.default_friction_coefficient is not None for container in request.containers)


def test_quality_gate_passes_on_the_current_baseline():
    for strategy in INDUSTRIAL_STRATEGIES:
        request = _industrial_strategy_request(strategy)
        quality = _quality_summary(request, solve(request))
        assert _check_quality_gate(f"industrial_{strategy}", quality) == []


def test_quality_gate_flags_a_degraded_metric_in_each_direction():
    request = _industrial_strategy_request("safe_loading")
    quality = _quality_summary(request, solve(request))

    # 越小越好的指标变大：多用一个容器（正是曾经靠人工比对才发现的那类回归）。
    worse = dict(quality, container_count=quality["container_count"] + 1)
    breaches = _check_quality_gate("industrial_safe_loading", worse)
    assert any("container_count" in breach for breach in breaches)

    # 越大越好的指标变小：体积利用率掉一半。
    worse = dict(quality, volume_utilization=quality["volume_utilization"] / 2)
    breaches = _check_quality_gate("industrial_safe_loading", worse)
    assert any("volume_utilization" in breach for breach in breaches)

    # 固定力是纵向 + 横向之和，两项任一变差都要报。
    worse = dict(quality, required_stack_longitudinal_restraint_kn=99.0)
    breaches = _check_quality_gate("industrial_safe_loading", worse)
    assert any("required_restraint_kn" in breach for breach in breaches)


def test_quality_gate_tolerates_noise_but_not_a_real_slide():
    request = _industrial_strategy_request("cost_efficiency")
    quality = _quality_summary(request, solve(request))

    within = dict(quality, stability_score=quality["stability_score"] * 0.99)
    assert _check_quality_gate("industrial_cost_efficiency", within) == []

    beyond = dict(quality, stability_score=quality["stability_score"] * 0.90)
    assert _check_quality_gate("industrial_cost_efficiency", beyond) != []


def test_every_benchmark_case_has_a_quality_baseline():
    expected = {f"industrial_{strategy}" for strategy in INDUSTRIAL_STRATEGIES}
    expected |= {f"industrial_large_{strategy}" for strategy in INDUSTRIAL_STRATEGIES}
    expected.add("industrial_large_safe_loading_safety_first")

    assert expected == set(QUALITY_BASELINES)
    # 每条基线只能引用有容差定义的指标，否则会被 _check_quality_gate 静默跳过。
    for metrics in QUALITY_BASELINES.values():
        assert set(metrics) <= set(QUALITY_TOLERANCES)
