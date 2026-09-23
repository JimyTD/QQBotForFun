"""Ellipse contact regressions independent from the future footprint model."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from plugins.aoe3.models import Unit
from plugins.games.aoe3_battle.simulator2d.config import Simulation2DConfig
from plugins.games.aoe3_battle.simulator2d.geometry import CollisionShape, shape_contact
from plugins.games.aoe3_battle.simulator2d.model import Side, Soldier2D
from plugins.games.aoe3_battle.simulator2d.movement import CollisionResolver
from plugins.games.aoe3_battle.simulator2d.spatial import SpatialHash


def _pair(angle, separation):
    first = CollisionShape(10.0, 10.0, 2.0, 0.5, angle)
    second = replace(first, x=first.x - math.sin(angle) * separation,
                     y=first.y + math.cos(angle) * separation)
    return first, second


@pytest.mark.parametrize("angle", [0.0, 0.17, 0.7, math.pi / 2, 2.6, math.pi])
@pytest.mark.parametrize("gap", [0.0, 0.0001, 0.2])
def test_separated_or_touching_ellipses_have_no_contact(angle, gap):
    first, second = _pair(angle, 1.0 + gap)
    assert math.hypot(second.x - first.x, second.y - first.y) < 4.0
    assert shape_contact(first, second) is None
    assert shape_contact(second, first) is None


@pytest.mark.parametrize("angle", [0.0, 0.23, 1.9, 3.7, 5.6])
def test_penetration_normal_points_from_first_to_second(angle):
    first, second = _pair(angle, 0.8)
    contact = shape_contact(first, second)
    reverse = shape_contact(second, first)
    assert contact is not None and reverse is not None
    assert contact.depth == pytest.approx(0.2, abs=1e-6)
    assert (contact.normal_x, contact.normal_y) == pytest.approx((-math.sin(angle), math.cos(angle)), abs=1e-5)
    assert reverse.depth == pytest.approx(contact.depth, abs=1e-6)
    assert (reverse.normal_x, reverse.normal_y) == pytest.approx((-contact.normal_x, -contact.normal_y), abs=1e-5)
    separated = replace(second, x=second.x + contact.normal_x * (contact.depth + 1e-5),
                        y=second.y + contact.normal_y * (contact.depth + 1e-5))
    assert shape_contact(first, separated) is None


def test_ellipse_tolerance_ignores_small_penetration_like_circles():
    first, second = _pair(0.43, 0.995)
    assert shape_contact(first, second) is not None
    assert shape_contact(first, second, tolerance=0.01) is None
    assert shape_contact(first, second, tolerance=0.001).depth == pytest.approx(0.005, abs=1e-6)


def test_ellipse_and_circle_do_not_collide_only_because_bounds_overlap():
    ellipse = CollisionShape(0, 0, 2, 0.5, 0)
    circle = CollisionShape(0, 1.2, 0.5, 0.5, 1.0)
    assert shape_contact(ellipse, circle) is None
    circle = replace(circle, y=0.9)
    contact = shape_contact(ellipse, circle)
    assert contact is not None
    assert contact.depth == pytest.approx(0.1, abs=1e-6)
    assert contact.normal_y == pytest.approx(1.0, abs=1e-5)


def test_concentric_ellipses_separate_along_the_short_axis():
    first = CollisionShape(0, 0, 2, 0.5, 0)
    second = CollisionShape(0, 0, 1, 0.3, 0)
    contact = shape_contact(first, second)
    assert contact is not None
    assert contact.depth == pytest.approx(0.8, abs=1e-6)
    assert abs(contact.normal_y) == pytest.approx(1.0, abs=1e-5)


def test_differently_rotated_ellipses_use_a_minimum_translation():
    first = CollisionShape(0, 0, 1.3, 0.6, 0.37)
    second = CollisionShape(0.8, 0.7, 0.7, 1.1, -0.64)
    contact = shape_contact(first, second)
    assert contact is not None
    # Independent dense support-axis reference, without using the search helper.
    separation = max(
        abs(second.x * math.cos(a) + second.y * math.sin(a))
        - first.extent(math.cos(a), math.sin(a))
        - second.extent(math.cos(a), math.sin(a))
        for a in (i * math.tau / 4096 for i in range(4096))
    )
    assert contact.depth == pytest.approx(-separation, abs=1e-5)
    assert contact.normal_x * second.x + contact.normal_y * second.y >= 0
    separated = replace(second, x=second.x + contact.normal_x * (contact.depth + 1e-5),
                        y=second.y + contact.normal_y * (contact.depth + 1e-5))
    assert shape_contact(first, separated) is None


@pytest.mark.parametrize("normal_angle", [0.0, 0.6, 1.5, 2.4])
@pytest.mark.parametrize("gap", [0.0, 0.0001])
def test_oblique_tangency_between_differently_rotated_ellipses(normal_angle, gap):
    first = CollisionShape(0, 0, 2, 0.5, 0.37)
    second = CollisionShape(0, 0, 1.1, 0.3, -0.64)
    nx, ny = math.cos(normal_angle), math.sin(normal_angle)

    def support(shape):
        c, s = math.cos(shape.angle), math.sin(shape.angle)
        lx, ly = c * nx + s * ny, -s * nx + c * ny
        length = math.hypot(shape.radius_x * lx, shape.radius_z * ly)
        px = shape.radius_x ** 2 * lx / length
        py = shape.radius_z ** 2 * ly / length
        return c * px - s * py, s * px + c * py

    ax, ay = support(first)
    bx, by = support(second)
    # Construct tangent bodies from their support points; the separation
    # direction need not coincide with the line between their centers.
    second = replace(second, x=ax + bx + gap * nx, y=ay + by + gap * ny)
    assert shape_contact(first, second) is None
    assert shape_contact(second, first) is None


def test_circle_analytic_contact_is_unchanged():
    first = CollisionShape(0, 0, 0.5, 0.5, 0)
    second = CollisionShape(0.6, 0, 0.5, 0.5, 0)
    contact = shape_contact(first, second)
    assert contact.depth == pytest.approx(0.4)
    assert (contact.normal_x, contact.normal_y) == (1.0, 0.0)
    assert shape_contact(first, second, tolerance=0.5) is None


@pytest.mark.parametrize("separation", [1.2, 0.9])
def test_collision_resolver_moves_only_real_overlaps_outward(separation):
    unit = Unit(id="ellipse", name="ellipse", name_en="ellipse", hp=100,
                obstruction_radius_x=2.0, obstruction_radius_z=0.5)
    first = Soldier2D(1, Side.RED, unit, 100, 100, 10, 10)
    second = Soldier2D(2, Side.BLUE, unit, 100, 100, 10, 10 + separation)
    config = Simulation2DConfig(max_known_unit_radius=2.0)
    spatial = SpatialHash(config.spatial_cell_size)
    before = (first.pos, second.pos)
    result = CollisionResolver(config, spatial).resolve([first, second], field_width=30, field_height=30)
    assert result.max_overlap <= config.separation_slop
    if separation > 1.0:
        assert result.corrections == 0
        assert (first.pos, second.pos) == before
    else:
        assert result.corrections > 0
        assert second.y - first.y >= 1.0
        assert first.y + second.y == pytest.approx(20 + separation)
