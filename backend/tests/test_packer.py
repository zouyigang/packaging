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
