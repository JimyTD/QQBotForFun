"""深海任务：牌面与出牌规则工具。"""

from __future__ import annotations

import random
import re


COLORS: dict[str, str] = {
    "pink": "粉",
    "yellow": "黄",
    "blue": "蓝",
    "green": "绿",
}
COLOR_ALIASES: dict[str, str] = {
    "粉": "pink",
    "粉色": "pink",
    "pink": "pink",
    "p": "pink",
    "红": "pink",
    "黄": "yellow",
    "黄色": "yellow",
    "yellow": "yellow",
    "y": "yellow",
    "蓝": "blue",
    "蓝色": "blue",
    "blue": "blue",
    "b": "blue",
    "绿": "green",
    "绿色": "green",
    "green": "green",
    "g": "green",
}
SUBMARINE_ALIASES = {"潜艇", "艇", "sub", "s", "黑"}

CARD_RE = re.compile(r"^\s*([^\d\s]+)\s*([1-9])\s*$", re.IGNORECASE)


def build_deck(rng: random.Random | None = None) -> list[str]:
    """构造并洗混 40 张大牌。"""
    deck = [f"{color}:{value}" for color in COLORS for value in range(1, 10)]
    deck.extend(f"sub:{value}" for value in range(1, 5))
    rand = rng or random
    rand.shuffle(deck)
    return deck


def sort_cards(cards: list[str]) -> list[str]:
    color_order = {"pink": 0, "yellow": 1, "blue": 2, "green": 3, "sub": 4}
    return sorted(cards, key=lambda c: (color_order[suit_of(c)], value_of(c)))


def deal(deck: list[str], player_ids: list[int]) -> dict[str, list[str]]:
    """按玩家顺序轮流发牌。3 人时自然会有一人多一张。"""
    hands = {str(pid): [] for pid in player_ids}
    for i, card in enumerate(deck):
        pid = player_ids[i % len(player_ids)]
        hands[str(pid)].append(card)
    return {pid: sort_cards(cards) for pid, cards in hands.items()}


def parse_card(text: str) -> str | None:
    """解析中文/英文简写牌面，例如 蓝4、b4、潜艇2。"""
    match = CARD_RE.match(text.strip())
    if not match:
        return None
    raw_suit, raw_value = match.groups()
    suit_key = raw_suit.strip().lower()
    value = int(raw_value)
    if suit_key in SUBMARINE_ALIASES:
        if 1 <= value <= 4:
            return f"sub:{value}"
        return None
    color = COLOR_ALIASES.get(suit_key)
    if color is None:
        return None
    return f"{color}:{value}"


def suit_of(card: str) -> str:
    return card.split(":", 1)[0]


def value_of(card: str) -> int:
    return int(card.split(":", 1)[1])


def display_card(card: str) -> str:
    suit = suit_of(card)
    value = value_of(card)
    if suit == "sub":
        return f"潜艇{value}"
    return f"{COLORS[suit]}{value}"


def display_cards(cards: list[str]) -> str:
    return " ".join(display_card(c) for c in sort_cards(cards))


def legal_play(hand: list[str], card: str, lead_suit: str | None) -> tuple[bool, str]:
    if card not in hand:
        return False, "你没有这张牌"
    if lead_suit is None:
        return True, ""
    if suit_of(card) == lead_suit:
        return True, ""
    if any(suit_of(c) == lead_suit for c in hand):
        return False, f"本墩首牌是{display_suit(lead_suit)}，你必须跟花色"
    return True, ""


def trick_winner(plays: list[dict[str, int | str]]) -> int:
    """计算一墩赢家。plays 保持出牌顺序，元素含 player/card。"""
    if not plays:
        raise ValueError("plays cannot be empty")
    lead_suit = suit_of(str(plays[0]["card"]))
    candidates = [p for p in plays if suit_of(str(p["card"])) == "sub"]
    if not candidates:
        candidates = [p for p in plays if suit_of(str(p["card"])) == lead_suit]
    winner = max(candidates, key=lambda p: value_of(str(p["card"])))
    return int(winner["player"])


def display_suit(suit: str) -> str:
    if suit == "sub":
        return "潜艇"
    return COLORS[suit]


def sonar_condition(hand: list[str], card: str, marker: str) -> bool:
    """校验声呐声明：highest / lowest / only。"""
    suit = suit_of(card)
    if suit == "sub" or card not in hand:
        return False
    same_suit = [c for c in hand if suit_of(c) == suit]
    value = value_of(card)
    if marker == "only":
        return len(same_suit) == 1
    if marker == "highest":
        return value == max(value_of(c) for c in same_suit)
    if marker == "lowest":
        return value == min(value_of(c) for c in same_suit)
    return False
