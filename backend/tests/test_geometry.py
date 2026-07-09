from app.core.geometry import (
    box_volume,
    box_within,
    boxes_overlap,
    oriented_dims,
)
from app.core.extreme_point import find_placement
from app.core.space import ExtremePointSet
from app.core.constraints import PlacedItem


def test_oriented_dims_default():
    assert oriented_dims(10, 20, 30, "LWH") == (10, 20, 30)


def test_oriented_dims_all_six_are_permutations():
    base = (10, 20, 30)
    for orient in ("LWH", "WLH", "LHW", "HWL", "WHL", "HLW"):
        d = oriented_dims(*base, orient)
        assert sorted(d) == sorted(base)


def test_oriented_dims_side_lay():
    # 把高(30)放到 y 轴上
    assert oriented_dims(10, 20, 30, "LHW") == (10, 30, 20)


def test_overlap_true_when_interpenetrating():
    a = (0, 0, 0, 10, 10, 10)
    b = (5, 5, 5, 10, 10, 10)
    assert boxes_overlap(a, b) is True


def test_overlap_false_when_face_touching():
    a = (0, 0, 0, 10, 10, 10)
    b = (10, 0, 0, 10, 10, 10)  # 沿 x 仅共面接触
    assert boxes_overlap(a, b) is False


def test_overlap_false_when_separated():
    a = (0, 0, 0, 10, 10, 10)
    b = (100, 0, 0, 10, 10, 10)
    assert boxes_overlap(a, b) is False


def test_within_true():
    assert box_within((0, 0, 0, 10, 10, 10), 10, 10, 10) is True


def test_within_false_when_exceeds():
    assert box_within((5, 0, 0, 10, 10, 10), 10, 10, 10) is False


def test_within_false_when_negative_coord():
    assert box_within((-1, 0, 0, 5, 5, 5), 10, 10, 10) is False


def test_box_volume():
    assert box_volume((0, 0, 0, 2, 3, 4)) == 24


def test_find_placement_accepts_cached_oriented_rotations():
    uncached = find_placement(10, 20, 30, ["LWH", "WLH"], ExtremePointSet(), [], 30, 30, 30)
    cached = find_placement(
        10,
        20,
        30,
        ["LWH", "WLH"],
        ExtremePointSet(),
        [],
        30,
        30,
        30,
        oriented_rotations=[
            ("LWH", 10, 20, 30),
            ("WLH", 20, 10, 30),
        ],
    )
    assert cached is not None
    assert uncached is not None
    assert cached.box == uncached.box
    assert cached.orientation == uncached.orientation


def test_extreme_points_prune_covered_points_keeps_boundaries():
    ep = ExtremePointSet()
    box = (0, 0, 0, 10, 10, 10)
    ep.add_from_placement(box)
    removed = ep.prune_covered(box)

    assert removed == 1
    assert ep.points() == [(10, 0, 0), (0, 10, 0), (0, 0, 10)]


def test_find_placement_prunes_covered_and_dimension_invalid_points():
    ep = ExtremePointSet()
    ep.add_from_placement((0, 0, 0, 10, 10, 10))
    ep.add_from_placement((90, 90, 90, 10, 10, 10))
    placed = [PlacedItem(box=(0, 0, 0, 10, 10, 10), weight=1, max_load_top=None, item_id="a")]
    counters = {}

    def count(name, amount=1):
        counters[name] = counters.get(name, 0) + amount

    cand = find_placement(
        10,
        10,
        10,
        ["LWH"],
        ep,
        placed,
        100,
        100,
        100,
        counter_fn=count,
    )

    assert cand is not None
    assert cand.point != (0.0, 0.0, 0.0)
    assert counters["candidate_points_raw"] > counters["candidate_points_ready"]
    assert counters["candidate_points_pruned"] > 0


def test_find_placement_skips_candidates_that_cannot_beat_best_score():
    ep = ExtremePointSet()
    ep._points = [(0, 0, 0), (10, 0, 0), (20, 0, 0)]
    counters = {}
    overlap_calls = {"count": 0}

    def count(name, amount=1):
        counters[name] = counters.get(name, 0) + amount

    def overlap_candidates(_box):
        overlap_calls["count"] += 1
        return []

    cand = find_placement(
        10,
        10,
        10,
        ["LWH"],
        ep,
        [],
        100,
        100,
        100,
        overlap_candidates_fn=overlap_candidates,
        counter_fn=count,
    )

    assert cand is not None
    assert cand.point == (0, 0, 0)
    assert overlap_calls["count"] == 1
    assert counters["candidate_boxes_skipped_by_score"] == 2
