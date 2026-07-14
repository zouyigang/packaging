"""多容器类型混装：开箱选择必须看「装完总共多少钱」，而不是「这一箱每元装几件」。"""
from app.core.packer import solve
from app.models.schemas import Container, Item, SolveRequest


def _request(objective="cost_efficiency"):
    # 12 件 500³（合计 1.5 m³）。
    # 大箱恰好装完 12 件，成本 300；小箱只能装 8 件，成本 190。
    # 「每元装载件数」小箱更高（8/190 = 0.042 > 12/300 = 0.040），于是旧逻辑先开小箱，
    # 剩 4 件又得再开一只小箱 → 总价 380，比直接开大箱的 300 还贵。
    return SolveRequest(
        items=[Item(id="a", length=500, width=500, height=500, weight=1, quantity=12)],
        containers=[
            Container(
                id="big", inner_length=1000, inner_width=1000, inner_height=1500,
                max_payload=10000, quantity=3, use_cost=300,
            ),
            Container(
                id="small", inner_length=1000, inner_width=1000, inner_height=1000,
                max_payload=10000, quantity=3, use_cost=190,
            ),
        ],
        objective=objective,
    )


def test_cost_strategy_does_not_open_a_cheap_container_that_cannot_finish():
    solution = solve(_request())

    assert not solution.unpacked
    assert [c.id for c in solution.containers] == ["big"]
    assert solution.cost_summary.total_cost == 300  # 而不是 190 + 190 = 380


def test_cost_strategy_still_downsizes_the_last_container():
    # 只有 8 件时大箱装得下但浪费钱，小箱刚好够——此时必须选小箱。
    request = _request()
    request.items[0].quantity = 8

    solution = solve(request)

    assert not solution.unpacked
    assert [c.id for c in solution.containers] == ["small"]
    assert solution.cost_summary.total_cost == 190


def test_single_container_type_is_unaffected():
    # 只有一种类型时没有可选项，行为与改动前一致。
    request = _request()
    request.containers = [request.containers[0]]

    solution = solve(request)

    assert not solution.unpacked
    assert [c.id for c in solution.containers] == ["big"]
