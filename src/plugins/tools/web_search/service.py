"""搜索提供方选择。默认只启用中国大陆 API，不回退网页抓取。"""

from __future__ import annotations

from .bocha import BochaSearchProvider
from .models import SearchBundle
from .provider import SearchProvider

_provider: SearchProvider = BochaSearchProvider()


def get_search_provider() -> SearchProvider:
    return _provider


async def search(query: str, *, count: int = 5) -> SearchBundle:
    return await _provider.search(query, count=count)
