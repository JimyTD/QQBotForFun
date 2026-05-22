"""格点几何（炮塔朝向、视线）。"""

from __future__ import annotations

import math

WANGLE_MAX = 1024


def cell_wangle(from_cell: tuple[int, int], to_cell: tuple[int, int]) -> int:
    """格坐标 → OpenRA WAngle（0 指向上方，顺时针）。"""
    dx = to_cell[0] - from_cell[0]
    dy = to_cell[1] - from_cell[1]
    if dx == 0 and dy == 0:
        return 0
    angle = math.atan2(dx, -dy)
    return int(round((angle / (2 * math.pi)) * WANGLE_MAX)) % WANGLE_MAX


def wangle_delta(current: int, target: int) -> int:
    """最短有符号差值（-512..512）。"""
    d = (target - current) % WANGLE_MAX
    if d > WANGLE_MAX // 2:
        d -= WANGLE_MAX
    return d


def rotate_toward(current: int, target: int, turn_speed: int) -> int:
    d = wangle_delta(current, target)
    if abs(d) <= turn_speed:
        return target % WANGLE_MAX
    step = turn_speed if d > 0 else -turn_speed
    return (current + step) % WANGLE_MAX


def iter_line_cells(
    a: tuple[int, int], b: tuple[int, int]
) -> list[tuple[int, int]]:
    """Bresenham 线段上的格（含端点）。"""
    x0, y0 = a
    x1, y1 = b
    cells: list[tuple[int, int]] = []
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    x, y = x0, y0
    while True:
        cells.append((x, y))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy
    return cells
