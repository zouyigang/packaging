from app.core.ga import GAConfig, solve_ga
from app.core.packer import solve
from app.models.schemas import Container, Item, SolveRequest

# 小种群/少代数，保证测试快。
FAST = GAConfig(population=12, generations=8, seed=1)


def _cargo_volume(sol, item_map):
    return sum(
        item_map[p.item_id].length * item_map[p.item_id].width * item_map[p.item_id].height
        for c in sol.containers
        for p in c.placements
    )


def test_ga_perfect_fit():
    item = Item(id="a", length=50, width=50, height=50, quantity=8)
    container = Container(id="c", inner_length=100, inner_width=100, inner_height=100,
                          max_payload=10000, quantity=1)
    sol = solve_ga(SolveRequest(items=[item], containers=[container]), FAST)
    assert len(sol.containers[0].placements) == 8
    assert sol.unpacked == []


def test_ga_not_worse_than_default():
    # GA 种群植入了默认顺序个体，结果体积不应劣于默认 solve。
    items = [
        Item(id="a", length=600, width=400, height=400, quantity=6),
        Item(id="b", length=400, width=300, height=300, quantity=10),
        Item(id="c", length=250, width=250, height=250, quantity=12),
    ]
    container = Container(id="x", inner_length=2000, inner_width=1200, inner_height=1200,
                          max_payload=100000, quantity=1)
    req = SolveRequest(items=items, containers=[container])
    item_map = {i.id: i for i in items}

    base = solve(req)
    ga = solve_ga(req, FAST)
    assert _cargo_volume(ga, item_map) >= _cargo_volume(base, item_map) - 1e-9


def test_ga_deterministic_with_seed():
    items = [Item(id="a", length=300, width=200, height=200, quantity=20)]
    container = Container(id="c", inner_length=1000, inner_width=800, inner_height=600,
                          max_payload=100000, quantity=2)
    req = SolveRequest(items=items, containers=[container])
    s1 = solve_ga(req, GAConfig(population=10, generations=5, seed=42))
    s2 = solve_ga(req, GAConfig(population=10, generations=5, seed=42))
    coords1 = [(p.item_id, p.x, p.y, p.z, p.seq) for c in s1.containers for p in c.placements]
    coords2 = [(p.item_id, p.x, p.y, p.z, p.seq) for c in s2.containers for p in c.placements]
    assert coords1 == coords2


def test_ga_empty_request():
    sol = solve_ga(SolveRequest(items=[], containers=[]), FAST)
    assert sol.containers == []
    assert sol.unpacked == []


def test_ga_reports_performance_metrics():
    item = Item(id="a", length=50, width=50, height=50, quantity=8)
    container = Container(
        id="c",
        inner_length=100,
        inner_width=100,
        inner_height=100,
        max_payload=10000,
        quantity=1,
    )
    sol = solve_ga(SolveRequest(items=[item], containers=[container]), FAST)
    assert sol.performance is not None
    assert sol.performance.runtime_ms >= 0
    assert "ga_initial_population" in sol.performance.stages_ms
    assert "ga_generation_1" in sol.performance.stages_ms
    assert sol.performance.counters["ga_decode_cache_hits"] > 0
    assert sol.performance.counters["ga_decode_cache_misses"] > 0


def test_ga_speed_profiles_scale_budget():
    fast = GAConfig.for_speed("fast", seed=1)
    standard = GAConfig.for_speed("standard", seed=1)
    fine = GAConfig.for_speed("fine", seed=1)

    assert fast.population < standard.population < fine.population
    assert fast.generations < standard.generations < fine.generations
    assert fast.early_stop_rounds < standard.early_stop_rounds < fine.early_stop_rounds
    assert standard.seed == 1


def test_ga_early_stop_reports_completed_generations():
    item = Item(id="a", length=50, width=50, height=50, quantity=8)
    container = Container(
        id="c",
        inner_length=100,
        inner_width=100,
        inner_height=100,
        max_payload=10000,
        quantity=1,
    )
    cfg = GAConfig(population=8, generations=20, seed=1, early_stop_rounds=1)
    sol = solve_ga(SolveRequest(items=[item], containers=[container]), cfg)

    assert sol.performance is not None
    assert sol.performance.counters["ga_early_stopped"] == 1
    assert sol.performance.counters["ga_generations_completed"] < cfg.generations


