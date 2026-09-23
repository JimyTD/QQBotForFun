"""Uniform spatial hash for dynamic 2D neighbor queries."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable

from .model import Soldier2D, Vec2


class SpatialHash:
    """One-unit-per-cell spatial index rebuilt once per simulation step."""

    def __init__(self, cell_size: float) -> None:
        if cell_size <= 0:
            raise ValueError("cell_size must be positive")
        self.cell_size = cell_size
        self._cells: dict[tuple[int, int], list[Soldier2D]] = defaultdict(list)

    def clear(self) -> None:
        self._cells.clear()

    def rebuild(self, soldiers: Iterable[Soldier2D]) -> None:
        self.clear()
        for soldier in soldiers:
            if soldier.alive:
                self._cells[self._key(soldier.x, soldier.y)].append(soldier)


    def _key(self, x: float, y: float) -> tuple[int, int]:
        return (
            math.floor(x / self.cell_size),
            math.floor(y / self.cell_size),
        )

    def query_circle(
        self,
        center: Vec2,
        radius: float,
        *,
        predicate: Callable[[Soldier2D], bool] | None = None,
    ) -> list[Soldier2D]:
        if radius < 0:
            return []
        min_x = math.floor((center.x - radius) / self.cell_size)
        max_x = math.floor((center.x + radius) / self.cell_size)
        min_y = math.floor((center.y - radius) / self.cell_size)
        max_y = math.floor((center.y + radius) / self.cell_size)
        radius_sq = radius * radius
        found: list[Soldier2D] = []

        for gx in range(min_x, max_x + 1):
            for gy in range(min_y, max_y + 1):
                for soldier in self._cells.get((gx, gy), ()):
                    if not soldier.alive:
                        continue
                    if predicate is not None and not predicate(soldier):
                        continue
                    dx = soldier.x - center.x
                    dy = soldier.y - center.y
                    if dx * dx + dy * dy <= radius_sq:
                        found.append(soldier)
        return found

    def query_box(
        self,
        min_x: float,
        max_x: float,
        min_y: float,
        max_y: float,
    ) -> list[Soldier2D]:
        gx0 = math.floor(min_x / self.cell_size)
        gx1 = math.floor(max_x / self.cell_size)
        gy0 = math.floor(min_y / self.cell_size)
        gy1 = math.floor(max_y / self.cell_size)
        found: list[Soldier2D] = []
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                for soldier in self._cells.get((gx, gy), ()):
                    if (
                        soldier.alive
                        and min_x <= soldier.x <= max_x
                        and min_y <= soldier.y <= max_y
                    ):
                        found.append(soldier)
        return found
