"""Persistent per-group default budget parsing and storage."""

from __future__ import annotations

import nonebot
import pytest

nonebot.init()

from core.group_config import get_group_config  # noqa: E402
from plugins.aoe3_battle_args import parse_default_budget  # noqa: E402
from src.plugins.game_launcher import handlers  # noqa: E402
from src.plugins.games.aoe3_battle.rival_pick import _resolve_budget  # noqa: E402


class _Matcher:
    def __init__(self) -> None:
        self.finished: str | None = None

    async def finish(self, message: str) -> None:
        self.finished = message


class _Event:
    group_id = 12345
    user_id = 67890


def test_parse_default_budget() -> None:
    assert parse_default_budget(["预算", "15000"]) == (15000, None)
    assert parse_default_budget(["预算"])[1] is not None
    assert parse_default_budget(["预算", "999"])[1] is not None
    assert parse_default_budget(["预算", "50001"])[1] is not None
    assert parse_default_budget(["预算", "abc"])[1] is not None
    assert parse_default_budget(["15000"]) == (None, None)


@pytest.mark.asyncio
async def test_entry_sets_budget_and_stops_without_launching(monkeypatch) -> None:
    matcher = _Matcher()

    async def fail_launch(*args, **kwargs):
        raise AssertionError("persistent budget setup must not launch a game")

    monkeypatch.setattr(handlers, "_launch_game", fail_launch)
    consumed = await handlers._handle_default_budget(matcher, 12345, ["预算", "15000"])

    assert consumed is True
    assert matcher.finished == "✅ 本群斗蛐蛐默认预算已设为【15000】"
    assert await handlers._get_default_budget(12345) == 15000


@pytest.mark.asyncio
async def test_set_and_read_default_budget_without_permission() -> None:
    matcher = _Matcher()
    await handlers._set_default_budget(matcher, 12345, 15000)

    assert matcher.finished == "✅ 本群斗蛐蛐默认预算已设为【15000】"
    assert await get_group_config(12345, handlers._BUDGET_CONFIG_KEY) == "15000"
    assert await handlers._get_default_budget(12345) == 15000


@pytest.mark.asyncio
async def test_invalid_stored_default_budget_falls_back() -> None:
    from core.group_config import set_group_config

    await set_group_config(12345, handlers._BUDGET_CONFIG_KEY, "broken")
    assert await handlers._get_default_budget(12345) is None


@pytest.mark.asyncio
async def test_rival_pick_resolves_group_budget_and_explicit_override() -> None:
    from core.group_config import set_group_config

    await set_group_config(54321, handlers._BUDGET_CONFIG_KEY, "15000")
    assert await _resolve_budget(54321, None) == 15000
    assert await _resolve_budget(54321, 5000) == 5000
