"""王中王锦标赛对阵图 / 排名图 Pillow 渲染器。

从 scripts/test_bracket_stages.py 移植而来，参数化所有硬编码数据。
返回 PNG bytes，不写文件。
"""

from __future__ import annotations

import io
import platform
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

# ────────────────── 数据类 ──────────────────

_STAGE_PRE = "pre"
_STAGE_QF_DONE = "qf_done"
_STAGE_SF_DONE = "sf_done"
_STAGE_FINAL = "final"


@dataclass
class BracketData:
    """对阵图渲染所需的全部数据。

    Parameters
    ----------
    title : 标题文本（如 "王中王锦标赛 · 火枪王"）
    stage_label : 阶段标题后缀（"抽签" / "八强战" / "半决赛" / "决赛"）
    hint : 右下角操作提示（如 "发送「开战」开始八强战"）；空字符串则不显示
    units : 8 个 (unit_id, display_name) 元组列表
    icon_paths : 8 个图标文件 Path（与 units 索引对应）
    stage : 当前阶段 "pre" / "qf_done" / "sf_done" / "final"
    qf_results : QF match_idx(0-3) → winner unit_idx(0-7)
    sf_results : SF match_idx(0-1) → winner unit_idx
    champion_idx : 冠军在 units 中的索引
    runner_up_idx : 亚军在 units 中的索引
    """

    title: str
    stage_label: str
    hint: str
    units: list[tuple[str, str]]
    icon_paths: list[Path | None]
    stage: str = _STAGE_PRE
    qf_results: dict[int, int] = field(default_factory=dict)
    sf_results: dict[int, int] = field(default_factory=dict)
    champion_idx: int | None = None
    runner_up_idx: int | None = None


@dataclass
class RankingData:
    """最终排名图渲染所需的数据。"""

    title: str  # "最终排名" / "王中王锦标赛 · 最终排名"
    ranks: list[tuple[int, str]]  # [(unit_idx, display_name), ...] 从 1st 到 8th
    icon_paths: list[Path | None]  # 与 BracketData.units 索引对应（共 8 个）


# ────────────────── 常量 ──────────────────

ICON_SIZE = 44
SMALL_ICON = 38
CHAMP_ICON = 58
CANVAS_W = 940
CANVAS_H = 660

COLORS = {
    "bg": (25, 25, 30),
    "line": (90, 90, 100),
    "text": (220, 220, 220),
    "text_dim": (90, 90, 95),
    "gold": (255, 200, 50),
    "gold_dark": (180, 140, 30),
    "silver": (190, 195, 210),
    "bronze": (200, 145, 80),
    "eliminated": (60, 60, 65),
    "elim_cross": (170, 60, 60),
    "winner": (80, 200, 120),
    "winner_dim": (50, 130, 75),
    "pending": (100, 100, 120),
    "pending_text": (120, 120, 140),
    "row_gold": (50, 45, 20),
    "row_silver": (40, 42, 50),
    "row_bronze": (45, 38, 28),
}

# 轮次标签的渐变色：八强(冷灰蓝) → 四强(亮银) → 决赛(暖金) → 冠军(纯金)
_LABEL_COLORS = [
    (140, 145, 160),
    (180, 185, 200),
    (220, 180, 100),
    (255, 215, 0),
]

# ────────────────── 字体 ──────────────────

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

_FONT_CANDIDATES = [
    # Windows
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyh.ttf",
    # Docker / Linux (需在 Dockerfile 中安装中文字体)
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]

_resolved_font_path: str | None = None


def _find_font_path() -> str:
    """查找可用的中文字体路径。找不到则返回空字符串（Pillow 用默认字体）。"""
    global _resolved_font_path  # noqa: PLW0603
    if _resolved_font_path is not None:
        return _resolved_font_path
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            _resolved_font_path = p
            return p
    _resolved_font_path = ""
    return ""


