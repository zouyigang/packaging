import pytest

from app.core.objectives import (
    Balanced,
    CenterOfGravity,
    LoadingEfficiency,
    MaxUtilization,
    MinContainers,
    Stability,
    get_objective,
)
from app.models.schemas import Container


def test_registry_returns_correct_types():
    assert isinstance(get_objective("max_utilization"), MaxUtilization)
    assert isinstance(get_objective("min_containers"), MinContainers)
    assert isinstance(get_objective("stability"), Stability)
    assert isinstance(get_objective("balanced"), Balanced)
    assert isinstance(get_objective("transport_cost"), MaxUtilization)
    assert isinstance(get_objective("load_stability"), Stability)
    assert isinstance(get_objective("weight_balance"), CenterOfGravity)
    assert isinstance(get_objective("loading_efficiency"), LoadingEfficiency)
    assert get_objective("multi_customer_delivery") is get_objective("loading_efficiency")
    assert isinstance(get_objective("advanced_score"), Balanced)


def test_unknown_objective_raises():
    with pytest.raises(ValueError):
        get_objective("nope")


def test_default_score_prefers_low_back_left():
    obj = Balanced()
    low = obj.placement_score((0, 0, 0, 10, 10, 10))
    high = obj.placement_score((0, 0, 50, 10, 10, 10))
    assert low < high


def test_stability_prefers_larger_base_at_same_height():
    obj = Stability()
    big_base = obj.placement_score((0, 0, 0, 40, 40, 10))
    small_base = obj.placement_score((0, 0, 0, 10, 10, 10))
    assert big_base < small_base  # 同高时大底面优先


def test_stability_prefers_low_height_over_base():
    obj = Stability()
    low = obj.placement_score((0, 0, 0, 10, 10, 10))
    higher_but_bigger = obj.placement_score((0, 0, 5, 40, 40, 10))
    assert low < higher_but_bigger  # 低重心优先于大底面


def test_order_containers_biggest_first():
    small = Container(id="s", inner_length=10, inner_width=10, inner_height=10, max_payload=1)
    big = Container(id="b", inner_length=100, inner_width=100, inner_height=100, max_payload=1)
    ordered = MinContainers().order_containers([small, big])
    assert [c.id for c in ordered] == ["b", "s"]


def test_loading_efficiency_prefers_inside_before_width():
    obj = get_objective("loading_efficiency")
    inside = obj.placement_score((0, 100, 0, 10, 10, 10))
    outside = obj.placement_score((100, 0, 0, 10, 10, 10))
    assert inside < outside