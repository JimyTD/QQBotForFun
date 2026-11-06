"""图片候选校验与交付。"""

from __future__ import annotations

import asyncio
import io

import httpx
from nonebot import logger
from PIL import Image

from src.plugins.tools.web_search.models import ImageResult, SearchError
from src.plugins.tools.web_search.service import search

MAX_BYTES = 8 * 1024 * 1024
MIN_BYTES = 8 * 1024
MIN_EDGE = 240
MAX_EDGE_RATIO = 5.0


class ImageSearchFailedError(SearchError):
    pass


async def search_images(query: str, *, count: int = 6) -> list[ImageResult]:
    bundle = await search(query, count=count)
    usable = [
        img
        for img in bundle.images
        if (not img.width or not img.height)
        or (
            min(img.width, img.height) >= MIN_EDGE
            and max(img.width, img.height) / min(img.width, img.height) <= MAX_EDGE_RATIO
        )
    ]
    return usable[:count]


async def download_valid_image(
    images: list[ImageResult], *, exclude_urls: set[str] | None = None
) -> tuple[bytes, str, ImageResult]:
    exclude_urls = exclude_urls or set()
    candidates = [img for img in images if img.content_url not in exclude_urls]
    if not candidates:
        raise ImageSearchFailedError("没找到新的合适图片。")
    results = await asyncio.gather(
        *(_try_download(img) for img in candidates),
        return_exceptions=True,
    )
    for item in results:
        if isinstance(item, tuple):
            return item
    raise ImageSearchFailedError("找到了图片结果，但没有一张能正常下载。")


async def _try_download(img: ImageResult) -> tuple[bytes, str, ImageResult]:
    url = img.content_url
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                ctype = (resp.headers.get("content-type") or "").lower()
                if not ctype.startswith("image/") or "svg" in ctype:
                    raise ValueError("not raster image")
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ValueError("too large")
                    chunks.append(chunk)
        raw = b"".join(chunks)
        if len(raw) < MIN_BYTES:
            raise ValueError("too small")
        with Image.open(io.BytesIO(raw)) as pil:
            if (pil.format or "").upper() not in {"JPEG", "PNG", "WEBP", "GIF"}:
                raise ValueError("unsupported format")
            pil.verify()
        return raw, ctype.split(";")[0], img
    except Exception as e:  # noqa: BLE001
        logger.info(f"[ask_ai] 图片候选不可用: {url[:100]} {e}")
        raise


def image_mime_to_base64(raw: bytes, mime: str) -> str:
    import base64

    _ = mime
    return "base64://" + base64.b64encode(raw).decode("ascii")
