"""Render the civilization-war opening card as a single QQ-friendly PNG."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.plugins.aoe3.icons import BLUE_ICON_BACKGROUND, RED_ICON_BACKGROUND, composite_icon
from src.plugins.aoe3.models import Unit

ICON_SIZE = 58
FLAG_W = 84
FLAG_H = 56
CANVAS_W = 940
SIDE_GAP = 28
SIDE_W = (CANVAS_W - 60 - SIDE_GAP) // 2
HEADER_H = 112
CARD_H = 126
ROW_GAP = 10
FOOTER_H = 72

FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyh.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)

COLORS = {
    "bg": (235, 233, 226),
    "panel": (249, 247, 242),
    "line": (202, 198, 189),
    "title": (35, 39, 35),
    "muted": (102, 108, 101),
    "body": (73, 79, 73),
    "red": (196, 55, 62),
    "blue": (54, 91, 166),
}

_font_path: str | None = None
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
_flag_root = Path(__file__).resolve().parents[4] / "resources" / "aoe3" / "civ_flags"


@dataclass(frozen=True)
class OpeningSide:
    """One side of the civ-war opening card."""

    civ_name: str
    civ_id: str
    strategy: str
    units: tuple[tuple[Unit, int], ...]


@dataclass(frozen=True)
class MatchOpeningSide:
    """One side of a generic match opening card."""

    label: str
    units: tuple[tuple[Unit, int], ...]


def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    global _font_path
    if _font_path is None:
        _font_path = next((path for path in FONT_CANDIDATES if Path(path).exists()), "")
    if not _font_path:
        return ImageFont.load_default()
    key = (_font_path, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(_font_path, size)
    return _font_cache[key]


def _unit_short_description(unit: Unit) -> str:
    text = (unit.description or unit.description_en or "").strip()
    return " ".join(text.split())


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    max_width: int,
    *,
    max_lines: int | None = None,
) -> list[str]:
    lines: list[str] = []
    current = ""
    for character in text:
        candidate = current + character
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = character
            if max_lines is not None and len(lines) == max_lines:
                return lines
        else:
            current = candidate
    if current and (max_lines is None or len(lines) < max_lines):
        lines.append(current)
    return lines


def _load_icon(unit: Unit, *, background: tuple[int, int, int]) -> Image.Image:
    from src.plugins.aoe3.repository import UnitRepo

    path = UnitRepo.get().get_icon_path(unit)
    if path and path.exists():
        return composite_icon(path, background).resize(
            (ICON_SIZE, ICON_SIZE),
            Image.Resampling.LANCZOS,
        ).convert("RGBA")
    return Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (90, 90, 88, 255))


def _load_flag(civ_id: str) -> Image.Image | None:
    for suffix in (".png", ".webp"):
        path = _flag_root / f"{civ_id}{suffix}"
        if path.is_file():
            with Image.open(path) as source:
                return source.convert("RGBA").resize((FLAG_W, FLAG_H), Image.Resampling.LANCZOS)
    return None


def _unit_card_height(draw: ImageDraw.ImageDraw, unit: Unit) -> int:
    description_lines = _wrap_text(
        draw,
        _unit_short_description(unit),
        _get_font(14),
        SIDE_W - 32,
    )
    return max(CARD_H, 76 + max(1, len(description_lines)) * 21)


def _side_height(draw: ImageDraw.ImageDraw, side: OpeningSide) -> int:
    if not side.units:
        return HEADER_H + CARD_H + ROW_GAP
    return HEADER_H + sum(
        _unit_card_height(draw, unit) + ROW_GAP for unit, _ in side.units
    )


def _draw_side(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    side: OpeningSide,
    color: tuple[int, int, int],
    icon_background: tuple[int, int, int],
    side_label: str,
) -> None:
    font_civ = _get_font(25)
    font_strategy = _get_font(17)
    font_name = _get_font(20)
    font_count = _get_font(18)
    font_desc = _get_font(14)

    draw.rounded_rectangle(
        (x, y, x + SIDE_W, y + HEADER_H - 12),
        radius=9,
        fill=(*color, 255),
    )
    draw.text((x + 18, y + 13), side_label, font=font_strategy, fill=(245, 243, 238))
    flag = _load_flag(side.civ_id)
    civ_x = x + 18
    if flag is not None:
        flag_x = x + SIDE_W - FLAG_W - 18
        flag_y = y + 19
        draw.rounded_rectangle(
            (flag_x - 2, flag_y - 2, flag_x + FLAG_W + 2, flag_y + FLAG_H + 2),
            radius=3,
            fill=(245, 243, 238, 255),
        )
        image.paste(flag, (flag_x, flag_y), flag)
    civ = side.civ_name
    draw.text(
        (civ_x, y + 38),
        civ,
        font=font_civ,
        fill="white",
    )
    draw.text(
        (x + 18, y + 69),
        _wrap_text(draw, side.strategy, font_strategy, SIDE_W - 36, max_lines=1)[0],
        font=font_strategy,
        fill=(245, 243, 238),
    )

    cursor = y + HEADER_H

    if not side.units:
        draw.text((x + 18, cursor + 22), "暂无可展示单位", font=font_desc, fill=COLORS["muted"])
        return

    for unit, count in side.units:
        card_h = _unit_card_height(draw, unit)
        draw.rounded_rectangle(
            (x, cursor, x + SIDE_W, cursor + card_h),
            radius=8,
            fill=COLORS["panel"],
            outline=COLORS["line"],
            width=1,
        )
        draw.rectangle((x, cursor, x + 6, cursor + card_h), fill=(*color, 255))
        icon = _load_icon(unit, background=icon_background)
        image.paste(icon, (x + 16, cursor + 14), icon)
        text_x = x + 16 + ICON_SIZE + 14
        text_w = SIDE_W - (text_x - x) - 16
        draw.text(
            (text_x, cursor + 14),
            _wrap_text(draw, unit.name, font_name, text_w - 62, max_lines=1)[0],
            font=font_name,
            fill=COLORS["title"],
        )
        draw.text(
            (x + SIDE_W - 18, cursor + 15),
            f"×{count}",
            anchor="ra",
            font=font_count,
            fill=color,
        )
        description_lines = _wrap_text(
            draw,
            _unit_short_description(unit),
            font_desc,
            SIDE_W - 32,
        )
        for line_index, line in enumerate(description_lines):
            draw.text(
                (x + 16, cursor + 72 + line_index * 21),
                line,
                font=font_desc,
                fill=COLORS["body"],
            )
        cursor += card_h + ROW_GAP


def _draw_match_side(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    side: MatchOpeningSide,
    color: tuple[int, int, int],
    icon_background: tuple[int, int, int],
    side_label: str,
) -> None:
    font_title = _get_font(24)
    font_name = _get_font(20)
    font_count = _get_font(18)
    font_desc = _get_font(14)

    draw.rounded_rectangle(
        (x, y, x + SIDE_W, y + HEADER_H - 12),
        radius=9,
        fill=(*color, 255),
    )
    draw.text((x + 18, y + 15), side_label, font=font_desc, fill=(245, 243, 238))
    draw.text(
        (x + 18, y + 42),
        _wrap_text(draw, side.label, font_title, SIDE_W - 36, max_lines=1)[0],
        font=font_title,
        fill=(255, 255, 255),
    )

    cursor = y + HEADER_H
    if not side.units:
        draw.text((x + 18, cursor + 22), "暂无单位", font=font_desc, fill=COLORS["muted"])
        return

    for unit, count in side.units:
        card_h = _unit_card_height(draw, unit)
        draw.rounded_rectangle(
            (x, cursor, x + SIDE_W, cursor + card_h),
            radius=8,
            fill=COLORS["panel"],
            outline=COLORS["line"],
            width=1,
        )
        draw.rectangle((x, cursor, x + 6, cursor + card_h), fill=(*color, 255))
        icon = _load_icon(unit, background=icon_background)
        image.paste(icon, (x + 16, cursor + 14), icon)
        text_x = x + 16 + ICON_SIZE + 14
        text_w = SIDE_W - (text_x - x) - 78
        draw.text(
            (text_x, cursor + 14),
            _wrap_text(draw, unit.name, font_name, text_w, max_lines=1)[0],
            font=font_name,
            fill=COLORS["title"],
        )
        draw.text(
            (x + SIDE_W - 18, cursor + 15),
            f"×{count}",
            anchor="ra",
            font=font_count,
            fill=color,
        )
        description_lines = _wrap_text(
            draw,
            _unit_short_description(unit),
            font_desc,
            SIDE_W - 32,
        )
        for line_index, line in enumerate(description_lines):
            draw.text(
                (x + 16, cursor + 72 + line_index * 21),
                line,
                font=font_desc,
                fill=COLORS["body"],
            )
        cursor += card_h + ROW_GAP


def format_match_opening_fallback(
    red: MatchOpeningSide,
    blue: MatchOpeningSide,
    *,
    age: int | None,
    mode_label: str = "普通对阵",
) -> str:
    """Build a concise fallback for a generic match opening card."""
    age_text = f" · {age} 时代" if age else ""
    lines = [f"帝国3斗蛐蛐 · {mode_label}{age_text}"]
    for marker, side in (("🔴", red), ("🔵", blue)):
        lines.append(f"{marker} {side.label}")
        lines.extend(f"  {unit.name} ×{count}" for unit, count in side.units)
    lines.append("@ 1 押红方 | @ 2 押蓝方 · @ 开战 直接开打")
    return "\n".join(lines)


def render_match_opening(
    *,
    red: MatchOpeningSide,
    blue: MatchOpeningSide,
    age: int | None,
    mode_label: str = "普通对阵",
    bet_hint: str = "@ 1 押红方 | @ 2 押蓝方 · @ 开战 直接开打",
) -> bytes:
    """Return a PNG opening card for a non-civ match."""
    measure_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    red_units = red.units
    blue_units = blue.units
    body_h = max(
        HEADER_H + sum(_unit_card_height(measure_draw, unit) + ROW_GAP for unit, _ in red_units),
        HEADER_H + sum(_unit_card_height(measure_draw, unit) + ROW_GAP for unit, _ in blue_units),
        HEADER_H + CARD_H + ROW_GAP,
    )
    title_h = 94
    canvas_h = title_h + body_h + FOOTER_H
    image = Image.new("RGB", (CANVAS_W, canvas_h), COLORS["bg"])
    draw = ImageDraw.Draw(image)

    font_title = _get_font(30)
    font_subtitle = _get_font(16)
    font_footer = _get_font(17)
    draw.text(
        (CANVAS_W // 2, 23),
        f"帝国3斗蛐蛐 · {mode_label}",
        anchor="ma",
        font=font_title,
        fill=COLORS["title"],
    )
    subtitle = "兵种对阵" if not age else f"{age} 时代 · 兵种对阵"
    draw.text(
        (CANVAS_W // 2, 62),
        subtitle,
        anchor="ma",
        font=font_subtitle,
        fill=COLORS["muted"],
    )
    draw.line((30, title_h - 8, CANVAS_W - 30, title_h - 8), fill=COLORS["line"], width=2)

    left_x = 30
    right_x = left_x + SIDE_W + SIDE_GAP
    _draw_match_side(
        image,
        draw,
        x=left_x,
        y=title_h,
        side=red,
        color=COLORS["red"],
        icon_background=RED_ICON_BACKGROUND,
        side_label="1号",
    )
    _draw_match_side(
        image,
        draw,
        x=right_x,
        y=title_h,
        side=blue,
        color=COLORS["blue"],
        icon_background=BLUE_ICON_BACKGROUND,
        side_label="2号",
    )

    footer_y = title_h + body_h + 5
    draw.line((30, footer_y, CANVAS_W - 30, footer_y), fill=COLORS["line"], width=1)
    draw.text(
        (CANVAS_W // 2, footer_y + 20),
        bet_hint,
        anchor="ma",
        font=font_footer,
        fill=COLORS["title"],
    )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def format_civ_war_fallback(red: OpeningSide, blue: OpeningSide, *, age: int) -> str:
    """Build a concise text fallback when the opening PNG cannot be delivered."""
    lines = [f"🌍 帝国3斗蛐蛐 · 国战 · {age} 时代"]
    for marker, side in (("🔴", red), ("🔵", blue)):
        lines.append(f"{marker} {side.civ_name} · {side.strategy}")
        lines.extend(f"  {unit.name} ×{count}" for unit, count in side.units)
    lines.append("@ 1 押红方 | @ 2 押蓝方 · @ 开战 直接开打")
    return "\n".join(lines)


def render_civ_war_opening(
    *,
    red: OpeningSide,
    blue: OpeningSide,
    age: int,
    bet_hint: str = "@ 1 押红方 | @ 2 押蓝方 · @ 开战 直接开打",
) -> bytes:
    """Return a PNG opening card for a civilization-war match."""
    measure_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    body_h = max(_side_height(measure_draw, red), _side_height(measure_draw, blue))
    title_h = 94
    canvas_h = title_h + body_h + FOOTER_H
    image = Image.new("RGB", (CANVAS_W, canvas_h), COLORS["bg"])
    draw = ImageDraw.Draw(image)

    font_title = _get_font(30)
    font_subtitle = _get_font(16)
    font_footer = _get_font(17)
    draw.text(
        (CANVAS_W // 2, 23),
        "帝国3斗蛐蛐 · 国战",
        anchor="ma",
        font=font_title,
        fill=COLORS["title"],
    )
    draw.text(
        (CANVAS_W // 2, 62),
        f"{age} 时代 · 兵团编制",
        anchor="ma",
        font=font_subtitle,
        fill=COLORS["muted"],
    )
    draw.line((30, title_h - 8, CANVAS_W - 30, title_h - 8), fill=COLORS["line"], width=2)

    left_x = 30
    right_x = left_x + SIDE_W + SIDE_GAP
    _draw_side(
        image,
        draw,
        x=left_x,
        y=title_h,
        side=red,
        color=COLORS["red"],
        icon_background=RED_ICON_BACKGROUND,
        side_label="1号",
    )
    _draw_side(
        image,
        draw,
        x=right_x,
        y=title_h,
        side=blue,
        color=COLORS["blue"],
        icon_background=BLUE_ICON_BACKGROUND,
        side_label="2号",
    )

    footer_y = title_h + body_h + 5
    draw.line((30, footer_y, CANVAS_W - 30, footer_y), fill=COLORS["line"], width=1)
    draw.text(
        (CANVAS_W // 2, footer_y + 20),
        bet_hint,
        anchor="ma",
        font=font_footer,
        fill=COLORS["title"],
    )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
