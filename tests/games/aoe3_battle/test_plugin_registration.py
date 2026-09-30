"""Regression tests for aoe3_battle command registration."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_civ_query_does_not_duplicate_aoe3_battle_matchers() -> None:
    # NoneBot's matcher registry is process-global and survives imports in other tests.
    code = """
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "src"))

import nonebot
from nonebot.matcher import matchers

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
assert len(registered) == 4, f"Expected 4 matchers, got {len(registered)}"
assert commands._start_fight in registered
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[3],
        env={**os.environ, "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
