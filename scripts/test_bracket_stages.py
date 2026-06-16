"""生成一场完整王中王锦标赛的各阶段对阵图。

阶段：
1. 赛前抽签（只有配对，无结果）
2. 八强战结束（QF1~4 有结果）
3. 排位赛 + 半决赛结束（LR + 5~8名 + SF 有结果）
4. 决赛结束（完整）+ 最终排名

赛制（12 场）：
QF1~4 → LR1/LR2(败者排位) → 7/8名战 + 5/6名战
→ SF1/SF2 → 季军战 → 决赛
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
    "pending": (100, 100, 120),       # 待定 / 未比赛
    "pending_text": (120, 120, 140),
    "row_gold": (50, 45, 20),
    "row_silver": (40, 42, 50),
    "row_bronze": (45, 38, 28),
}

LABEL_COLORS = [
    (140, 145, 160),   # 八强：冷灰蓝
    (180, 185, 200),   # 四强：亮银
    (220, 180, 100),   # 决赛：暖金偏橙
    (255, 215, 0),     # 冠军：纯金
]

# ── 8 个测试兵种 ──
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

# ── 模拟完整赛果 ──
# QF (4 场): match_idx → winner unit idx
QF_RESULTS = {0: 1, 1: 2, 2: 4, 3: 6}
# QF 败者: 0(火枪), 3(长矛), 5(骑射), 7(奥火)
# LR1: QF1败者(0火枪) vs QF2败者(3长矛) → 3长矛 胜
# LR2: QF3败者(5骑射) vs QF4败者(7奥火) → 7奥火 胜
LR_RESULTS = {0: 3, 1: 7}
# 7/8名战: LR1败(0火枪) vs LR2败(5骑射) → 0火枪 胜 → 火枪7th, 骑射8th
MATCH_7_8 = (0, 5, 0)  # (unit_a, unit_b, winner)
# 5/6名战: LR1胜(3长矛) vs LR2胜(7奥火) → 7奥火 胜 → 奥火5th, 长矛6th
MATCH_5_6 = (3, 7, 7)
# SF: 散兵(1) vs 弩手(2) → 散兵 胜; 轻骑(4) vs 枪骑(6) → 轻骑 胜
SF_RESULTS = {0: 1, 1: 4}
# 季军战: SF败者 弩手(2) vs 枪骑(6) → 弩手 胜 → 弩手3rd, 枪骑4th
MATCH_3RD = (2, 6, 2)
# 决赛: 散兵(1) vs 轻骑(4) → 散兵 胜
CHAMPION_IDX = 1
RUNNERUP_IDX = 4

# 最终排名 1~8
FINAL_RANKS = [
    (1, "散兵"),      # 1st: 决赛胜
    (4, "轻骑兵"),    # 2nd: 决赛败
    (2, "弩手"),      # 3rd: 季军战胜
    (6, "枪骑兵"),    # 4th: 季军战败
    (7, "奥斯曼火枪"),# 5th: 5/6名战胜
    (3, "长矛兵"),    # 6th: 5/6名战败
    (0, "火枪兵"),    # 7th: 7/8名战胜
    (5, "骑射手"),    # 8th: 7/8名战败
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


def _name_width(draw, name, font):
    bbox = draw.textbbox((0, 0), name, font=font)
    return bbox[2] - bbox[0]


def _draw_unit(img, draw, x, y, idx, icons, font, state="winner"):
    """
    state: "winner" / "loser" / "pending" (未比赛，用亮色)
    """
    icon = icons[idx]
    if state == "loser":
        icon = dim_icon(icon, 0.25)
    # pending 不做暗化，直接用原始亮图标
    img.paste(icon, (x, y - ICON_SIZE // 2), icon)
    if state == "loser":
        draw_cross(draw, x, y - ICON_SIZE // 2, ICON_SIZE)

    name = UNITS[idx][1]
    if state in ("winner", "pending"):
        text_color = (230, 220, 180)  # 存活/候场都用浅金
    else:
        text_color = COLORS["text_dim"]
    draw.text((x + ICON_SIZE + 5, y - 8), name, fill=text_color, font=font)


def draw_bracket(stage: str = "final", title_suffix: str = "",
                 subtitle: str = "", out_path: str = None):
    """
    stage:
      "pre"     - 赛前抽签，只有配对
      "qf_done" - 八强战结束
      "sf_done" - 排位赛+半决赛结束
      "final"   - 决赛结束（完整）
    """
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), COLORS["bg"])
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, 16)
    font_sm = ImageFont.truetype(FONT_PATH, 14)
    font_title = ImageFont.truetype(FONT_PATH, 20)
    font_champ = ImageFont.truetype(FONT_PATH, 18)
    font_legend = ImageFont.truetype(FONT_PATH, 12)
    font_label = ImageFont.truetype(FONT_PATH, 17)
    font_hint = ImageFont.truetype(FONT_PATH, 15)

    icons = {i: load_icon(uid, ICON_SIZE) for i, (uid, _) in enumerate(UNITS)}
    icons_sm = {i: load_icon(uid, SMALL_ICON) for i, (uid, _) in enumerate(UNITS)}

    # 列位置
    col1_x = 35
    col2_x = 250
    col3_x = 460
    col4_x = 670
    start_y = 75
    pair_gap = 140

    # 标题
    title_text = "王中王锦标赛 · 火枪王"
    if title_suffix:
        title_text += f" · {title_suffix}"
    draw.text((35, 15), title_text, fill=COLORS["gold"], font=font_title)

    # 轮次标签
    label_y = 53
    for (lx, label), lc in zip(
        [(col1_x, "八强"), (col2_x, "四强"),
         (col3_x, "决赛"), (col4_x + 10, "冠军")],
        LABEL_COLORS
    ):
        # 未到达的轮次用暗色
        if stage == "pre":
            lc = (80, 80, 90)  # 全暗
        elif stage == "qf_done" and label in ("决赛", "冠军"):
            lc = (80, 80, 90)
        elif stage == "sf_done" and label == "冠军":
            lc = (80, 80, 90)
        draw.text((lx, label_y), label, fill=lc, font=font_label)

    # ── 八强 ──
    qf_done = stage in ("qf_done", "sf_done", "final")
    qf_positions = []
    for m in range(4):
        y1 = start_y + m * pair_gap
        y2 = y1 + 55
        qf_positions.append((y1, y2))

    sf_ys = []
    for m_idx, (y1, y2) in enumerate(qf_positions):
        idx1 = m_idx * 2
        idx2 = m_idx * 2 + 1

        if qf_done:
            winner = QF_RESULTS[m_idx]
            top_wins = (idx1 == winner)
            _draw_unit(img, draw, col1_x, y1, idx1, icons, font,
                       state="winner" if top_wins else "loser")
            _draw_unit(img, draw, col1_x, y2, idx2, icons, font,
                       state="winner" if not top_wins else "loser")
        else:
            # 赛前：所有人 pending
            _draw_unit(img, draw, col1_x, y1, idx1, icons, font, state="pending")
            _draw_unit(img, draw, col1_x, y2, idx2, icons, font, state="pending")

        mid_y = (y1 + y2) // 2
        sf_ys.append(mid_y)
        junc_x = col2_x - 15

        if qf_done:
            for (yy, wins) in [(y1, top_wins), (y2, not top_wins)]:
                c = COLORS["winner"] if wins else COLORS["eliminated"]
                u = idx1 if yy == y1 else idx2
                line_sx = col1_x + ICON_SIZE + _name_width(draw, UNITS[u][1], font) + 12
                line_sx = min(line_sx, junc_x - 5)
                draw.line([(line_sx, yy), (junc_x, yy)], fill=c, width=2)
            draw.line([(junc_x, y1), (junc_x, mid_y)], fill=COLORS["line"], width=2)
            draw.line([(junc_x, y2), (junc_x, mid_y)], fill=COLORS["line"], width=2)
            draw.line([(junc_x, mid_y), (col2_x, mid_y)],
                      fill=COLORS["winner_dim"], width=2)
            # 四强图标
            w = QF_RESULTS[m_idx]
            w_icon = icons_sm[w]
            img.paste(w_icon, (col2_x, mid_y - SMALL_ICON // 2), w_icon)
            draw.text((col2_x + SMALL_ICON + 4, mid_y - 8),
                      UNITS[w][1], fill=(230, 220, 180), font=font)
        else:
            # 赛前：画虚线到四强（待定风格）
            for yy in [y1, y2]:
                u = idx1 if yy == y1 else idx2
                line_sx = col1_x + ICON_SIZE + _name_width(draw, UNITS[u][1], font) + 12
                line_sx = min(line_sx, junc_x - 5)
                draw.line([(line_sx, yy), (junc_x, yy)],
                          fill=COLORS["pending"], width=1)
            draw.line([(junc_x, y1), (junc_x, mid_y)], fill=COLORS["pending"], width=1)
            draw.line([(junc_x, y2), (junc_x, mid_y)], fill=COLORS["pending"], width=1)
            draw.line([(junc_x, mid_y), (col2_x, mid_y)],
                      fill=COLORS["pending"], width=1)
            # 问号占位
            draw.text((col2_x + 8, mid_y - 10), "?",
                      fill=COLORS["pending_text"], font=font_title)

    # ── 四强 → 决赛 ──
    sf_done = stage in ("sf_done", "final")
    sf_pairs = [
        (0, 1, SF_RESULTS.get(0)),
        (2, 3, SF_RESULTS.get(1)),
    ]
    sf_unit_map = [QF_RESULTS[i] for i in range(4)]
    fin_ys = []

    for sf_idx, (a, b, winner) in enumerate(sf_pairs):
        ya, yb = sf_ys[a], sf_ys[b]
        mid_y = (ya + yb) // 2
        fin_ys.append(mid_y)
        junc_x = col3_x - 15

        if sf_done:
            for (yy, sf_slot) in [(ya, a), (yb, b)]:
                u_idx = sf_unit_map[sf_slot]
                wins = (u_idx == winner)
                c = COLORS["winner"] if wins else COLORS["line"]
                line_sx = col2_x + SMALL_ICON + _name_width(draw, UNITS[u_idx][1], font) + 10
                line_sx = min(line_sx, junc_x - 5)
                draw.line([(line_sx, yy), (junc_x, yy)], fill=c, width=2)
            draw.line([(junc_x, ya), (junc_x, mid_y)], fill=COLORS["line"], width=2)
            draw.line([(junc_x, yb), (junc_x, mid_y)], fill=COLORS["line"], width=2)
            draw.line([(junc_x, mid_y), (col3_x, mid_y)],
                      fill=COLORS["winner_dim"], width=2)
            w_icon = icons_sm[winner]
            img.paste(w_icon, (col3_x, mid_y - SMALL_ICON // 2), w_icon)
            draw.text((col3_x + SMALL_ICON + 4, mid_y - 8),
                      UNITS[winner][1], fill=(230, 220, 180), font=font)
        elif qf_done:
            # 八强结束但四强未打：画待定连线
            for yy in [ya, yb]:
                line_sx = col2_x + SMALL_ICON + 60
                line_sx = min(line_sx, junc_x - 5)
                draw.line([(line_sx, yy), (junc_x, yy)],
                          fill=COLORS["pending"], width=1)
            draw.line([(junc_x, ya), (junc_x, mid_y)], fill=COLORS["pending"], width=1)
            draw.line([(junc_x, yb), (junc_x, mid_y)], fill=COLORS["pending"], width=1)
            draw.line([(junc_x, mid_y), (col3_x, mid_y)],
                      fill=COLORS["pending"], width=1)
            draw.text((col3_x + 8, mid_y - 10), "?",
                      fill=COLORS["pending_text"], font=font_title)
        else:
            # 赛前
            draw.line([(col2_x + 30, ya), (junc_x, ya)],
                      fill=COLORS["pending"], width=1)
            draw.line([(col2_x + 30, yb), (junc_x, yb)],
                      fill=COLORS["pending"], width=1)
            draw.line([(junc_x, ya), (junc_x, mid_y)], fill=COLORS["pending"], width=1)
            draw.line([(junc_x, yb), (junc_x, mid_y)], fill=COLORS["pending"], width=1)
            draw.line([(junc_x, mid_y), (col3_x, mid_y)],
                      fill=COLORS["pending"], width=1)
            draw.text((col3_x + 8, mid_y - 10), "?",
                      fill=COLORS["pending_text"], font=font_title)

    # ── 决赛 → 冠军 ──
    is_final = (stage == "final")
    champ_y = (fin_ys[0] + fin_ys[1]) // 2
    junc_x = col4_x - 15

    if is_final:
        for yy, u_idx in [(fin_ys[0], CHAMPION_IDX), (fin_ys[1], RUNNERUP_IDX)]:
            wins = (u_idx == CHAMPION_IDX)
            c = COLORS["gold"] if wins else COLORS["silver"]
            line_sx = col3_x + SMALL_ICON + _name_width(draw, UNITS[u_idx][1], font) + 10
            line_sx = min(line_sx, junc_x - 5)
            draw.line([(line_sx, yy), (junc_x, yy)], fill=c, width=2)
        draw.line([(junc_x, fin_ys[0]), (junc_x, champ_y)],
                  fill=COLORS["gold_dark"], width=2)
        draw.line([(junc_x, fin_ys[1]), (junc_x, champ_y)],
                  fill=COLORS["gold_dark"], width=2)
        draw.line([(junc_x, champ_y), (col4_x, champ_y)],
                  fill=COLORS["gold"], width=3)

        # 冠军大图标
        champ_icon = load_icon(UNITS[CHAMPION_IDX][0], CHAMP_ICON)
        icon_x = col4_x + 5
        icon_y = champ_y - CHAMP_ICON // 2
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
    else:
        # 未到决赛
        if sf_done:
            for yy in fin_ys:
                line_sx = col3_x + SMALL_ICON + 60
                line_sx = min(line_sx, junc_x - 5)
                draw.line([(line_sx, yy), (junc_x, yy)],
                          fill=COLORS["pending"], width=1)
        else:
            for yy in fin_ys:
                draw.line([(col3_x + 30, yy), (junc_x, yy)],
                          fill=COLORS["pending"], width=1)
        draw.line([(junc_x, fin_ys[0]), (junc_x, champ_y)],
                  fill=COLORS["pending"], width=1)
        draw.line([(junc_x, fin_ys[1]), (junc_x, champ_y)],
                  fill=COLORS["pending"], width=1)
        draw.line([(junc_x, champ_y), (col4_x, champ_y)],
                  fill=COLORS["pending"], width=1)
        draw.text((col4_x + 12, champ_y - 10), "?",
                  fill=COLORS["pending_text"], font=font_title)

    # ── 图例 ──
    ly = CANVAS_H - 35
    draw.line([(35, ly), (65, ly)], fill=COLORS["winner"], width=2)
    draw.text((72, ly - 7), "晋级", fill=COLORS["text_dim"], font=font_legend)
    draw.line([(130, ly), (160, ly)], fill=COLORS["eliminated"], width=2)
    draw_cross(draw, 137, ly - 7, 14)
    draw.text((168, ly - 7), "淘汰", fill=COLORS["text_dim"], font=font_legend)
    draw.line([(226, ly), (256, ly)], fill=COLORS["pending"], width=1)
    draw.text((264, ly - 7), "待定", fill=COLORS["text_dim"], font=font_legend)
    if is_final:
        draw.line([(320, ly), (350, ly)], fill=COLORS["gold"], width=3)
        draw.text((358, ly - 7), "冠军路径", fill=COLORS["text_dim"], font=font_legend)

    # ── 右下角操作提示 ──
    if subtitle:
        hint_bbox = draw.textbbox((0, 0), subtitle, font=font_hint)
        hint_w = hint_bbox[2] - hint_bbox[0]
        hint_x = CANVAS_W - hint_w - 30
        hint_y = CANVAS_H - 38
        draw.text((hint_x, hint_y), subtitle, fill=(200, 195, 160), font=font_hint)

    out = out_path or "scripts/test_bracket_stages.png"
    img.save(out)
    print(f"Done: {out}")
    return out


def draw_ranking():
    """最终排名图。"""
    W, H = 400, 540
    img = Image.new("RGBA", (W, H), COLORS["bg"])
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, 16)
    font_title = ImageFont.truetype(FONT_PATH, 20)
    font_rank = ImageFont.truetype(FONT_PATH, 14)
    font_sm = ImageFont.truetype(FONT_PATH, 12)

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

        if rank < 3:
            draw.rounded_rectangle(
                [20, ry - 2, W - 20, ry + row_h - 6],
                radius=6, fill=row_colors[rank]
            )

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

        ix = 68
        img.paste(icon, (ix, ry + 5), icon)

        if rank == 0:
            nc = COLORS["gold"]
        elif rank < 3:
            nc = COLORS["text"]
        else:
            nc = (180, 180, 185)
        draw.text((ix + icon_size + 10, ry + 13), name, fill=nc, font=font)

    draw.line([(30, H - 32), (W - 30, H - 32)], fill=(60, 60, 65), width=1)
    draw.text((W // 2 - 55, H - 26), "Tournament Complete",
              fill=COLORS["text_dim"], font=font_sm)

    out = "scripts/test_ranking_stages.png"
    img.save(out)
    print(f"Done: {out}")
    return out


if __name__ == "__main__":
    # 阶段 1: 赛前抽签
    draw_bracket(
        stage="pre",
        title_suffix="抽签",
        subtitle="八强对阵已确定 · 发送「开战」开始八强战",
        out_path="scripts/stage1_pre.png",
    )

    # 阶段 2: 八强战结束
    draw_bracket(
        stage="qf_done",
        title_suffix="八强战",
        subtitle="八强战结束 · 发送「开战」进入半决赛",
        out_path="scripts/stage2_qf.png",
    )

    # 阶段 3: 半决赛结束
    draw_bracket(
        stage="sf_done",
        title_suffix="半决赛",
        subtitle="半决赛结束 · 发送「开战」进入决赛",
        out_path="scripts/stage3_sf.png",
    )

    # 阶段 4: 决赛结束（完整）
    draw_bracket(
        stage="final",
        title_suffix="决赛",
        out_path="scripts/stage4_final.png",
    )

    # 最终排名
    draw_ranking()
