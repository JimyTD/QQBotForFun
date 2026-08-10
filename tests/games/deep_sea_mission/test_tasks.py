from __future__ import annotations

import random

from src.plugins.games.deep_sea_mission.tasks import TASK_CARDS, draw_tasks


def test_all_96_tasks_are_recorded_in_chinese() -> None:
    assert len(TASK_CARDS) == 96
    assert all(card.text for card in TASK_CARDS)
    assert all("Win " not in card.text for card in TASK_CARDS)


def test_draw_tasks_matches_target_difficulty_for_player_count() -> None:
    tasks = draw_tasks(5, 4, random.Random(1))
    assert sum(int(t["difficulty"]) for t in tasks) == 5
    assert all(t["assigned_to"] is None for t in tasks)
    assert all(t["completed"] is False for t in tasks)
