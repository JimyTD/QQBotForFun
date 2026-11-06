"""图片输入校验。"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from src.plugins.tools.ask_ai.media import ImageInputError, prepare_image


def _png(size: tuple[int, int] = (64, 32)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (255, 0, 0)).save(out, format="PNG")
    return out.getvalue()


def test_prepare_png_as_data_url() -> None:
    prepared = prepare_image(_png())
    assert prepared.data_url.startswith("data:image/png;base64,")
    assert (prepared.width, prepared.height) == (64, 32)


def test_large_image_is_resized() -> None:
    prepared = prepare_image(_png((4096, 1024)))
    assert max(prepared.width, prepared.height) == 2048


def test_invalid_bytes_rejected() -> None:
    with pytest.raises(ImageInputError):
        prepare_image(b"<html>not an image</html>")


def test_oversize_rejected() -> None:
    with pytest.raises(ImageInputError):
        prepare_image(b"0" * (8 * 1024 * 1024 + 1))
