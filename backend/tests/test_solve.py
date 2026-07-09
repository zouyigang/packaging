from app.core.packer import solve
from app.models.schemas import Container, Item, SolveRequest


def _box50(qty):
    return Item(id="a", length=50, width=50, height=50, weight=10, quantity=qty)


def _cube100(qty=1, cid="c"):
    return Container(
        id=cid, inner_length=100, inner_width=100, inner_height=100,
        max_payload=1000, quantity=qty,
    )


def test_single_container_all_packed():
    req = SolveRequest(items=[_box50(8)], containers=[_cube100(1)])
    sol = solve(req)
    assert len(sol.containers) == 1
    assert len(sol.containers[0].placements) == 8
    assert sol.unpacked == []
    assert sol.containers[0].volume_utilization == 1.0


def test_solve_reports_performance_metrics():
    req = SolveRequest(items=[_box50(8)], containers=[_cube100(1)])
    sol = solve(req)
    assert sol.performance is not None
    assert sol.performance.runtime_ms >= 0
    assert "build_placeables" in sol.performance.stages_ms
    assert "find_placement" in sol.performance.stages_ms
    assert sol.performance.counters["find_placement_calls"] >= 1


def test_spills_into_second_container():
    # 16 个 50³ 需要 2 只 100³ 容器
    req = SolveRequest(items=[_box50(16)], containers=[_cube100(2)])
    sol = solve(req)
    assert len(sol.containers) == 2
    assert sum(len(c.placements) for c in sol.containers) == 16
    assert sol.unpacked == []


def test_unpacked_when_containers_exhausted():
    # 只给 1 只容器(放得下 8)，却有 10 件 → 2 件余货
    req = SolveRequest(items=[_box50(10)], containers=[_cube100(1)])
    sol = solve(req)
    assert len(sol.containers) == 1
    assert len(sol.containers[0].placements) == 8
    assert sol.unpacked == ["a", "a"]


def test_weight_utilization_reported():
    # 8 件 × 10kg = 80kg，载重上限 1000kg → 0.08
    req = SolveRequest(items=[_box50(8)], containers=[_cube100(1)])
    sol = solve(req)
    assert abs(sol.containers[0].weight_utilization - 0.08) < 1e-9


def test_min_containers_opens_bigger_first():
    small = Container(
        id="small", inner_length=50, inner_width=50, inner_height=50,
        max_payload=1000, quantity=1,
    )
    big = _cube100(1, cid="big")
    # 故意把小容器排在前面，目标应重排为大容器先开
    req = SolveRequest(
        items=[_box50(8)], containers=[small, big], objective="min_containers"
    )
    sol = solve(req)
    # 8 件全进大容器一只，小容器不使用
    assert len(sol.containers) == 1
    assert sol.containers[0].id == "big"
    assert sol.unpacked == []


def test_empty_containers_not_appended():
    # 第二只容器没用上时不应出现在结果里
    req = SolveRequest(items=[_box50(8)], containers=[_cube100(2)])
    sol = solve(req)
    assert len(sol.containers) == 1