def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = _find_font_path()
    if not path:
        return ImageFont.load_default()
    key = (path, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(path, size)
    return _font_cache[key]


# ────────────────── 图标工具 ──────────────────


def _load_icon(path: Path | None, size: int) -> Image.Image:
    """加载图标，缺失则生成灰色占位方块。"""
    if path and path.exists():
        img = Image.open(path).convert("RGBA")
        return img.resize((size, size), Image.LANCZOS)
    # 占位
    img = Image.new("RGBA", (size, size), (60, 60, 65, 200))
    return img


def _dim_icon(img: Image.Image, factor: float = 0.25) -> Image.Image:
    return ImageEnhance.Brightness(img).enhance(factor)


def _draw_cross(draw: ImageDraw.Draw, x: int, y: int, size: int):
    m = size // 5
    draw.line(
        [(x + m, y + m), (x + size - m, y + size - m)],
        fill=COLORS["elim_cross"],
        width=2,
    )
    draw.line(
        [(x + size - m, y + m), (x + m, y + size - m)],
        fill=COLORS["elim_cross"],
        width=2,
    )


def _name_width(draw: ImageDraw.Draw, name: str, font) -> int:
    bbox = draw.textbbox((0, 0), name, font=font)
    return bbox[2] - bbox[0]


# ────────────────── 兵种绘制 ──────────────────


def _draw_unit(
    img: Image.Image,
    draw: ImageDraw.Draw,
    x: int,
    y: int,
    idx: int,
    *,
    data: BracketData,
    icons: dict[int, Image.Image],
    font,
    state: str = "winner",
):
    """绘制一个兵种单元（图标 + 名称）。

    state: "winner" / "loser" / "pending"
    """
    icon = icons[idx]
    if state == "loser":
        icon = _dim_icon(icon, 0.25)
    # pending 不做暗化，直接用原始亮图标

    img.paste(icon, (x, y - ICON_SIZE // 2), icon)
    if state == "loser":
        _draw_cross(draw, x, y - ICON_SIZE // 2, ICON_SIZE)

    name = data.units[idx][1]
    if state in ("winner", "pending"):
        text_color = (230, 220, 180)  # 存活/候场都用浅金
    else:
        text_color = COLORS["text_dim"]
    draw.text((x + ICON_SIZE + 5, y - 8), name, fill=text_color, font=font)


# ────────────────── render_bracket ──────────────────


def render_bracket(data: BracketData) -> bytes:
    """渲染对阵图，返回 PNG bytes。"""
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), COLORS["bg"])
    draw = ImageDraw.Draw(img)

    font = _get_font(16)
    font_sm = _get_font(14)
    font_title = _get_font(20)
    font_champ = _get_font(18)
    font_legend = _get_font(12)
    font_label = _get_font(17)
    font_hint = _get_font(15)

    stage = data.stage

    # 加载图标
    icons = {
        i: _load_icon(data.icon_paths[i], ICON_SIZE) for i in range(len(data.units))
    }
    icons_sm = {
        i: _load_icon(data.icon_paths[i], SMALL_ICON) for i in range(len(data.units))
    }

    # 列位置
    col1_x = 35
    col2_x = 250
    col3_x = 460
    col4_x = 670
    start_y = 75
    pair_gap = 140

    # ── 标题 ──
    title_text = data.title
    if data.stage_label:
        title_text += f" · {data.stage_label}"
    draw.text((35, 15), title_text, fill=COLORS["gold"], font=font_title)

    # ── 轮次标签 ──
    label_y = 53
    _label_items = [
        (col1_x, "八强"),
        (col2_x, "四强"),
        (col3_x, "决赛"),
        (col4_x + 10, "冠军"),
    ]
    for (lx, label), lc in zip(_label_items, _LABEL_COLORS):
        # 未到达的轮次用暗色
        if stage == _STAGE_PRE:
            lc = (80, 80, 90)
        elif stage == _STAGE_QF_DONE and label in ("决赛", "冠军"):
            lc = (80, 80, 90)
        elif stage == _STAGE_SF_DONE and label == "冠军":
            lc = (80, 80, 90)
        draw.text((lx, label_y), label, fill=lc, font=font_label)

    # ── 八强 ──
    qf_done = stage in (_STAGE_QF_DONE, _STAGE_SF_DONE, _STAGE_FINAL)
    qf_positions = []
    for m in range(4):
        y1 = start_y + m * pair_gap
        y2 = y1 + 55
        qf_positions.append((y1, y2))

    sf_ys: list[int] = []
    for m_idx, (y1, y2) in enumerate(qf_positions):
        idx1 = m_idx * 2
        idx2 = m_idx * 2 + 1

        if qf_done:
            winner = data.qf_results[m_idx]
            top_wins = idx1 == winner
            _draw_unit(
                img, draw, col1_x, y1, idx1,
                data=data, icons=icons, font=font,
                state="winner" if top_wins else "loser",
            )
            _draw_unit(
                img, draw, col1_x, y2, idx2,
                data=data, icons=icons, font=font,
                state="winner" if not top_wins else "loser",
            )
        else:
            _draw_unit(
                img, draw, col1_x, y1, idx1,
                data=data, icons=icons, font=font, state="pending",
            )
            _draw_unit(
                img, draw, col1_x, y2, idx2,
                data=data, icons=icons, font=font, state="pending",
            )

        mid_y = (y1 + y2) // 2
        sf_ys.append(mid_y)
        junc_x = col2_x - 15

        if qf_done:
            top_wins = idx1 == data.qf_results[m_idx]
            for yy, wins in [(y1, top_wins), (y2, not top_wins)]:
                c = COLORS["winner"] if wins else COLORS["eliminated"]
                u = idx1 if yy == y1 else idx2
                line_sx = col1_x + ICON_SIZE + _name_width(draw, data.units[u][1], font) + 12
                line_sx = min(line_sx, junc_x - 5)
                draw.line([(line_sx, yy), (junc_x, yy)], fill=c, width=2)
            draw.line([(junc_x, y1), (junc_x, mid_y)], fill=COLORS["line"], width=2)
            draw.line([(junc_x, y2), (junc_x, mid_y)], fill=COLORS["line"], width=2)
            draw.line(
                [(junc_x, mid_y), (col2_x, mid_y)],
                fill=COLORS["winner_dim"],
                width=2,
            )
            # 四强图标
            w = data.qf_results[m_idx]
            w_icon = icons_sm[w]
            img.paste(w_icon, (col2_x, mid_y - SMALL_ICON // 2), w_icon)
            draw.text(
                (col2_x + SMALL_ICON + 4, mid_y - 8),
                data.units[w][1],
                fill=(230, 220, 180),
                font=font,
            )
        else:
            # 赛前：画虚线到四强（待定风格）
            for yy in [y1, y2]:
                u = idx1 if yy == y1 else idx2
                line_sx = col1_x + ICON_SIZE + _name_width(draw, data.units[u][1], font) + 12
                line_sx = min(line_sx, junc_x - 5)
                draw.line(
                    [(line_sx, yy), (junc_x, yy)],
                    fill=COLORS["pending"],
                    width=1,
                )
            draw.line([(junc_x, y1), (junc_x, mid_y)], fill=COLORS["pending"], width=1)
            draw.line([(junc_x, y2), (junc_x, mid_y)], fill=COLORS["pending"], width=1)
            draw.line(
                [(junc_x, mid_y), (col2_x, mid_y)],
                fill=COLORS["pending"],
                width=1,
            )
            # 问号占位
            draw.text(
                (col2_x + 8, mid_y - 10),
                "?",
                fill=COLORS["pending_text"],
                font=font_title,
            )

    # ── 四强 → 决赛 ──
    sf_done = stage in (_STAGE_SF_DONE, _STAGE_FINAL)
    sf_unit_map = [data.qf_results.get(i, -1) for i in range(4)]
    fin_ys: list[int] = []

    sf_pairs: list[tuple[int, int, int | None]] = [
        (0, 1, data.sf_results.get(0)),
        (2, 3, data.sf_results.get(1)),
    ]

    for sf_idx, (a, b, winner) in enumerate(sf_pairs):
        ya, yb = sf_ys[a], sf_ys[b]
        mid_y = (ya + yb) // 2
        fin_ys.append(mid_y)
        junc_x = col3_x - 15

        if sf_done and winner is not None:
            for yy, sf_slot in [(ya, a), (yb, b)]:
                u_idx = sf_unit_map[sf_slot]
                wins = u_idx == winner
                c = COLORS["winner"] if wins else COLORS["line"]
                line_sx = (
                    col2_x
                    + SMALL_ICON
                    + _name_width(draw, data.units[u_idx][1], font)
                    + 10
                )
                line_sx = min(line_sx, junc_x - 5)
                draw.line([(line_sx, yy), (junc_x, yy)], fill=c, width=2)
            draw.line([(junc_x, ya), (junc_x, mid_y)], fill=COLORS["line"], width=2)
            draw.line([(junc_x, yb), (junc_x, mid_y)], fill=COLORS["line"], width=2)
            draw.line(
                [(junc_x, mid_y), (col3_x, mid_y)],
                fill=COLORS["winner_dim"],
                width=2,
            )
            w_icon = icons_sm[winner]
            img.paste(w_icon, (col3_x, mid_y - SMALL_ICON // 2), w_icon)
            draw.text(
                (col3_x + SMALL_ICON + 4, mid_y - 8),
                data.units[winner][1],
                fill=(230, 220, 180),
                font=font,
            )
        elif qf_done:
            # 八强结束但四强未打：画待定连线
            for yy in [ya, yb]:
                line_sx = col2_x + SMALL_ICON + 60
                line_sx = min(line_sx, junc_x - 5)
                draw.line(
                    [(line_sx, yy), (junc_x, yy)],
                    fill=COLORS["pending"],
                    width=1,
                )
            draw.line([(junc_x, ya), (junc_x, mid_y)], fill=COLORS["pending"], width=1)
            draw.line([(junc_x, yb), (junc_x, mid_y)], fill=COLORS["pending"], width=1)
            draw.line(
                [(junc_x, mid_y), (col3_x, mid_y)],
                fill=COLORS["pending"],
                width=1,
            )
            draw.text(
                (col3_x + 8, mid_y - 10),
                "?",
                fill=COLORS["pending_text"],
                font=font_title,
            )
        else:
            # 赛前
            draw.line(
                [(col2_x + 30, ya), (junc_x, ya)],
                fill=COLORS["pending"],
                width=1,
            )
            draw.line(
                [(col2_x + 30, yb), (junc_x, yb)],
                fill=COLORS["pending"],
                width=1,
            )
            draw.line([(junc_x, ya), (junc_x, mid_y)], fill=COLORS["pending"], width=1)
            draw.line([(junc_x, yb), (junc_x, mid_y)], fill=COLORS["pending"], width=1)
            draw.line(
                [(junc_x, mid_y), (col3_x, mid_y)],
                fill=COLORS["pending"],
                width=1,
            )
            draw.text(
                (col3_x + 8, mid_y - 10),
                "?",
                fill=COLORS["pending_text"],
                font=font_title,
            )

    # ── 决赛 → 冠军 ──
    is_final = stage == _STAGE_FINAL
    champ_y = (fin_ys[0] + fin_ys[1]) // 2 if len(fin_ys) >= 2 else CANVAS_H // 2
    junc_x = col4_x - 15

    if is_final and data.champion_idx is not None and data.runner_up_idx is not None:
        for yy, u_idx in [(fin_ys[0], data.champion_idx), (fin_ys[1], data.runner_up_idx)]:
            wins = u_idx == data.champion_idx
            c = COLORS["gold"] if wins else COLORS["silver"]
            line_sx = (
                col3_x
                + SMALL_ICON
                + _name_width(draw, data.units[u_idx][1], font)
                + 10
            )
            line_sx = min(line_sx, junc_x - 5)
            draw.line([(line_sx, yy), (junc_x, yy)], fill=c, width=2)
        draw.line(
            [(junc_x, fin_ys[0]), (junc_x, champ_y)],
            fill=COLORS["gold_dark"],
            width=2,
        )
        draw.line(
            [(junc_x, fin_ys[1]), (junc_x, champ_y)],
            fill=COLORS["gold_dark"],
            width=2,
        )
        draw.line(
            [(junc_x, champ_y), (col4_x, champ_y)],
            fill=COLORS["gold"],
            width=3,
        )

        # 冠军大图标
        champ_icon = _load_icon(data.icon_paths[data.champion_idx], CHAMP_ICON)
        icon_x = col4_x + 5
        icon_y = champ_y - CHAMP_ICON // 2
        glow_pad = 5
        draw.rounded_rectangle(
            [
                icon_x - glow_pad,
                icon_y - glow_pad,
                icon_x + CHAMP_ICON + glow_pad,
                icon_y + CHAMP_ICON + glow_pad,
            ],
            radius=8,
            outline=COLORS["gold"],
            width=3,
        )
        img.paste(champ_icon, (icon_x, icon_y), champ_icon)
        champ_name = data.units[data.champion_idx][1]
        draw.text(
            (icon_x + CHAMP_ICON + 10, champ_y - 12),
            champ_name,
            fill=COLORS["gold"],
            font=font_champ,
        )
        draw.text(
            (icon_x + CHAMP_ICON + 10, champ_y + 8),
            "CHAMPION",
            fill=COLORS["gold_dark"],
            font=font_sm,
        )
    else:
        # 未到决赛
        if sf_done:
            for yy in fin_ys:
                line_sx = col3_x + SMALL_ICON + 60
                line_sx = min(line_sx, junc_x - 5)
                draw.line(
                    [(line_sx, yy), (junc_x, yy)],
                    fill=COLORS["pending"],
                    width=1,
                )
        else:
            for yy in fin_ys:
                draw.line(
                    [(col3_x + 30, yy), (junc_x, yy)],
                    fill=COLORS["pending"],
                    width=1,
                )
        draw.line(
            [(junc_x, fin_ys[0]), (junc_x, champ_y)],
            fill=COLORS["pending"],
            width=1,
        )
        draw.line(
            [(junc_x, fin_ys[1]), (junc_x, champ_y)],
            fill=COLORS["pending"],
            width=1,
        )
        draw.line(
            [(junc_x, champ_y), (col4_x, champ_y)],
            fill=COLORS["pending"],
            width=1,
        )
        draw.text(
            (col4_x + 12, champ_y - 10),
            "?",
            fill=COLORS["pending_text"],
            font=font_title,
        )

    # ── 图例 ──
    ly = CANVAS_H - 35
    draw.line([(35, ly), (65, ly)], fill=COLORS["winner"], width=2)
    draw.text((72, ly - 7), "晋级", fill=COLORS["text_dim"], font=font_legend)
    draw.line([(130, ly), (160, ly)], fill=COLORS["eliminated"], width=2)
    _draw_cross(draw, 137, ly - 7, 14)
    draw.text((168, ly - 7), "淘汰", fill=COLORS["text_dim"], font=font_legend)
    draw.line([(226, ly), (256, ly)], fill=COLORS["pending"], width=1)
    draw.text((264, ly - 7), "待定", fill=COLORS["text_dim"], font=font_legend)
    if is_final:
        draw.line([(320, ly), (350, ly)], fill=COLORS["gold"], width=3)
        draw.text((358, ly - 7), "冠军路径", fill=COLORS["text_dim"], font=font_legend)

    # ── 右下角操作提示 ──
    if data.hint:
        hint_bbox = draw.textbbox((0, 0), data.hint, font=font_hint)
        hint_w = hint_bbox[2] - hint_bbox[0]
        hint_x = CANVAS_W - hint_w - 30
        hint_y = CANVAS_H - 38
        draw.text((hint_x, hint_y), data.hint, fill=(200, 195, 160), font=font_hint)

    # ── 输出 PNG bytes ──
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ────────────────── render_ranking ──────────────────


def render_ranking(data: RankingData) -> bytes:
    """渲染最终排名图，返回 PNG bytes。"""
    W, H = 400, 540
    img = Image.new("RGBA", (W, H), COLORS["bg"])
    draw = ImageDraw.Draw(img)

    font = _get_font(16)
    font_title = _get_font(20)
    font_rank = _get_font(14)
    font_sm = _get_font(12)

    # 标题居中
    title_text = data.title
    tb = draw.textbbox((0, 0), title_text, font=font_title)
    title_w = tb[2] - tb[0]
    draw.text(((W - title_w) // 2, 10), title_text, fill=COLORS["gold"], font=font_title)
    draw.line([(30, 38), (W - 30, 38)], fill=(60, 60, 65), width=1)

    rank_labels = ["1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th"]
    row_colors = [COLORS["row_gold"], COLORS["row_silver"], COLORS["row_bronze"]]

    y_start = 50
    row_h = 54
    icon_size = 38

    for rank, (idx, name) in enumerate(data.ranks):
        ry = y_start + rank * row_h
        icon = _load_icon(data.icon_paths[idx], icon_size)

        # 前三名有背景色
        if rank < 3:
            draw.rounded_rectangle(
                [20, ry - 2, W - 20, ry + row_h - 6],
                radius=6,
                fill=row_colors[rank],
            )

        # 排名标签颜色
        rank_text = rank_labels[rank]
        if rank == 0:
            rc = COLORS["gold"]
        elif rank == 1:
            rc = COLORS["silver"]
        elif rank == 2:
            rc = COLORS["bronze"]
        else:
            rc = COLORS["text_dim"]
        draw.text((28, ry + 13), rank_text, fill=rc, font=font_rank)

        # 图标
        ix = 68
        img.paste(icon, (ix, ry + 5), icon)

        # 名称
        if rank == 0:
            nc = COLORS["gold"]
        elif rank < 3:
            nc = COLORS["text"]
        else:
            nc = (180, 180, 185)
        draw.text((ix + icon_size + 10, ry + 13), name, fill=nc, font=font)

    # 底部分隔线 + 完成标志
    draw.line([(30, H - 32), (W - 30, H - 32)], fill=(60, 60, 65), width=1)
    draw.text(
        (W // 2 - 55, H - 26),
        "Tournament Complete",
        fill=COLORS["text_dim"],
        font=font_sm,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
