"""Composite unit icons onto fixed backgrounds without changing source assets."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

QUERY_ICON_BACKGROUND = (0, 0, 0)
# AoE3:DE playercolors.xml friendorfoeenemy/self color1 (not minimap colors).
# Source: https://forums.ageofempires.com/t/friend-foe-colors-the-tutorial/232827
RED_ICON_BACKGROUND = (230, 40, 40)
BLUE_ICON_BACKGROUND = (75, 75, 230)


def render_icon_png(path: Path, background: tuple[int, int, int]) -> bytes:
    """Return an opaque PNG, blending only transparent and translucent pixels."""
    with Image.open(path) as source:
        icon = source.convert("RGBA")
    canvas = Image.new("RGB", icon.size, background)
    canvas.paste(icon, (0, 0), icon.getchannel("A"))
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()
