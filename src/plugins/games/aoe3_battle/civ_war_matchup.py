"""Static matchup estimation and randomized selection for civ-war candidates."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from src.plugins.aoe3.models import Multiplier, Unit
from src.plugins.aoe3.repository import UnitRepo
from src.plugins.games.aoe3_battle.civ_war_civs import get_civ_profile
from src.plugins.games.aoe3_battle.civ_war_lineups import (
    CivWarCandidate,
    allocate_candidate,
    choose_candidate,
    generate_civ_candidates,
    shortlist_candidates,
)
from src.plugins.games.aoe3_battle.lineup import BUDGET, Lineup, MatchLineup

_IDENTITY_TIER_PENALTY = 0.04
_MIRROR_STRATEGY_PENALTY = 0.06


@dataclass(frozen=True)
class MatchupEstimate:
    """One concrete candidate pairing and its pre-battle static estimate."""

    red_candidate: CivWarCandidate
    blue_candidate: CivWarCandidate
    red_lineup: Lineup
    blue_lineup: Lineup
    red_pressure: float
    blue_pressure: float
    advantage_log: float
    balance_gap: float
    selection_score: float

    @property
    def is_strategy_mirror(self) -> bool:
        return (
            self.red_candidate.source == self.blue_candidate.source
            and self.red_candidate.strategy_id == self.blue_candidate.strategy_id
        )


def _multiplier_product(multipliers: list[Multiplier], target: Unit) -> float:
    target_tags = {tag.lower() for tag in target.type}
    result = 1.0
    for multiplier in multipliers:
        if multiplier.vs.rstrip(" *").lower() in target_tags:
            result *= multiplier.value
    return result


def _armor(target: Unit, damage_type: str) -> float:
    if damage_type == "Siege":
        return target.armor_siege
    if damage_type == "Hand":
        return target.armor_melee
    return target.armor_ranged


def _attack_dps(attacker: Unit, target: Unit, target_count: int, *, melee: bool) -> float:
    if melee:
        attack = attacker.attack_melee
        if attack <= 0:
            return 0.0
        projectiles = attacker.num_projectiles_melee or 1
        multipliers = attacker.multipliers_melee
        damage_type = attacker.damage_type_melee or "Hand"
        rof = attacker.rof_melee or 1.5
        aoe = attacker.aoe_radius_melee
        engagement = 0.75 + min(attacker.speed, 8.0) / 16.0
    else:
        attack = attacker.attack_ranged
        if attack <= 0 or attacker.range <= 0:
            return 0.0
        projectiles = attacker.num_projectiles_ranged or 1
        multipliers = attacker.multipliers_ranged
        damage_type = attacker.damage_type_ranged or "Ranged"
        rof = attacker.rof_ranged or 3.0
        aoe = attacker.aoe_radius_ranged
        engagement = 1.0 + min(attacker.range, 24.0) / 120.0

    hit = (
        attack
        * projectiles
        * _multiplier_product(multipliers, target)
        * max(0.0, 1.0 - _armor(target, damage_type))
    )
    crowd = min(1.0, max(0, target_count - 1) / 8.0)
    aoe_factor = 1.0 + min(float(aoe), 4.0) * 0.2 * crowd
    return max(1.0, hit) / max(0.1, rof) * engagement * aoe_factor


def unit_pressure(attacker: Unit, target: Unit, target_count: int) -> float:
    """Estimate one unit's best sustainable pressure against a target type."""
    return max(
        _attack_dps(attacker, target, target_count, melee=False),
        _attack_dps(attacker, target, target_count, melee=True),
    )


def lineup_pressure(attacking: Lineup, defending: Lineup) -> float:
    """Estimate resource-weighted kill pressure without running BattleSimulator."""
    defending_cost = max(1, defending.total_cost)
    pressure = 0.0
    for target_slot in defending.slots:
        incoming_dps = sum(
            attacker_slot.count
            * unit_pressure(attacker_slot.unit, target_slot.unit, target_slot.count)
            for attacker_slot in attacking.slots
        )
        target_hp = max(1.0, target_slot.unit.hp * target_slot.count)
        target_weight = target_slot.total_cost / defending_cost
        pressure += target_weight * incoming_dps / target_hp
    return pressure


