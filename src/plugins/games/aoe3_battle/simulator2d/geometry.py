"""Collision geometry helpers for the 2D battle simulator."""

from __future__ import annotations

from ....aoe3.models import Unit


def unit_radius(unit: Unit, fallback: float) -> float:
    """Return a unit's equivalent circular radius or the configured fallback."""
    return unit.collision_radius or fallback


def combined_radius(first: Unit, second: Unit, fallback: float) -> float:
    """Return the non-overlap distance for two equivalent circular units."""
    return unit_radius(first, fallback) + unit_radius(second, fallback)
