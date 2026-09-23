"""High-level replay generation for a battle result."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from pathlib import Path

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from core import session

from .model import Replay
from .renderer import ReplayRenderer

logger = logging.getLogger("aoe3_battle.replay.service")

REPLAY_DIR = Path(__file__).resolve().parents[5] / "logs" / "aoe3_battle" / "replays"
REPLAY_MAX_AGE_SECONDS = 24 * 60 * 60
REPLAY_MAX_FILES = 50
REPLAY_MAX_BYTES = 500 * 1024 * 1024


async def _retry_delay() -> None:
    await asyncio.sleep(1)


def cleanup_replay_files(*, now: float | None = None) -> int:
    """Remove stale replay files and enforce count/size limits."""
    if not REPLAY_DIR.exists():
        return 0
    current = time.time() if now is None else now
    removed = 0
    files = [path for path in REPLAY_DIR.glob("*.mp4") if path.is_file()]
    for path in files:
        try:
            if current - path.stat().st_mtime > REPLAY_MAX_AGE_SECONDS:
                path.unlink()
                removed += 1
        except OSError:
            logger.debug("failed to remove stale replay %s", path, exc_info=True)

    remaining = sorted(
        (path for path in REPLAY_DIR.glob("*.mp4") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
    )
    while len(remaining) > REPLAY_MAX_FILES:
        path = remaining.pop(0)
        try:
            path.unlink()
            removed += 1
        except OSError:
            logger.debug("failed to remove excess replay %s", path, exc_info=True)

    total = sum(path.stat().st_size for path in remaining if path.exists())
    for path in remaining:
        if total <= REPLAY_MAX_BYTES:
            break
        try:
            size = path.stat().st_size
            path.unlink()
            total -= size
            removed += 1
        except OSError:
            logger.debug("failed to remove oversized replay %s", path, exc_info=True)
    return removed


def _save_failed_replay(video: bytes) -> Path:
    """Keep a failed upload locally for diagnostics, subject to cleanup."""
    cleanup_replay_files()
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    path = REPLAY_DIR / f"replay-{int(time.time() * 1000)}.mp4"
    path.write_bytes(video)
    return path


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
    try:
        path = await asyncio.to_thread(_save_failed_replay, video)
        logger.info("failed replay retained for diagnostics: %s", path)
    except OSError:
        logger.debug("failed to retain replay after upload failure", exc_info=True)
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
