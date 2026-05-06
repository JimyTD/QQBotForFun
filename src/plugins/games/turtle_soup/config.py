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
    # ---- 经济接入（核心设计：及时正反馈 > 公平性；永不负反馈）----
    # 赢家（宣告 correct）奖励
    reward_coin_on_win: int = 100         # 发到 coin（钱包）
    reward_score_on_win: int = 20         # 发到 score（全局排行榜）
    # 互动奖励：提问命中时发 score + coin，强化参与感
    reward_score_on_key_hit: int = 2      # 问到 key 线索 +2 score
    reward_coin_on_key_hit: int = 5       # 问到 key 线索 +5 coin（= 一次提示）
    reward_score_on_yes: int = 1          # 问到 yes +1 score
    reward_coin_on_yes: int = 2           # 问到 yes +2 coin（两次 yes ≈ 一次提示）
    reward_score_on_partial_hit: int = 1  # partial 命中 +1 score
    # 主动购买提示
    hint_cost_coin: int = 5               # 每次买提示消耗 coin
    max_hints_per_game: int = 3           # 每局最多购买 N 次提示
    # 兼容旧字段（已废弃，迁移期保留）
    reward_on_win: int = 100              # = reward_coin_on_win 的同名别名，不再读取
    penalty_on_lose: int = 0              # 永远保持 0（不做负反馈）
    # 烂题淘汰机制
    llm_generated_cap: int = 200         # llm_generated 总数上限，超限前删最老一条
    mark_bad_window_seconds: int = 300   # 本局结束后 N 秒内允许玩家 /汤 烂题


_config: TurtleSoupConfig | None = None


def get_config() -> TurtleSoupConfig:
    global _config
    if _config is None:
        _config = TurtleSoupConfig()  # type: ignore[call-arg]
    return _config
