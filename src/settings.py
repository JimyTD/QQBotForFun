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
    # 腾讯云 TokenHub（OpenAI 兼容，单 Key 多模型）。
    # 本项目**只消费免费额度**，额度按模型各自独立、不刷新、用完/下线即失效，
    # 因此 scene 配成「阶梯链」：前档耗尽自动降下一档。详见
    # docs/plans/2026-09-17-llm-tokenhub-model-ladder.md。
    # 注意：广州站与新加坡站的 Key 不互通（本项对应广州站的 base_url）。
    tokenhub_api_key: str = ""

    # ---------- Games（所有游戏统一）----------
    # 整局兜底超时（小时）。为什么必须有：**真人没有单步超时**（大原则：
    # 「AI 有超时，真实玩家没有」），所以"有人挂机"只会僵住这一局，只剩这层收尾。
    # 24 小时 = 正常对局绝不会被打断，但也不会有一局永远占着群。
    # 各游戏若需特殊值，覆盖 `GameBase.default_session_timeout_seconds` 即可，
    # 不要在各自的 config 里再抄一份。
    game_session_timeout_hours: int = 24

    # ---------- Turtle Soup ----------
    game_turtle_soup_max_questions: int = 50
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
