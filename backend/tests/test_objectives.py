import pytest

from app.core.objectives import (
    AdvancedScoreWeights,
    Balanced,
    CenterOfGravity,
    LoadingEfficiency,
    MaxUtilization,
    MinContainers,
    ScoreContext,
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


def test_balanced_score_prefers_low_positions():
    obj = Balanced()
    low = obj.placement_score((0, 0, 0, 10, 10, 10))
    high = obj.placement_score((0, 0, 50, 10, 10, 10))
    assert low < high


def test_balanced_weighted_score_offsets_existing_imbalance():
    obj = Balanced()
    ctx = ScoreContext(
        inner_length=100,
        inner_width=100,
        inner_height=100,
        unit_w=10,
        total_w=10,
        sum_wx=100,
        sum_wy=500,
        loading_access_sides=("z_max",),
    )
    scorer = obj.make_scorer(ctx)

    stays_left = scorer((0, 40, 0, 20, 20, 20))
    pulls_right = scorer((80, 40, 0, 20, 20, 20))

    assert pulls_right < stays_left


def test_balanced_pallet_score_allows_dense_multi_item_loads():
    obj = Balanced()
    assert obj.should_palletize(load_efficiency=0.5, count_per_pallet=8) is True
    assert obj.should_palletize(load_efficiency=0.5, count_per_pallet=1) is False
    assert obj.should_palletize(load_efficiency=0.3, count_per_pallet=2) is False


def test_loading_efficiency_declines_pallet_that_sterilizes_the_column():
    # 托盘块封顶：净码高只有直接堆叠可达高度的 70%，余下 30% 柱高永久作废。
    # 装卸效率类目标此时宁可散装，即使托盘本身填得很满。
    obj = get_objective("delivery_sequence")

    assert obj.should_palletize(0.85, 40, column_efficiency=0.70) is False
    assert obj.should_palletize(0.85, 40, column_efficiency=0.95) is True
    # 老的两条判据仍然生效：填充率太低、单托盘只有 1 件，都不码。
    assert obj.should_palletize(0.30, 40, column_efficiency=0.95) is False
    assert obj.should_palletize(0.85, 1, column_efficiency=0.95) is False


def test_stability_palletizes_even_when_the_column_is_wasted():
    # 稳定性/安全装载要的是「整块不散」，甘愿付出柱高，故不看 column_efficiency。
    obj = get_objective("safe_loading")

    assert obj.should_palletize(0.85, 40, column_efficiency=0.30) is True


def test_get_objective_applies_advanced_weights():
    obj = get_objective("advanced_score", {"palletization": 0.6})
    assert isinstance(obj, Balanced)
    assert obj.weights == AdvancedScoreWeights(
        space_utilization=0.35,
        stability=0.25,
        palletization=0.6,
        balance=0.15,
        loading_position=0.10,
    )
    assert get_objective("advanced_score").weights.palletization == 0.15


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
