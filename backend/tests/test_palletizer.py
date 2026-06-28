from app.core.objectives import get_objective
from app.core.palletizer import (
    build_pallet_load,
    fits_on_pallet,
    pallet_load_efficiency,
    select_pallet,
)
from app.models.schemas import Item, Pallet

OBJ = get_objective("stability")


def _item(qty=1, stackable=True):
    return Item(id="a", length=50, width=50, height=50, weight=10, quantity=qty, stackable=stackable)


def _pallet(qty=2):
    return Pallet(
        id="p", length=100, width=100, deck_height=10,
        max_stack_height=200, max_load=1000, quantity=qty,
    )


def test_fits_on_pallet_true():
    assert fits_on_pallet(_item(), _pallet()) is True


def test_fits_on_pallet_false_when_too_big():
    big = Item(id="b", length=300, width=300, height=300, quantity=1)
    assert fits_on_pallet(big, _pallet()) is False


def test_build_pallet_load_counts_and_height():
    load = build_pallet_load(_item(), _pallet(), OBJ, instance_id="p#1")
    # 100/50=2 → 2x2=4 件/层，200/50=4 层 → 16 件
    assert load.count == 16
    # 台面高 10 + 码放 200
    assert load.total_height == 210
    assert load.footprint_l == 100 and load.footprint_w == 100


def test_pallet_contents_sit_above_deck():
    load = build_pallet_load(_item(), _pallet(), OBJ, instance_id="p#1")
    zs = [c[3] for c in load.contents]
    assert min(zs) == 10  # 最底层货物紧贴台面（z=台面高）


def test_limit_caps_count():
    load = build_pallet_load(_item(), _pallet(), OBJ, instance_id="p#1", limit=5)
    assert load.count == 5


def test_max_load_caps_count():
    heavy = Item(id="h", length=50, width=50, height=50, weight=300, quantity=99)
    pallet = _pallet()  # max_load 1000 → 最多 3 件(900) ，第4件 1200>1000
    load = build_pallet_load(heavy, pallet, OBJ, instance_id="p#1")
    assert load.count == 3


def test_efficiency():
    load = build_pallet_load(_item(), _pallet(), OBJ, instance_id="p#1")
    eff = pallet_load_efficiency(load, _item())
    assert abs(eff - (16 * 125000) / (100 * 100 * 210)) < 1e-9


def test_select_pallet_picks_max_count():
    small = Pallet(id="s", length=50, width=50, deck_height=10,
                   max_stack_height=200, max_load=1000, quantity=1)
    big = _pallet()
    chosen = select_pallet(_item(), [small, big], OBJ)
    assert chosen.id == "p"


def test_select_pallet_none_when_no_quantity():
    assert select_pallet(_item(), [_pallet(qty=0)], OBJ) is None
