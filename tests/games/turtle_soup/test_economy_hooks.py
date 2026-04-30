"""海龟汤经济配置守门测试。

注：GameBase.award() 的通用接口测试在 tests/core/test_game_base_award.py。
本文件只测海龟汤自己的 config 字段是否符合"及时正反馈 > 公平性"的核心设计哲学。
"""

from __future__ import annotations

from src.plugins.games.turtle_soup.config import get_config


# ------------------------------------------------------------------
# 配置字段守门：所有奖励数必须为非负（确保永不负反馈）
# ------------------------------------------------------------------
def test_rewards_are_non_negative() -> None:
    """核心设计哲学守门：所有奖励字段 >= 0，penalty 必须 == 0。"""
    cfg = get_config()
    assert cfg.reward_coin_on_win >= 0
    assert cfg.reward_score_on_win >= 0
    assert cfg.reward_score_on_key_hit >= 0
    assert cfg.reward_score_on_partial_hit >= 0
    assert cfg.penalty_on_lose == 0, \
        "核心设计哲学要求永不负反馈：penalty_on_lose 必须保持 0"


def test_winner_reward_is_larger_than_participation() -> None:
    """赢家奖应该明显大于参与奖，否则激励结构失衡。"""
    cfg = get_config()
    assert cfg.reward_score_on_win > cfg.reward_score_on_key_hit, (
        f"赢家 score 奖({cfg.reward_score_on_win}) "
        f"应大于单次 key 奖({cfg.reward_score_on_key_hit})"
    )
    assert cfg.reward_score_on_key_hit >= cfg.reward_score_on_partial_hit, \
        "key 奖应 >= partial 奖（key 比 partial 更有含金量）"
