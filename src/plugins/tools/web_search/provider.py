"""中国大陆 AI 助手搜索接口。"""

from __future__ import annotations

from typing import Protocol

from .models import SearchBundle


class SearchProvider(Protocol):
    name: str

    @property
    def configured(self) -> bool: ...

    async def search(self, query: str, *, count: int = 5) -> SearchBundle: ...
