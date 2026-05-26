"""应用配置：从 .env / 环境变量加载，统一暴露给全项目。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """主配置对象。在 bot 启动时实例化一次，全局通过 get_settings() 访问。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- App ----------
    app_env: str = "dev"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8080

    admin_qq: str = ""  # 逗号分隔

    # ---------- OneBot ----------
    bot_qq: str = ""
    onebot_access_token: str = "change_me"

    # ---------- Data ----------
    database_url: str = "sqlite+aiosqlite:///./data/bot.db"
    redis_url: str = ""

    # ---------- LLM ----------
    llm_config_path: str = "./config/llm.yaml"
    zhipu_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    longcat_api_key: str = ""  # 美团龙猫，https://longcat.chat

    # ---------- Turtle Soup ----------
    game_turtle_soup_max_questions: int = 50
    game_turtle_soup_session_timeout_minutes: int = 60
    game_turtle_soup_idle_timeout_minutes: int = 15
    game_turtle_soup_prefer_llm_generation: bool = False
    game_turtle_soup_judge_timeout_seconds: int = 30
    game_turtle_soup_claim_timeout_seconds: int = 45
    game_turtle_soup_reward_on_win: int = 100

    @field_validator("app_env")
    @classmethod
    def _validate_env(cls, v: str) -> str:
        if v not in ("dev", "staging", "prod"):
            raise ValueError(f"APP_ENV must be dev/staging/prod, got: {v}")
        return v

    # --- helpers ---
    @property
    def admin_qq_list(self) -> list[int]:
        if not self.admin_qq.strip():
            return []
        return [int(x.strip()) for x in self.admin_qq.split(",") if x.strip()]

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @property
    def use_redis(self) -> bool:
        return bool(self.redis_url.strip())

    @property
    def data_dir(self) -> Path:
        p = Path("data")
        p.mkdir(exist_ok=True)
        return p


@lru_cache
def get_settings() -> Settings:
    """全局单例。测试中可通过 `get_settings.cache_clear()` 重置。"""
    return Settings()  # type: ignore[call-arg]
