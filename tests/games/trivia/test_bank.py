"""题库加载 & 运行时抽题测试。"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

import pytest

from src.plugins.games.trivia import puzzle_generator as pg
from src.plugins.games.trivia.puzzle_generator import (
    BankEntry,
    BankNotAvailableError,
    TriviaPuzzle,
    get_puzzle_from_bank,
    load_bank,
)


def _make_bank_file(tmp_dir: Path, type_id: str, entries: list[dict]) -> Path:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    path = tmp_dir / f"{type_id}.json"
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _clear_cache():
    """每个测试前清空题库缓存，避免串扰。"""
    pg._bank_cache.clear()
    yield
    pg._bank_cache.clear()


@pytest.fixture
def tmp_bank_dir(tmp_path, monkeypatch):
    """把题库目录指向 tmp_path 下一个子目录。"""
    bank_dir = tmp_path / "trivia_bank"
    monkeypatch.setattr(pg, "_BANK_DIR", bank_dir)
    return bank_dir


def _good_entry(answer: str = "爱因斯坦", aliases: list[str] | None = None) -> dict:
    return {
        "answer": answer,
        "aliases": aliases if aliases is not None else ["Einstein", "阿尔伯特"],
        "clue_sets": [
            [
                "他提出了一个改变物理学的理论",
                "他在瑞士专利局工作过",
                "他的相对论让时空变得可变",
                "他因光电效应获得诺贝尔奖",
                "他那张吐舌头的照片广为流传",
            ],
            [
                "20 世纪最被仰慕的科学家之一",
                "他的理论让光速不可超越",
                "他曾在普林斯顿工作",
                "他的头发标志性地凌乱",
                "他和 E=mc² 紧紧绑定",
            ],
        ],
        "explanation": "20 世纪最伟大的物理学家之一。",
        "difficulty": "easy",
        "source": "test_fixture",
    }


class TestLoadBank:
    def test_missing_file_raises(self, tmp_bank_dir: Path) -> None:
        with pytest.raises(BankNotAvailableError) as exc:
            load_bank("country")
        assert "country" in str(exc.value)

    def test_invalid_json_raises(self, tmp_bank_dir: Path) -> None:
        tmp_bank_dir.mkdir(parents=True)
        (tmp_bank_dir / "country.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(BankNotAvailableError):
            load_bank("country")

    def test_empty_list_raises(self, tmp_bank_dir: Path) -> None:
        _make_bank_file(tmp_bank_dir, "country", [])
        with pytest.raises(BankNotAvailableError):
            load_bank("country")

    def test_good_bank_loads(self, tmp_bank_dir: Path) -> None:
        _make_bank_file(tmp_bank_dir, "country", [_good_entry(), _good_entry("牛顿")])
        entries = load_bank("country")
        assert len(entries) == 2
        assert entries[0].answer == "爱因斯坦"
        assert entries[0].aliases == ["Einstein", "阿尔伯特"]
        assert len(entries[0].clue_sets) == 2
        assert len(entries[0].clue_sets[0]) == 5

    def test_cache_hit(self, tmp_bank_dir: Path) -> None:
        path = _make_bank_file(tmp_bank_dir, "country", [_good_entry()])
        entries1 = load_bank("country")
        # 删掉文件，如果有缓存仍能返回
        path.unlink()
        entries2 = load_bank("country")
        assert entries1 is entries2

    def test_reload_bypasses_cache(self, tmp_bank_dir: Path) -> None:
        _make_bank_file(tmp_bank_dir, "country", [_good_entry()])
        load_bank("country")
        # 写入新题
        _make_bank_file(tmp_bank_dir, "country", [_good_entry(), _good_entry("达芬奇")])
        entries = load_bank("country", reload=True)
        assert len(entries) == 2

    def test_filters_invalid_entries(self, tmp_bank_dir: Path) -> None:
        _make_bank_file(
            tmp_bank_dir,
            "country",
            [
                _good_entry(),
                {"answer": "没有线索的题"},           # 缺 clue_sets
                "not a dict",                          # 完全乱来
                {"clue_sets": [["a"]]},                # 缺 answer
            ],
        )
        entries = load_bank("country")
        # 只有第一条是合法的
        assert len(entries) == 1
        assert entries[0].answer == "爱因斯坦"


class TestGetPuzzleFromBank:
    def test_returns_triviaPuzzle(self, tmp_bank_dir: Path) -> None:
        _make_bank_file(tmp_bank_dir, "country", [_good_entry()])
        puzzle = get_puzzle_from_bank("country")
        assert isinstance(puzzle, TriviaPuzzle)
        assert puzzle.type_id == "country"
        assert puzzle.answer == "爱因斯坦"
        assert len(puzzle.clues) == 5
        assert puzzle.explanation

    def test_clue_set_randomly_picked(self, tmp_bank_dir: Path) -> None:
        _make_bank_file(tmp_bank_dir, "country", [_good_entry()])
        # 多次抽，应该两套线索都出现过
        first_clues = []
        for _ in range(30):
            puzzle = get_puzzle_from_bank("country")
            first_clues.append(puzzle.clues[0])
        assert len(set(first_clues)) == 2

    def test_avoid_excludes_matching_answer(self, tmp_bank_dir: Path) -> None:
        _make_bank_file(
            tmp_bank_dir,
            "country",
            [
                _good_entry("爱因斯坦", aliases=["Einstein"]),
                _good_entry("牛顿", aliases=["Newton"]),
            ],
        )
        # 禁用爱因斯坦 → 多次抽只会得到牛顿
        for _ in range(20):
            puzzle = get_puzzle_from_bank("country", avoid=["爱因斯坦"])
            assert puzzle.answer == "牛顿"

    def test_avoid_excludes_matching_alias(self, tmp_bank_dir: Path) -> None:
        _make_bank_file(
            tmp_bank_dir,
            "country",
            [
                _good_entry("爱因斯坦", aliases=["Einstein"]),
                _good_entry("牛顿", aliases=["Newton"]),
            ],
        )
        # 禁用 "Einstein"（爱因斯坦的别名）→ 只会得到牛顿
        for _ in range(20):
            puzzle = get_puzzle_from_bank("country", avoid=["Einstein"])
            assert puzzle.answer == "牛顿"

    def test_exhausted_pool_falls_back_to_all(self, tmp_bank_dir: Path) -> None:
        """本局 avoid 把题库撸光时降级为整库可选（允许重复）。"""
        _make_bank_file(tmp_bank_dir, "country", [_good_entry()])
        puzzle = get_puzzle_from_bank("country", avoid=["爱因斯坦", "Einstein"])
        # 降级后仍能抽到（只有一道题）
        assert puzzle.answer == "爱因斯坦"

    def test_bank_missing_raises(self, tmp_bank_dir: Path) -> None:
        with pytest.raises(BankNotAvailableError):
            get_puzzle_from_bank("country")
