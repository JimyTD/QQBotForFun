"""Private-message steps for building one lineup. No bot I/O."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from core.render import join_sections
from src.plugins.aoe3.repository import UnitRepo
from src.plugins.games.aoe3_battle.civ_war_civs import (
    CIV_PROFILES,
    CivProfile,
    resolve_civ,
)
from src.plugins.games.aoe3_battle.lineup import _unit_cost
from src.plugins.games.aoe3_battle.lineup_draft import (
    CompiledArmy,
    compile_custom,
    compile_tactic,
    draft_units,
    list_selectable_techs,
    parse_weights,
    tactics_for,
    targets_fielded_unit,
)


class WizardStep(Enum):
    CIV = "civ"
    ROUTE = "route"
    UNITS = "units"
    WEIGHTS = "weights"
    TECHS = "techs"
    DONE = "done"


@dataclass
class Wizard:
    step: WizardStep = WizardStep.CIV
    civ_id: str = ""
    tactic_ids: tuple[str, ...] = ()
    unit_ids: tuple[str, ...] = ()
    picked_unit_ids: tuple[str, ...] = ()
    tech_ids: tuple[str, ...] = ()
    pending_weights: tuple[int, ...] = ()
    army: CompiledArmy | None = None
    _units_by_id: dict = field(default_factory=dict, repr=False)


def opening_prompt() -> str:
    return (
        "配兵 · 选国家\n"
        "回复国家名，或回复「随机」。\n"
        "想重来时回复「重来」。"
    )


def advance(
    wizard: Wizard,
    text: str,
    *,
    repo: UnitRepo,
    age: int,
    budget: int,
    nickname: str,
    rng: random.Random | None = None,
) -> tuple[Wizard, str]:
    """Consume one private reply. The returned wizard is the next state."""
    rng = rng or random.Random()
    message = text.strip()
    if message == "重来":
        fresh = Wizard()
        return fresh, opening_prompt()
    if wizard.step == WizardStep.DONE and wizard.army is not None:
        return wizard, _ready_text(wizard.army)
    if wizard.step == WizardStep.CIV:
        return _pick_civ(wizard, message, repo, age, rng)
    if wizard.step == WizardStep.ROUTE:
        return _pick_route(wizard, message, repo, age, budget, nickname)
    if wizard.step == WizardStep.UNITS:
        return _pick_units(wizard, message, repo, age, budget, nickname)
    if wizard.step == WizardStep.WEIGHTS:
        return _pick_weights(wizard, message, repo, age, budget, nickname)
    if wizard.step == WizardStep.TECHS:
        return _pick_techs(wizard, message, repo, age, budget, nickname)
    return wizard, opening_prompt()


def _pick_civ(wizard, message, repo, age, rng) -> tuple[Wizard, str]:
    if message == "随机":
        civ = rng.choice(list(CIV_PROFILES))
    else:
        civ = resolve_civ(message)
        if civ is None:
            return wizard, f"找不到可玩主文明「{message}」。回复国家名，或回复「随机」。"
    return _enter_route(wizard, civ, repo, age)


def _enter_route(wizard, civ: CivProfile, repo, age) -> tuple[Wizard, str]:
    units = draft_units(repo, civ.id, age)
    by_id = {unit.id: unit for unit in units}
    tactics = tactics_for(civ.id, age, by_id)
    wizard.step = WizardStep.ROUTE
    wizard.civ_id = civ.id
    wizard.tactic_ids = tuple(tactic.id for tactic in tactics)
    wizard._units_by_id = by_id
    lines = [f"{civ.name} · 选择军队", ""]
    if tactics:
        for index, tactic in enumerate(tactics, start=1):
            names = "、".join(by_id[unit_id].name for unit_id in tactic.unit_ids)
            lines.append(f"{index}. {tactic.title}（{names}）")
        lines.append("0. 自己配")
        lines.append("")
        lines.append("回复序号。")
    else:
        lines.append("这个国家没有可出的预定义阵容。")
        lines.append(_unit_menu(units))
        wizard.step = WizardStep.UNITS
        wizard.unit_ids = tuple(unit.id for unit in units)
    return wizard, "\n".join(lines)


def _pick_route(wizard, message, repo, age, budget, nickname) -> tuple[Wizard, str]:
    if message == "0":
        units = draft_units(repo, wizard.civ_id, age)
        wizard.step = WizardStep.UNITS
        wizard.unit_ids = tuple(unit.id for unit in units)
        wizard._units_by_id = {unit.id: unit for unit in units}
        return wizard, "自己配\n" + _unit_menu(units)
    if not message.isdigit():
        return wizard, "回复阵容序号，或回复 0 自己配。"
    index = int(message) - 1
    tactics = _current_tactics(wizard, repo, age)
    if not 0 <= index < len(tactics):
        return wizard, "没有这个序号。回复阵容序号，或回复 0 自己配。"
    civ = resolve_civ(wizard.civ_id)
    assert civ is not None
    try:
        army = compile_tactic(
            repo,
            civ=civ,
            tactic=tactics[index],
            age=age,
            budget=budget,
            label=f"{nickname}·{civ.name}",
        )
    except ValueError as exc:
        return wizard, f"{exc}。换一个阵容，或回复 0 自己配。"
    wizard.step = WizardStep.DONE
    wizard.army = army
    return wizard, _ready_text(army)


def _pick_units(wizard, message, repo, age, budget, nickname) -> tuple[Wizard, str]:
    parts = message.split()
    if not 1 <= len(parts) <= 3 or not all(part.isdigit() for part in parts):
        return wizard, "回复 1 到 3 个序号，按出场顺序，例如 2 5。"
    indexes = [int(part) - 1 for part in parts]
    if len(set(indexes)) != len(indexes):
        return wizard, "不能把同一个兵点两次。"
    if any(index < 0 or index >= len(wizard.unit_ids) for index in indexes):
        return wizard, "序号超出列表。"
    wizard.picked_unit_ids = tuple(wizard.unit_ids[index] for index in indexes)
    if len(wizard.picked_unit_ids) == 1:
        return _enter_techs(wizard, repo, age, budget, nickname, weights=(1,))
    wizard.step = WizardStep.WEIGHTS
    names = [wizard._units_by_id[unit_id].name for unit_id in wizard.picked_unit_ids]
    example = " ".join(str(8 + index * 2) for index in range(len(names)))
    return wizard, (
        "按顺序给这几个兵分配资源：\n"
        + "、".join(names)
        + f"\n回复 {len(names)} 个正整数，例如 {example}"
    )


def _pick_weights(wizard, message, repo, age, budget, nickname) -> tuple[Wizard, str]:
    parsed = parse_weights(message, len(wizard.picked_unit_ids))
    if isinstance(parsed, str):
        return wizard, parsed
    return _enter_techs(wizard, repo, age, budget, nickname, weights=parsed)


def _enter_techs(wizard, repo, age, budget, nickname, weights) -> tuple[Wizard, str]:
    units = tuple(wizard._units_by_id[unit_id] for unit_id in wizard.picked_unit_ids)
    techs = list_selectable_techs(wizard.civ_id, units, age)
    if not techs:
        wizard.step = WizardStep.ROUTE
        wizard.picked_unit_ids = ()
        return wizard, "这套兵没有可选科技。换兵，或回到上面选预定义阵容。回复 0 继续自己配，或回复阵容序号。"
    wizard.tech_ids = tuple(tech.id for tech in techs)
    wizard.step = WizardStep.TECHS
    wizard.pending_weights = tuple(weights)
    lines = ["选择 1 到 2 条科技：", ""]
    for index, tech in enumerate(techs, start=1):
        kind = "专属" if targets_fielded_unit(tech, units) else "通用"
        name = tech.name_zh or tech.id
        lines.append(f"{index}. {name}（{kind}）")
    lines.append("")
    lines.append("回复 1 个或 2 个序号。")
    return wizard, "\n".join(lines)


def _pick_techs(wizard, message, repo, age, budget, nickname) -> tuple[Wizard, str]:
    parts = message.split()
    if not 1 <= len(parts) <= 2 or not all(part.isdigit() for part in parts):
        return wizard, "回复 1 个或 2 个科技序号。"
    indexes = [int(part) - 1 for part in parts]
    if len(set(indexes)) != len(indexes):
        return wizard, "不能把同一条科技点两次。"
    if any(index < 0 or index >= len(wizard.tech_ids) for index in indexes):
        return wizard, "序号超出列表。"
    civ = resolve_civ(wizard.civ_id)
    assert civ is not None
    weights = wizard.pending_weights
    if not weights:
        return wizard, "权重丢了，回复「重来」。"
    try:
        army = compile_custom(
            repo,
            civ=civ,
            unit_ids=wizard.picked_unit_ids,
            weights=tuple(weights),
            tech_ids=tuple(wizard.tech_ids[index] for index in indexes),
            age=age,
            budget=budget,
            label=f"{nickname}·{civ.name}",
        )
    except ValueError as exc:
        return wizard, f"{exc}。可以换科技，或回复「重来」。"
    wizard.step = WizardStep.DONE
    wizard.army = army
    return wizard, _ready_text(army)


def _current_tactics(wizard, repo, age):
    units = draft_units(repo, wizard.civ_id, age)
    by_id = {unit.id: unit for unit in units}
    wizard._units_by_id = by_id
    return [tactic for tactic in tactics_for(wizard.civ_id, age, by_id) if tactic.id in wizard.tactic_ids]


def _unit_menu(units) -> str:
    lines = ["可选兵：", ""]
    for index, unit in enumerate(units, start=1):
        lines.append(f"{index}. {unit.name}  费用{_unit_cost(unit)}")
    lines.append("")
    lines.append("回复 1 到 3 个序号，按出场顺序。")
    return "\n".join(lines)


def _ready_text(army: CompiledArmy) -> str:
    slots = "、".join(f"{name}×{count}" for _unit_id, name, count in army.slots)
    tech_lines = "\n".join(f"· {summary}" for summary in army.tech_summaries)
    techs = tech_lines if tech_lines else "无"
    return join_sections(
        f"已备好 {army.civ_name} · {army.strategy}",
        slots,
        f"科技：\n{techs}",
        "想重配回复「重来」。",
    )
