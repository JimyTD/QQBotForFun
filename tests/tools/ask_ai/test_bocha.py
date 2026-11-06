"""博查搜索结果解析。"""

from __future__ import annotations

from src.plugins.tools.web_search.bocha import _parse_bundle
from src.plugins.tools.web_search.service import get_search_provider


def test_default_provider_is_china_ai_search_not_html_scraping() -> None:
    provider = get_search_provider()
    assert provider.name == "bocha"
    assert "api.bochaai.com" in provider.endpoint


def test_parse_web_and_images() -> None:
    payload = {
        "data": {
            "webPages": {
                "value": [
                    {
                        "name": "测试网页",
                        "url": "https://example.com/article",
                        "snippet": "摘要",
                        "summary": "完整正文",
                    }
                ]
            },
            "images": {
                "value": [
                    {
                        "name": "测试图片",
                        "contentUrl": "https://example.com/a.jpg",
                        "hostPageUrl": "https://example.com/page",
                        "width": 800,
                        "height": 600,
                    }
                ]
            },
        }
    }
    bundle = _parse_bundle("测试", payload)
    assert bundle.query == "测试"
    assert bundle.web_results[0].title == "测试网页"
    assert bundle.web_results[0].body == "完整正文"
    assert bundle.images[0].content_url.endswith("a.jpg")
    assert bundle.images[0].width == 800


def test_parse_flat_response_and_skip_invalid() -> None:
    payload = {
        "webPages": {
            "value": [
                {"name": "", "url": "https://example.com"},
                {"name": "有效", "url": "https://example.com/ok"},
            ]
        },
        "images": {"value": [{"name": "无地址"}]},
    }
    bundle = _parse_bundle("x", payload)
    assert [r.title for r in bundle.web_results] == ["有效"]
    assert bundle.images == []
