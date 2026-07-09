"""接口层测试。

环境暂无 httpx，故不走 TestClient，而是直接调用路由处理函数 + 校验 OpenAPI 模式；
等装好 httpx 可补一个基于 fastapi.testclient.TestClient 的端到端 HTTP 测试。
"""
import pytest

from app.api.routes import health, router, solve_endpoint
from app.main import app
from app.models.schemas import Container, Item, Solution, SolveRequest


def test_routes_registered():
    paths = {route.path for route in router.routes}
    assert "/solve" in paths
    assert "/health" in paths


def test_app_exposes_api_prefixed_routes():
    paths = set(app.openapi()["paths"])
    assert "/api/solve" in paths
    assert "/api/health" in paths


def test_health():
    assert health() == {"status": "ok"}


def test_solve_endpoint_returns_solution():
    req = SolveRequest(
        items=[Item(id="a", length=50, width=50, height=50, quantity=8)],
        containers=[Container(
            id="c", inner_length=100, inner_width=100, inner_height=100,
            max_payload=10000, quantity=1,
        )],
        objective="max_utilization",
    )
    sol = solve_endpoint(req)
    assert isinstance(sol, Solution)
    assert len(sol.containers) == 1
    assert len(sol.containers[0].placements) == 8
    assert sol.unpacked == []
    assert sol.alternatives == []
    assert sol.performance is not None


def test_solve_endpoint_logs_performance(caplog):
    req = SolveRequest(
        items=[Item(id="a", length=50, width=50, height=50, quantity=1)],
        containers=[Container(
            id="c", inner_length=100, inner_width=100, inner_height=100,
            max_payload=10000, quantity=1,
        )],
    )

    with caplog.at_level("INFO", logger="uvicorn.error"):
        solve_endpoint(req)

    assert "solve completed mode=heuristic" in caplog.text
    assert "runtime_ms=" in caplog.text


def test_openapi_schema_has_solve_contract():
    schema = app.openapi()
    assert "/solve" in schema["paths"]
    post = schema["paths"]["/solve"]["post"]
    # 请求体引用 SolveRequest，响应引用 Solution
    assert "requestBody" in post
    assert "200" in post["responses"]
    components = schema["components"]["schemas"]
    assert "SolveRequest" in components
    assert "Solution" in components
    assert "AdvancedWeights" in components
    assert "Evaluation" in components
    assert "ContainerEvaluation" in components
    assert "PerformanceMetrics" in components
    assert "SolutionAlternative" in components


def test_solve_endpoint_accepts_json_dict():
    # 模拟前端传入的 JSON（dict）→ Pydantic 校验通过并求解
    payload = {
        "items": [{"id": "x", "length": 100, "width": 100, "height": 100, "quantity": 1}],
        "containers": [{
            "id": "c", "inner_length": 100, "inner_width": 100, "inner_height": 100,
            "max_payload": 1000, "quantity": 1,
        }],
        "objective": "balanced",
    }
    sol = solve_endpoint(SolveRequest.model_validate(payload))
    assert len(sol.containers[0].placements) == 1
    assert sol.containers[0].placements[0].seq == 1
    assert sol.evaluation is not None


def test_solve_request_accepts_advanced_weights():
    req = SolveRequest.model_validate({
        "objective": "advanced_score",
        "advanced_weights": {
            "space_utilization": 0.2,
            "stability": 0.3,
            "palletization": 0.1,
            "balance": 0.3,
            "loading_position": 0.1,
        },
    })
    assert req.advanced_weights is not None
    assert req.advanced_weights.balance == 0.3


def test_solve_request_accepts_candidate_count():
    req = SolveRequest.model_validate({"candidate_count": 5})
    assert req.candidate_count == 5


def test_solve_request_rejects_empty_advanced_weights():
    with pytest.raises(ValueError):
        SolveRequest.model_validate({
            "objective": "advanced_score",
            "advanced_weights": {
                "space_utilization": 0,
                "stability": 0,
                "palletization": 0,
                "balance": 0,
                "loading_position": 0,
            },
        })
