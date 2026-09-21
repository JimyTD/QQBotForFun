"""斗蛐蛐公开模式名只保留短中文主路径。"""
from __future__ import annotations

from src.plugins.games.aoe3_battle.game import AoE3BattleGame


def test_mode_aliases_keep_only_short_public_names():
    aliases = {mode.id: mode.aliases for mode in AoE3BattleGame.MODES}

    assert aliases["duel"] == ("单挑",)
    assert aliases["blacklist"] == ("乱斗",)
    assert aliases["civ_war"] == ("国战",)
    assert aliases["custom"] == ()
    assert aliases["rival"] == ("王中王",)
    assert aliases["rival_tournament"] == ("锦标赛",)


def test_removed_mode_aliases_are_not_registered():
    all_aliases = {
        alias
        for mode in AoE3BattleGame.MODES
        for alias in mode.aliases
    }

    assert not {
        "1v1", "duel", "黑名单", "黑名单乱斗", "blacklist",
        "自选", "宿敌", "宿敌挑战", "王中王锦标赛", "tournament",
    } & all_aliases
