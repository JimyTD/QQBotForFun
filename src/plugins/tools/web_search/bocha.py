"""博查 AI 搜索：中国大陆区域可用的网页 + 图片 API。

文档端点：POST https://api.bochaai.com/v1/web-search
"""

from __future__ import annotations

import httpx
from nonebot import logger

from src.settings import get_settings

from .models import (
    ImageResult,
    SearchBundle,
    SearchError,
    SearchNotConfiguredError,
    SearchResult,
)


class BochaSearchProvider:
    name = "bocha"
    endpoint = "https://api.bochaai.com/v1/web-search"

    @property
    def configured(self) -> bool:
        return bool(get_settings().bocha_api_key.strip())

    async def search(self, query: str, *, count: int = 5) -> SearchBundle:
        key = get_settings().bocha_api_key.strip()
        if not key:
            raise SearchNotConfiguredError(
                "图片和联网搜索尚未配置。请在服务器 .env 填入 BOCHA_API_KEY 后重启 bot。"
            )

        payload = {
            "query": query,
            "summary": True,
            "count": max(1, min(count, 10)),
        }
        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                resp = await client.post(
                    self.endpoint,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[search] 博查请求失败: {e}")
            raise SearchError("联网搜索暂时不可用，请稍后再试。") from e

        if resp.status_code in (401, 403):
            raise SearchError("联网搜索鉴权失败，请管理员检查 BOCHA_API_KEY。")
        if resp.status_code == 429:
            raise SearchError("联网搜索额度不足或请求过于频繁，请稍后再试。")
        if resp.status_code >= 400:
            logger.warning(f"[search] 博查 HTTP {resp.status_code}: {resp.text[:300]}")
            raise SearchError("联网搜索暂时不可用，请稍后再试。")

        try:
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            raise SearchError("联网搜索返回了无法解析的数据。") from e

        return _parse_bundle(query, data)


def _parse_bundle(query: str, data: dict) -> SearchBundle:
    body = data.get("data") if isinstance(data.get("data"), dict) else data
    web = body.get("webPages", {}).get("value", [])
    images = body.get("images", {}).get("value", [])

    web_results: list[SearchResult] = []
    for item in web if isinstance(web, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("name") or item.get("title") or "").strip()
        url = str(item.get("url") or item.get("link") or "").strip()
        if not title or not url:
            continue
        snippet = str(item.get("snippet") or "").strip()
        summary = str(item.get("summary") or "").strip()
        web_results.append(
            SearchResult(
                title=title,
                url=url,
                snippet=snippet,
                body=summary,
                source="bocha",
            )
        )

    image_results: list[ImageResult] = []
    for item in images if isinstance(images, list) else []:
        if not isinstance(item, dict):
            continue
        content_url = str(item.get("contentUrl") or "").strip()
        if not content_url:
            continue
        image_results.append(
            ImageResult(
                title=str(item.get("name") or item.get("title") or query).strip(),
                content_url=content_url,
                page_url=str(item.get("hostPageUrl") or "").strip(),
                width=_to_int(item.get("width")),
                height=_to_int(item.get("height")),
                source="bocha",
            )
        )
    return SearchBundle(query=query, web_results=web_results, images=image_results)


def _to_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
