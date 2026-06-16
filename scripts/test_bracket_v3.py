"""Pillow 快速原型：王中王锦标赛括号对阵图 v3。

改进点 (vs v2):
- 去掉 emoji（Pillow 渲染不了），用纯文字/图形替代
- 缩短横线距离，整体更紧凑
- 淘汰图标更暗（0.25 亮度），对比更明显
- 冠军金色高亮 + 金框
- 文字长度截断防溢出
- 图例更醒目
- 排名图前三名加底色条、冠军金色文字
"""

from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from pathlib import Path

ICONS_DIR = Path("resources/aoe3/icons")
FONT_PATH = "C:/Windows/Fonts/msyh.ttc"
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
    "champ_glow": (255, 215, 0, 60),
    "row_gold": (50, 45, 20),
    "row_silver": (40, 42, 50),
    "row_bronze": (45, 38, 28),
}

# 8 个测试单位
UNITS = [
    ("musketeer", "火枪兵"),
    ("skirmisher", "散兵"),
    ("crossbowman", "弩手"),
    ("pikeman", "长矛兵"),
    ("hussar", "轻骑兵"),
    ("cavalryarcher", "骑射手"),
    ("dragoon", "枪骑兵"),
    ("janissary", "奥斯曼火枪"),
]

# 模拟锦标赛结果
# QF: 每组 (上idx, 下idx) → 胜者idx
QF_RESULTS = {0: 1, 1: 2, 2: 4, 3: 6}  # match_idx → winner unit idx
# SF: 散兵(1) vs 弩手(2) → 散兵(1)胜, 轻骑兵(4) vs 枪骑兵(6) → 轻骑兵(4)胜
SF_RESULTS = {0: 1, 1: 4}  # match_idx → winner unit idx
# Final: 散兵(1) vs 轻骑兵(4) → 散兵(1)胜
CHAMPION_IDX = 1
RUNNERUP_IDX = 4

FINAL_RANKS = [
    (1, "散兵"),
    (4, "轻骑兵"),
    (2, "弩手"),
    (7, "奥斯曼火枪"),
    (0, "火枪兵"),
    (6, "枪骑兵"),
    (3, "长矛兵"),
    (5, "骑射手"),
]


def load_icon(unit_id: str, size: int) -> Image.Image:
    img = Image.open(ICONS_DIR / f"{unit_id}.png").convert("RGBA")
    return img.resize((size, size), Image.LANCZOS)


def dim_icon(img: Image.Image, factor: float = 0.25) -> Image.Image:
    return ImageEnhance.Brightness(img).enhance(factor)


def draw_cross(draw: ImageDraw.Draw, x: int, y: int, size: int):
    m = size // 5
    draw.line([(x + m, y + m), (x + size - m, y + size - m)],
              fill=COLORS["elim_cross"], width=2)
    draw.line([(x + size - m, y + m), (x + m, y + size - m)],
              fill=COLORS["elim_cross"], width=2)


def draw_rounded_rect(draw: ImageDraw.Draw, bbox, fill, radius=6):
    """画圆角矩形背景。"""
    x1, y1, x2, y2 = bbox
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill)


