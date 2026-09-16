"""板子与房间配置校验。

对应源项目 ``shared/validators.ts`` + ``shared/constants.ts`` 的 PRESETS。
"""

from __future__ import annotations

import re

import pytest

from src.plugins.games.silent_mark.engine import constants as C  # noqa: N812
from src.plugins.games.silent_mark.engine.resolve import (
    get_roles_from_settings,
    get_total_players_from_settings,
    is_mark_reason_allowed_for_identity,
    validate_game_settings,
)


def _settings(
    *,
    mode: str = "preset",
    preset: str | None = None,
    roles: dict[str, int] | None = None,
    win: str = C.WIN_EDGE,
) -> dict:
    return {
        "mode": mode,
        "preset": preset,
        "roles": roles or {},
        "win_condition": win,
        "items": {"enabled": True, "pool": list(C.BASIC_ITEM_POOL)},
    }


# =====================================================================
# 预设板子
# =====================================================================
def test_every_preset_is_valid_and_matches_its_name():
    """12 套预设板子全部合法，且人数与名字里的数字一致。"""
    for key in C.PRESETS:
        ok, error = validate_game_settings(_settings(preset=key))
        assert ok, f"{key} 应当合法：{error}"

        expected = int(re.match(r"\d+", key).group())  # type: ignore[union-attr]
        assert get_total_players_from_settings(_settings(preset=key)) == expected, key

        assert len(get_roles_from_settings(_settings(preset=key))) == expected, key


def test_every_preset_has_a_label():
    assert set(C.PRESET_LABELS) == set(C.PRESETS)


def test_only_6standard_defaults_to_city_win():
    """6 人标准局是唯一默认屠城的板子，其余默认屠边。"""
    for key, preset in C.PRESETS.items():
        expected = C.WIN_CITY if key == "6standard" else C.WIN_EDGE
        assert preset.win_condition == expected, key


def test_unknown_preset_is_rejected():
    ok, error = validate_game_settings(_settings(preset="99standard"))
    assert not ok
    assert error == "无效的预设模板"


def test_preset_mode_without_preset_name_is_rejected():
    ok, error = validate_game_settings(_settings(preset=None))
    assert not ok
    assert error == "无效的预设模板"


# =====================================================================
# 自定义板子
# =====================================================================
def test_custom_board_is_valid():
    ok, error = validate_game_settings(
        _settings(mode="custom", roles={C.WEREWOLF: 2, C.SEER: 1, C.WITCH: 1, C.VILLAGER: 2})
    )
    assert ok, error


@pytest.mark.parametrize(
    ("roles", "expected_error"),
    [
        ({C.WEREWOLF: 1, C.VILLAGER: 2}, "总人数不能少于 4 人"),
        ({C.WEREWOLF: 4, C.VILLAGER: 9}, "总人数不能超过 12 人"),
        ({C.SEER: 1, C.VILLAGER: 3}, "至少需要 1 个狼人"),
        ({C.WEREWOLF: 2, C.VILLAGER: 2}, "好人数量必须多于狼人数量"),
        ({C.WEREWOLF: 1, "dragon": 3}, "未知角色：dragon"),
        # 人数与狼人数量都要先合法，才会走到「角色数量」校验
        ({C.WEREWOLF: 1, C.VILLAGER: -1, C.SEER: 2, C.WITCH: 2}, "角色数量不合法：villager"),
        ({C.WEREWOLF: 1, C.VILLAGER: 1.5, C.SEER: 2, C.WITCH: 1}, "角色数量不合法：villager"),
        # 屠边模式必须两类角色都存在（源项目 502ef26 同步修正）
        ({C.WEREWOLF: 1, C.VILLAGER: 3}, "屠边模式至少需要 1 个神职"),
        ({C.WEREWOLF: 1, C.SEER: 2, C.WITCH: 1}, "屠边模式至少需要 1 个平民"),
    ],
)
def test_invalid_custom_boards(roles, expected_error):
    ok, error = validate_game_settings(_settings(mode="custom", roles=roles))
    assert not ok
    assert error == expected_error


def test_wolf_king_counts_as_wolf():
    """白狼王算狼人：1 白狼王 + 1 狼人 时"至少 1 狼"满足。"""
    ok, error = validate_game_settings(
        _settings(mode="custom", roles={C.WOLF_KING: 1, C.SEER: 1, C.WITCH: 1, C.VILLAGER: 1})
    )
    assert ok, error


def test_custom_roles_are_flattened_in_insertion_order():
    roles = {C.WEREWOLF: 2, C.SEER: 1}
    assert get_roles_from_settings(_settings(mode="custom", roles=roles)) == [
        C.WEREWOLF,
        C.WEREWOLF,
        C.SEER,
    ]


def test_edge_class_requirement_only_applies_to_edge_mode():
    """同样是 1 狼 + 3 平民：屠边被拒（会开局即判狼胜），屠城合法。"""
    ok, error = validate_game_settings(
        _settings(mode="custom", roles={C.WEREWOLF: 1, C.VILLAGER: 3}, win=C.WIN_EDGE)
    )
    assert not ok
    assert error == "屠边模式至少需要 1 个神职"

    ok, error = validate_game_settings(
        _settings(mode="custom", roles={C.WEREWOLF: 1, C.VILLAGER: 3}, win=C.WIN_CITY)
    )
    assert ok, error


def test_every_edge_preset_has_both_classes():
    """新校验不能误伤预设板子：所有屠边预设都必须同时有神职与平民。

    这条同时防止以后改板子数据时悄悄引入"开局即判狼胜"的配置。
    """
    for key, preset in C.PRESETS.items():
        if preset.win_condition != C.WIN_EDGE:
            continue
        assert any(role in C.SPECIAL_ROLES for role in preset.roles), key
        assert C.VILLAGER in preset.roles, key


def test_special_roles_are_exactly_the_seven_gods():
    """神职集合是**跨实现标识符**（屠边判定用），源项目已核对含白痴与骑士。"""
    assert C.SPECIAL_ROLES == frozenset(
        {C.SEER, C.WITCH, C.HUNTER, C.GUARD, C.GRAVEDIGGER, C.FOOL, C.KNIGHT}
    )
    assert C.WOLF_ROLES == frozenset({C.WEREWOLF, C.WOLF_KING})


# =====================================================================
# 标记理由权限（转写自源项目 p0Rules.test.ts 的「标记理由权限」三例）
# =====================================================================
def test_common_reason_available_to_every_identity():
    assert is_mark_reason_allowed_for_identity("平民", C.REASON_INTUITION) is True


def test_special_reason_requires_matching_claimed_identity():
    assert is_mark_reason_allowed_for_identity("狼人", C.REASON_INVESTIGATION) is False
    assert is_mark_reason_allowed_for_identity("预言家", C.REASON_INVESTIGATION) is True
    assert is_mark_reason_allowed_for_identity("守墓人", C.REASON_INVESTIGATION) is True
    assert is_mark_reason_allowed_for_identity("女巫", C.REASON_POTION_RESULT) is True
    assert is_mark_reason_allowed_for_identity("预言家", C.REASON_POTION_RESULT) is False


def test_wolf_can_fake_seer_and_use_investigation_reason():
    """狼人诈称预言家后可以使用【查验结论】——权限只看申报身份。"""
    assert is_mark_reason_allowed_for_identity("预言家", C.REASON_INVESTIGATION) is True


def test_unknown_reason_is_rejected():
    assert is_mark_reason_allowed_for_identity("平民", "unknown_reason") is False
