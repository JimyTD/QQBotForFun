"""红警2斗蛐蛐 —— 接口冒烟测试（**不打 `ra2` 标记，每次都跑**）。

红警玩法已基本不再迭代，重量级战斗模拟测试默认跳过（见 `conftest.py`）。
但玩法**仍在线上**，所以必须留一条极快的兜底：确保改动 `core.game_base` /
`core.session` / `core.economy` 接口时，ra2 插件不会静默失配到线上才炸。

只做静态断言（导入 + 注册 + 元信息 + 模式解析），不跑模拟器，耗时 <1s。
"""

from __future__ import annotations

from core.game_base import GameBase, get_game_class, resolve_mode


def test_plugin_imports_and_registers():
    """导入插件即注册到大厅；接口签名变化会在这里立刻暴露。"""
    import plugins.games.ra2_battle.game  # noqa: F401

    cls = get_game_class("ra2_battle")
    assert issubclass(cls, GameBase)


def test_metadata_intact():
    import plugins.games.ra2_battle.game  # noqa: F401

    cls = get_game_class("ra2_battle")
    assert cls.id == "ra2_battle"
    assert cls.name
    assert cls.min_players <= cls.max_players


def test_modes_resolvable():
    """快捷开局用的模式 id / 别名仍然可解析。"""
    import plugins.games.ra2_battle.game  # noqa: F401

    modes = get_game_class("ra2_battle").MODES
    assert {m.id for m in modes} >= {"bet", "duel"}
    assert resolve_mode(list(modes), "duel") is not None
    assert resolve_mode(list(modes), "红警单挑") is not None


def test_broadcast_config_key_shared_with_aoe3():
    """红警播报模式复用 aoe3 的群配置键 —— 改键名时这里会响。"""
    from plugins.games.ra2_battle.broadcaster import BROADCAST_MODE_CONFIG_KEY

    assert BROADCAST_MODE_CONFIG_KEY == "aoe3_battle.broadcast_mode"
