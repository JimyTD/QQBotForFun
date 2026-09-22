"""Civilization unit-list lookup used by ``aoe3 文明``."""

from __future__ import annotations

import pytest

from plugins.aoe3.repository import UnitRepo


@pytest.fixture(scope="module")
def repo() -> UnitRepo:
    return UnitRepo.get()


@pytest.mark.parametrize("query", ["日本", "日本人", "Japanese"])
def test_list_by_civ_accepts_common_names(repo: UnitRepo, query: str) -> None:
    units = repo.list_by_civ(query)
    unit_ids = {unit.id for unit in units}

    assert units
    assert {"ypashigaru", "ypyumi", "ypnaginatarider"} <= unit_ids


def test_list_by_civ_returns_combat_pool_units_only(repo: UnitRepo) -> None:
    units = repo.list_by_civ("日本")

    unit_ids = {unit.id for unit in units}
    assert unit_ids
    assert "ypashigaru" in unit_ids
    assert "ypsettlerjapanese" not in unit_ids
    assert "ypmonkjapanese" not in unit_ids
    assert "monitor" not in unit_ids
    assert "depetelephant" not in unit_ids
    assert "xpspy" not in unit_ids


def test_unknown_civ_returns_empty(repo: UnitRepo) -> None:
    assert repo.list_by_civ("不存在的文明") == []
