"""配兵编制：预定义阵容、自选权重、兵种改价计入人数。"""

from __future__ import annotations

import random
from types import SimpleNamespace

from src.plugins.aoe3.repository import UnitRepo
from src.plugins.games.aoe3_battle.civ_war_civs import resolve_civ
from src.plugins.games.aoe3_battle.civ_war_lineups import (
    allocate_candidate_with_techs,
    generate_civ_candidates,
)
from src.plugins.games.aoe3_battle.lineup_draft import (
    army_is_ai,
    compile_ai_army,
    compile_custom,
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
    assert "VeteranMusketeers" not in ids
    assert "VeteranHussars" not in ids


def test_age_upgrade_line_is_not_a_choice():
    repo = UnitRepo.get()
    dutch = {unit.id: unit for unit in draft_units(repo, "Dutch", 5)}
    techs = list_selectable_techs(
        "Dutch",
        (dutch["grenadier"], dutch["falconet"], dutch["ruyter"]),
        3,
    )
    ids = {tech.id for tech in techs}
    names = {tech.name_zh for tech in techs}
    assert {
        "VeteranGrenadiers",
        "GuardGrenadiers",
        "FieldGun",
        "ImperialFieldGun",
        "RGCarabineer",
    }.isdisjoint(ids)
    assert {
        "老练掷弹兵",
        "护卫掷弹兵",
        "野战炮",
        "帝国野战炮",
        "护卫荷兰枪骑兵",
    }.isdisjoint(names)


def test_unit_price_change_changes_headcount_and_research_cost_does_not():
    repo = UnitRepo.get()
    civ = resolve_civ("中国")
    assert civ is not None
    by_id = {unit.id: unit for unit in draft_units(repo, civ.id, 3)}
    ordered = (by_id["ypchukonu"], by_id["ypqiangpikeman"])
    bare = compile_custom(
        repo,
        civ=civ,
        unit_ids=tuple(unit.id for unit in ordered),
        weights=(1, 1),
        tech_ids=(),
        age=3,
        budget=10000,
        label="自选",
    )
    priced = compile_custom(
        repo,
        civ=civ,
        unit_ids=tuple(unit.id for unit in ordered),
        weights=(1, 1),
        tech_ids=("YPHCOldHanArmyReforms",),
        age=3,
        budget=10000,
        label="自选",
    )
    bare_counts = [count for _unit_id, _name, count in bare.slots]
    priced_counts = [count for _unit_id, _name, count in priced.slots]
    assert sum(priced_counts) < sum(bare_counts)
    reforms = next(
        tech
        for tech in list_selectable_techs(civ.id, ordered, 3)
        if tech.id == "YPHCOldHanArmyReforms"
    )
    cost_ops = [op for op in reforms.runtime_tech()["ops"] if op.get("stat") == "cost"]
    assert cost_ops
    assert {op.get("kind") for op in cost_ops} == {"mult"}


def test_predefined_tactic_matches_civ_war_allocation():
    repo = UnitRepo.get()
    civ = resolve_civ("中国")
    assert civ is not None
    tactic = next(item for item in tactics_for(
        civ.id, 3, {unit.id: unit for unit in draft_units(repo, civ.id, 3)},
    ) if item.id == "old_han_army")
    army = compile_tactic(repo, civ=civ, tactic=tactic, age=3, budget=10000, label="中国")
    candidate = next(
        item
        for item in generate_civ_candidates(repo, "Chinese", age=3)
        if item.id == "national:old_han_army"
    )
    lineup, techs = allocate_candidate_with_techs(candidate, budget=10000, age=3)
    assert army.tech_ids == tuple(tech.id for tech in techs)
    assert [count for _unit_id, _name, count in army.slots] == [
        slot.count for slot in lineup.slots
    ]
    assert army.slots[0][2] == 51

    dutch = resolve_civ("荷兰")
    assert dutch is not None
    lowlands = next(item for item in tactics_for(
        dutch.id, 3, {unit.id: unit for unit in draft_units(repo, dutch.id, 3)},
    ) if item.id == "ruyter_skirm")
    assert not lowlands.required_tech_ids
    dutch_army = compile_tactic(
        repo, civ=dutch, tactic=lowlands, age=3, budget=10000, label="荷兰",
    )
    dutch_candidate = next(
        item
        for item in generate_civ_candidates(repo, "Dutch", age=3)
        if item.id == "national:ruyter_skirm"
    )
    dutch_lineup, dutch_techs = allocate_candidate_with_techs(
        dutch_candidate, budget=10000, age=3,
    )
    assert dutch_techs
    assert dutch_army.tech_ids == tuple(tech.id for tech in dutch_techs)
    assert [count for _unit_id, _name, count in dutch_army.slots] == [
        slot.count for slot in dutch_lineup.slots
    ]


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


def test_ai_filler_matches_civ_war_allocation(monkeypatch):
    from src.plugins.games.aoe3_battle import lineup_draft
    from src.plugins.games.aoe3_battle.civ_war_lineups import (
        allocate_candidate_with_techs,
        generate_civ_candidates,
    )

    repo = UnitRepo.get()
    candidate = next(
        item
        for item in generate_civ_candidates(repo, "Dutch", age=4)
        if item.title == "低地机动军"
    )
    assert not candidate.required_tech_ids

    def choice(seq):
        for item in seq:
            if getattr(item, "id", None) == "Dutch":
                return item
        return list(seq)[0]

    monkeypatch.setattr(
        lineup_draft,
        "generate_civ_candidates",
        lambda _repo, _civ_id, age: [candidate],
    )
    monkeypatch.setattr(
        lineup_draft,
        "choose_candidate",
        lambda candidates, rng: candidates[0],
    )
    army = compile_ai_army(
        repo,
        age=4,
        budget=10000,
        rng=type("Rng", (), {"choice": staticmethod(choice)})(),
    )
    lineup, techs = allocate_candidate_with_techs(
        candidate, budget=10000, age=4,
    )
    assert techs
    assert army.tech_ids == tuple(tech.id for tech in techs)
    assert [
        (unit_id, count) for unit_id, _name, count in army.slots
    ] == [(slot.unit.id, slot.count) for slot in lineup.slots]


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
    assert wizard.army.tech_summaries
    assert any(summary.split("：", 1)[0] in text for summary in wizard.army.tech_summaries)


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
                "tech_summaries": ["细细的红线：生命+20%，移速-10%"],
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
    assert "细细的红线：生命+20%，移速-10%" in text
    assert "2. AI·法国·1（火力）" in text
    assert "散兵×20" in text
    assert text.endswith("发送「开战」开始八强战")
    sections = text.split("\n\n")
    assert len(sections) == 5
    assert sections[1] == "参赛军队："
    assert sections[2].startswith("  1. JimyTD·荷兰")
    assert sections[3] == "  2. AI·法国·1（火力）\n     散兵×20"


def test_tournament_roster_spaces_all_eight_armies_with_optional_details():
    units = [
        SimpleNamespace(idx=i, unit_id=f"army-{i}", display_name=f"Army {i}")
        for i in range(8)
    ]
    text = format_lineup_tournament_roster(
        units,
        {
            "army-0": {"tech_names": ["Tech A", "Tech B"]},
            "army-1": {"tech_summaries": ["", "Tech C"], "slots": []},
        },
    )
    sections = text.split("\n\n")
    assert len(sections) == 11
    for i, section in enumerate(sections[2:-1]):
        assert section.startswith(f"  {i + 1}. Army {i}")
    assert "科技：Tech A\n     科技：Tech B" in sections[2]
    assert "科技：Tech C" in sections[3]
    assert "\n\n\n" not in text
    assert not text.endswith("\n")


def test_ready_text_separates_army_techs_and_action():
    from src.plugins.games.aoe3_battle.lineup_draft import CompiledArmy
    from src.plugins.games.aoe3_battle.lineup_wizard import _ready_text

    for summaries in ((), ("Tech A", "Tech B")):
        army = CompiledArmy(
            label="P1", civ_id="Japanese", civ_name="日本", strategy="自选",
            tech_ids=(), tech_names=(), slots=(("unit", "Unit", 12),),
            tech_summaries=summaries,
        )
        sections = _ready_text(army).split("\n\n")
        assert sections == [
            "已备好 日本 · 自选",
            "Unit×12",
            "科技：\n" + ("· Tech A\n· Tech B" if summaries else "无"),
            "想重配回复「重来」。",
        ]


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
