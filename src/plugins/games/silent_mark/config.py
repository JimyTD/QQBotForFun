"""静夜标记 · 可调参数。

**超时原则（本仓库大原则，任何游戏都遵守）：AI 有超时，真实玩家没有。**
所以这里的 ``ai_*_timeout`` 只作用于 **AI 补位座位**；真人座位一律永不计时
（``session.ask(timeout=None)``）。

整局兜底**不在这里配**：由全局 ``game_session_timeout_hours``（默认 24 小时）
经 `GameBase.default_session_timeout_seconds` 统一提供。

环境变量前缀 ``GAME_SILENT_MARK_``。
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class SilentMarkConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GAME_SILENT_MARK_")

    # ---- 各阶段的单步等待时长（秒）· **仅 AI 座位** ----
    ai_night_timeout: float = 60.0
    ai_marking_timeout: float = 120.0
    ai_voting_timeout: float = 60.0
    ai_trigger_timeout: float = 60.0

    # ---- 语法错误允许重问的轮数（真人不计时，但没人愿意被无限重问）----
    retry_rounds: int = 2

    # ---- 奖励（胜负双方都给正向奖励，符合"永不负反馈"约定）----
    win_coin: int = 30
    win_score: int = 10
    lose_coin: int = 5
    lose_score: int = 2

    # ---- 消息节流 ----
    # 群里的"对局面板"是**原地更新**（删旧发新），不会新增消息；这里不再另设节流，
    # 真正的速率限制由 `core.session._throttle()` 统一负责。


cfg = SilentMarkConfig()
