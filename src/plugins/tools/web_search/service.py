"""搜索服务入口：恢复原有搜索链路，不引入新账号依赖。"""

from __future__ import annotations

from .models import SearchBundle
from .searxng import SearchResult
from .searxng import search as _legacy_search


async def search(query: str, *, count: int = 5) -> SearchBundle:
    results = await _legacy_search(query, max_results=count)
    return SearchBundle(query=query, web_results=list(results))


__all__ = ["SearchBundle", "SearchResult", "search"]
