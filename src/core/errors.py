"""Core 公共异常。

所有游戏层/业务层抛出的异常都应继承 `GameError` 或其子类。
"""

from __future__ import annotations


class GameError(Exception):
    """游戏层异常基类。"""


class TimeoutError(GameError):  # noqa: A001 - shadow builtin intentionally inside core
    """等待玩家输入超时。"""


class PlayerQuitError(GameError):
    """玩家主动退出（如 /quit）。"""


class WhisperFailedError(GameError):
    """私聊发送失败（如对方未加机器人为好友）。"""


class InsufficientFundsError(GameError):
    """经济余额/道具数量不足。"""


class PermissionDeniedError(GameError):
    """权限不足。"""


class CooldownError(GameError):
    """命中冷却，尚未结束。"""

    def __init__(self, remaining_seconds: float, message: str | None = None) -> None:
        super().__init__(message or f"cooldown {remaining_seconds:.1f}s remaining")
        self.remaining_seconds = remaining_seconds


class RateLimitedError(GameError):
    """命中频率限制。"""


class GameNotFoundError(GameError):
    """请求的游戏未注册。"""


class GameAlreadyRunningError(GameError):
    """该群已有游戏在进行中。"""


class InvalidStateError(GameError):
    """状态机非法转移。"""


# -------- LLM 子族 --------
class LLMError(GameError):
    """LLM 调用失败基类。"""


class LLMTimeoutError(LLMError):
    """LLM 调用读超时。"""


class LLMRateLimitError(LLMError):
    """LLM 429 重试耗尽。"""


class LLMJSONParseError(LLMError):
    """LLM JSON 模式输出无法解析。"""


class LLMConfigError(GameError):
    """LLM 配置错误（启动时发现）。"""