def estimate_matchup(
    red_candidate: CivWarCandidate,
    blue_candidate: CivWarCandidate,
    *,
    budget: int = BUDGET,
    age: int = 3,
) -> MatchupEstimate:
    red_lineup = allocate_candidate(red_candidate, budget=budget, age=age)
    blue_lineup = allocate_candidate(blue_candidate, budget=budget, age=age)
    red_pressure = lineup_pressure(red_lineup, blue_lineup)
    blue_pressure = lineup_pressure(blue_lineup, red_lineup)
    advantage_log = math.log(max(red_pressure, 1e-9) / max(blue_pressure, 1e-9))
    balance_gap = abs(advantage_log)
    mirror = (
        red_candidate.source == blue_candidate.source
        and red_candidate.strategy_id == blue_candidate.strategy_id
    )
    selection_score = (
        balance_gap
        + (red_candidate.identity_tier + blue_candidate.identity_tier)
        * _IDENTITY_TIER_PENALTY
        + (float(mirror) * _MIRROR_STRATEGY_PENALTY)
    )
    return MatchupEstimate(
        red_candidate=red_candidate,
        blue_candidate=blue_candidate,
        red_lineup=red_lineup,
        blue_lineup=blue_lineup,
        red_pressure=red_pressure,
        blue_pressure=blue_pressure,
        advantage_log=advantage_log,
        balance_gap=balance_gap,
        selection_score=selection_score,
    )


def rank_matchups(
    red_candidates: list[CivWarCandidate],
    blue_candidates: list[CivWarCandidate],
    *,
    budget: int = BUDGET,
    age: int = 3,
) -> list[MatchupEstimate]:
    """Rank bounded candidate pairings by static balance and identity."""
    estimates = [
        estimate_matchup(red, blue, budget=budget, age=age)
        for red in shortlist_candidates(red_candidates)
        for blue in shortlist_candidates(blue_candidates)
    ]
    estimates.sort(key=lambda estimate: (
        estimate.selection_score,
        estimate.balance_gap,
        estimate.is_strategy_mirror,
        estimate.red_candidate.id,
        estimate.blue_candidate.id,
    ))
    return estimates


def select_civ_matchup(
    repo: UnitRepo,
    red_civ: str,
    blue_civ: str,
    *,
    budget: int = BUDGET,
    age: int = 3,
    rng: random.Random | None = None,
) -> MatchupEstimate:
    """Randomly select among several close static estimates; never pre-run the battle."""
    if red_civ == blue_civ:
        raise ValueError("civ war requires two distinct civilizations")
    if rng is None:
        rng = random.Random()
    red_candidate = choose_candidate(
        generate_civ_candidates(repo, red_civ, age=age),
        rng=rng,
    )
    blue_candidate = choose_candidate(
        generate_civ_candidates(repo, blue_civ, age=age),
        rng=rng,
    )
    return estimate_matchup(
        red_candidate,
        blue_candidate,
        budget=budget,
        age=age,
    )


def generate_civ_war_lineup(
    repo: UnitRepo,
    red_civ: str,
    blue_civ: str,
    *,
    budget: int = BUDGET,
    age: int = 3,
    rng: random.Random | None = None,
) -> tuple[MatchLineup, MatchupEstimate]:
    """Build the public battle lineup while retaining its audit estimate."""
    estimate = select_civ_matchup(
        repo,
        red_civ,
        blue_civ,
        budget=budget,
        age=age,
        rng=rng,
    )
    red_profile = get_civ_profile(red_civ)
    blue_profile = get_civ_profile(blue_civ)
    match = MatchLineup(
        red=estimate.red_lineup,
        blue=estimate.blue_lineup,
        mode="civ_war",
        age=age,
        red_civ_name=red_profile.name,
        blue_civ_name=blue_profile.name,
        red_strategy=estimate.red_candidate.title,
        blue_strategy=estimate.blue_candidate.title,
    )
    return match, estimate
