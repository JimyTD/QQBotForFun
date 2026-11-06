"""恢复后的文字搜索入口。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.plugins.tools.web_search.searxng import SearchResult
from src.plugins.tools.web_search.service import search


@pytest.mark.asyncio
async def test_service_uses_original_search_chain_without_new_key() -> None:
    legacy = [
        SearchResult(
            title="结果",
            url="https://example.com",
            snippet="摘要",
            source="page",
        )
    ]
    with patch(
        "src.plugins.tools.web_search.service._legacy_search",
        AsyncMock(return_value=legacy),
    ) as call:
        bundle = await search("测试", count=3)
    call.assert_awaited_once_with("测试", max_results=3)
    assert bundle.query == "测试"
    assert bundle.web_results[0].title == "结果"
