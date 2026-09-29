"""配兵编制：预定义阵容、自选权重、科技只改战斗。"""

from __future__ import annotations

import random
from types import SimpleNamespace

from src.plugins.aoe3.repository import UnitRepo
from src.plugins.games.aoe3_battle.civ_war_civs import resolve_civ
from src.plugins.games.aoe3_battle.lineup_draft import (
    army_is_ai,
    combat_runtime,
    compile_ai_army,
    compile_tactic,
    draft_units,
    format_lineup_tournament_roster,
    list_selectable_techs,
    materialize_army,
    tactics_for,
    targets_fielded_unit,
    tournament_match_needs_replay,
)
from src.plugins.games.aoe3_battle.lineup_wizard import Wizard, WizardStep, advance


def test_selectable_techs_follow_the_units_that_receive_them():
    repo = UnitRepo.get()
    units = {unit.id: unit for unit in draft_units(repo, "British", 3)}
    chosen = (units["musketeer"], units["hussar"])
    techs = list_selectable_techs("British", chosen, 3)
    ids = [tech.id for tech in techs]
    assert "HCImprovedLongbows" not in ids
    assert "ChurchThinRedLine" in ids
    specific_flags = [targets_fielded_unit(tech, chosen) for tech in techs]
    assert specific_flags == sorted(specific_flags, reverse=True)
    assert any(specific_flags)
    assert not all(specific_flags)


def test_selectable_techs_only_change_combat():
    repo = UnitRepo.get()
    units = tuple(draft_units(repo, "British", 5)[:3])
    techs = list_selectable_techs("British", units, 5)
    assert techs
    for tech in techs:
        assert tech.combat_ops
        assert all(op.get("stat") != "cost" for op in combat_runtime(tech)["ops"])


def test_predefined_tactic_allocates_and_materializes():
    repo = UnitRepo.get()
    civ = resolve_civ("英国")
    assert civ is not None
    units = {unit.id: unit for unit in draft_units(repo, civ.id, 3)}
    tactics = tactics_for(civ.id, 3, units)
    assert tactics
    army = compile_tactic(
        repo,
        civ=civ,
        tactic=tactics[0],
        age=3,
        budget=10000,
        label="阿伟·英国",
    )
    assert all(count >= 1 for _unit_id, _name, count in army.slots)
    lineup = materialize_army(repo, army.to_dict(), 3)
    assert [slot.count for slot in lineup.slots] == [
        count for _unit_id, _name, count in army.slots
    ]


def test_ai_army_is_labeled_and_allocated():
    army = compile_ai_army(
        UnitRepo.get(),
        age=3,
        budget=10000,
        rng=random.Random(1),
    )
    assert army.label.startswith("AI·")
    assert army.slots


def test_wizard_predefined_finishes_without_tech_step():
    repo = UnitRepo.get()
    wizard = Wizard()
    wizard, _text = advance(
        wizard, "英国", repo=repo, age=3, budget=10000, nickname="阿伟",
    )
    assert wizard.step == WizardStep.ROUTE
    wizard, text = advance(
        wizard, "1", repo=repo, age=3, budget=10000, nickname="阿伟",
    )
    assert wizard.step == WizardStep.DONE
    assert wizard.army is not None
    assert "已备好" in text


def test_wizard_custom_rejects_duplicate_units():
    repo = UnitRepo.get()
    wizard = Wizard()
    wizard, _text = advance(
        wizard, "英国", repo=repo, age=3, budget=10000, nickname="阿伟",
    )
    wizard, _text = advance(
        wizard, "0", repo=repo, age=3, budget=10000, nickname="阿伟",
    )
    assert wizard.step == WizardStep.UNITS
    wizard, text = advance(
        wizard, "1 1", repo=repo, age=3, budget=10000, nickname="阿伟",
    )
    assert "不能" in text
    assert wizard.step == WizardStep.UNITS


def test_wizard_custom_picks_weights_and_one_tech():
    repo = UnitRepo.get()
    wizard = Wizard()
    wizard, _text = advance(
        wizard, "英国", repo=repo, age=4, budget=10000, nickname="阿伟",
    )
    if wizard.step == WizardStep.ROUTE:
        wizard, _text = advance(
            wizard, "0", repo=repo, age=4, budget=10000, nickname="阿伟",
        )
    assert wizard.step == WizardStep.UNITS
    wizard, text = advance(
        wizard, "1 2", repo=repo, age=4, budget=10000, nickname="阿伟",
    )
    if wizard.step == WizardStep.WEIGHTS:
        wizard, text = advance(
            wizard, "8 12", repo=repo, age=4, budget=10000, nickname="阿伟",
        )
    if wizard.step == WizardStep.TECHS:
        wizard, text = advance(
            wizard, "1", repo=repo, age=4, budget=10000, nickname="阿伟",
        )
    assert wizard.army is not None, text
    assert 1 <= len(wizard.army.tech_ids) <= 2
    assert all(count >= 1 for _unit_id, _name, count in wizard.army.slots)


def test_tournament_roster_lists_soldiers_and_techs():
    units = [
        SimpleNamespace(idx=0, unit_id="lineup-0", display_name="JimyTD·荷兰"),
        SimpleNamespace(idx=1, unit_id="lineup-1", display_name="AI·法国·1"),
    ]
    text = format_lineup_tournament_roster(
        units,
        {
            "lineup-0": {
                "strategy": "自选",
                "tech_names": ["细细的红线"],
                "slots": [
                    {"unit_name": "火枪兵", "count": 18},
                    {"unit_name": "长枪兵", "count": 12},
                ],
            },
            "lineup-1": {
                "strategy": "火力",
                "tech_names": [],
                "slots": [{"unit_name": "散兵", "count": 20}],
            },
        },
    )
    assert "1. JimyTD·荷兰（自选）" in text
    assert "火枪兵×18、长枪兵×12" in text
    assert "科技：细细的红线" in text
    assert "2. AI·法国·1（火力）" in text
    assert "散兵×20" in text
    assert text.endswith("发送「开战」开始八强战")


def test_lineup_tournament_films_human_matches_and_the_final():
    assert tournament_match_needs_replay(
        "lineup_tournament", "QF1", red_ai=False, blue_ai=True,
    )
    assert tournament_match_needs_replay(
        "lineup_tournament", "SF2", red_ai=False, blue_ai=False,
    )
    assert not tournament_match_needs_replay(
        "lineup_tournament", "QF3", red_ai=True, blue_ai=True,
    )
    assert tournament_match_needs_replay(
        "lineup_tournament", "FINAL", red_ai=True, blue_ai=True,
    )
    assert not tournament_match_needs_replay(
        "rival_tournament", "QF1", red_ai=False, blue_ai=False,
    )
    assert tournament_match_needs_replay(
        "rival_tournament", "FINAL", red_ai=True, blue_ai=True,
    )
    assert army_is_ai({"ai": True, "label": "AI·法国"})
    assert not army_is_ai({"ai": False, "label": "JimyTD·荷兰"})
    assert army_is_ai({"label": "AI·印度"}, "AI·印度·1")
    assert not army_is_ai(None, "JimyTD·荷兰")
