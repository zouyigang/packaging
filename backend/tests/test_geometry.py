from app.core.geometry import (
    box_volume,
    box_within,
    boxes_overlap,
    oriented_dims,
)


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
