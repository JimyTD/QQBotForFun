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

# AoE3:DE playercolors.xml player num=1..8 color1, in player-number order.
# Pinned XML sources and verification notes: docs/games/aoe3.md, section 3.2.
PLAYER_ICON_BACKGROUNDS = (
    (45, 45, 245),
    (210, 40, 40),
    (224, 224, 30),
    (145, 15, 243),
    (42, 212, 58),
    (234, 135, 0),
    (28, 194, 219),
    (235, 97, 235),
)


def composite_icon(path: Path, background: tuple[int, int, int]) -> Image.Image:
    """Return an opaque image, blending only transparent and translucent pixels."""
    with Image.open(path) as source:
        icon = source.convert("RGBA")
    canvas = Image.new("RGB", icon.size, background)
    canvas.paste(icon, (0, 0), icon.getchannel("A"))
    return canvas


def render_icon_png(path: Path, background: tuple[int, int, int]) -> bytes:
    """Return a composited icon as PNG bytes."""
    canvas = composite_icon(path, background)
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()
