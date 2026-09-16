"""M3：自定义板子向导（`custom_setup`）。

向导是**纯交互**，所以这里用假的 `session.choose` / `session.whisper` 驱动它：
按顺序喂"玩家点了几号"，断言它产出的板子 —— 以及不合法时它**会不会挡下来重来**。
"""

from __future__ import annotations

from unittest.mock import patch

from core import session
from src.plugins.games.silent_mark.custom_setup import CAST_ORDER, run_custom_wizard
from src.plugins.games.silent_mark.engine import constants as C  # noqa: N812

HOST = 2001

#: CAST_ORDER 里的下标（写测试时用名字，免得数字对不上）
IDX = {role: index for index, role in enumerate(CAST_ORDER)}


def _drive(*picks: int):
    """按顺序喂给 `session.choose` 的下标；whisper 只记账。"""
    remaining = list(picks)
    whispers: list[str] = []

    async def fake_choose(
        qq_id: int,  # noqa: ARG001
        options: list[str],
        *,
        prompt: str | None = None,
        group_id: int | None = None,  # noqa: ARG001
        timeout: float | None = None,  # noqa: ARG001
        **_kwargs: object,
    ) -> int:
        assert remaining, f"向导多问了一次：{prompt}"
        index = remaining.pop(0)
        assert 0 <= index < len(options), (prompt, index, options)
        return index

    async def fake_whisper(qq_id: int, text: str) -> int:  # noqa: ARG001
        whispers.append(str(text))
        return 1

    return fake_choose, fake_whisper, remaining, whispers


async def test_wizard_builds_a_legal_board() -> None:
    fake_choose, fake_whisper, remaining, whispers = _drive(
        0,  # 人数：第 1 项 = 4 人
        IDX[C.WEREWOLF],
        IDX[C.GUARD],
        IDX[C.WITCH],
        IDX[C.VILLAGER],
        0,  # 屠边
        0,  # 物品开
        0,  # 确认
    )
    with (
        patch.object(session, "choose", fake_choose),
        patch.object(session, "whisper", fake_whisper),
    ):
        board = await run_custom_wizard(HOST)

    assert board is not None
    assert board.roles == {
        C.WEREWOLF: 1,
        C.GUARD: 1,
        C.WITCH: 1,
        C.VILLAGER: 1,
    }
    assert board.player_count == 4
    assert board.win_condition == C.WIN_EDGE
    assert board.items_enabled is True
    assert not remaining, "还有没喂完的选择 = 向导流程和预期不一致"
    # 每落一个座位给一次进度反馈（否则 12 次选择心里没数）
    assert any("4/4" in text for text in whispers)

    config = board.to_config()
    assert config["mode"] == "custom"
    assert config["roles"][C.WITCH] == 1


async def test_illegal_cast_is_rejected_and_wizard_retries() -> None:
    """3 狼 1 好人 → 必须被挡下来（"好人必须多于狼"），而不是开出一局坏棋。"""
    fake_choose, fake_whisper, remaining, whispers = _drive(
        0,  # 4 人
        IDX[C.WEREWOLF],
        IDX[C.WEREWOLF],
        IDX[C.WEREWOLF],
        IDX[C.VILLAGER],
        0,  # 屠边
        0,  # 物品开
        # ↓ 被拒后重来一轮（人数不重问，只重选人）
        IDX[C.WEREWOLF],
        IDX[C.SEER],
        IDX[C.WITCH],
        IDX[C.VILLAGER],
        0,
        0,
        0,  # 确认
    )
    with (
        patch.object(session, "choose", fake_choose),
        patch.object(session, "whisper", fake_whisper),
    ):
        board = await run_custom_wizard(HOST)

    assert board is not None
    assert board.roles == {
        C.WEREWOLF: 1,
        C.SEER: 1,
        C.WITCH: 1,
        C.VILLAGER: 1,
    }
    assert any("不合法" in text for text in whispers)
    assert not remaining


async def test_wizard_cancel_returns_none() -> None:
    fake_choose, fake_whisper, _remaining, _whispers = _drive(
        0,
        IDX[C.WEREWOLF],
        IDX[C.GUARD],
        IDX[C.WITCH],
        IDX[C.VILLAGER],
        0,
        0,
        2,  # 确认那一步选"取消"
    )
    with (
        patch.object(session, "choose", fake_choose),
        patch.object(session, "whisper", fake_whisper),
    ):
        assert await run_custom_wizard(HOST) is None


async def test_wizard_gives_up_when_input_is_unavailable() -> None:
    """拿不到输入（超时/退出/私聊失败/反复答错）→ 返回 None，绝不抛出去打断上层。"""
    from core.errors import TimeoutError as GameTimeoutError

    async def fake_choose(*_args: object, **_kwargs: object) -> int:
        raise GameTimeoutError("nope")

    with patch.object(session, "choose", fake_choose):
        assert await run_custom_wizard(HOST) is None
