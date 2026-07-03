import itertools

from app.core.geometry import oriented_dims
from app.core.packer import pack_single_container
from app.models.schemas import Container, Item


def _placement_box(p, item: Item):
    dx, dy, dz = oriented_dims(item.length, item.width, item.height, p.orientation)
    return (p.x, p.y, p.z, dx, dy, dz)


def _overlaps(a, b, eps=1e-6):
    ax, ay, az, adx, ady, adz = a
    bx, by, bz, bdx, bdy, bdz = b
    if ax + adx <= bx + eps or bx + bdx <= ax + eps:
        return False
    if ay + ady <= by + eps or by + bdy <= ay + eps:
        return False
    if az + adz <= bz + eps or bz + bdz <= az + eps:
        return False
    return True


def test_perfect_fit_fills_container():
    # 8 个 50×50×50 的小箱恰好填满 100×100×100 容器
    item = Item(id="a", length=50, width=50, height=50, quantity=8)
    container = Container(
        id="c", inner_length=100, inner_width=100, inner_height=100, max_payload=10000
    )
    loaded = pack_single_container([item], container)
    assert len(loaded.placements) == 8
    assert loaded.volume_utilization == 1.0


def test_no_overlap_and_within_bounds():
    item = Item(id="a", length=40, width=30, height=20, quantity=20)
    container = Container(
        id="c", inner_length=120, inner_width=120, inner_height=120, max_payload=10000
    )
    loaded = pack_single_container([item], container)
    boxes = [_placement_box(p, item) for p in loaded.placements]
    # 两两不重叠
    for a, b in itertools.combinations(boxes, 2):
        assert not _overlaps(a, b)
    # 均在容器内
    for x, y, z, dx, dy, dz in boxes:
        assert x >= -1e-6 and y >= -1e-6 and z >= -1e-6
        assert x + dx <= 120 + 1e-6
        assert y + dy <= 120 + 1e-6
        assert z + dz <= 120 + 1e-6


def test_seq_is_sequential():
    item = Item(id="a", length=50, width=50, height=50, quantity=8)
    container = Container(
        id="c", inner_length=100, inner_width=100, inner_height=100, max_payload=10000
    )
    loaded = pack_single_container([item], container)
    seqs = [p.seq for p in loaded.placements]
    assert seqs == list(range(1, len(seqs) + 1))


def test_oversized_item_not_placed():
    item = Item(id="big", length=200, width=200, height=200, quantity=1)
    container = Container(
        id="c", inner_length=100, inner_width=100, inner_height=100, max_payload=10000
    )
    loaded = pack_single_container([item], container)
    assert loaded.placements == []
    assert loaded.volume_utilization == 0.0


def test_partial_fit_leaves_some_unplaced():
    # 容器只能放下 8 个 50³，给 10 个 → 放下 8，2 个放不下
    item = Item(id="a", length=50, width=50, height=50, quantity=10)
    container = Container(
        id="c", inner_length=100, inner_width=100, inner_height=100, max_payload=10000
    )
    loaded = pack_single_container([item], container)
    assert len(loaded.placements) == 8


def test_seq_loads_from_inside_to_outside():
    item = Item(id="a", length=100, width=100, height=100, quantity=2)
    container = Container(
        id="c", inner_length=200, inner_width=100, inner_height=100,
        max_payload=10000,
    )

    loaded = pack_single_container([item], container)

    assert [p.x for p in loaded.placements] == [0.0, 100.0]
    assert [p.seq for p in loaded.placements] == [1, 2]


def test_seq_never_places_upper_item_before_full_support():
    item = Item(id="a", length=50, width=50, height=50, quantity=8)
    container = Container(
        id="c", inner_length=100, inner_width=100, inner_height=100,
        max_payload=10000,
    )

    loaded = pack_single_container([item], container)
    placed = []
    for p in sorted(loaded.placements, key=lambda p: p.seq):
        box = _placement_box(p, item)
        x, y, z, dx, dy, _dz = box
        if z > 1e-6:
            support_area = 0.0
            for bx, by, bz, bdx, bdy, bdz in placed:
                if abs((bz + bdz) - z) > 1e-6:
                    continue
                ox = max(0.0, min(x + dx, bx + bdx) - max(x, bx))
                oy = max(0.0, min(y + dy, by + bdy) - max(y, by))
                support_area += ox * oy
            assert support_area >= dx * dy - 1e-6
        placed.append(box)

def test_seq_respects_x_min_loading_access():
    item = Item(id="a", length=100, width=100, height=100, quantity=2)
    container = Container(
        id="c", inner_length=200, inner_width=100, inner_height=100,
        max_payload=10000, loading_accesses=[{"side": "x_min"}],
    )

    loaded = pack_single_container([item], container)

    assert [p.x for p in loaded.placements] == [100.0, 0.0]
    assert [p.seq for p in loaded.placements] == [1, 2]


def test_door_height_is_not_enforced_yet():
    item = Item(
        id="a", length=50, width=50, height=100, quantity=1,
        allowed_rotations=["LWH"],
    )
    container = Container(
        id="c", inner_length=100, inner_width=100, inner_height=120,
        max_payload=10000, door_height=80,
    )

    loaded = pack_single_container([item], container)

    assert len(loaded.placements) == 1

def test_loading_efficiency_single_front_door_places_toward_far_end():
    item = Item(id="a", length=100, width=100, height=100, quantity=1)
    container = Container(
        id="c", inner_length=300, inner_width=300, inner_height=150,
        max_payload=10000, loading_accesses=[{"side": "x_min"}],
    )

    loaded = pack_single_container([item], container, "loading_efficiency")

    assert loaded.placements[0].x > 150


def test_loading_efficiency_side_door_starts_near_side_and_centered_along_length():
    item = Item(id="a", length=100, width=100, height=100, quantity=1)
    container = Container(
        id="c", inner_length=300, inner_width=300, inner_height=150,
        max_payload=10000, loading_accesses=[{"side": "y_min"}],
    )

    loaded = pack_single_container([item], container, "loading_efficiency")
    placement = loaded.placements[0]

    assert placement.y < 50
    assert placement.x == 100


def test_loading_efficiency_multi_access_places_in_nearest_access_zone():
    item = Item(id="a", length=100, width=100, height=100, quantity=1)
    container = Container(
        id="c", inner_length=300, inner_width=300, inner_height=150,
        max_payload=10000,
        loading_accesses=[{"side": "x_min"}, {"side": "x_max"}],
    )

    loaded = pack_single_container([item], container, "loading_efficiency")
    placement = loaded.placements[0]
    nearest_door_depth = min(placement.x, 300 - (placement.x + 100))

    assert nearest_door_depth <= 25


def test_loading_efficiency_top_access_prefers_centered_low_placement():
    item = Item(id="a", length=100, width=100, height=100, quantity=1)
    container = Container(
        id="c", inner_length=300, inner_width=300, inner_height=150,
        max_payload=10000, loading_accesses=[{"side": "z_max"}],
    )

    loaded = pack_single_container([item], container, "loading_efficiency")
    placement = loaded.placements[0]

    assert (placement.x, placement.y, placement.z) == (100.0, 100.0, 0.0)
