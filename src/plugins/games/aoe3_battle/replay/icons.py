"""Shared unit-icon normalization for replay and viewer rendering."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw

ICON_SIZE = 64
ICON_PADDING = 8
BACKGROUND = (36, 43, 47)


def render_unit_icon(path: Path) -> Image.Image:
    """Render one source icon onto the shared circular canvas."""
    with Image.open(path) as source:
        icon = source.convert("RGBA")
    canvas = Image.new(
        "RGBA",
        (ICON_SIZE, ICON_SIZE),
        (*BACKGROUND, 255),
    )
    fitted = icon.copy()
    fitted.thumbnail(
        (ICON_SIZE - ICON_PADDING, ICON_SIZE - ICON_PADDING),
        Image.Resampling.LANCZOS,
    )
    canvas.paste(
        fitted,
        ((ICON_SIZE - fitted.width) // 2, (ICON_SIZE - fitted.height) // 2),
        fitted,
    )
    mask = Image.new("L", (ICON_SIZE, ICON_SIZE), 0)
    ImageDraw.Draw(mask).ellipse(
        (0, 0, ICON_SIZE - 1, ICON_SIZE - 1),
        fill=255,
    )
    canvas.putalpha(mask)
    return canvas


def render_unit_icon_png(path: Path) -> bytes:
    """Return the shared icon canvas encoded as PNG."""
    output = io.BytesIO()
    render_unit_icon(path).save(output, format="PNG")
    return output.getvalue()
