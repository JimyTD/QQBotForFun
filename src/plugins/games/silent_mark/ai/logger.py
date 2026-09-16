"""AI 决策日志（移植自源项目 `ai/AILogger.ts`，形态改为 JSON Lines）。

为什么必须有它：AI 的每一步"为什么这么打"事后得能查 —— 提示里喂了什么、
模型回了什么、守卫是否纠正过、最终是否落到兜底。没有这份日志，排查
"AI 表现很怪"就只能靠猜。源项目的 `ai-improvement-plan.md` 也把这类日志
当作调优 AI 的前置条件。

- 目录沿用源项目名：`logs/silent_mark_ai/`（**不写 DB**，计划 §9.1）
- 每局一个 `.jsonl`，按 mtime 只留最近 ``AI_LOG_KEEP`` 局（照抄 `aoe3_battle` 的轮转做法）
- ⚠️ 日志自身出任何问题都**绝不影响对局**：写失败只告警
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from nonebot import logger

#: 与 `aoe3_battle` 同级：<仓库根>/logs/silent_mark_ai/
AI_LOG_DIR = Path(__file__).resolve().parents[5] / "logs" / "silent_mark_ai"
AI_LOG_KEEP = 20


class AILog:
    """一局一份的决策日志。由游戏在 `on_start` 建一份，随 `ctx.state` 走。"""

    def __init__(self, session_id: str, *, root: Path | None = None) -> None:
        self.dir = root or AI_LOG_DIR
        self.path = self.dir / f"{session_id}.jsonl"

    def record(self, kind: str, **fields: Any) -> None:
        """记一次事件（``kind`` 用短标识，如 ``night`` / ``mark`` / ``vote`` / ``guard``）。"""
        payload = {"at": datetime.now().isoformat(timespec="seconds"), "kind": kind}
        payload.update(fields)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        except (OSError, TypeError, ValueError) as exc:
            logger.warning(f"[silent_mark.ai] 决策日志写入失败（已忽略）：{exc!r}")

    def rotate(self) -> None:
        """只留最近 N 局，避免长期运行把磁盘吃掉。"""
        try:
            files = sorted(
                self.dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
            )
            for stale in files[AI_LOG_KEEP:]:
                stale.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(f"[silent_mark.ai] 决策日志轮转失败（已忽略）：{exc!r}")