def test_ga_parallel_decode_matches_single_process():
    items = [
        Item(id="a", length=300, width=200, height=200, quantity=8),
        Item(id="b", length=250, width=200, height=150, quantity=8),
    ]
    container = Container(
        id="c",
        inner_length=1200,
        inner_width=800,
        inner_height=600,
        max_payload=100000,
        quantity=1,
    )
    req = SolveRequest(items=items, containers=[container], objective="advanced_score", use_ga=True)
    serial = solve_ga(req, GAConfig(population=8, generations=2, seed=9, parallel_workers=0))
    parallel = solve_ga(
        req,
        GAConfig(population=8, generations=2, seed=9, parallel_workers=2, parallel_min_population=1),
    )

    assert _placement_signature(parallel) == _placement_signature(serial)
    assert parallel.performance is not None
    assert parallel.performance.counters["ga_parallel_workers"] == 2
    assert parallel.performance.counters["ga_parallel_tasks"] > 0


def test_ga_min_containers_objective_runs():
    items = [Item(id="a", length=50, width=50, height=50, quantity=16)]
    small = Container(id="s", inner_length=100, inner_width=100, inner_height=100,
                      max_payload=10000, quantity=4)
    req = SolveRequest(items=items, containers=[small], objective="min_containers")
    sol = solve_ga(req, FAST)
    placed = sum(len(c.placements) for c in sol.containers)
    assert placed == 16
    assert sol.unpacked == []


def test_ga_advanced_score_uses_weighted_fitness_path():
    items = [
        Item(id="a", length=50, width=50, height=50, weight=10, quantity=8),
        Item(id="b", length=40, width=40, height=40, weight=2, quantity=8, stop_seq=2),
    ]
    container = Container(
        id="c",
        inner_length=200,
        inner_width=120,
        inner_height=120,
        max_payload=10000,
        quantity=1,
    )
    req = SolveRequest.model_validate({
        "items": [item.model_dump() for item in items],
        "containers": [container.model_dump()],
        "objective": "advanced_score",
        "use_ga": True,
        "advanced_weights": {
            "space_utilization": 0.3,
            "stability": 0.25,
            "palletization": 0.05,
            "balance": 0.25,
            "loading_position": 0.15,
        },
    })
    sol = solve_ga(req, FAST)
    placed = sum(len(c.placements) for c in sol.containers)
    assert placed > 0
    assert len(sol.unpacked) < sum(item.quantity for item in items)


def test_ga_returns_ranked_unique_alternatives():
    items = [
        Item(id="a", length=300, width=200, height=200, quantity=8),
        Item(id="b", length=250, width=250, height=150, quantity=8),
        Item(id="c", length=180, width=160, height=120, quantity=10),
    ]
    container = Container(
        id="c",
        inner_length=1200,
        inner_width=800,
        inner_height=700,
        max_payload=100000,
        quantity=1,
    )
    req = SolveRequest(items=items, containers=[container], objective="advanced_score", use_ga=True, candidate_count=3)
    sol = solve_ga(req, GAConfig(population=18, generations=6, seed=7))

    assert sol.evaluation is not None
    assert len(sol.alternatives) <= 2
    assert len(sol.alternatives) > 0
    assert all(alt.evaluation is not None for alt in sol.alternatives)
    assert all(alt.rank >= 2 for alt in sol.alternatives)
    assert [alt.score for alt in sol.alternatives] == sorted(
        [alt.score for alt in sol.alternatives],
        reverse=True,
    )

    signatures = {_placement_signature(sol)}
    signatures.update(_placement_signature(alt) for alt in sol.alternatives)
    assert len(signatures) == len(sol.alternatives) + 1


def _placement_signature(sol):
    return tuple(
        (ci, loaded.id, p.seq, p.item_id, p.x, p.y, p.z, p.orientation)
        for ci, loaded in enumerate(sol.containers)
        for p in loaded.placements
    )
