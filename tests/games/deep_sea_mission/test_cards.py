from __future__ import annotations

from src.plugins.games.deep_sea_mission.cards import (
    deal,
    display_card,
    legal_play,
    parse_card,
    trick_winner,
)


def test_parse_card_supports_chinese_and_short_aliases() -> None:
    assert parse_card("蓝4") == "blue:4"
    assert parse_card("b4") == "blue:4"
    assert parse_card("潜艇2") == "sub:2"
    assert parse_card("s2") == "sub:2"
    assert display_card("green:6") == "绿6"


def test_deal_three_players_leaves_one_extra_card() -> None:
    deck = [f"pink:{i}" for i in range(1, 10)] + [f"yellow:{i}" for i in range(1, 10)]
    deck += [f"blue:{i}" for i in range(1, 10)] + [f"green:{i}" for i in range(1, 10)]
    deck += [f"sub:{i}" for i in range(1, 5)]
    hands = deal(deck, [1, 2, 3])
    sizes = sorted(len(h) for h in hands.values())
    assert sizes == [13, 13, 14]


def test_follow_suit_is_required() -> None:
    ok, reason = legal_play(["blue:4", "sub:1"], "sub:1", "blue")
    assert ok is False
    assert "必须跟花色" in reason

    ok, reason = legal_play(["sub:1"], "sub:1", "blue")
    assert ok is True
    assert reason == ""


def test_submarine_trump_wins_trick() -> None:
    winner = trick_winner(
        [
            {"player": 1, "card": "blue:9"},
            {"player": 2, "card": "sub:1"},
            {"player": 3, "card": "yellow:9"},
        ]
    )
    assert winner == 2
