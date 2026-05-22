"""中文展示名覆盖。"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.games.ra2_battle.display import (
    display_name,
    format_attack_summary,
    format_description_blurb,
)
from plugins.games.ra2_battle.locale import (
    localized_actor_name,
    locale_actor_ids,
)
from plugins.games.ra2_battle.repo import load_actors

_DATA = Path(__file__).resolve().parents[3] / "data" / "ra2" / "actors.json"
_LOCALE = Path(__file__).resolve().parents[3] / "data" / "ra2" / "locale_zh.json"


@pytest.fixture(scope="module")
def require_export():
    if not _DATA.is_file() or not _LOCALE.is_file():
        pytest.skip("缺少 data/ra2 或 locale_zh.json")


@pytest.fixture(scope="module")
def actors(require_export):
    return load_actors()


def test_all_exported_actors_have_chinese_name(actors):
    zh_ids = locale_actor_ids()
    for aid in actors:
        assert aid in zh_ids, f"{aid} 缺少 locale_zh 中文名"
        name = localized_actor_name(aid, actors[aid].name)
        assert name != actors[aid].name or " " in name or any(
            "\u4e00" <= c <= "\u9fff" for c in name
        ), f"{aid} 名称未中文化: {name}"


def test_ccomand_flakt_chinese(actors):
    assert display_name(actors["ccomand"]) == "超时空突击队"
    assert display_name(actors["flakt"]) == "防空步兵"
    desc = format_description_blurb(actors["ccomand"])
    assert "强对" in desc or "步兵" in desc
    assert "Elite commando" not in desc


def test_attack_summary_no_raw_weapon_id(actors):
    s = format_attack_summary(actors["flakt"])
    assert "FlakGuyGun" not in s
    assert "伤" in s
