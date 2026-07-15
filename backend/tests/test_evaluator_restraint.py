"""工业模式下 safe_loading 评分把「堆垛簇所需固定力」计入排序的单元测试。

背景见 docs/ga-industrial-restraint-experiment.md「评分器对固定力失明」缺口：
两个稳定性/重心相近但固定力悬殊的解，旧评分器给相同分；补 restraint_score 后
低固定力解应严格更高，且仅在 validation_mode=industrial 时生效。
"""
import pytest

from app.core.evaluator import (
    _SAFE_LOADING_INDUSTRIAL_WEIGHTS,
    _STRATEGY_WEIGHTS,
    _weighted_score,
    evaluate_solution,
)
from app.core.industrial import finalize_solution
from app.models.schemas import (
    AccelerationProfile,
    Container,
    Item,
    LoadedContainer,
    Placement,
    Solution,
    SolveRequest,
)


def _container(**patch):
    data = {
        "id": "c",
        "inner_length": 1200,
        "inner_width": 1000,
        "inner_height": 2400,
        "max_payload": 20000,
        "quantity": 1,
        "acceleration_profile": AccelerationProfile(longitudinal_g=0.8, transverse_g=0.5),
    }
    data.update(patch)
    return Container(**data)


def _item():
    # 底面 400×400、每件高 400，可竖直堆成细高簇。
    return Item(id="a", length=400, width=400, height=400, weight=200, quantity=6)


def _tall_solution():
    # 6 件竖直堆成一柱：高重心 + 大力臂 → 所需固定力高。
    return Solution(containers=[LoadedContainer(id="c", placements=[
        Placement(item_id="a", x=0, y=0, z=level * 400, orientation="LWH", seq=level + 1)
        for level in range(6)
    ])])


def _flat_solution():
    # 6 件平铺成一层：无堆叠簇 → 所需固定力为 0。
    return Solution(containers=[LoadedContainer(id="c", placements=[
        Placement(item_id="a", x=col * 400, y=row * 400, z=0, orientation="LWH", seq=col + row + 1)
        for row in range(2) for col in range(3)
    ])])


def _request(validation_mode: str) -> SolveRequest:
    return SolveRequest(
        items=[_item()],
        containers=[_container()],
        objective="safe_loading",
        validation_mode=validation_mode,
    )


def _evaluate(validation_mode: str, solution: Solution):
    request = _request(validation_mode)
    # evaluate_solution 读的是 finalize 已挂上的 industrial_metrics。
    finalize_solution(request, solution, [])
    return evaluate_solution(request, solution)


def test_industrial_safe_loading_penalizes_high_restraint():
    """工业模式：高固定力(细高柱)评分严格低于低固定力(平铺)。"""
    tall = _evaluate("industrial", _tall_solution())
    flat = _evaluate("industrial", _flat_solution())
    assert "restraint_score" in tall.metrics
    assert tall.metrics["restraint_score"] < flat.metrics["restraint_score"]
    assert tall.score < flat.score


def test_standard_mode_does_not_wire_restraint_into_score():
    """标准模式沿用不含 restraint_score 的旧权重，评分与固定力维度解耦。

    restraint_score 仍会被算出并作为信息挂进 metrics（它由容器加速度 profile 决定、
    与 validation_mode 无关），但标准 profile 不引用它，故标准模式评分等于「仅用旧权重」
    对同一批 metrics 的加权分——逐位复刻改动前行为。
    """
    assert "restraint_score" not in _STRATEGY_WEIGHTS["safe_loading"]
    assert "restraint_score" in _SAFE_LOADING_INDUSTRIAL_WEIGHTS

    evaluation = _evaluate("standard", _tall_solution())
    # metrics 仍带信息性的 restraint_score（细高柱远小于 1）。
    assert evaluation.metrics["restraint_score"] < 1.0
    # 但标准模式评分完全由旧权重决定：用存储 metrics 复算应与呈现分一致（四舍五入到 1 位）。
    expected = round(_weighted_score(evaluation.metrics, _STRATEGY_WEIGHTS["safe_loading"]), 1)
    assert evaluation.score == pytest.approx(expected, abs=0.1)


def test_restraint_score_only_wired_for_safe_loading():
    """其他策略即便工业模式，profile 不含 restraint_score，评分不受其影响。"""
    request = SolveRequest(
        items=[_item()],
        containers=[_container()],
        objective="cost_efficiency",
        validation_mode="industrial",
    )
    tall = _tall_solution()
    flat = _flat_solution()
    finalize_solution(request, tall, [])
    finalize_solution(request, flat, [])
    # cost_efficiency profile 无 restraint_score 权重，两解在该维度上无差异贡献；
    # 装载量/成本相同(同一批货、同一只容器)，故评分应相等。
    assert evaluate_solution(request, tall).score == pytest.approx(
        evaluate_solution(request, flat).score
    )
