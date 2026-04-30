"""趣味问答配置。"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class TriviaConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GAME_TRIVIA_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- 对局长度 ---
    total_questions_per_game: int = 10
    max_clues_per_puzzle: int = 5

    # --- 超时 ---
    session_timeout_minutes: int = 30
    generator_timeout_seconds: int = 20

    # --- LLM ---
    llm_retry_times: int = 3

    # --- 计分（score 入全局榜）---
    # 2026-04-30 v1.2 校准：对齐海龟汤（赢一局 20 分）。
    # 10 题全对理论上限 60 分 ≈ 3x 海龟汤，体现知识面广的奖励；
    # 一般水平 6 题命中 ≈ 28 分，与海龟汤接近。
    score_tier_1_clue: int = 5        # 第 1 条线索内答对
    score_tier_2_3_clue: int = 3      # 第 2-3 条线索内答对
    score_tier_4_5_clue: int = 1      # 第 4-5 条线索内答对
    mvp_score_bonus: int = 10         # 本局第一额外 score

    # --- 金币奖励（coin 进钱包）---
    # 和海龟汤对齐单位时间产出：问答 10 题密集得分，单题金币给得较小，
    # 避免成为刷 coin 的捷径；MVP 有较大一次性奖励
    coin_tier_1_clue: int = 3
    coin_tier_2_3_clue: int = 2
    coin_tier_4_5_clue: int = 1
    mvp_coin_bonus: int = 30

    # --- 判定 ---
    max_answer_length: int = 40       # 作答文本长度上限（超过视为闲聊）


_config: TriviaConfig | None = None


def get_config() -> TriviaConfig:
    global _config
    if _config is None:
        _config = TriviaConfig()  # type: ignore[call-arg]
    return _config
