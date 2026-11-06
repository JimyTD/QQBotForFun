"""QQ 入站图片下载、校验和打包为 LLM 多模态内容。"""

from __future__ import annotations

import base64
import io
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx
from nonebot import logger
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_EDGE = 2048
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}


@dataclass
class PreparedImage:
    data_url: str
    mime: str
    width: int
    height: int
    size_bytes: int


class ImageInputError(ValueError):
    """入站图片不合格，消息可直接展示。"""


async def fetch_image(url: str) -> bytes:
    if not url.startswith(("http://", "https://")):
        raise ImageInputError("图片地址无效，请重新发送图片。")
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                content_type = (resp.headers.get("content-type") or "").lower()
                if not content_type.startswith("image/"):
                    raise ImageInputError("收到的不是图片文件。")
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_IMAGE_BYTES:
                        raise ImageInputError("图片超过 8 MB，请压缩后再发。")
                    chunks.append(chunk)
    except ImageInputError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.info(f"[ask_ai] 图片下载失败: {url[:80]} {e}")
        raise ImageInputError("图片下载失败，请重新发送或改用文字描述。") from e
    return b"".join(chunks)


def prepare_image(raw: bytes) -> PreparedImage:
    if not raw:
        raise ImageInputError("图片内容为空。")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ImageInputError("图片超过 8 MB，请压缩后再发。")
    try:
        with Image.open(io.BytesIO(raw)) as img:
            fmt = (img.format or "").upper()
            if fmt not in ALLOWED_FORMATS:
                raise ImageInputError("暂不支持这种图片格式，请发 JPEG、PNG、WebP 或 GIF。")
            img.load()
            if fmt == "GIF":
                img.seek(0)
            width, height = img.size
            longest = max(width, height)
            needs_resize = longest > MAX_IMAGE_EDGE
            if needs_resize:
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA" if "A" in img.mode else "RGB")
                scale = MAX_IMAGE_EDGE / longest
                img = img.resize(
                    (max(1, round(width * scale)), max(1, round(height * scale))),
                    Image.Resampling.LANCZOS,
                )
            if needs_resize:
                out = io.BytesIO()
                if img.mode == "RGBA" or fmt == "PNG":
                    img.save(out, format="PNG", optimize=True)
                    payload = out.getvalue()
                    mime = "image/png"
                else:
                    img.save(out, format="JPEG", quality=88, optimize=True)
                    payload = out.getvalue()
                    mime = "image/jpeg"
            else:
                payload = raw
                mime = {
                    "JPEG": "image/jpeg",
                    "PNG": "image/png",
                    "WEBP": "image/webp",
                    "GIF": "image/gif",
                }[fmt]
            width, height = img.size
    except ImageInputError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise ImageInputError("无法识别这张图片，请换一张再试。") from e
    encoded = base64.b64encode(payload).decode("ascii")
    return PreparedImage(
        data_url=f"data:{mime};base64,{encoded}",
        mime=mime,
        width=width,
        height=height,
        size_bytes=len(payload),
    )


def save_temp_image(raw: bytes, suffix: str = ".img") -> Path:
    """写入仓库外临时目录；只用于测试或需要落盘的适配器。"""
    path = Path(tempfile.gettempdir()) / f"qqbot-ai-{id(raw)}{suffix}"
    path.write_bytes(raw)
    return path
