from app.core.constraints import (
    PlacedItem,
    check_stack_load,
    check_support,
    commit_stack_load,
    supporters,
)


def _pi(box, weight=10, max_load_top=None, item_id="x"):
    return PlacedItem(box=box, weight=weight, max_load_top=max_load_top, item_id=item_id)


def test_floor_box_has_no_supporters():
    box = (0, 0, 0, 10, 10, 10)
    assert supporters(box, []) == []


def test_floor_box_is_supported():
    assert check_support((0, 0, 0, 10, 10, 10), []) is True


def test_floating_box_not_supported():
    # 下方无任何箱，且不在地面 → 悬空
    floating = (0, 0, 20, 10, 10, 10)
    base = _pi((0, 0, 0, 10, 10, 10))  # 顶面 z=10，托不到 z=20
    assert check_support(floating, [base]) is False


def test_full_support_ok():
    base = _pi((0, 0, 0, 10, 10, 10))
    on_top = (0, 0, 10, 10, 10, 10)
    assert check_support(on_top, [base]) is True


def test_partial_support_below_ratio_rejected():
    base = _pi((0, 0, 0, 10, 10, 10))
    # 仅一半底面落在 base 上 → 比例 0.5 < 0.6
    half = (5, 0, 10, 10, 10, 10)
    assert check_support(half, [base], min_support_ratio=0.6) is False


def test_stack_load_unlimited_when_none():
    base = _pi((0, 0, 0, 10, 10, 10), max_load_top=None)
    assert check_stack_load((0, 0, 10, 10, 10, 10), weight=999, placed=[base]) is True


def test_stack_load_rejected_when_exceeds():
    base = _pi((0, 0, 0, 10, 10, 10), max_load_top=5)
    assert check_stack_load((0, 0, 10, 10, 10, 10), weight=10, placed=[base]) is False


def test_fragile_rejects_any_weight():
    fragile = _pi((0, 0, 0, 10, 10, 10), max_load_top=0)
    assert check_stack_load((0, 0, 10, 10, 10, 10), weight=1, placed=[fragile]) is False


def test_commit_accumulates_carried_and_blocks_second():
    base = _pi((0, 0, 0, 20, 10, 10), max_load_top=15)
    first = (0, 0, 10, 10, 10, 10)   # 压在 base 左半
    assert check_stack_load(first, 10, [base]) is True
    commit_stack_load(first, 10, [base])
    assert abs(base.carried - 10) < 1e-9
    second = (10, 0, 10, 10, 10, 10)  # 压在 base 右半 → 累计 20 > 15
    assert check_stack_load(second, 10, [base]) is False


def test_default_support_requires_full_base_contact():
    base = _pi((0, 0, 0, 10, 10, 10))
    half = (5, 0, 10, 10, 10, 10)
    assert check_support(half, [base]) is False
