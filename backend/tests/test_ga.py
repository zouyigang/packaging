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


def test_ga_min_containers_objective_runs():
    items = [Item(id="a", length=50, width=50, height=50, quantity=16)]
    small = Container(id="s", inner_length=100, inner_width=100, inner_height=100,
                      max_payload=10000, quantity=4)
    req = SolveRequest(items=items, containers=[small], objective="min_containers")
    sol = solve_ga(req, FAST)
    placed = sum(len(c.placements) for c in sol.containers)
    assert placed == 16
    assert sol.unpacked == []
