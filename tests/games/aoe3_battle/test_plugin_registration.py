"""Regression tests for aoe3_battle command registration."""

from __future__ import annotations

import sys
from pathlib import Path

import nonebot
from nonebot.matcher import matchers


def test_civ_query_does_not_duplicate_aoe3_battle_matchers() -> None:
    src = Path(__file__).resolve().parents[3] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init(command_start={""}, command_sep={" "})

    from src.plugins.aoe3.repository import UnitRepo
    from src.plugins.games.aoe3_battle import commands

    UnitRepo.get().list_by_civ("奥斯曼")

    registered = [
        matcher
        for group in matchers.values()
        for matcher in group
        if matcher.module_name == "src.plugins.games.aoe3_battle.commands"
    ]
    assert len(registered) == 4
    assert commands._start_fight in registered
