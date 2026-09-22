"""Civ-war opening PNG rendering tests."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.civ_war_civs import get_civ_profile
from plugins.games.aoe3_battle.civ_war_lineups import generate_civ_candidates
from plugins.games.aoe3_battle.civ_war_matchup import estimate_matchup
from plugins.games.aoe3_battle.opening_renderer import (
    OpeningSide,
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
