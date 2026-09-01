"""海龟汤购买提示：应直接揭示未发现的关键线索原文。"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from core.types import GameContext, User, new_session_id
from src.plugins.games.turtle_soup.game import (
    TurtleSoupGame,
    canonical_discovered_clues,
    clue_progress,
)


def _ctx(*, key_clues: list[str] | None = None) -> GameContext:
    clues = key_clues or ["王子其实想杀国王", "杯子里有毒"]
    return GameContext(
        session_id=new_session_id(),
        game_id="turtle_soup",
        group_id=9001,
        host_id=1001,
        players=[User(qq_id=1001, nickname="P1001", group_id=9001)],
        started_at=datetime.utcnow(),
        config={},
        state={
            "puzzle": {
                "id": 1,
                "title": "测试汤",
                "surface": "汤面",
                "truth": "汤底",
                "key_clues": clues,
            },
            "hints_purchased": [],
            "hit_clue_idx": [],
        },
    )


@pytest.mark.asyncio
async def test_handle_hint_reveals_key_clue_text() -> None:
    game = TurtleSoupGame()
    ctx = _ctx()

    with patch(
        "src.plugins.games.turtle_soup.game.eco_deduct",
        AsyncMock(return_value=None),
    ), patch(
        "src.plugins.games.turtle_soup.game.db_session",
        _fake_db_session(),
    ):
        text = await game.handle_hint(ctx, 1001)

    assert text == "王子其实想杀国王"
    assert ctx.state["hints_purchased"] == [0]
    assert ctx.state["hit_clue_idx"] == [0]
    assert clue_progress(ctx) == (1, 2)


@pytest.mark.asyncio
async def test_handle_hint_skips_already_hit_clues() -> None:
    game = TurtleSoupGame()
    ctx = _ctx()
    ctx.state["hit_clue_idx"] = [0]

    with patch(
        "src.plugins.games.turtle_soup.game.eco_deduct",
        AsyncMock(return_value=None),
    ), patch(
        "src.plugins.games.turtle_soup.game.db_session",
        _fake_db_session(),
    ):
        text = await game.handle_hint(ctx, 1001)

    assert text == "杯子里有毒"
    assert ctx.state["hints_purchased"] == [1]
    assert sorted(ctx.state["hit_clue_idx"]) == [0, 1]


@pytest.mark.asyncio
async def test_handle_hint_all_revealed() -> None:
    game = TurtleSoupGame()
    ctx = _ctx(key_clues=["仅有一条"])
    ctx.state["hit_clue_idx"] = [0]

    with patch(
        "src.plugins.games.turtle_soup.game.session.broadcast",
        AsyncMock(),
    ) as broadcast:
        text = await game.handle_hint(ctx, 1001)

    assert text is None
    assert broadcast.await_count == 1
    assert "都已揭示" in broadcast.await_args.args[1]


def _fake_db_session():
    """最小可用的 async context manager，吞掉 SoupQuestion 写入。"""

    class _Sess:
        def add(self, _obj) -> None:
            return None

        async def get(self, *_a, **_k):
            return None

    class _CM:
        async def __aenter__(self):
            return _Sess()

        async def __aexit__(self, *args):
            return None

    return _CM


def test_canonical_discovered_clues_excludes_dynamic_hints_and_purchased() -> None:
    clues = ["我是爸爸捡来的孩子", "爸爸患有阿尔兹海默症", "我早就知道我的特工妈妈就是你"]

    assert canonical_discovered_clues(clues, [0, 2, 2], [0]) == [
        "我早就知道我的特工妈妈就是你"
    ]
