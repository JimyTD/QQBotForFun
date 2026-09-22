"""Civ-war opening PNG rendering tests."""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO

from PIL import Image, ImageChops

from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.civ_war_civs import CIV_PROFILES, get_civ_profile
from plugins.games.aoe3_battle.civ_war_lineups import generate_civ_candidates
from plugins.games.aoe3_battle.civ_war_matchup import estimate_matchup
from plugins.games.aoe3_battle.opening_renderer import (
    OpeningSide,
    _load_flag,
    format_civ_war_fallback,
    render_civ_war_opening,
)


def _side(civ_id: str, strategy_id: str) -> OpeningSide:
    repo = UnitRepo.get()
    candidate = next(
        candidate
        for candidate in generate_civ_candidates(repo, civ_id, age=3)
        if candidate.source == "national" and candidate.strategy_id == strategy_id
    )
    lineup = estimate_matchup(
        candidate,
        candidate,
        age=3,
    ).red_lineup
    profile = get_civ_profile(civ_id)
    return OpeningSide(
        civ_name=profile.name,
        civ_id=civ_id,
        strategy=candidate.title,
        units=tuple((slot.unit, slot.count) for slot in lineup.slots),
    )


def test_civ_war_opening_renders_one_vs_three_unit_composition() -> None:
    red = _side("French", "cuirassier_mass")
    blue = _side("DEDanish", "danish_musk_huss_falc")
    png = render_civ_war_opening(
        red=red,
        blue=blue,
        age=3,
    )
    with Image.open(BytesIO(png)) as image:
        assert image.format == "PNG"
        assert image.width == 940
        assert image.height > 500

    fallback = format_civ_war_fallback(red, blue, age=3)
    assert "法国" in fallback
    assert "丹麦" in fallback
    assert "老练胸甲骑兵" in fallback
    assert "鹰炮" in fallback


def test_civ_war_opening_draws_civ_flag_and_tolerates_missing() -> None:
    """已提取旗帜的文明画出旗帜；没有旗帜的文明留空，且不影响渲染。"""
    red = _side("French", "cuirassier_mass")
    blank = replace(red, civ_id="__NoSuchCiv__")
    assert _load_flag(red.civ_id) is not None
    assert _load_flag(blank.civ_id) is None

    with_flag = render_civ_war_opening(red=red, blue=blank, age=3)
    without_flag = render_civ_war_opening(red=blank, blue=blank, age=3)
    assert with_flag != without_flag, "有旗帜的版本应与无旗帜版本不同"

    with (
        Image.open(BytesIO(with_flag)) as a,
        Image.open(BytesIO(without_flag)) as b,
    ):
        diff_bbox = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox()
    assert diff_bbox is not None, "旗帜必须真的被画进图里"
    # 旗帜固定画在 1 号（红方）头部右侧：差异区域应落在左半图
    assert diff_bbox[0] < 940 // 2


def test_every_playable_civ_has_a_flag_file() -> None:
    """可玩文明必须都有国旗文件：缺失时开屏会静默留空，需在此拦住。"""
    missing = [profile.id for profile in CIV_PROFILES if _load_flag(profile.id) is None]
    assert missing == [], f"缺少国旗文件: {missing}"
