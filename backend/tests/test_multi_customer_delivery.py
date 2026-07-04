from app.core.geometry import oriented_dims
from app.core.objectives import LoadingEfficiency, get_objective
from app.core.packer import _single_placeable, pack_single_container, solve
from app.models.schemas import Container, Item, SolveRequest


def _access_depth_x_max(placement, item, container):
    dx, _dy, _dz = oriented_dims(item.length, item.width, item.height, placement.orientation)
    return container.inner_length - (placement.x + dx)


def test_loading_efficiency_delivery_places_later_stop_deeper_and_sequences_first():
    early = Item(id="early", length=100, width=100, height=100, stop_seq=1, customer_id="A")
    late = Item(id="late", length=100, width=100, height=100, stop_seq=2, customer_id="B")
    container = Container(
        id="c", inner_length=300, inner_width=100, inner_height=100,
        max_payload=1000, loading_accesses=[{"side": "x_max"}],
    )

    loaded = pack_single_container([early, late], container, "loading_efficiency")
    placements = {p.item_id: p for p in loaded.placements}

    assert [p.stop_seq for p in loaded.placements] == [2, 1]
    assert _access_depth_x_max(placements["late"], late, container) > _access_depth_x_max(placements["early"], early, container)


def test_loading_efficiency_delivery_keeps_customer_and_order_metadata_on_placements():
    item = Item(
        id="box", length=50, width=50, height=50, quantity=1,
        customer_id="cust-1", order_id="ord-1", destination_id="dest-1", stop_seq=3,
    )
    container = Container(id="c", inner_length=100, inner_width=100, inner_height=100, max_payload=1000)

    loaded = pack_single_container([item], container, "loading_efficiency")
    placement = loaded.placements[0]

    assert placement.customer_id == "cust-1"
    assert placement.order_id == "ord-1"
    assert placement.destination_id == "dest-1"
    assert placement.stop_seq == 3


def test_loading_efficiency_delivery_defaults_support_legacy_items():
    item = Item(id="legacy", length=50, width=50, height=50, quantity=1)
    req = SolveRequest(
        items=[item],
        containers=[Container(id="c", inner_length=100, inner_width=100, inner_height=100, max_payload=1000)],
        objective="loading_efficiency",
    )

    sol = solve(req)

    assert len(sol.containers[0].placements) == 1
    assert sol.containers[0].placements[0].stop_seq == 1


def test_loading_efficiency_delivery_orders_same_stop_by_customer_then_order():
    obj = get_objective("loading_efficiency")
    assert isinstance(obj, LoadingEfficiency)
    items = [
        Item(id="b2", length=50, width=50, height=50, stop_seq=1, customer_id="B", order_id="2"),
        Item(id="a2", length=50, width=50, height=50, stop_seq=1, customer_id="A", order_id="2"),
        Item(id="a1", length=50, width=50, height=50, stop_seq=1, customer_id="A", order_id="1"),
    ]

    ordered = obj.order_placeables([_single_placeable(i) for i in items])

    assert [p.item_id for p in ordered] == ["a1", "a2", "b2"]


def test_loading_efficiency_delivery_multi_access_runs_and_preserves_later_stop_first():
    items = [
        Item(id="early", length=100, width=100, height=100, stop_seq=1),
        Item(id="late", length=100, width=100, height=100, stop_seq=2),
    ]
    container = Container(
        id="c", inner_length=300, inner_width=100, inner_height=100, max_payload=1000,
        loading_accesses=[{"side": "x_min"}, {"side": "x_max"}],
    )

    loaded = pack_single_container(items, container, "loading_efficiency")

    assert [p.stop_seq for p in loaded.placements] == [2, 1]


def test_loading_efficiency_delivery_does_not_bypass_payload_constraint():
    items = [
        Item(id="a", length=50, width=50, height=50, weight=10, customer_id="A"),
        Item(id="b", length=50, width=50, height=50, weight=10, customer_id="A"),
    ]
    container = Container(id="c", inner_length=100, inner_width=100, inner_height=100, max_payload=15)

    loaded = pack_single_container(items, container, "loading_efficiency")

    assert len(loaded.placements) == 1
    assert loaded.weight_utilization <= 1.0
