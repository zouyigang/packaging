"""safe_loading 策略把「堆垛簇所需固定力」并入 GA fitness 的单元测试。

实验性改动（仅 safe_loading，仅工业模式），见 docs/industrial-strategies.md 与
计划 ga-encapsulated-parasol。这里直接对 _make_fitness 做隔离测试，避免被
「高堆本身稳定性罚项更大」这类混淆项干扰——精确断言罚项等于
权重 × (纵向 + 横向) 所需固定力。
"""
import pytest

import app.core.ga as ga
from app.core.ga import _make_fitness
from app.core.industrial_context import analyze_stack_clusters
from app.models.schemas import Container, Item, LoadedContainer, Placement, Solution

# 罚项默认关（opt-in）；测试里显式打开到已知权重，断言与默认值无关。
TEST_WEIGHT = 20.0


@pytest.fixture(autouse=True)
def _enable_restraint_penalty(monkeypatch):
    monkeypatch.setattr(ga, "_SAFE_LOADING_RESTRAINT_WEIGHT", TEST_WEIGHT)


def _container():
    return Container(
        id="c",
        inner_length=2000,
        inner_width=2000,
        inner_height=2000,
        max_payload=100000,
        quantity=1,
        acceleration_profile={
            "longitudinal_g": 0.8,
            "transverse_g": 0.5,
            "vertical_g": 0.2,
        },
    )


def _item():
    return Item(id="a", length=100, width=100, height=100, weight=100, quantity=4)


def _tall_solution():
    # 4 层竖直堆叠 = 一个细高危险簇，需要正的固定力。
    return Solution(containers=[LoadedContainer(id="c", placements=[
        Placement(item_id="a", x=0, y=0, z=level * 100, orientation="LWH", seq=level + 1)
        for level in range(4)
    ])])


def _flat_solution():
    # 4 件平铺、互不堆叠 = 无堆垛簇，所需固定力为 0。
    return Solution(containers=[LoadedContainer(id="c", placements=[
        Placement(item_id="a", x=col * 200, y=0, z=0, orientation="LWH", seq=col + 1)
        for col in range(4)
    ])])


def _maps():
    return {"a": _item()}, {"c": _container()}


def _fitness(objective, industrial):
    item_map, container_map = _maps()
    return _make_fitness(objective, item_map, container_map, industrial=industrial)


def test_restraint_penalty_equals_weight_times_required_force():
    """工业模式下 safe_loading 对危险簇的罚项 = 权重 × (纵+横) 所需固定力。"""
    tall = _tall_solution()
    cluster = analyze_stack_clusters(_container(), [
        ((0, 0, level * 100, 100, 100, 100), 100) for level in range(4)
    ])
    expected = TEST_WEIGHT * (
        cluster.required_longitudinal_restraint_kn
        + cluster.required_transverse_restraint_kn
    )
    assert expected > 0.0

    industrial = _fitness("safe_loading", industrial=True)(tall)
    standard = _fitness("safe_loading", industrial=False)(tall)
    # 唯一差别就是罚项；工业模式严格更低。
    assert standard - industrial == pytest.approx(expected)


def test_flat_layout_incurs_no_restraint_penalty():
    """无堆垛簇的平铺解，工业与非工业 fitness 相等（罚项为 0）。"""
    flat = _flat_solution()
    industrial = _fitness("safe_loading", industrial=True)(flat)
    standard = _fitness("safe_loading", industrial=False)(flat)
    assert industrial == pytest.approx(standard)


def test_penalty_prefers_lower_restraint_layout():
    """在 safe_loading 工业 fitness 下，低固定力布局评分高于高固定力布局。"""
    fitness = _fitness("safe_loading", industrial=True)
    assert fitness(_flat_solution()) > fitness(_tall_solution())


@pytest.mark.parametrize(
    "objective",
    ["cost_efficiency", "space_utilization", "delivery_sequence", "custom"],
)
def test_other_strategies_ignore_industrial_flag(objective):
    """除 safe_loading 外的四策略 fitness 与 industrial 开关无关，行为逐位不变。"""
    tall = _tall_solution()
    flat = _flat_solution()
    on = _fitness(objective, industrial=True)
    off = _fitness(objective, industrial=False)
    assert on(tall) == pytest.approx(off(tall))
    assert on(flat) == pytest.approx(off(flat))
