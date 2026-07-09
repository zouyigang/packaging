"""Run repeatable solver benchmarks and print runtime metrics.

Usage:
    python scripts/benchmark_solver.py --iterations 5
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.ga import GAConfig, solve_ga  # noqa: E402
from app.core.packer import solve  # noqa: E402
from app.models.schemas import Container, Item, LoadingAccess, Pallet, SolveRequest  # noqa: E402

ALL_ROTATIONS = ["LWH", "WLH", "LHW", "HLW", "WHL", "HWL"]
DEFAULT_BASE_ROTATIONS = ["LWH", "WLH"]
TWO_BASE_ROTATIONS = ["LWH", "WLH", "LHW", "HLW"]


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
                quantity=120,
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
                quantity=400,
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--include-frontend", action="store_true")
    parser.add_argument("--include-frontend-ga", action="store_true")
    args = parser.parse_args()

    cases = [
        ("heuristic_transport", lambda: solve(_default_request())),
        ("heuristic_cog", lambda: solve(_balanced_request())),
        ("ga_fast", lambda: solve_ga(_ga_request(), GAConfig.for_speed("fast", seed=7))),
    ]
    if args.include_frontend:
        cases.append(("frontend_default_cog", lambda: solve(_frontend_default_request("center_of_gravity"))))
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
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
