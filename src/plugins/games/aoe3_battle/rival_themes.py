"""王中王（rival）—— 主题定义与兵种池筛选。

设计文档：docs/games/aoe3-battle.md §2.5
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from src.plugins.aoe3.models import Unit


@dataclass(frozen=True)
class PickSlotEmoji:
    """NapCat set_msg_emoji_like 槽位（QQ 官方 emoji_id + 选单对照符号）。"""

    id: str
    hint: str


# 顺序 = 消息下方表情栏从左到右（QQ EmojiType=2，U+2460/U+2461/U+2462）
PICK_SLOT_EMOJIS: tuple[PickSlotEmoji, PickSlotEmoji, PickSlotEmoji] = (
    PickSlotEmoji("9312", "1️⃣"),
    PickSlotEmoji("9313", "2️⃣"),
    PickSlotEmoji("9314", "3️⃣"),
)
PICK_SLOT_EMOJI_IDS: tuple[str, str, str] = tuple(s.id for s in PICK_SLOT_EMOJIS)


@dataclass(frozen=True)
class RivalTheme:
    """单个王中王主题。"""

    id: str
    title: str
    aliases: tuple[str, ...]
    include_all: frozenset[str] = frozenset()
    include_any: frozenset[str] = frozenset()
    exclude_any: frozenset[str] = frozenset()

    def matches(self, unit: Unit) -> bool:
        tags = set(unit.type)
        if self.include_all and not self.include_all <= tags:
            return False
        if self.include_any and not (tags & self.include_any):
            return False
        if self.exclude_any and (tags & self.exclude_any):
            return False
        return True


RIVAL_THEMES: tuple[RivalTheme, ...] = (
    RivalTheme(
        "skirmisher",
        "散兵王",
        ("散兵", "散兵王", "skirmisher"),
        include_all=frozenset({"AbstractSkirmisher"}),
    ),
    RivalTheme(
        "musketeer",
        "火枪王",
        ("火枪", "火枪王", "火枪兵", "musketeer"),
        include_all=frozenset({"AbstractMusketeer"}),
    ),
    RivalTheme(
        "melee_heavy",
        "近战重步王",
        ("近战重步", "近战重步王", "重步", "melee_heavy"),
        include_all=frozenset({"AbstractHandInfantry", "AbstractHeavyInfantry"}),
    ),
    RivalTheme(
        "archer",
        "弓手王",
        ("弓手", "弓手王", "弓", "archer"),
        include_any=frozenset({"AbstractFootArcher", "AbstractArcher"}),
        exclude_any=frozenset({"AbstractRangedCavalry"}),
    ),
    RivalTheme(
        "grenadier",
        "掷弹王",
        ("掷弹", "掷弹王", "掷弹兵", "grenadier"),
        include_all=frozenset({"AbstractGrenadier"}),
    ),
    RivalTheme(
        "hand_cavalry",
        "近战骑王",
        ("近战骑", "近战骑王", "hand_cavalry"),
        include_all=frozenset({"AbstractHandCavalry"}),
    ),
    RivalTheme(
        "ranged_cavalry",
        "远程骑王",
        ("远程骑", "远程骑王", "ranged_cavalry"),
        include_all=frozenset({"AbstractRangedCavalry"}),
    ),
    RivalTheme(
        "artillery",
        "炮王",
        ("炮", "炮王", "炮兵", "artillery"),
        include_all=frozenset({"AbstractArtillery"}),
    ),
    RivalTheme(
        "outlaw",
        "亡命徒王",
        ("亡命徒", "亡命徒王", "outlaw"),
        include_all=frozenset({"AbstractOutlaw"}),
    ),
    RivalTheme(
        "mercenary",
        "佣兵王",
        ("佣兵", "佣兵王", "mercenary"),
        include_all=frozenset({"Mercenary"}),
    ),
)

_THEMES_BY_ID: dict[str, RivalTheme] = {t.id: t for t in RIVAL_THEMES}
_ALIAS_MAP: dict[str, RivalTheme] = {}
for _t in RIVAL_THEMES:
    _ALIAS_MAP[_t.id.lower()] = _t
    _ALIAS_MAP[_t.title.lower()] = _t
    for _a in _t.aliases:
        _ALIAS_MAP[_a.lower()] = _t


def resolve_theme(token: str) -> RivalTheme | None:
    """解析主题 id / 展示名 / 别名。"""
    return _ALIAS_MAP.get(token.strip().lower())


def get_theme_by_id(theme_id: str) -> RivalTheme | None:
    return _THEMES_BY_ID.get(theme_id)


def filter_theme_pool(pool: list[Unit], theme: RivalTheme) -> list[Unit]:
    """从基础池筛出某主题的兵种列表。"""
    return [u for u in pool if theme.matches(u)]


def pick_random_themes(*, count: int = 3, rng: random.Random | None = None) -> list[RivalTheme]:
    """随机抽取不重复的主题（用于表情选单）。"""
    if rng is None:
        rng = random.Random()
    n = min(count, len(RIVAL_THEMES))
    return rng.sample(list(RIVAL_THEMES), n)


def format_pick_message(options: list[RivalTheme]) -> str:
    """生成选主题消息正文。"""
    lines = [
        "⚔️ 王中王 · 点消息下方 1️⃣ 2️⃣ 3️⃣ 选主题（从左到右）",
        "",
    ]
    for i, theme in enumerate(options):
        slot = PICK_SLOT_EMOJIS[i]
        lines.append(f"{slot.hint}  {i + 1}. {theme.title}")
    lines.extend([
        "",
        "回复 1 / 2 / 3 亦可（无需 @）",
    ])
    return "\n".join(lines)
