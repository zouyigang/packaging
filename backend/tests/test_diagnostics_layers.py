"""结果诊断的三层语义：error / warning / info，以及它们与 status 的对应关系。"""
from app.core.packer import solve
from app.models.schemas import Container, Item, SolveRequest
from scripts.benchmark_solver import _frontend_industrial_request


def _severities(solution):
    return {violation.severity for violation in solution.violations}


def test_config_notes_are_info_not_risk_warnings():
    # 「设备未申报固定能力」是配置口径说明，不要求改布局；不该和倾覆风险混为一谈。
    solution = solve(_frontend_industrial_request("safe_loading"))

    codes = {v.code: v.severity for v in solution.violations}
    assert codes["STACK_RESTRAINT_UNVERIFIED"] == "info"
    assert codes["TIPPING_RISK"] == "warning"
    assert codes["STACK_CLUSTER_TIPPING_RISK"] == "warning"


def test_feasible_with_risks_is_still_feasible_but_reports_them():
    solution = solve(_frontend_industrial_request("safe_loading"))

    assert solution.status == "feasible"  # 可以执行
    assert solution.diagnostics.error_count == 0
    assert solution.diagnostics.warning_count > 0  # 但要先绑扎支挡
    assert "风险" in solution.diagnostics.status_reason


def test_every_container_warning_can_be_traced_to_its_instance():
    # 多只容器共用同一个类型 id，只有实例下标能定位到具体是哪一只。
    solution = solve(_frontend_industrial_request("safe_loading"))
    assert len(solution.containers) >= 2

    per_container = {v.container_index for v in solution.violations if v.severity == "warning"}
    assert per_container == set(range(len(solution.containers)))


def test_identical_warnings_from_different_containers_are_not_deduped_away():
    solution = solve(_frontend_industrial_request("safe_loading"))

    tipping = [v for v in solution.violations if v.code == "TIPPING_RISK"]
    # 两只箱子各自的倾覆风险都要保留，不能因为文案相同就吞掉一条。
    assert len(tipping) == len(solution.containers)
    assert {v.container_index for v in tipping} == set(range(len(solution.containers)))


def test_unpacked_without_errors_is_partial():
    solution = solve(SolveRequest(
        items=[Item(id="a", length=100, width=100, height=100, weight=1, quantity=20)],
        containers=[Container(
            id="c", inner_length=100, inner_width=100, inner_height=100,
            max_payload=1000, quantity=1,
        )],
        objective="space_utilization",
    ))

    assert solution.status == "partial"
    assert solution.diagnostics.error_count == 0
    assert solution.diagnostics.unpacked_count == 19
    assert "余货" in solution.diagnostics.status_reason


def test_missing_industrial_input_is_an_error_and_makes_it_infeasible():
    solution = solve(SolveRequest(
        items=[Item(id="a", length=100, width=100, height=100, weight=0, quantity=1)],
        containers=[Container(
            id="c", inner_length=1000, inner_width=1000, inner_height=1000,
            max_payload=1000, quantity=1,
        )],
        objective="space_utilization",
        validation_mode="industrial",
    ))

    assert solution.status == "infeasible"
    assert "error" in _severities(solution)
    assert solution.diagnostics.error_count > 0
    assert "不可执行" in solution.diagnostics.status_reason


def test_clean_standard_solve_reports_no_risk():
    solution = solve(SolveRequest(
        items=[Item(id="a", length=50, width=50, height=50, weight=1, quantity=8)],
        containers=[Container(
            id="c", inner_length=100, inner_width=100, inner_height=100,
            max_payload=1000, quantity=1,
        )],
        objective="space_utilization",
    ))

    assert solution.status == "feasible"
    assert solution.diagnostics.error_count == 0
    assert solution.diagnostics.warning_count == 0
    assert solution.diagnostics.status_reason == "方案可执行，无风险项。"
