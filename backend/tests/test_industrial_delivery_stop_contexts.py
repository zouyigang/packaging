"""顺序配送逐站点工业载荷上下文与重心可达区间。

覆盖：
- 卸货后剩余载荷的重心保护：没有更晚站点货物可修正时，偏心候选被拒绝；
- 同站点剩余货物可修正的临时偏心被放行（逐站点可达区间）；
- 顺序配送现在允许全载重心恢复遍（此前被整体禁用）；
- 相同输入重复求解布局签名一致。
"""

from app.core.packer import _DeliveryStopCogTracker, _single_placeable, solve
from app.models.schemas import Container, Item, SolveRequest


def _container(container_id="c", **updates):
    data = dict(
        id=container_id,
        inner_length=1000,
        inner_width=1000,
        inner_height=1000,
        max_payload=10000,
        quantity=1,
        cog_limits={
            "x_min_ratio": 0.40,
            "x_max_ratio": 0.60,
            "y_min_ratio": 0.0,
            "y_max_ratio": 1.0,
            "z_max_ratio": 1.0,
        },
        max_floor_load_kg_m2=10000,
        acceleration_profile={
            "longitudinal_g": 0.8,
            "transverse_g": 0.5,
            "vertical_g": 0.2,
        },
        default_friction_coefficient=0.4,
    )
    data.update(updates)
    return Container(**data)


def _request(items, containers, **updates):
    data = dict(
        items=items,
        containers=containers,
        objective="delivery_sequence",
        validation_mode="industrial",
        pallet_policy="avoid",
    )
    data.update(updates)
    return SolveRequest(**data)


def _box(item_id, stop_seq, weight=100, stackable=True, **updates):
    data = dict(
        id=item_id,
        length=200,
        width=200,
        height=200,
        weight=weight,
        quantity=1,
        allowed_rotations=["LWH"],
        stop_seq=stop_seq,
    )
    if not stackable:
        data["stackable"] = False
    data.update(updates)
    return Item(**data)


def _layout_signature(solution):
    return tuple(
        (
            loaded.id,
            tuple(
                (p.item_id, p.seq, p.x, p.y, p.z, p.orientation)
                for p in loaded.placements
            ),
        )
        for loaded in solution.containers
    )


def _post_drop_errors(solution):
    return [v for v in solution.violations if v.code.startswith("POST_DROP_")]


def test_last_stop_cargo_must_hold_post_drop_cog_without_later_correction():
    # 只有一件停靠 2 的货物：站点 1 卸货后它单独承担剩余载荷重心，
    # 没有更晚卸货的货物可修正，因此必须直接放在设备重心范围内。
    items = [
        _box("late", stop_seq=2, stackable=False),
        _box("early-a", stop_seq=1, stackable=False),
        _box("early-b", stop_seq=1, stackable=False),
    ]
    solution = solve(_request(items, [_container()]))

    assert solution.status == "feasible"
    assert solution.unpacked == []
    assert _post_drop_errors(solution) == []
    late = next(
        p for loaded in solution.containers for p in loaded.placements
        if p.item_id == "late"
    )
    center_x = late.x + 100
    assert 400 - 1e-6 <= center_x <= 600 + 1e-6
    counters = solution.performance.counters
    assert counters.get("industrial_preview_post_drop_cog_exceeded", 0) > 0


