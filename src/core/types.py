"""Core 公共数据结构。"""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# ---------- 用户 ----------
@dataclass(frozen=True)
class User:
    qq_id: int
    nickname: str
    group_id: int | None = None


@dataclass(frozen=True)
class GroupInfo:
    group_id: int
    name: str
    member_count: int


class Scope(str, Enum):
    GROUP = "group"
    PRIVATE = "private"


# ---------- 游戏 ----------
class EndReason(str, Enum):
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    ABORTED = "aborted"
    ERROR = "error"


@dataclass
class GameContext:
    """一局游戏的运行期上下文，由 Core 在启动时构造并传给 Game 钩子。"""

    session_id: str
    game_id: str
    group_id: int
    host_id: int
    players: list[User]
    started_at: datetime
    config: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)

    def player_ids(self) -> list[int]:
        return [p.qq_id for p in self.players]

    def get_player(self, qq_id: int) -> User | None:
        for p in self.players:
            if p.qq_id == qq_id:
                return p
        return None


# ---------- 工具：生成 session_id ----------
_SID_ALPHABET = string.ascii_uppercase + string.digits


def new_session_id() -> str:
    """生成 6 位随机 session id，例如 'A7F3K2'。"""
    return "".join(secrets.choice(_SID_ALPHABET) for _ in range(6))
