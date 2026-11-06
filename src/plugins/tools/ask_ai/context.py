"""群聊 AI 短会话上下文。"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass

MAX_TURNS = 6
MAX_CHARS = 6000
IDLE_SECONDS = 15 * 60


@dataclass
class Turn:
    question: str
    answer: str
    search_query: str = ""
    created_at: float = 0.0


_store: dict[tuple[int | None, int], deque[Turn]] = defaultdict(lambda: deque(maxlen=MAX_TURNS))


def _key(group_id: int | None, user_id: int) -> tuple[int | None, int]:
    return group_id, user_id


def remember(
    group_id: int | None,
    user_id: int,
    *,
    question: str,
    answer: str,
    search_query: str = "",
) -> None:
    _store[_key(group_id, user_id)].append(
        Turn(
            question=question[:1000],
            answer=answer[:3000],
            search_query=search_query[:200],
            created_at=time.time(),
        )
    )


def history(group_id: int | None, user_id: int) -> list[Turn]:
    turns = _store.get(_key(group_id, user_id))
    if not turns:
        return []
    now = time.time()
    while turns and now - turns[0].created_at > IDLE_SECONDS:
        turns.popleft()
    return list(turns)


def last(group_id: int | None, user_id: int) -> Turn | None:
    turns = history(group_id, user_id)
    return turns[-1] if turns else None


def clear(group_id: int | None, user_id: int) -> None:
    _store.pop(_key(group_id, user_id), None)


def build_context_text(turns: list[Turn], *, max_chars: int = MAX_CHARS) -> str:
    parts: list[str] = []
    for turn in reversed(turns):
        parts.append(f"用户：{turn.question}\n助手：{turn.answer}")
    text = "\n\n".join(reversed(parts))
    return text[-max_chars:]
