"""One-way artillery deployment behavior in the 2D simulator."""

from __future__ import annotations

from plugins.aoe3.models import Unit
from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.simulator2d import BattleSimulator2D
from plugins.games.aoe3_battle.simulator2d.model import ArtilleryState


def _init_pair(red: Unit, blue: Unit) -> BattleSimulator2D:
    sim = BattleSimulator2D(red, 1, blue, 1, seed=1)
    sim._init_soldiers()
    return sim


def _place_in_range(sim: BattleSimulator2D) -> tuple[object, object]:
    attacker, target = sim._soldiers
    attacker.x, attacker.y = 5.0, 10.0
    target.x, target.y, target.stopped = 15.0, 10.0, True
    sim._spatial_hash.rebuild(sim._soldiers)
    return attacker, target


def test_artillery_starts_limber_and_deploys_after_configured_time() -> None:
    repo = UnitRepo.get()
    falconet = repo.get_by_id("falconet")
    sim = _init_pair(falconet, repo.get_by_id("musketeer"))
    attacker, _target = _place_in_range(sim)

    assert attacker.artillery_state == ArtilleryState.LIMBER
    assert falconet.deploy_time == 2.0

    sim._tick = 0
    sim._process_artillery_states()
    assert attacker.artillery_state == ArtilleryState.DEPLOYING

    sim._tick = 19
    sim._process_artillery_states()
    assert attacker.artillery_state == ArtilleryState.DEPLOYING

    sim._tick = 20
    sim._process_artillery_states()
    assert attacker.artillery_state == ArtilleryState.DEPLOYED


def test_zero_deploy_time_switches_in_one_tick() -> None:
    repo = UnitRepo.get()
    flaming_arrow = repo.get_by_id("ypflamingarrow")
    sim = _init_pair(flaming_arrow, repo.get_by_id("musketeer"))
    attacker, _target = _place_in_range(sim)

    assert flaming_arrow.has_limber_stance
    assert flaming_arrow.deploy_time == 0.0

    sim._tick = 0
    sim._process_artillery_states()
    assert attacker.artillery_state == ArtilleryState.DEPLOYING

    sim._tick = 1
    sim._process_artillery_states()
    assert attacker.artillery_state == ArtilleryState.DEPLOYED


def test_limber_artillery_has_no_attack_candidates() -> None:
    repo = UnitRepo.get()
    sim = _init_pair(repo.get_by_id("falconet"), repo.get_by_id("musketeer"))
    attacker, target = _place_in_range(sim)

    assert not attacker.can_attack
    assert sim._combat.attack_candidates(attacker) == []
    assert sim._combat.determine_attack_mode(attacker, target) is None


def test_deploying_artillery_is_stationary() -> None:
    repo = UnitRepo.get()
    sim = _init_pair(repo.get_by_id("falconet"), repo.get_by_id("musketeer"))
    attacker, _target = _place_in_range(sim)
    sim._tick = 0
    sim._process_artillery_states()

    assert attacker.artillery_state == ArtilleryState.DEPLOYING
    sim._process_movement()
    assert attacker.velocity.length() == 0.0


def test_deployed_artillery_uses_speed_multiplier() -> None:
    repo = UnitRepo.get()
    falconet = repo.get_by_id("falconet")
    sim = _init_pair(falconet, repo.get_by_id("musketeer"))
    attacker, _target = _place_in_range(sim)
    attacker.artillery_state = ArtilleryState.DEPLOYED

    assert falconet.deployed_speed_multiplier == 0.4
    assert attacker.effective_speed == falconet.speed * 0.4


def test_deployed_artillery_physically_moves_at_multiplier() -> None:
    repo = UnitRepo.get()
    falconet = repo.get_by_id("falconet")
    sim = _init_pair(falconet, repo.get_by_id("musketeer"))
    attacker, target = _place_in_range(sim)
    attacker.artillery_state = ArtilleryState.DEPLOYED
    attacker.x, attacker.y = 60.0, 60.0
    target.x, target.y = 70.0, 60.0
    sim._field_width = sim._field_height = 100.0
    sim._spatial_hash.rebuild(sim._soldiers)

    start = attacker.x
    for tick in range(5):
        sim._tick = tick
        sim._process_movement()

    assert attacker.x - start < falconet.speed * sim.config.tick_interval * 5
