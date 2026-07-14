"""Run repeatable solver benchmarks and print runtime metrics.

Usage:
    python scripts/benchmark_solver.py --iterations 5
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.ga import GAConfig, solve_ga  # noqa: E402
from app.core.geometry import oriented_dims  # noqa: E402
from app.core.packer import solve  # noqa: E402
from app.models.schemas import (  # noqa: E402
    AccelerationProfile,
    CogLimits,
    Container,
    Item,
    LoadDistributionPoint,
    LoadingAccess,
    Pallet,
    SolveRequest,
)

ALL_ROTATIONS = ["LWH", "WLH", "LHW", "HLW", "WHL", "HWL"]
DEFAULT_BASE_ROTATIONS = ["LWH", "WLH"]
TWO_BASE_ROTATIONS = ["LWH", "WLH", "LHW", "HLW"]
INDUSTRIAL_STRATEGIES = (
    "cost_efficiency",
    "space_utilization",
    "safe_loading",
    "delivery_sequence",
)


def _default_request() -> SolveRequest:
    return SolveRequest(
        items=[
            Item(
                id="box-A",
                length=600,
                width=400,
                height=400,
                weight=20,
                quantity=4,
                stackable=False,
                stacking_type="not_stackable",
            ),
            Item(
                id="box-B",
                length=400,
                width=300,
                height=300,
                weight=8,
                quantity=18,
            ),
            Item(
                id="box-C",
                length=500,
                width=400,
                height=230,
                weight=10,
                quantity=24,
                stop_seq=2,
            ),
        ],
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
        objective="transport_cost",
    )


def _balanced_request() -> SolveRequest:
    request = _default_request()
    request.objective = "center_of_gravity"
    return request


def _ga_request() -> SolveRequest:
    request = _default_request()
    request.use_ga = True
    request.candidate_count = 3
    return request


def _frontend_default_request(objective: str = "center_of_gravity", use_ga: bool = False) -> SolveRequest:
    return SolveRequest(
        items=[
            Item(
                id="box-A",
                name="大箱A",
                length=600,
                width=400,
                height=400,
                weight=20,
                quantity=40,
                allowed_rotations=DEFAULT_BASE_ROTATIONS,
                stackable=False,
                stacking_type="not_stackable",
                max_load_top=0,
                category="A",
                customer_id="甲",
                stop_seq=1,
            ),
            Item(
                id="box-B",
                name="小箱B",
                length=400,
                width=300,
                height=300,
                weight=8,
                quantity=300,
                allowed_rotations=ALL_ROTATIONS,
                stackable=True,
                stacking_type="stackable",
                category="B",
                customer_id="甲",
                stop_seq=1,
            ),
            Item(
                id="box-C",
                name="新货品",
                length=500,
                width=400,
                height=230,
                weight=10,
                quantity=300,
                allowed_rotations=TWO_BASE_ROTATIONS,
                stackable=True,
                stacking_type="stackable",
                category="C",
                customer_id="乙",
                stop_seq=2,
            ),
            Item(
                id="box-D",
                name="新货品",
                length=300,
                width=200,
                height=200,
                weight=1,
                quantity=500,
                allowed_rotations=ALL_ROTATIONS,
                stackable=True,
                stacking_type="stackable",
                customer_id="乙",
                stop_seq=2,
            ),
        ],
        pallets=[
            Pallet(
                id="plt",
                name="标准托盘",
                length=1200,
                width=1000,
                tare_weight=10,
                deck_height=150,
                max_stack_height=1500,
                max_load=1000,
                quantity=4,
            )
        ],
        containers=[
            Container(
                id="cntr",
                name="20GP",
                inner_length=5900,
                inner_width=2350,
                inner_height=2390,
                max_payload=28000,
                loading_accesses=[LoadingAccess(side="x_max")],
                quantity=10,
            )
        ],
        objective=objective,
        use_ga=use_ga,
        candidate_count=3,
    )


def _industrial_strategy_request(objective: str) -> SolveRequest:
    """Small production-like case shared by all canonical strategy benchmarks."""
    return SolveRequest(
        items=[
            Item(
                id="early-heavy",
                length=600,
                width=400,
                height=300,
                weight=120,
                quantity=12,
                must_load=True,
                priority=100,
                customer_id="A",
                stop_seq=1,
            ),
            Item(
                id="late-medium",
                length=500,
                width=400,
                height=250,
                weight=90,
                quantity=16,
                customer_id="B",
                stop_seq=2,
            ),
            Item(
                id="late-small",
                length=300,
                width=250,
                height=200,
                weight=35,
                quantity=20,
                customer_id="B",
                stop_seq=2,
            ),
        ],
        containers=[
            Container(
                id="vehicle",
                inner_length=3000,
                inner_width=1600,
                inner_height=1600,
                max_payload=5000,
                quantity=2,
                use_cost=750,
                equipment_profile="generic",
                cog_limits={
                    "x_min_ratio": 0.20,
                    "x_max_ratio": 0.80,
                    "y_min_ratio": 0.20,
                    "y_max_ratio": 0.80,
                    "z_max_ratio": 0.70,
                },
                max_floor_load_kg_m2=5000,
                acceleration_profile={
                    "longitudinal_g": 0.8,
                    "transverse_g": 0.5,
                    "vertical_g": 0.2,
                },
                default_friction_coefficient=0.4,
                loading_accesses=[LoadingAccess(side="x_max")],
            )
        ],
        objective=objective,
        validation_mode="industrial",
        pallet_policy="avoid",
    )


def _frontend_industrial_request(objective: str) -> SolveRequest:
    """Production-scale industrial case using the 1,140-item frontend sample."""
    request = _frontend_default_request(objective)
    request.validation_mode = "industrial"
    request.pallet_policy = "auto"
    for pallet in request.pallets:
        pallet.handling_cost = 20
    for container in request.containers:
        container.use_cost = 2000
        container.equipment_profile = "road_vehicle"
        container.cog_limits = CogLimits(
            x_min_ratio=0.15,
            x_max_ratio=0.85,
            y_min_ratio=0.15,
            y_max_ratio=0.85,
            z_max_ratio=0.75,
        )
        container.load_distribution_curve = [
            LoadDistributionPoint(x_ratio=0.0, max_payload=container.max_payload),
            LoadDistributionPoint(x_ratio=1.0, max_payload=container.max_payload),
        ]
        container.max_floor_load_kg_m2 = 10000
        container.acceleration_profile = AccelerationProfile(
            longitudinal_g=0.8,
            transverse_g=0.5,
            vertical_g=0.2,
        )
        container.default_friction_coefficient = 0.4
    return request


def _summarize(samples: list[dict]) -> dict:
    runtimes = [sample["runtime_ms"] for sample in samples]
    stage_keys = sorted({key for sample in samples for key in sample["stages_ms"]})
    counter_keys = sorted({key for sample in samples for key in sample["counters"]})
    return {
        "runtime_ms_avg": round(mean(runtimes), 3),
        "runtime_ms_min": round(min(runtimes), 3),
        "runtime_ms_max": round(max(runtimes), 3),
        "stages_ms_avg": {
            key: round(mean(sample["stages_ms"].get(key, 0.0) for sample in samples), 3)
            for key in stage_keys
        },
        "counters_avg": {
            key: round(mean(sample["counters"].get(key, 0) for sample in samples), 3)
            for key in counter_keys
        },
    }


def _run_case(name: str, solver: Callable[[], object], iterations: int, warmups: int) -> dict:
    for _ in range(warmups):
        solver()
    samples = []
    for _ in range(iterations):
        solution = solver()
        if solution.performance is None:
            raise RuntimeError(f"{name} did not return performance metrics")
        samples.append(solution.performance.model_dump())
    return {"case": name, **_summarize(samples)}


def _solution_signature(solution) -> str:
    layout = [
        {
            "container": loaded.id,
            "placements": [
                [
                    placement.item_id,
                    placement.x,
                    placement.y,
                    placement.z,
                    placement.orientation,
                    placement.stop_seq,
                ]
                for placement in loaded.placements
            ],
        }
        for loaded in solution.containers
    ]
    payload = json.dumps(layout, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _quality_summary(request: SolveRequest, solution) -> dict:
    evaluation_metrics = solution.evaluation.metrics if solution.evaluation else {}
    loaded_count = sum(len(loaded.placements) for loaded in solution.containers)
    industrial = [loaded.industrial_metrics for loaded in solution.containers]
    error_codes = sorted({v.code for v in solution.violations if v.severity == "error"})
    item_map = {item.id: item for item in request.items}
    pallet_overhang_count = 0
    for loaded in solution.containers:
        pallet_instances = {pallet.id: pallet for pallet in loaded.pallet_instances}
        for placement in loaded.placements:
            pallet = pallet_instances.get(placement.pallet_id)
            item = item_map.get(placement.item_id)
            if pallet is None or item is None:
                continue
            dx, dy, _dz = oriented_dims(item.length, item.width, item.height, placement.orientation)
            if (
                placement.x < pallet.x - 1e-6
                or placement.y < pallet.y - 1e-6
                or placement.x + dx > pallet.x + pallet.length + 1e-6
                or placement.y + dy > pallet.y + pallet.width + 1e-6
            ):
                pallet_overhang_count += 1
    return {
        "status": solution.status,
        "loaded_count": loaded_count,
        "requested_count": sum(item.quantity for item in request.items),
        "unpacked_count": len(solution.unpacked),
        "container_count": len(solution.containers),
        "total_cost": solution.cost_summary.total_cost if solution.cost_summary else 0.0,
        "volume_utilization": evaluation_metrics.get("used_volume_utilization", 0.0),
        "stability_score": evaluation_metrics.get("stability_score", 0.0),
        "balance_score": evaluation_metrics.get("balance_score", 0.0),
        "loading_score": evaluation_metrics.get("loading_score", 0.0),
        "max_floor_load_kg_m2": max((m.get("max_floor_load_kg_m2", 0.0) for m in industrial), default=0.0),
        "min_tip_stability_margin": min((m.get("tip_stability_margin", 1.0) for m in industrial), default=1.0),
        "required_securement_kn": max((m.get("required_securement_kn", 0.0) for m in industrial), default=0.0),
        "stack_cluster_tip_margin": evaluation_metrics.get("stack_cluster_tip_margin", 1.0),
        "risky_stack_cluster_count": int(evaluation_metrics.get("risky_stack_cluster_count", 0)),
        "max_stack_cluster_slenderness": evaluation_metrics.get("max_stack_cluster_slenderness", 0.0),
        "required_stack_longitudinal_restraint_kn": evaluation_metrics.get("required_stack_longitudinal_restraint_kn", 0.0),
        "required_stack_transverse_restraint_kn": evaluation_metrics.get("required_stack_transverse_restraint_kn", 0.0),
        "pallet_overhang_count": pallet_overhang_count,
        "error_codes": error_codes,
        "layout_signature": _solution_signature(solution),
    }


def _run_strategy_case(strategy: str, iterations: int, warmups: int) -> dict:
    request = _industrial_strategy_request(strategy)
    for _ in range(warmups):
        solve(request)
    solutions = [solve(request) for _ in range(iterations)]
    signatures = {_solution_signature(solution) for solution in solutions}
    if len(signatures) != 1:
        raise RuntimeError(f"industrial_{strategy} produced non-deterministic layouts: {sorted(signatures)}")
    performance = [solution.performance.model_dump() for solution in solutions if solution.performance]
    if len(performance) != len(solutions):
        raise RuntimeError(f"industrial_{strategy} did not return performance metrics")
    return {
        "case": f"industrial_{strategy}",
        "strategy": strategy,
        "deterministic": len(solutions) > 1,
        **_quality_summary(request, solutions[-1]),
        **_summarize(performance),
    }


def _run_large_strategy_case(
    strategy: str, iterations: int, warmups: int, safety_priority: bool = False
) -> dict:
    request = _frontend_industrial_request(strategy)
    request.safety_priority = safety_priority
    label = f"{strategy}_safety_first" if safety_priority else strategy
    for _ in range(warmups):
        solve(request)
    solutions = [solve(request) for _ in range(iterations)]
    signatures = {_solution_signature(solution) for solution in solutions}
    if len(signatures) != 1:
        raise RuntimeError(f"industrial_large_{label} produced non-deterministic layouts: {sorted(signatures)}")
    performance = [solution.performance.model_dump() for solution in solutions if solution.performance]
    if len(performance) != len(solutions):
        raise RuntimeError(f"industrial_large_{label} did not return performance metrics")
    quality = _quality_summary(request, solutions[-1])
    if quality["status"] != "feasible" or quality["loaded_count"] != quality["requested_count"]:
        raise RuntimeError(
            f"industrial_large_{label} failed completion gate: "
            f"status={quality['status']} loaded={quality['loaded_count']}/{quality['requested_count']}"
        )
    if quality["error_codes"]:
        raise RuntimeError(f"industrial_large_{label} returned industrial errors: {quality['error_codes']}")
    if quality["pallet_overhang_count"]:
        raise RuntimeError(
            f"industrial_large_{label} returned {quality['pallet_overhang_count']} pallet overhangs"
        )
    if quality["container_count"] > 3:
        raise RuntimeError(
            f"industrial_large_{label} exceeded container gate: {quality['container_count']} > 3"
        )
    return {
        "case": f"industrial_large_{label}",
        "strategy": strategy,
        "safety_priority": safety_priority,
        "scale": "frontend_1140_items",
        "deterministic": len(solutions) > 1,
        **quality,
        **_summarize(performance),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--include-frontend", action="store_true")
    parser.add_argument("--include-frontend-all", action="store_true")
    parser.add_argument("--include-frontend-ga", action="store_true")
    parser.add_argument(
        "--industrial-strategies",
        action="store_true",
        help="compare the four canonical production strategies on one industrial case",
    )
    parser.add_argument(
        "--industrial-large",
        action="store_true",
        help="compare the four production strategies on the 1,140-item frontend-scale industrial case",
    )
    args = parser.parse_args()

    cases = [
        ("heuristic_transport", lambda: solve(_default_request())),
        ("heuristic_cog", lambda: solve(_balanced_request())),
        ("ga_fast", lambda: solve_ga(_ga_request(), GAConfig.for_speed("fast", seed=7))),
    ]
    if args.include_frontend:
        cases.append(("frontend_default_cog", lambda: solve(_frontend_default_request("center_of_gravity"))))
    if args.include_frontend_all:
        cases.extend([
            ("frontend_default_cost", lambda: solve(_frontend_default_request("cost_efficiency"))),
            ("frontend_default_space", lambda: solve(_frontend_default_request("space_utilization"))),
            ("frontend_default_safe", lambda: solve(_frontend_default_request("safe_loading"))),
            ("frontend_default_delivery", lambda: solve(_frontend_default_request("delivery_sequence"))),
            ("frontend_default_custom", lambda: solve(_frontend_default_request("custom"))),
        ])
    if args.include_frontend_ga:
        cases.append((
            "frontend_default_ga_fast",
            lambda: solve_ga(
                _frontend_default_request("center_of_gravity", use_ga=True),
                GAConfig.for_speed("fast", seed=7),
            ),
        ))
    results = [
        _run_case(name, solver, max(1, args.iterations), max(0, args.warmups))
        for name, solver in cases
    ]
    if args.industrial_strategies:
        results.extend(
            _run_strategy_case(strategy, max(1, args.iterations), max(0, args.warmups))
            for strategy in INDUSTRIAL_STRATEGIES
        )
    if args.industrial_large:
        results.extend(
            _run_large_strategy_case(strategy, max(1, args.iterations), max(0, args.warmups))
            for strategy in INDUSTRIAL_STRATEGIES
        )
        # 安全优先是 safe_loading 的第二条路径（用容器换低固定力），一并纳入门禁。
        results.append(
            _run_large_strategy_case(
                "safe_loading", max(1, args.iterations), max(0, args.warmups),
                safety_priority=True,
            )
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
