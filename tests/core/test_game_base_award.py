"""GameBase.award() 统一奖励接口单元测试。

覆盖两个层次：
- 产品约束（来自核心设计哲学）：永不负反馈 → 只加不减
- API 行为约定（实现选择）：amount <= 0 静默跳过、economy 失败吞异常、多货币隔离
"""

from __future__ import annotations

from core import economy
from core.game_base import GameBase


# ------------------------------------------------------------------
# 基础路径：不同货币、不同玩家都能正确入账
# ------------------------------------------------------------------
async def test_award_coin_adds_to_coin_balance() -> None:
    qq = 8001
    start = await economy.balance(qq, currency="coin")
    await GameBase.award(qq, 100, reason="ut_coin", currency="coin")
    end = await economy.balance(qq, currency="coin")
    assert end - start == 100


async def test_award_score_adds_to_score_balance() -> None:
    qq = 8002
    start = await economy.balance(qq, currency="score")
    await GameBase.award(qq, 20, reason="ut_score", currency="score")
    end = await economy.balance(qq, currency="score")
    assert end - start == 20


async def test_award_default_currency_is_coin() -> None:
    """不指定 currency 时默认发到 coin。"""
    qq = 8003
    await GameBase.award(qq, 50, reason="ut_default")
    assert await economy.balance(qq, currency="coin") == 50
    assert await economy.balance(qq, currency="score") == 0


async def test_coin_and_score_are_separate_pots() -> None:
    """coin 和 score 是独立货币，互不影响。"""
    qq = 8004
    await GameBase.award(qq, 100, reason="ut_sep_coin", currency="coin")
    await GameBase.award(qq, 20, reason="ut_sep_score", currency="score")
    assert await economy.balance(qq, currency="coin") == 100
    assert await economy.balance(qq, currency="score") == 20


# ------------------------------------------------------------------
# API 行为：amount<=0 静默跳过（实现选择，不是哲学）
# ------------------------------------------------------------------
async def test_award_zero_amount_is_noop() -> None:
    """amount == 0 时什么都不做，不报错。"""
    qq = 8005
    await GameBase.award(qq, 0, reason="ut_zero")
    assert await economy.balance(qq, currency="coin") == 0


async def test_award_negative_amount_is_noop() -> None:
    """amount < 0 时静默跳过。

    这是 API 行为约定（方便调用方不写 `if x > 0`）；同时也和产品约束
    "永不负反馈"自然对齐——即使误传负数也不会扣款。
    """
    qq = 8006
    await GameBase.award(qq, -100, reason="ut_negative")
    # 余额必须仍是 0，不能被"扣"成负数
    assert await economy.balance(qq, currency="coin") == 0


# ------------------------------------------------------------------
# API 行为：economy 失败吞异常（实现选择，务实防御）
# ------------------------------------------------------------------
async def test_award_swallows_exception_from_economy(monkeypatch) -> None:
    """即使 economy.add 抛异常，award 也要吞掉不向外抛。"""
    from core import economy as eco

    async def fake_add(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated economy failure")

    monkeypatch.setattr(eco, "add", fake_add)

    # 这次调用不应该抛异常
    try:
        await GameBase.award(8007, 100, reason="ut_fail_safe")
    except Exception:  # pragma: no cover
        raise AssertionError("GameBase.award 应吞掉 economy 异常不向外抛")
