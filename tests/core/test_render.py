"""render 模块测试（纯函数，不依赖 DB）。"""

from __future__ import annotations

from core import render


def test_text_card_basic() -> None:
    s = render.text_card("标题", ["第一行", "第二行"], emoji="🎮", footer="尾注")
    assert "🎮" in s
    assert "标题" in s
    assert "第一行" in s
    assert "尾注" in s
    assert render.SEP_HEAVY in s
    assert render.SEP_LIGHT in s


def test_menu() -> None:
    items = [
        render.MenuItem(emoji="🐢", name="海龟汤", subtitle="1-10 人", command="/play turtle_soup"),
    ]
    s = render.menu("大厅", items)
    assert "🐢 海龟汤" in s
    assert "/play turtle_soup" in s


def test_status_line() -> None:
    s = render.status_line("@张三", "❓ 问题", "✅ 是")
    assert "@张三" in s
    assert "↳" in s
    assert "是" in s


def test_paginate() -> None:
    items = [str(i) for i in range(25)]
    page1, label = render.paginate(items, 1, per_page=10)
    assert len(page1) == 10
    assert label == "(1/3)"
    page3, label = render.paginate(items, 3, per_page=10)
    assert len(page3) == 5
    assert label == "(3/3)"


def test_truncate() -> None:
    assert render.truncate("abcdef", 10) == "abcdef"
    assert render.truncate("abcdef", 4) == "abc…"
