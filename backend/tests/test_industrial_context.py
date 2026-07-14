import pytest

from app.core.industrial_context import IndustrialLoadContext
from app.models.schemas import Container


def _container(**updates):
    data = dict(
        id="c",
        inner_length=1000,
        inner_width=1000,
        inner_height=1000,
        max_payload=10000,
        quantity=1,
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


def test_preview_does_not_mutate_incremental_load_state():
    context = IndustrialLoadContext(_container())
    base = (0, 0, 0, 1000, 1000, 100)
    top = (0, 0, 100, 1000, 1000, 100)

    committed = context.commit(base, 100)
    preview = context.preview(top, 50)

    assert committed.total_mass == 100
    assert committed.max_floor_load_kg_m2 == pytest.approx(100)
    assert preview.total_mass == 150
    assert preview.max_floor_load_kg_m2 == pytest.approx(150)
    assert context.metrics() == committed


def test_commit_updates_mass_moments_floor_load_and_transport_metrics():
    context = IndustrialLoadContext(_container())
    context.commit((0, 0, 0, 1000, 1000, 100), 100, friction=0.5)
    metrics = context.commit((0, 0, 100, 1000, 1000, 100), 50, friction=0.3)

    assert metrics.total_mass == 150
    assert metrics.cog_x_ratio == pytest.approx(0.5)
    assert metrics.cog_y_ratio == pytest.approx(0.5)
    assert metrics.cog_z_ratio == pytest.approx((100 * 50 + 50 * 150) / 150 / 1000)
    assert metrics.max_floor_load_kg_m2 == pytest.approx(150)
    assert metrics.required_securement_kn > 0
    assert metrics.tip_stability_margin == pytest.approx(0.92)


def test_load_is_recursively_distributed_across_multiple_ground_supports():
    context = IndustrialLoadContext(_container())
    context.commit((0, 0, 0, 500, 1000, 100), 50)
    context.commit((500, 0, 0, 500, 1000, 100), 50)
    metrics = context.commit((0, 0, 100, 1000, 1000, 100), 100)

    assert metrics.total_mass == 200
    assert metrics.max_floor_load_kg_m2 == pytest.approx(200)


def test_load_distribution_curve_margin_is_incremental():
    context = IndustrialLoadContext(_container(load_distribution_curve=[
        {"x_ratio": 0.0, "max_payload": 1000},
        {"x_ratio": 1.0, "max_payload": 2000},
    ]))
    metrics = context.commit((400, 0, 0, 200, 1000, 100), 300)

    assert metrics.cog_x_ratio == pytest.approx(0.5)
    assert metrics.load_distribution_margin == pytest.approx(0.8)
