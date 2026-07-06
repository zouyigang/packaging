from app.core.evaluator import evaluate_solution
from app.core.packer import solve
from app.models.schemas import Container, Item, Placement, Solution, SolveRequest, LoadedContainer


def _container(**patch):
    data = {
        "id": "c",
        "inner_length": 100,
        "inner_width": 100,
        "inner_height": 100,
        "max_payload": 10000,
        "quantity": 1,
    }
    data.update(patch)
    return Container(**data)


def _item(**patch):
    data = {
        "id": "a",
        "length": 50,
        "width": 50,
        "height": 50,
        "weight": 10,
        "quantity": 1,
    }
    data.update(patch)
    return Item(**data)


def _solution(placements, unpacked=None):
    return Solution(
        containers=[LoadedContainer(id="c", placements=placements)],
        unpacked=unpacked or [],
    )


def _two_container_solution(first, second):
    return Solution(
        containers=[
            LoadedContainer(id="c", placements=first),
            LoadedContainer(id="c", placements=second),
        ],
    )


def test_solve_attaches_evaluation():
    req = SolveRequest(items=[_item(quantity=8)], containers=[_container()], objective="transport_cost")
    sol = solve(req)
    assert sol.evaluation is not None
    assert sol.evaluation.objective == "transport_cost"
    assert 0 <= sol.evaluation.score <= 100
    assert "loaded_completion" in sol.evaluation.metrics
    assert len(sol.evaluation.containers) == len(sol.containers)
    assert "loading_score" in sol.evaluation.containers[0].metrics


def test_transport_cost_penalizes_unpacked_volume():
    item = _item(quantity=2)
    container = _container()
    req = SolveRequest(items=[item], containers=[container], objective="transport_cost")
    placed = Placement(item_id="a", x=0, y=0, z=0, orientation="LWH", seq=1)

    full = evaluate_solution(req, _solution([placed, placed]))
    partial = evaluate_solution(req, _solution([placed], unpacked=["a"]))

    assert full.score > partial.score
    assert partial.metrics["unpacked_penalty"] > 0


def test_stability_scores_low_wide_load_higher_than_high_load():
    item = _item(length=80, width=80, height=20)
    container = _container()
    req = SolveRequest(items=[item], containers=[container], objective="load_stability")
    low = Placement(item_id="a", x=0, y=0, z=0, orientation="LWH", seq=1)
    high = Placement(item_id="a", x=0, y=0, z=70, orientation="LWH", seq=1)

    low_eval = evaluate_solution(req, _solution([low]))
    high_eval = evaluate_solution(req, _solution([high]))

    assert low_eval.metrics["stability_score"] > high_eval.metrics["stability_score"]
    assert low_eval.score > high_eval.score


def test_balance_strategy_scores_centered_load_higher_than_corner_load():
    item = _item(length=20, width=20, height=20)
    container = _container()
    req = SolveRequest(items=[item], containers=[container], objective="weight_balance")
    centered = Placement(item_id="a", x=40, y=40, z=0, orientation="LWH", seq=1)
    corner = Placement(item_id="a", x=0, y=0, z=0, orientation="LWH", seq=1)

    centered_eval = evaluate_solution(req, _solution([centered]))
    corner_eval = evaluate_solution(req, _solution([corner]))

    assert centered_eval.metrics["balance_score"] > corner_eval.metrics["balance_score"]
    assert centered_eval.score > corner_eval.score


def test_balance_score_uses_physical_container_instances_not_id_groups():
    item = _item(length=20, width=20, height=20, quantity=2)
    container = _container(quantity=2)
    req = SolveRequest(items=[item], containers=[container], objective="weight_balance")
    centered_each_box = _two_container_solution(
        [Placement(item_id="a", x=40, y=40, z=0, orientation="LWH", seq=1)],
        [Placement(item_id="a", x=40, y=40, z=0, orientation="LWH", seq=1)],
    )
    opposite_corners = _two_container_solution(
        [Placement(item_id="a", x=0, y=0, z=0, orientation="LWH", seq=1)],
        [Placement(item_id="a", x=80, y=80, z=0, orientation="LWH", seq=1)],
    )

    centered_eval = evaluate_solution(req, centered_each_box)
    corner_eval = evaluate_solution(req, opposite_corners)

    assert centered_eval.metrics["balance_score"] == 1
    assert corner_eval.metrics["balance_score"] < centered_eval.metrics["balance_score"]


def test_loading_strategy_scores_stop_depth_match_higher_than_reversed():
    item_a = _item(id="a", stop_seq=1)
    item_b = _item(id="b", stop_seq=2)
    container = _container()
    req = SolveRequest(items=[item_a, item_b], containers=[container], objective="loading_efficiency")
    good = _solution([
        Placement(item_id="a", stop_seq=1, x=50, y=0, z=0, orientation="LWH", seq=1),
        Placement(item_id="b", stop_seq=2, x=0, y=50, z=0, orientation="LWH", seq=2),
    ])
    bad = _solution([
        Placement(item_id="a", stop_seq=1, x=0, y=0, z=0, orientation="LWH", seq=1),
        Placement(item_id="b", stop_seq=2, x=50, y=50, z=0, orientation="LWH", seq=2),
    ])

    good_eval = evaluate_solution(req, good)
    bad_eval = evaluate_solution(req, bad)

    assert good_eval.metrics["loading_score"] > bad_eval.metrics["loading_score"]
    assert good_eval.score > bad_eval.score


def test_advanced_weights_change_score_direction():
    item = _item(length=20, width=20, height=20)
    container = _container()
    corner_solution = _solution([Placement(item_id="a", x=0, y=0, z=0, orientation="LWH", seq=1)])
    space_req = SolveRequest.model_validate({
        "items": [item.model_dump()],
        "containers": [container.model_dump()],
        "objective": "advanced_score",
        "advanced_weights": {
            "space_utilization": 1,
            "stability": 0,
            "palletization": 0,
            "balance": 0,
            "loading_position": 0,
        },
    })
    balance_req = SolveRequest.model_validate({
        "items": [item.model_dump()],
        "containers": [container.model_dump()],
        "objective": "advanced_score",
        "advanced_weights": {
            "space_utilization": 0,
            "stability": 0,
            "palletization": 0,
            "balance": 1,
            "loading_position": 0,
        },
    })

    assert evaluate_solution(space_req, corner_solution).score > evaluate_solution(balance_req, corner_solution).score