def draw_bracket():
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), COLORS["bg"])
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, 16)
    font_sm = ImageFont.truetype(FONT_PATH, 14)
    font_title = ImageFont.truetype(FONT_PATH, 20)
    font_champ = ImageFont.truetype(FONT_PATH, 18)
    font_legend = ImageFont.truetype(FONT_PATH, 12)

    icons = {i: load_icon(uid, ICON_SIZE) for i, (uid, _) in enumerate(UNITS)}
    icons_sm = {i: load_icon(uid, SMALL_ICON) for i, (uid, _) in enumerate(UNITS)}

    # ── 列位置（加大边距防重叠）──
    col1_x = 35      # 八强
    col2_x = 250     # 四强
    col3_x = 460     # 决赛
    col4_x = 670     # 冠军
    start_y = 75
    pair_gap = 140    # 每对之间的 y 距离

    # ── 标题 ──
    draw.text((35, 15), "王中王锦标赛 · 火枪王",
              fill=COLORS["gold"], font=font_title)

    # ── 轮次标签（渐进高亮：越往后越暖越亮）──
    font_label = ImageFont.truetype(FONT_PATH, 17)
    label_y = 53
    label_colors = [
        (140, 145, 160),   # 八强：冷灰蓝
        (180, 185, 200),   # 四强：亮银
        (220, 180, 100),   # 决赛：暖金偏橙
        (255, 215, 0),     # 冠军：纯金
    ]
    for (lx, label), lc in zip(
        [(col1_x, "八强"), (col2_x, "四强"),
         (col3_x, "决赛"), (col4_x + 10, "冠军")],
        label_colors
    ):
        draw.text((lx, label_y), label, fill=lc, font=font_label)

    # ── 第一轮（八强）──
    qf_positions = []  # [(y_top, y_bot), ...]
    for m in range(4):
        y1 = start_y + m * pair_gap
        y2 = y1 + 55
        qf_positions.append((y1, y2))

    sf_ys = []  # 四强节点 y 坐标
    for m_idx, (y1, y2) in enumerate(qf_positions):
        idx1 = m_idx * 2
        idx2 = m_idx * 2 + 1
        winner = QF_RESULTS[m_idx]
        top_wins = (idx1 == winner)

        # 上方选手
        _draw_unit(img, draw, col1_x, y1, idx1, icons, font, is_winner=top_wins)
        # 下方选手
        _draw_unit(img, draw, col1_x, y2, idx2, icons, font, is_winner=not top_wins)

        # 连线到四强
        mid_y = (y1 + y2) // 2
        sf_ys.append(mid_y)
        junc_x = col2_x - 15

        for (yy, wins) in [(y1, top_wins), (y2, not top_wins)]:
            c = COLORS["winner"] if wins else COLORS["eliminated"]
            line_sx = col1_x + ICON_SIZE + _name_width(draw, UNITS[idx1 if yy == y1 else idx2][1], font) + 12
            line_sx = min(line_sx, junc_x - 5)
            draw.line([(line_sx, yy), (junc_x, yy)], fill=c, width=2)

        draw.line([(junc_x, y1), (junc_x, mid_y)], fill=COLORS["line"], width=2)
        draw.line([(junc_x, y2), (junc_x, mid_y)], fill=COLORS["line"], width=2)
        draw.line([(junc_x, mid_y), (col2_x, mid_y)], fill=COLORS["winner_dim"], width=2)

        # 四强图标
        w_icon = icons_sm[winner]
        img.paste(w_icon, (col2_x, mid_y - SMALL_ICON // 2), w_icon)
        draw.text((col2_x + SMALL_ICON + 4, mid_y - 8),
                  UNITS[winner][1], fill=(230, 220, 180), font=font)

    # ── 第二轮（四强 → 决赛）──
    sf_pairs = [
        (0, 1, SF_RESULTS[0]),  # 四强 match 0: sf_ys[0] vs sf_ys[1]
        (2, 3, SF_RESULTS[1]),  # 四强 match 1: sf_ys[2] vs sf_ys[3]
    ]
    fin_ys = []
    sf_unit_map = [QF_RESULTS[i] for i in range(4)]  # 四强的单位 idx

    for sf_idx, (a, b, winner) in enumerate(sf_pairs):
        ya, yb = sf_ys[a], sf_ys[b]
        mid_y = (ya + yb) // 2
        fin_ys.append(mid_y)
        junc_x = col3_x - 15

        for (yy, sf_slot) in [(ya, a), (yb, b)]:
            u_idx = sf_unit_map[sf_slot]
            wins = (u_idx == winner)
            c = COLORS["winner"] if wins else COLORS["line"]
            line_sx = col2_x + SMALL_ICON + _name_width(draw, UNITS[u_idx][1], font) + 10
            line_sx = min(line_sx, junc_x - 5)
            draw.line([(line_sx, yy), (junc_x, yy)], fill=c, width=2)

        draw.line([(junc_x, ya), (junc_x, mid_y)], fill=COLORS["line"], width=2)
        draw.line([(junc_x, yb), (junc_x, mid_y)], fill=COLORS["line"], width=2)
        draw.line([(junc_x, mid_y), (col3_x, mid_y)], fill=COLORS["winner_dim"], width=2)

        # 决赛图标
        w_icon = icons_sm[winner]
        img.paste(w_icon, (col3_x, mid_y - SMALL_ICON // 2), w_icon)
        draw.text((col3_x + SMALL_ICON + 4, mid_y - 8),
                  UNITS[winner][1], fill=(230, 220, 180), font=font)

    # ── 决赛 → 冠军 ──
    champ_y = (fin_ys[0] + fin_ys[1]) // 2
    junc_x = col4_x - 15

    for yy, u_idx in [(fin_ys[0], CHAMPION_IDX), (fin_ys[1], RUNNERUP_IDX)]:
        wins = (u_idx == CHAMPION_IDX)
        c = COLORS["gold"] if wins else COLORS["silver"]
        line_sx = col3_x + SMALL_ICON + _name_width(draw, UNITS[u_idx][1], font) + 10
        line_sx = min(line_sx, junc_x - 5)
        draw.line([(line_sx, yy), (junc_x, yy)], fill=c, width=2)

    draw.line([(junc_x, fin_ys[0]), (junc_x, champ_y)], fill=COLORS["gold_dark"], width=2)
    draw.line([(junc_x, fin_ys[1]), (junc_x, champ_y)], fill=COLORS["gold_dark"], width=2)
    draw.line([(junc_x, champ_y), (col4_x, champ_y)], fill=COLORS["gold"], width=3)

    # 冠军：金色边框 + 大图标
    champ_icon = load_icon(UNITS[CHAMPION_IDX][0], CHAMP_ICON)
    icon_x = col4_x + 5
    icon_y = champ_y - CHAMP_ICON // 2

    # 金色背景光晕
    glow_pad = 5
    draw.rounded_rectangle(
        [icon_x - glow_pad, icon_y - glow_pad,
         icon_x + CHAMP_ICON + glow_pad, icon_y + CHAMP_ICON + glow_pad],
        radius=8, outline=COLORS["gold"], width=3
    )
    img.paste(champ_icon, (icon_x, icon_y), champ_icon)

    draw.text((icon_x + CHAMP_ICON + 10, champ_y - 12),
              UNITS[CHAMPION_IDX][1], fill=COLORS["gold"], font=font_champ)
    draw.text((icon_x + CHAMP_ICON + 10, champ_y + 8),
              "CHAMPION", fill=COLORS["gold_dark"], font=font_sm)

    # ── 图例 ──
    ly = CANVAS_H - 35
    # 晋级
    draw.line([(35, ly), (65, ly)], fill=COLORS["winner"], width=2)
    draw.text((72, ly - 7), "晋级", fill=COLORS["text_dim"], font=font_legend)
    # 淘汰
    draw.line([(130, ly), (160, ly)], fill=COLORS["eliminated"], width=2)
    draw_cross(draw, 137, ly - 7, 14)
    draw.text((168, ly - 7), "淘汰", fill=COLORS["text_dim"], font=font_legend)
    # 冠军路径
    draw.line([(226, ly), (256, ly)], fill=COLORS["gold"], width=3)
    draw.text((264, ly - 7), "冠军路径", fill=COLORS["text_dim"], font=font_legend)

    out = "scripts/test_bracket_v3.png"
    img.save(out)
    print(f"Done: {out}")
    return out


def _draw_unit(img, draw, x, y, idx, icons, font, is_winner):
    """画一个参赛单位（图标 + 名字），区分胜/败。"""
    icon = icons[idx]
    if not is_winner:
        icon = dim_icon(icon, 0.25)
    img.paste(icon, (x, y - ICON_SIZE // 2), icon)
    if not is_winner:
        draw_cross(draw, x, y - ICON_SIZE // 2, ICON_SIZE)

    name = UNITS[idx][1]
    text_color = (230, 220, 180) if is_winner else COLORS["text_dim"]  # 胜者浅金
    draw.text((x + ICON_SIZE + 5, y - 8), name, fill=text_color, font=font)


def _name_width(draw, name, font):
    bbox = draw.textbbox((0, 0), name, font=font)
    return bbox[2] - bbox[0]


def draw_ranking():
    """最终排名图 v3：前三名有底色高亮，冠军金色文字，无 emoji。"""
    W, H = 400, 540
    img = Image.new("RGBA", (W, H), COLORS["bg"])
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, 16)
    font_title = ImageFont.truetype(FONT_PATH, 20)
    font_rank = ImageFont.truetype(FONT_PATH, 14)
    font_sm = ImageFont.truetype(FONT_PATH, 12)

    # 标题（居中）
    title_text = "最终排名"
    tb = draw.textbbox((0, 0), title_text, font=font_title)
    title_w = tb[2] - tb[0]
    draw.text(((W - title_w) // 2, 10), title_text, fill=COLORS["gold"], font=font_title)
    draw.line([(30, 38), (W - 30, 38)], fill=(60, 60, 65), width=1)

    rank_labels = ["1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th"]
    row_colors = [COLORS["row_gold"], COLORS["row_silver"], COLORS["row_bronze"]]

    y = 50
    row_h = 54
    icon_size = 38

    for rank, (idx, name) in enumerate(FINAL_RANKS):
        ry = y + rank * row_h
        icon = load_icon(UNITS[idx][0], icon_size)

        # 前三名加底色
        if rank < 3:
            draw.rounded_rectangle(
                [20, ry - 2, W - 20, ry + row_h - 6],
                radius=6, fill=row_colors[rank]
            )

        # 排名标签
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

        # 名字
        if rank == 0:
            nc = COLORS["gold"]
        elif rank < 3:
            nc = COLORS["text"]
        else:
            nc = (180, 180, 185)
        draw.text((ix + icon_size + 10, ry + 13), name, fill=nc, font=font)

    # 底部装饰线
    draw.line([(30, H - 32), (W - 30, H - 32)], fill=(60, 60, 65), width=1)
    draw.text((W // 2 - 55, H - 26), "Tournament Complete",
              fill=COLORS["text_dim"], font=font_sm)

    out = "scripts/test_ranking_v3.png"
    img.save(out)
    print(f"Done: {out}")
    return out


if __name__ == "__main__":
    draw_bracket()
    draw_ranking()
