"""Unit icon compositing and message delivery regression tests."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock

import nonebot
import pytest
from PIL import Image

from src.plugins.aoe3.icons import (
    BLUE_ICON_BACKGROUND,
    PLAYER_ICON_BACKGROUNDS,
    QUERY_ICON_BACKGROUND,
    RED_ICON_BACKGROUND,
    render_icon_png,
)


def test_backgrounds_match_aoe3_de_friend_or_foe_palette():
    assert QUERY_ICON_BACKGROUND == (0, 0, 0)
    assert RED_ICON_BACKGROUND == (230, 40, 40)
    assert BLUE_ICON_BACKGROUND == (75, 75, 230)


@pytest.fixture
def icon_path(tmp_path: Path) -> Path:
    path = tmp_path / "unit.png"
    icon = Image.new("RGBA", (3, 1))
    icon.putdata([(200, 100, 50, 0), (200, 100, 50, 128), (200, 100, 50, 255)])
    icon.save(path)
    return path


@pytest.mark.parametrize(
    "background",
    [QUERY_ICON_BACKGROUND, RED_ICON_BACKGROUND, BLUE_ICON_BACKGROUND, *PLAYER_ICON_BACKGROUNDS],
)
def test_composite_preserves_opaque_pixels_and_source(icon_path, background):
    original = icon_path.read_bytes()
    with Image.open(BytesIO(render_icon_png(icon_path, background))) as rendered:
        assert rendered.format == "PNG"
        assert rendered.mode == "RGB"
        assert rendered.size == (3, 1)
        assert rendered.getpixel((0, 0)) == background
        assert rendered.getpixel((1, 0)) == tuple(
            (foreground * 128 + backdrop * 127 + 127) // 255
            for foreground, backdrop in zip((200, 100, 50), background, strict=True)
        )
        assert rendered.getpixel((2, 0)) == (200, 100, 50)
    assert icon_path.read_bytes() == original


def test_opaque_rgb_icon_unchanged(tmp_path):
    path = tmp_path / "opaque.png"
    Image.new("RGB", (2, 2), (60, 120, 180)).save(path)
    with Image.open(BytesIO(render_icon_png(path, RED_ICON_BACKGROUND))) as rendered:
        assert rendered.getextrema() == ((60, 60), (120, 120), (180, 180))


def test_palette_transparency(tmp_path):
    path = tmp_path / "palette.png"
    icon = Image.new("P", (2, 1))
    icon.putpalette([200, 100, 50, 60, 120, 180] + [0] * 762)
    icon.putdata([0, 1])
    icon.save(path, transparency=0)
    with Image.open(BytesIO(render_icon_png(path, BLUE_ICON_BACKGROUND))) as rendered:
        assert rendered.getpixel((0, 0)) == BLUE_ICON_BACKGROUND
        assert rendered.getpixel((1, 0)) == (60, 120, 180)


def _assert_message_icons(message, background, count):
    images = [segment for segment in message if segment.type == "image"]
    assert len(images) == count
    for segment in images:
        encoded = segment.data["file"]
        assert encoded.startswith("base64://")
        with Image.open(BytesIO(base64.b64decode(encoded.removeprefix("base64://")))) as icon:
            assert icon.mode == "RGB"
            assert icon.getpixel((0, 0)) == background
            assert icon.getpixel((2, 0)) == (200, 100, 50)


@pytest.mark.parametrize("count", [0, 1, 2])
async def test_query_and_compare_send_black_icons(icon_path, count):
    nonebot.init()
    from src.plugins.aoe3.commands import _send_with_icons

    bot = AsyncMock()
    event = object()
    await _send_with_icons(bot, event, "unit details", [icon_path] * count)

    bot.send.assert_awaited_once()
    sent_event, message = bot.send.await_args.args
    assert sent_event is event
    if count:
        _assert_message_icons(message, QUERY_ICON_BACKGROUND, count)
        assert message.extract_plain_text() == "unit details"
    else:
        assert message == "unit details"


@pytest.mark.parametrize("count", [1, 2])
async def test_battle_sends_single_opening_card(icon_path, monkeypatch, count):
    from core.types import GameContext
    from src.plugins.aoe3.models import Unit
    from src.plugins.games.aoe3_battle import game as game_module
    from src.plugins.games.aoe3_battle.lineup import Lineup, MatchLineup, UnitSlot

    unit = Unit(id="test", name="Test", name_en="Test", hp=100)
    lineup = Lineup(slots=[UnitSlot(unit=unit, count=1) for _ in range(count)])
    match = MatchLineup(red=lineup, blue=lineup, mode="bet", age=3)
    game = game_module.AoE3BattleGame()
    game._match = match
    monkeypatch.setattr(game_module.UnitRepo, "get_icon_path", lambda self, unit: icon_path)
    rendered = Image.new("RGB", (4, 4), RED_ICON_BACKGROUND)
    output = BytesIO()
    rendered.save(output, format="PNG")
    rich = AsyncMock()
    monkeypatch.setattr(game_module.session, "broadcast_rich", rich)
    monkeypatch.setattr(game_module.session, "broadcast", AsyncMock())
    monkeypatch.setattr(
        game_module,
        "render_match_opening",
        lambda **_kwargs: output.getvalue(),
    )
    ctx = GameContext(
        session_id="ICON",
        game_id="aoe3_battle",
        group_id=42,
        host_id=1,
        players=[],
        started_at=datetime.now(UTC),
        state={
            "mode": "bet",
            "red_army": [{"unit_name": "Test", "count": count}],
            "blue_army": [{"unit_name": "Test", "count": count}],
        },
    )

    await game.on_start(ctx)

    rich.assert_awaited_once()
    group_id, message, fallback = rich.await_args.args
    assert group_id == 42
    images = [segment for segment in message if segment.type == "image"]
    assert len(images) == 1
    encoded = images[0].data["file"]
    assert encoded.startswith("base64://")
    with Image.open(BytesIO(base64.b64decode(encoded.removeprefix("base64://")))) as image:
        assert image.size == (4, 4)
    assert "普通对阵" in fallback
