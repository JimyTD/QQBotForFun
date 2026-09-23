"""Replay recording, rendering, and delivery tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from core.types import GameContext
from src.plugins.games.aoe3_battle.battle_contract import ArmySlot, EventType
from src.plugins.games.aoe3_battle.game import AoE3BattleGame
from src.plugins.games.aoe3_battle.replay.model import Replay
from src.plugins.games.aoe3_battle.replay.recorder import ReplaySession
from src.plugins.games.aoe3_battle.replay.renderer import ReplayRenderer
from src.plugins.games.aoe3_battle.replay.service import (
    REPLAY_DIR,
    broadcast_replay_video,
    cleanup_replay_files,
)


@dataclass
class _Event:
    tick: int
    time: float
    event_type: EventType
    data: dict


@dataclass
class _Result:
    winner: object
    events: list
    ticks: int
    duration: float
    red_alive: list
    blue_alive: list
    red_dead: list
    blue_dead: list
    red_army: list
    blue_army: list
    red_count: int
    blue_count: int
    timeout: bool = False

    @property
    def red_unit(self):
        return self.red_army[0].unit

    @property
    def blue_unit(self):
        return self.blue_army[0].unit


def _frame(tick: int, *, target_id: int | None = None, extra: dict | None = None) -> dict:
    return {
        "tick": tick,
        "time": tick * 0.1,
        "status": "running",
        "winner": None,
        "field": {"width": 36.0, "height": 36.0},
        "sides": {
            "red": {"alive": 1, "initial_count": 1, "hp_ratio": 0.5},
            "blue": {"alive": 1, "initial_count": 1, "hp_ratio": 0.4},
        },
        "summary": {"debug_only": True},
        "units": [
            {
                "id": 1,
                "side": "red",
                "name": "火枪手",
                "x": 10.0,
                "y": 12.0,
                "hp": 50.0,
                "max_hp": 100.0,
                "stopped": True,
                "target_id": target_id,
                "radius": 0.45,
                "steer_reason": "debug",
            },
            {
                "id": 2,
                "side": "blue",
                "name": "长枪兵",
                "x": 15.0,
                "y": 12.0,
                "hp": 40.0,
                "max_hp": 100.0,
                "stopped": False,
                "target_id": 1,
                "radius": 0.45,
                "steer_reason": "debug",
            },
        ]
        if target_id is not None
        else [],
    }


def _replay() -> Replay:
    session = ReplaySession(
        session_id="test",
        mode="bet",
        match_label="火枪手 vs 长枪兵",
        red_label="火枪手×2",
        blue_label="长枪兵×2",
        red_count=2,
        blue_count=2,
    )
    session.frame_callback(_frame(0))
    session.frame_callback(_frame(1, target_id=2))
    session.frame_callback(_frame(2, target_id=1))
    result = _Result(
        winner=None,
        events=[
            _Event(
                1,
                0.1,
                EventType.ATTACK,
                {"target_id": 2, "attacker_name": "火枪手", "target_name": "长枪兵"},
            ),
            _Event(
                2,
                0.2,
                EventType.DEATH,
                {
                    "soldier_id": 2,
                    "soldier_name": "长枪兵",
                    "killer_name": "火枪手",
                },
            ),
        ],
        ticks=2,
        duration=0.2,
        red_alive=[],
        blue_alive=[],
        red_dead=[],
        blue_dead=[],
        red_army=[],
        blue_army=[],
        red_count=2,
        blue_count=2,
    )
    return session.finish(result)


def test_recorder_keeps_only_public_replay_fields() -> None:
    replay = _replay()

    assert len(replay.frames) == 3
    assert replay.frames[1].units[0]["target_id"] == 2
    assert "steer_reason" not in replay.frames[1].units[0]
    assert replay.frames[1].summary == {}
    death = next(event for event in replay.events if event.event_type == "DEATH")
    assert (death.x, death.y) == (15.0, 12.0)


def test_recorder_backfills_radius_for_legacy_frames() -> None:
    session = ReplaySession(
        session_id="legacy-frame",
        mode="bet",
        red_count=1,
        blue_count=1,
    )
    frame = _frame(0, target_id=2)
    for unit in frame["units"]:
        unit.pop("radius")

    session.frame_callback(frame)

    assert session.recorder.frames[0].units[0]["radius"] == 0.45


def test_renderer_produces_expected_frame_sequence() -> None:
    replay = _replay()
    frames = list(ReplayRenderer().iter_images(replay))

    assert len(frames) == 2 * 10 + 2 + 3 * 10
    assert all(frame.size == (960, 540) for frame in frames)
    assert frames[20].getpixel((480, 270)) != (13, 20, 17)


def test_renderer_compresses_long_replay_output_frames() -> None:
    session = ReplaySession(
        session_id="long",
        mode="bet",
        red_count=1,
        blue_count=1,
    )
    for tick in range(0, 801, 10):
        session.frame_callback(_frame(tick, target_id=2))
    replay = session.recorder.build()

    frames = list(ReplayRenderer().iter_images(replay))

    assert len(frames) <= 36 * 10 + 5


def test_renderer_encodes_mp4() -> None:
    video = ReplayRenderer().render(_replay())

    assert video.startswith(b"\x00\x00\x00")
    assert b"ftyp" in video[:32]
    assert len(video) > 1000


@pytest.mark.asyncio
async def test_broadcast_replay_video_retries_then_succeeds(monkeypatch) -> None:
    attempts = 0

    async def fake_broadcast(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary")

    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.replay.service.session.broadcast",
        fake_broadcast,
    )
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.replay.service._retry_delay",
        lambda: asyncio.sleep(0),
    )

    assert await broadcast_replay_video(1, b"video") is True
    assert attempts == 2


@pytest.mark.asyncio
async def test_broadcast_replay_video_uses_base64_for_napcat(monkeypatch) -> None:
    sent = []

    async def fake_broadcast(_group_id, message, **_kwargs):
        sent.append(message)

    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.replay.service.session.broadcast",
        fake_broadcast,
    )

    assert await broadcast_replay_video(1, b"video") is True
    assert sent[0].extract_plain_text() == ""
    video_segment = sent[0][0]
    assert video_segment.type == "video"
    assert video_segment.data["file"] == "base64://dmlkZW8="


def test_renderer_rejects_empty_replay() -> None:
    replay = Replay(
        session_id="empty",
        mode="bet",
        match_label="",
        red_label="",
        blue_label="",
        red_count=0,
        blue_count=0,
        frames=[],
        events=[],
    )

    with pytest.raises(ValueError, match="no frames"):
        ReplayRenderer().render(replay)


def test_renderer_image_is_png() -> None:
    renderer = ReplayRenderer()
    image = Image.open(BytesIO(renderer._render_scene_png(_replay())))

    assert image.format == "PNG"
    assert image.size == (960, 540)


def test_cleanup_replay_files_removes_expired_and_excess(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.replay.service.REPLAY_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.replay.service.REPLAY_MAX_FILES",
        1,
    )
    old = tmp_path / "old.mp4"
    new = tmp_path / "new.mp4"
    old.write_bytes(b"old")
    new.write_bytes(b"new")
    old.touch()
    new.touch()

    assert cleanup_replay_files(now=old.stat().st_mtime + 2 * 24 * 60 * 60) == 2
    assert not old.exists()
    assert not new.exists()


def test_replay_dir_is_under_logs() -> None:
    assert REPLAY_DIR.parts[-3:] == ("logs", "aoe3_battle", "replays")


@pytest.mark.asyncio
async def test_generic_match_start_sends_one_opening_image(monkeypatch) -> None:
    rich_messages = []
    plain_messages = []

    async def fake_rich(_group_id, message, fallback):
        rich_messages.append((message, fallback))

    async def fake_plain(_group_id, message, **_kwargs):
        plain_messages.append(message)

    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game.session.broadcast_rich",
        fake_rich,
    )
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game.session.broadcast",
        fake_plain,
    )
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game.render_match_opening",
        lambda **_kwargs: b"png",
    )

    game = AoE3BattleGame()
    game._match = SimpleNamespace(
        mode="bet",
        age=3,
        rival_theme=None,
        red=SimpleNamespace(
            slots=[SimpleNamespace(unit=SimpleNamespace(name="火枪手"), count=1)]
        ),
        blue=SimpleNamespace(
            slots=[SimpleNamespace(unit=SimpleNamespace(name="长枪兵"), count=1)]
        ),
    )
    ctx = GameContext(
        session_id="opening-card",
        game_id="aoe3_battle",
        group_id=1,
        host_id=2,
        players=[],
        started_at=__import__("datetime").datetime.utcnow(),
        config={},
    )
    ctx.state["mode"] = "bet"

    await game.on_start(ctx)

    assert len(rich_messages) == 1
    assert plain_messages == []


@pytest.mark.asyncio
async def test_tournament_only_records_final(monkeypatch) -> None:
    callbacks: list[object] = []
    sent_videos: list[list] = []

    class FakeReplaySession:
        def __init__(self, **kwargs):
            self.recorder = SimpleNamespace(match_label=kwargs["match_label"])

        def frame_callback(self, _frame):
            return None

        def finish(self, _result):
            return object()

    class FakeSimulator:
        def __init__(self, **kwargs):
            callbacks.append(kwargs.get("frame_callback"))

        def run(self):
            return _Result(
                winner=None,
                events=[],
                ticks=1,
                duration=0.1,
                red_alive=[],
                blue_alive=[],
                red_dead=[],
                blue_dead=[],
                red_army=[
                    ArmySlot(SimpleNamespace(id="a", name="A"), 1)
                ],
                blue_army=[
                    ArmySlot(SimpleNamespace(id="b", name="B"), 1)
                ],
                red_count=1,
                blue_count=1,
            )

    class FakeTournament:
        theme_title = "火枪王"

        def __init__(self):
            self.stage = SimpleNamespace(name="QF")
            self.round = [
                SimpleNamespace(
                    match_id="QF1",
                    label="八强赛",
                    unit_a_idx=0,
                    unit_b_idx=1,
                    loser_idx=1,
                ),
                SimpleNamespace(
                    match_id="FINAL",
                    label="决赛",
                    unit_a_idx=0,
                    unit_b_idx=1,
                    loser_idx=1,
                ),
            ]

        def get_current_round_matches(self):
            return self.round

        def get_unit(self, idx):
            unit = SimpleNamespace(name="火枪手" if idx == 0 else "长枪兵")
            return SimpleNamespace(
                unit=unit,
                display_name=unit.name,
            )

        def record_result(self, *_args):
            return None

        def try_advance(self):
            return None

        def is_bracket_stage(self):
            return False

    async def fake_broadcast(*_args, **_kwargs):
        return None

    async def fake_send_videos(_group_id, replays):
        sent_videos.append(replays)
        return True

    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game.BattleSimulator2D",
        FakeSimulator,
    )
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game.ReplaySession",
        FakeReplaySession,
    )
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game.broadcast_replay",
        fake_send_videos,
    )
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game.session.broadcast",
        fake_broadcast,
    )
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game._unit_cost",
        lambda _unit: 1,
    )
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game.approx_lcm_budget",
        lambda *_args: 1,
    )
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game.battle_resource_loss",
        lambda _result: (0, 0),
    )

    game = AoE3BattleGame()
    game._tournament = FakeTournament()
    ctx = GameContext(
        session_id="tournament",
        game_id="aoe3_battle",
        group_id=1,
        host_id=2,
        players=[],
        started_at=__import__("datetime").datetime.utcnow(),
        config={},
    )
    ctx.state.update(mode="rival_tournament", phase="tournament_fighting")
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game.TournamentStage",
        SimpleNamespace(FINISHED=object()),
    )

    await game._run_tournament_round(ctx)

    assert callbacks == [None, callbacks[1]]
    assert callbacks[1] is not None
    assert len(sent_videos) == 1


@pytest.mark.asyncio
async def test_run_battle_wires_recorder_and_sends_video(monkeypatch) -> None:
    captured_callback = None
    sent_video = False

    class FakeSimulator:
        def __init__(self, **kwargs):
            nonlocal captured_callback
            captured_callback = kwargs["frame_callback"]

        def run(self):
            captured_callback(_frame(0, target_id=2))
            return _Result(
                winner=None,
                events=[],
                ticks=1,
                duration=0.1,
                red_alive=[],
                blue_alive=[],
                red_dead=[],
                blue_dead=[],
                red_army=[
                    ArmySlot(SimpleNamespace(id="musketeer", name="火枪手"), 1)
                ],
                blue_army=[
                    ArmySlot(SimpleNamespace(id="pikeman", name="长枪兵"), 1)
                ],
                red_count=1,
                blue_count=1,
            )

    async def fake_video(_replay):
        return b"video"

    async def fake_broadcast_video(_group_id, video):
        nonlocal sent_video
        sent_video = video == b"video"
        return True

    game = AoE3BattleGame()
    game._match = SimpleNamespace(
        mode="bet",
        rival_theme=None,
        red=SimpleNamespace(
            slots=[SimpleNamespace(unit=SimpleNamespace(name="火枪手"), count=1)],
            total_count=1,
            unit=SimpleNamespace(name="火枪手"),
        ),
        blue=SimpleNamespace(
            slots=[SimpleNamespace(unit=SimpleNamespace(name="长枪兵"), count=1)],
            total_count=1,
            unit=SimpleNamespace(name="长枪兵"),
        ),
        red_civ_name=None,
        blue_civ_name=None,
        red_strategy=None,
        blue_strategy=None,
    )
    ctx = GameContext(
        session_id="replay-test",
        game_id="aoe3_battle",
        group_id=1,
        host_id=2,
        players=[],
        started_at=__import__("datetime").datetime.utcnow(),
        config={},
    )
    ctx.state.update(mode="bet", phase="fighting", bets={})
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game.BattleSimulator2D",
        FakeSimulator,
    )
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game.generate_replay_video",
        fake_video,
    )
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game.broadcast_replay_video",
        fake_broadcast_video,
    )
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game._dump_battle_log",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game.session.broadcast",
        AsyncMock(),
    )
    monkeypatch.setattr(game, "_settle_bets", AsyncMock(return_value=""))

    await game._run_battle(ctx)

    assert captured_callback is not None
    assert sent_video is True


@pytest.mark.asyncio
async def test_run_battle_sends_video_report_then_settlement(monkeypatch) -> None:
    messages: list[str] = []

    class FakeSimulator:
        def __init__(self, **kwargs):
            self.frame_callback = kwargs["frame_callback"]

        def run(self):
            self.frame_callback(_frame(0, target_id=2))
            return _Result(
                winner=None,
                events=[],
                ticks=1,
                duration=0.1,
                red_alive=[],
                blue_alive=[],
                red_dead=[],
                blue_dead=[],
                red_army=[
                    ArmySlot(SimpleNamespace(id="musketeer", name="火枪手"), 1)
                ],
                blue_army=[
                    ArmySlot(SimpleNamespace(id="pikeman", name="长枪兵"), 1)
                ],
                red_count=1,
                blue_count=1,
            )

    async def fake_video(_replay):
        return b"video"

    async def fake_send_video(_group_id, video):
        messages.append("video")
        return True

    async def fake_broadcast(_group_id, message, **kwargs):
        messages.append(str(message))

    game = AoE3BattleGame()
    game._match = SimpleNamespace(
        mode="bet",
        rival_theme=None,
        red=SimpleNamespace(
            slots=[SimpleNamespace(unit=SimpleNamespace(name="火枪手"), count=1)],
            total_count=1,
            unit=SimpleNamespace(name="火枪手"),
        ),
        blue=SimpleNamespace(
            slots=[SimpleNamespace(unit=SimpleNamespace(name="长枪兵"), count=1)],
            total_count=1,
            unit=SimpleNamespace(name="长枪兵"),
        ),
        red_civ_name=None,
        blue_civ_name=None,
        red_strategy=None,
        blue_strategy=None,
    )
    ctx = GameContext(
        session_id="replay-order",
        game_id="aoe3_battle",
        group_id=1,
        host_id=2,
        players=[],
        started_at=__import__("datetime").datetime.utcnow(),
        config={},
    )
    ctx.state.update(mode="bet", phase="fighting", bets={"1": "red"})
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game.BattleSimulator2D",
        FakeSimulator,
    )
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game.generate_replay_video",
        fake_video,
    )
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game.broadcast_replay_video",
        fake_send_video,
    )
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game.session.broadcast",
        fake_broadcast,
    )
    monkeypatch.setattr(
        "src.plugins.games.aoe3_battle.game._dump_battle_log",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(game, "_settle_bets", AsyncMock(return_value="押注结算"))

    await game._run_battle(ctx)

    assert messages[0] == "video"
    assert "战斗结果" in messages[1]
    assert messages[2] == "押注结算"
