"""空旷平地 A* 寻路（四方向）。"""

from __future__ import annotations

import heapq
from collections.abc import Callable

Coord = tuple[int, int]
DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def manhattan(a: Coord, b: Coord) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def astar(
    start: Coord,
    goal: Coord,
    width: int,
    height: int,
    blocked: Callable[[Coord], bool],
) -> list[Coord]:
    if start == goal:
        return [start]
    if blocked(goal):
        return []

    open_heap: list[tuple[int, int, Coord]] = [(manhattan(start, goal), 0, start)]
    came_from: dict[Coord, Coord | None] = {start: None}
    g_score: dict[Coord, int] = {start: 0}

    while open_heap:
        _, g, current = heapq.heappop(open_heap)
        if current == goal:
            path = [current]
            while came_from[current] is not None:
                current = came_from[current]  # type: ignore[assignment]
                path.append(current)
            path.reverse()
            return path

        if g > g_score.get(current, 10**9):
            continue

        for dx, dy in DIRS:
            nxt = (current[0] + dx, current[1] + dy)
            if nxt[0] < 0 or nxt[1] < 0 or nxt[0] >= width or nxt[1] >= height:
                continue
            if blocked(nxt):
                continue
            ng = g + 1
            if ng < g_score.get(nxt, 10**9):
                g_score[nxt] = ng
                came_from[nxt] = current
                heapq.heappush(open_heap, (ng + manhattan(nxt, goal), ng, nxt))

    return []
