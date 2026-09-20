"""自选斗蛐蛐固定数量语法与阵容生成测试。"""
from __future__ import annotations

import importlib.util
import random
from pathlib import Path

import pytest

from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.lineup import (
    generate_custom_lineup,
    resolve_unit_name,
)

_ARGS_PATH = Path(__file__).resolve().parents[3] / "src" / "plugins" / "aoe3_battle_args.py"
_SPEC = importlib.util.spec_from_file_location("aoe3_battle_args_test", _ARGS_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_ARGS_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_ARGS_MODULE)
parse_custom_battle_args = _ARGS_MODULE.parse_custom_battle_args
extract_age = _ARGS_MODULE.extract_age


@pytest.fixture(scope="module")
def repo() -> UnitRepo:
    return UnitRepo.get()


def test_parse_fixed_counts():
    names, counts, budget, error = parse_custom_battle_args(
        ["胸甲骑兵", "100", "瑞士长枪兵", "50"]
    )
    assert error is None
    assert names == ["胸甲骑兵", "瑞士长枪兵"]
    assert counts == [100, 50]
    assert budget is None


def test_parse_fixed_counts_with_age_removed():
    age, parts = extract_age(["胸甲骑兵", "100", "瑞士长枪兵", "50", "5时代"])
    assert age == 5
    names, counts, budget, error = parse_custom_battle_args(parts)
    assert error is None
    assert names == ["胸甲骑兵", "瑞士长枪兵"]
    assert counts == [100, 50]
    assert budget is None


@pytest.mark.parametrize(
    ("parts", "expected_error"),
    [
        (["胸甲骑兵", "0", "瑞士长枪兵", "50"], "1~1000"),
        (["胸甲骑兵", "1001", "瑞士长枪兵", "50"], "1~1000"),
        (["胸甲骑兵", "100", "瑞士长枪兵"], "兵种A 数量 兵种B 数量"),
        (["100", "胸甲骑兵", "50", "瑞士长枪兵"], "兵种A 数量 兵种B 数量"),
        (["胸甲骑兵", "100", "胸甲骑兵", "50"], "两个不同兵种"),
    ],
)
def test_parse_fixed_counts_rejects_invalid_input(parts, expected_error):
    _, _, _, error = parse_custom_battle_args(parts)
    assert error is not None
    assert expected_error in error


def test_legacy_budget_formats_unchanged():
    names, counts, budget, error = parse_custom_battle_args(
        ["火枪手", "散兵", "15000"]
    )
    assert error is None
    assert names == ["火枪手", "散兵"]
    assert counts is None
    assert budget == 15000

    names, counts, budget, error = parse_custom_battle_args(["火枪手", "15000"])
    assert error is None
    assert names == ["火枪手"]
    assert counts is None
    assert budget == 15000


def test_generate_custom_lineup_fixed_counts(repo):
    match = generate_custom_lineup(
        repo,
        ["胸甲骑兵", "瑞士长枪兵"],
        budget=1000,
        unit_counts=[100, 50],
        age=3,
        rng=random.Random(1),
    )
    assert not isinstance(match, str)
    assert match.red.slots[0].unit.id == "cuirassier"
    assert match.red.slots[0].count == 100
    assert match.blue.slots[0].unit.id == "mercswisspikeman"
    assert match.blue.slots[0].count == 50


def test_generate_custom_lineup_legacy_lcm(repo):
    match = generate_custom_lineup(
        repo,
        ["胸甲骑兵", "瑞士长枪兵"],
        budget=1000,
        age=3,
        rng=random.Random(1),
    )
    assert not isinstance(match, str)
    assert (match.red.slots[0].count, match.blue.slots[0].count) == (3, 5)


def test_swiss_pikeman_fuzzy_alias_remains_resolvable(repo):
    unit = resolve_unit_name(repo, "瑞士长枪兵")
    assert unit is not None
    assert unit.id == "mercswisspikeman"
