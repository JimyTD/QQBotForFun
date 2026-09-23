"""High-level replay generation for a battle result."""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from core import session

from .model import Replay
from .renderer import ReplayRenderer

logger = logging.getLogger("aoe3_battle.replay.service")


async def _retry_delay() -> None:
    await asyncio.sleep(1)


def render_replay(replay: Replay) -> bytes:
    """Render a replay to H.264 MP4 bytes."""
    return ReplayRenderer().render(replay)


def render_replays(replays: list[Replay]) -> bytes:
    """Render one or more replays into a single video."""
    return ReplayRenderer().render_many(replays)


def render_replay_file(replay: Replay, path: Path) -> Path:
    """Render a replay to a file, creating the parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return ReplayRenderer().render_to_path(replay, path)


async def generate_replay_video(replay: Replay) -> bytes:
    """Render without blocking the bot event loop."""
    return await asyncio.to_thread(render_replay, replay)

async def generate_replays_video(replays: list[Replay]) -> bytes:
    """Render one or more replays without blocking the bot event loop."""
    return await asyncio.to_thread(render_replays, replays)


async def broadcast_replay_video(group_id: int, video: bytes) -> bool:
    """Send a rendered replay to a group."""
    b64 = base64.b64encode(video).decode()
    message = Message(MessageSegment.video(f"base64://{b64}"))
    last_exc: Exception | None = None
    for attempt in range(1, 3):
        try:
            await session.broadcast(group_id, message)
            return True
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "battle replay upload attempt %d/2 failed: %s",
                attempt,
                exc,
            )
            if attempt == 1:
                await _retry_delay()
    logger.warning("battle replay upload failed: %s", last_exc)
    return False


async def broadcast_replay(group_id: int, replay: Replay) -> bool:
    """Render and send one replay video to a group."""
    try:
        video = await generate_replay_video(replay)
    except Exception as exc:
        logger.warning("battle replay generation failed: %s", exc, exc_info=True)
        return await _broadcast_replay_failure(group_id)
    return await broadcast_replay_video(group_id, video)


async def broadcast_replays(group_id: int, replays: list[Replay]) -> bool:
    """Render and send one combined video for a set of replays."""
    try:
        video = await generate_replays_video(replays)
    except Exception as exc:
        logger.warning("battle replay generation failed: %s", exc, exc_info=True)
        return await _broadcast_replay_failure(group_id)
    return await broadcast_replay_video(group_id, video)


async def _broadcast_replay_failure(group_id: int) -> bool:
    try:
        await session.broadcast(group_id, "⚠️ 战场回放生成失败，文字战报如下")
    except Exception:
        logger.debug("failed to broadcast replay fallback notice", exc_info=True)
    return False
