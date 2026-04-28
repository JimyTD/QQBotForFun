"""海龟汤游戏配置。"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class TurtleSoupConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GAME_TURTLE_SOUP_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    max_questions: int = 50
    session_timeout_minutes: int = 60
    idle_timeout_minutes: int = 15
    prefer_llm_generation: bool = False
    llm_retry_times: int = 3
    judge_timeout_seconds: int = 30
    claim_timeout_seconds: int = 45
    reward_on_win: int = 100
    penalty_on_lose: int = 0


_config: TurtleSoupConfig | None = None


def get_config() -> TurtleSoupConfig:
    global _config
    if _config is None:
        _config = TurtleSoupConfig()  # type: ignore[call-arg]
    return _config