def test_unrecoverable_post_drop_eccentricity_surfaces_explicit_error():
    # 设备要求整体重心靠前（x ≤ 0.35）。停靠 2 的大件无论放哪，站点 1 卸货后
    # 它单独的重心都在 0.4 以上，且没有更晚卸货货物可修正：应给出明确的
    # POST_DROP_COG_OUT_OF_RANGE 错误，而不是无原因的 partial。
    items = [
        _box("late", stop_seq=2, length=800, width=800, height=200, stackable=False),
        _box("early-a", stop_seq=1, weight=500, stackable=False),
        _box("early-b", stop_seq=1, weight=500, stackable=False),
    ]
    container = _container(cog_limits={
        "x_min_ratio": 0.0,
        "x_max_ratio": 0.35,
        "y_min_ratio": 0.0,
        "y_max_ratio": 1.0,
        "z_max_ratio": 1.0,
    })
    solution = solve(_request(items, [container]))

    assert "late" in solution.unpacked
    assert solution.status == "infeasible"
    assert any(v.code == "POST_DROP_COG_OUT_OF_RANGE" for v in solution.violations)
    counters = solution.performance.counters
    assert counters.get("industrial_preview_post_drop_cog_exceeded", 0) > 0


def test_delivery_allows_recoverable_full_load_offset_in_first_pass():
    # 三件停靠 2 货物互不可堆叠：第二件放置时任何位置都让全载重心临时超限。
    # 之前顺序配送逐候选执行严格全载检查会全部拒绝；现在全载状态由逐站点
    # 跟踪器按可达区间判定，第一遍搜索即可放行，由第三件拉回最终重心。
    items = [
        _box("late-a", stop_seq=2, stackable=False),
        _box("late-b", stop_seq=2, stackable=False),
        _box("late-c", stop_seq=2, stackable=False),
        _box("early", stop_seq=1, weight=1, stackable=False),
    ]
    container = _container(cog_limits={
        "x_min_ratio": 0.45,
        "x_max_ratio": 0.55,
        "y_min_ratio": 0.45,
        "y_max_ratio": 0.55,
        "z_max_ratio": 1.0,
    })
    solution = solve(_request(items, [container]))

    assert solution.status == "feasible"
    assert solution.unpacked == []
    assert _post_drop_errors(solution) == []
    counters = solution.performance.counters
    assert counters.get("industrial_preview_cog_recoverable", 0) > 0
    assert counters.get("industrial_preview_post_drop_cog_recoverable", 0) > 0
    metrics = solution.containers[0].industrial_metrics
    assert 0.45 - 1e-6 <= metrics["cog_x_ratio"] <= 0.55 + 1e-6
    assert 0.45 - 1e-6 <= metrics["cog_y_ratio"] <= 0.55 + 1e-6


def test_delivery_solutions_stay_deterministic():
    items = [
        _box("late-a", stop_seq=2, stackable=False),
        _box("late-b", stop_seq=2, stackable=False),
        _box("early-a", stop_seq=1, stackable=False),
        _box("early-b", stop_seq=1, stackable=False),
    ]

    first = solve(_request(items, [_container()]))
    second = solve(_request(items, [_container()]))

    assert first.status == second.status == "feasible"
    assert _layout_signature(first) == _layout_signature(second)


def test_tracker_pool_excludes_cargo_dropped_at_or_before_state_stop():
    container = _container()
    late = _single_placeable(_box("late", stop_seq=2))
    early = _single_placeable(_box("early", stop_seq=1))
    tracker = _DeliveryStopCogTracker(container, [late, early])

    assert tracker.check_stops == [0, 1]
    tracker.advance(late)
    # 剩余池只剩 stop=1 的货物；对「卸完站点 1 之后」的状态它不可用作修正质量。
    assert tracker.pool[1][0] == 0.0

    # 卸货后状态只剩这件深处的 stop=2 货物且无修正质量：候选必须被拒绝。
    rejection_codes: set[str] = set()
    eccentric = tracker.candidate_ok(
        2,
        [((0.0, 400.0, 0.0, 200.0, 200.0, 200.0), 100.0, None)],
        None,
        rejection_codes,
    )
    assert eccentric is False
    assert "POST_DROP_COG_OUT_OF_RANGE" in rejection_codes

    centered = tracker.candidate_ok(
        2,
        [((400.0, 400.0, 0.0, 200.0, 200.0, 200.0), 100.0, None)],
        None,
        set(),
    )
    assert centered is True
