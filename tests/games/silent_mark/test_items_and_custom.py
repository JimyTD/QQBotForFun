"""M3：物品快照（猎犬哨）与自定义板子。

这两个是 M3 的两块新能力：

- **猎犬哨快照**：源项目只在客户端标签里承诺了"场上存活 N 只狼"，服务端从未赋值
  → 语义在 `record_death`（唯一出局出口）里定下来。
- **自定义板子**：`validate_game_settings` 早就支持自定义，但 `_build_settings`
  只认预设，`mode="custom"` 会被无声回落到 4 人标准 —— 这里把它接上并锁死。
"""

from __future__ import annotations

from unittest.mock import patch

from core import session
from src.plugins.games.silent_mark.engine import constants as C  # noqa: N812
from src.plugins.games.silent_mark.engine.resolve import (
    get_roles_from_settings,
    record_death,
    validate_game_settings,
)
from src.plugins.games.silent_mark.engine.types import PlayerDict
from src.plugins.games.silent_mark.game import SilentMarkGame
from src.testing.harness import GameTestHarness

from .test_game_flow import FakePlayer


def _player(
    pid: str,
    seat: int,
    role: str,
    faction: str,
    *,
    alive: bool = True,
    items: list[dict] | None = None,
) -> PlayerDict:
    return {
        "pid": pid,
        "nickname": f"P{seat}",
        "seat": seat,
        "role": role,
        "faction": faction,
        "alive": alive,
        "items": items or [],
        "role_state": {},
        "ai": False,
    }


def _item(item_type: str, value: int | str = "") -> dict:
    return {"type": item_type, "value": value, "revealed": False}


# =====================================================================
# 猎犬哨
# =====================================================================
def test_hound_whistle_snapshots_the_wolves_left_alive() -> None:
    whistle = _item(C.HOUND_WHISTLE)
    villager = _player("1", 1, C.VILLAGER, C.GOOD, items=[whistle])
    wolf_a = _player("2", 2, C.WEREWOLF, C.EVIL)
    wolf_b = _player("3", 3, C.WOLF_KING, C.EVIL)
    state = {"round": 3, "players": [villager, wolf_a, wolf_b]}

    record = record_death(state, villager, C.DEATH_ATTACKED)

    assert whistle["value"] == 2
    assert whistle["revealed"] is True
    # 遗物快照跟着死亡记录一起公开
    assert record["relics"][0]["value"] == 2


def test_hound_whistle_on_a_wolf_does_not_count_itself() -> None:
    """死者是狼时不能把自己算进去：`record_death` 先关 `alive` 再数。"""
    whistle = _item(C.HOUND_WHISTLE)
    wolf = _player("1", 1, C.WEREWOLF, C.EVIL, items=[whistle])
    other = _player("2", 2, C.VILLAGER, C.GOOD)
    state = {"round": 1, "players": [wolf, other]}

    record_death(state, wolf, C.DEATH_EXILED)

    assert whistle["value"] == 0


def test_other_items_keep_their_value() -> None:
    """快照只碰猎犬哨：月光石的计数、天平徽章的中文/字符串值都不能被覆盖。"""
    moon = _item(C.MOONSTONE, 4)
    balance = _item(C.BALANCE, "balanced")
    villager = _player("1", 1, C.VILLAGER, C.GOOD, items=[moon, balance])
    state = {"round": 2, "players": [villager, _player("2", 2, C.WEREWOLF, C.EVIL)]}

    record_death(state, villager, C.DEATH_POISONED)

    assert moon["value"] == 4
    assert balance["value"] == "balanced"


# =====================================================================
# 12 套预设逐个校验
# =====================================================================
def test_every_preset_is_valid_and_has_a_sane_player_count() -> None:
    """M3 验收项：12 套板子逐个过校验，且人数等于角色总和。"""
    assert len(C.PRESETS) == 12
    for key, preset in C.PRESETS.items():
        total = sum(preset.roles.values())
        assert C.MIN_PLAYERS <= total <= C.MAX_PLAYERS, key
        settings = {"mode": "preset", "preset": key}
        ok, reason = validate_game_settings(settings)
        assert ok, f"{key} 校验失败：{reason}"
        # 摊平后的角色数必须与人头数一致（房间"开始"就是靠这个对齐的）
        assert len(get_roles_from_settings(settings)) == total


# =====================================================================
# 自定义板子
# =====================================================================
def test_illegal_custom_boards_are_rejected() -> None:
    cases = [
        ({C.WEREWOLF: 3, C.VILLAGER: 3}, "好人"),  # 好人必须多于狼
        ({C.SEER: 1, C.VILLAGER: 4}, "狼"),  # 至少要 1 狼
        ({C.WEREWOLF: 1, C.SEER: 1, C.WITCH: 1, C.HUNTER: 1}, "平民"),  # 屠边两类都要有
        ({C.WEREWOLF: 1, C.SEER: 1, C.VILLAGER: 12}, "人数"),  # 超过 12 人
        ({C.WEREWOLF: 1, "不存在的角色": 1, C.VILLAGER: 3}, "未知角色"),
    ]
    for roles, keyword in cases:
        ok, reason = validate_game_settings(
            {"mode": "custom", "roles": roles, "win_condition": C.WIN_EDGE}
        )
        assert not ok, roles
        assert keyword in reason, (roles, reason)


async def test_custom_board_actually_starts_with_the_given_roles() -> None:
    """自定义板子能开局，且 roles / 胜负条件 / 物品开关都按 config 生效。"""
    config = {
        "mode": "custom",
        "roles": {C.WEREWOLF: 1, C.SEER: 1, C.WITCH: 1, C.VILLAGER: 3},
        "win_condition": C.WIN_CITY,
        "item_pool": [C.MOONSTONE],
    }
    fake = FakePlayer(wolf_target_role=C.VILLAGER, witch="不用")
    harness = GameTestHarness(
        SilentMarkGame,
        players=[1001, 1002, 1003, 1004, 1005, 1006],
        config=config,
    )
    fake.harness = harness
    async with harness:
        with patch.object(session, "ask", fake.ask):
            await harness.start()

    assert harness.runner is not None
    state = harness.runner.ctx.state
    settings = state["settings"]
    assert settings["mode"] == "custom"
    assert settings["roles"][C.VILLAGER] == 3
    assert state["win_condition"] == C.WIN_CITY
    assert len(state["players"]) == 6
    # 物品池只给了月光石 → 每个人手里只能有月光石
    assert {item["type"] for p in state["players"] for item in p["items"]} <= {C.MOONSTONE}


async def test_items_can_be_switched_off_per_room() -> None:
    fake = FakePlayer()
    harness = GameTestHarness(
        SilentMarkGame,
        players=[1001, 1002, 1003, 1004],
        config={"mode": "4standard", "items": False},
    )
    fake.harness = harness
    async with harness:
        with patch.object(session, "ask", fake.ask):
            await harness.start()

    assert harness.runner is not None
    state = harness.runner.ctx.state
    assert all(p["items"] == [] for p in state["players"])
