"""Civ-war public argument and civilization-name resolution tests."""

from __future__ import annotations

import random

from plugins.aoe3_battle_args import parse_civ_war_args
from plugins.games.aoe3_battle.civ_war_civs import pick_random_civs, resolve_civ


def test_parse_random_civ_war() -> None:
    assert parse_civ_war_args([]) == (None, None, None)
    assert parse_civ_war_args(["15000"]) == (None, 15000, None)


def test_parse_explicit_civ_war() -> None:
    assert parse_civ_war_args(["英国", "日本", "15000"]) == (
        ["英国", "日本"],
        15000,
        None,
    )


def test_parse_one_or_same_civ_rejected() -> None:
    assert parse_civ_war_args(["英国"])[2] is not None
    assert parse_civ_war_args(["英国", "英国"])[2] is not None


def test_resolve_common_and_legacy_civ_names() -> None:
    assert resolve_civ("英国").id == "British"
    assert resolve_civ("英国人").id == "British"
    assert resolve_civ("易洛魁").id == "XPIroquois"
    assert resolve_civ("拉科塔").id == "XPSioux"
    assert resolve_civ("French").id == "French"
    assert resolve_civ("不存在") is None


def test_random_civs_are_distinct_and_reproducible() -> None:
    first = pick_random_civs(rng=random.Random(42))
    second = pick_random_civs(rng=random.Random(42))
    assert first == second
    assert first[0].id != first[1].id
