"""AI 助手内部数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TaskKind(StrEnum):
    CHAT = "chat"
    WEB_SEARCH = "web_search"
    IMAGE_SEARCH = "image_search"
    IMAGE_UNDERSTAND = "image_understand"


class SearchState(StrEnum):
    NOT_USED = "not_used"
    USED = "used"
    FAILED = "failed"


@dataclass
class AssistantInput:
    text: str = ""
    image_sources: list[str] = field(default_factory=list)
    quoted_text: str = ""
    bot: object | None = None
    group_id: int | None = None
    user_id: int = 0
    message_id: str | None = None

    @property
    def has_image(self) -> bool:
        return bool(self.image_sources)


@dataclass
class AskResult:
    answer: str = ""
    sources: list[str] = field(default_factory=list)
    used_search: bool = False
    search_state: SearchState = SearchState.NOT_USED
    truncated: bool = False
    status_message: str = ""
    error: str = ""
