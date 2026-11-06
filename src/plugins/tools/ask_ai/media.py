"""QQ 入站图片下载、校验和打包为 LLM 多模态内容。"""

from __future__ import annotations

import base64
import io
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from anyio import to_thread
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


def _read_local_image_sync(path: str) -> bytes:
    candidate = _local_path(path)
    if not candidate.is_file():
        raise ImageInputError("找不到这张图片，请重新发送。")
    if candidate.stat().st_size > MAX_IMAGE_BYTES:
        raise ImageInputError("图片超过 8 MB，请压缩后再发。")
    return candidate.read_bytes()


def _local_path(value: str) -> Path:
    if not value.startswith("file://"):
        return Path(value).expanduser()
    parsed = urlparse(value)
    path = unquote(parsed.path)
    if parsed.netloc:
        path = f"//{parsed.netloc}{path}"
    if path.startswith("/") and len(path) >= 3 and path[2] == ":":
        path = path[1:]
    return Path(path).expanduser()


async def read_local_image(path: str) -> bytes:
    return await to_thread.run_sync(_read_local_image_sync, path)


async def read_bot_image(bot: object, file_id: str) -> bytes:
    """通过 OneBot 标准 get_image 接口解析图片文件标识。"""
    try:
        data = await bot.call_api("get_image", file=file_id)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        logger.info(f"[ask_ai] get_image 失败: {file_id[:80]} {e}")
        raise ImageInputError("无法读取这张图片，请重新发送。") from e
    if not isinstance(data, dict):
        raise ImageInputError("图片接口没有返回有效内容。")
    local = str(data.get("file") or "").strip()
    if local:
        candidate = await to_thread.run_sync(lambda: _local_path(local))
        if await to_thread.run_sync(candidate.is_file):
            return await read_local_image(str(candidate))
        if local.startswith(("http://", "https://")):
            return await fetch_image(local)
    remote = str(data.get("url") or "").strip()
    if remote.startswith(("http://", "https://")):
        return await fetch_image(remote)
    raise ImageInputError("图片接口没有返回可读取的图片。")


async def resolve_image_source(source: str, *, bot: object | None = None) -> bytes:
    """读取 URL、本地路径或 OneBot 图片文件标识。"""
    value = source.strip()
    if value.startswith(("http://", "https://")):
        return await fetch_image(value)
    if value.startswith("file://"):
        return await read_local_image(value)
    path = await to_thread.run_sync(lambda: Path(value).expanduser())
    if await to_thread.run_sync(path.is_file):
        return await read_local_image(value)
    if bot is not None:
        return await read_bot_image(bot, value)
    raise ImageInputError("无法读取这张图片，请重新发送。")


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
