"""代表性兵种对战：武器选择、伤害输出、特殊机制与胜负 smoke。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from plugins.games.ra2_battle.simulator import BattleResult, BattleSimulator, EventType, Side

_DATA = Path(__file__).resolve().parents[3] / "data" / "ra2" / "actors.json"


@pytest.fixture(scope="module")
def require_export():
    if not _DATA.is_file():
        pytest.skip("缺少 data/ra2，先运行 openra_ra2_export.py")


def _run(
    red: list,
    blue: list,
    *,
    seed: int = 0,
    max_ticks: int = 8000,
    width: int = 14,
    height: int = 8,
) -> BattleResult:
    return BattleSimulator(
        red,
        blue,
        seed=seed,
        max_ticks=max_ticks,
        width=width,
        height=height,
    ).run()


def _attacks(
    result: BattleResult,
    *,
    attacker: str | None = None,
    weapon: str | None = None,
) -> list:
    out = [e for e in result.events if e.type == EventType.ATTACK]
    if attacker is not None:
        out = [e for e in out if e.payload.get("attacker") == attacker]
    if weapon is not None:
        out = [e for e in out if e.payload.get("weapon") == weapon]
    return out


def _damage(result: BattleResult, attacker: str) -> int:
    return sum(e.payload.get("damage", 0) for e in _attacks(result, attacker=attacker))


def _weapons_used(result: BattleResult, attacker: str) -> set[str]:
    return {e.payload["weapon"] for e in _attacks(result, attacker=attacker)}


def _has_events(result: BattleResult, *types: EventType) -> bool:
    got = {e.type for e in result.events}
    return all(t in got for t in types)


@dataclass(frozen=True)
class MatchupSpec:
    id: str
    red: list
    blue: list
    seed: int = 0
    max_ticks: int = 8000
    width: int = 14
    height: int = 8


def _assert_resolves(r: BattleResult) -> None:
    assert r.ticks > 0
    assert _has_events(r, EventType.BATTLE_START, EventType.BATTLE_END)
    assert r.winner is not None, f"不应平局 ticks={r.ticks}"


def _assert_red_wins(r: BattleResult) -> None:
    _assert_resolves(r)
    assert r.winner == Side.RED


def _check_apoc_vs_ground(r: BattleResult) -> None:
    _assert_resolves(r)
    assert _weapons_used(r, "apoc") & {"120mmx", "120mmxE"}
    assert "MammothTusk" not in _weapons_used(r, "apoc")


def _check_apoc_vs_air(r: BattleResult) -> None:
    _assert_red_wins(r)
    assert "MammothTusk" in _weapons_used(r, "apoc")
    assert not (_weapons_used(r, "apoc") & {"120mmx", "120mmxE"})


def _check_hyd_vs_dlph_weapons(r: BattleResult) -> None:
    _assert_red_wins(r)
    assert "FlakTrackGun" in _weapons_used(r, "hyd")
    assert "FlakWeapon" not in _weapons_used(r, "hyd")


def _check_tany_c4_vs_tank(r: BattleResult) -> None:
    _assert_red_wins(r)
    assert _attacks(r, attacker="tany", weapon="C4")
    assert not _attacks(r, attacker="tany", weapon="DoublePistols")


def _check_tany_pistols_vs_inf(r: BattleResult) -> None:
    assert _damage(r, "tany") > 0
    assert not _attacks(r, attacker="tany", weapon="C4")


def _check_ghost_mp5_vs_tank(r: BattleResult) -> None:
    _assert_red_wins(r)
    assert _damage(r, "ghost") > 0
    assert not _attacks(r, attacker="ghost", weapon="C4")


def _check_disk_laser(r: BattleResult) -> None:
    _assert_red_wins(r)
    assert "DiskLaser" in _weapons_used(r, "disk")
    assert "DiskDrain" not in _weapons_used(r, "disk")


def _check_dlph_beam(r: BattleResult) -> None:
    assert len(_attacks(r, attacker="dlph")) >= 60
    assert _damage(r, "dlph") >= 100


def _check_hyd_dlph_damage(r: BattleResult) -> None:
    assert _damage(r, "hyd") >= 1500
    assert _damage(r, "dlph") >= 100


def _check_yuri_mc(r: BattleResult) -> None:
    _assert_red_wins(r)
    assert any(e.type == EventType.MIND_CONTROL for e in r.events)


def _check_mind_multi(r: BattleResult) -> None:
    mc = [e for e in r.events if e.type == EventType.MIND_CONTROL]
    assert len(mc) >= 2


def _check_carrier_hornet(r: BattleResult) -> None:
    assert any(e.type == EventType.SPAWN_CHILD for e in r.events)
    assert _attacks(r, attacker="hornet")


def _check_v3_spawn(r: BattleResult) -> None:
    assert any(e.type == EventType.SPAWN_CHILD for e in r.events)


def _check_dog_vs_inf(r: BattleResult) -> None:
    _assert_red_wins(r)
    assert _attacks(r, attacker="dog", weapon="DogJaw")
    assert _damage(r, "dog") >= 500


def _check_htk_vs_orca(r: BattleResult) -> None:
    _assert_red_wins(r)
    assert _damage(r, "htk") >= 200


def _check_aegis_vs_orca(r: BattleResult) -> None:
    _assert_red_wins(r)
    assert _attacks(r, attacker="aegis", weapon="Medusa")


def _check_ttnk_vs_htnk(r: BattleResult) -> None:
    assert _damage(r, "ttnk") > 0
    assert "TankBolt" in _weapons_used(r, "ttnk")


def _check_sref_vs_htnk(r: BattleResult) -> None:
    assert _damage(r, "sref") > 0
    assert "Comet" in _weapons_used(r, "sref")


def _check_lunr_vs_htnk(r: BattleResult) -> None:
    _assert_red_wins(r)
    assert _damage(r, "lunr") >= 500


def _check_sub_vs_dest(r: BattleResult) -> None:
    _assert_red_wins(r)
    assert _attacks(r, attacker="sub", weapon="SubTorpedo")


def _check_boris_vs_e1(r: BattleResult) -> None:
    _assert_red_wins(r)
    assert _damage(r, "boris") >= 400


def _check_ggi_vs_e1(r: BattleResult) -> None:
    assert _damage(r, "ggi") > 0
    assert len(_attacks(r, attacker="ggi")) >= 20


def _check_jumpjet_vs_e1(r: BattleResult) -> None:
    _assert_red_wins(r)
    assert _damage(r, "jumpjet") > 0


def _check_mgtk_vs_htnk(r: BattleResult) -> None:
    assert _damage(r, "mgtk") > 0


def _check_bsub_vs_dest(r: BattleResult) -> None:
    _assert_red_wins(r)
    assert _damage(r, "bsub") > 0


def _check_deso_vs_e1(r: BattleResult) -> None:
    assert _damage(r, "deso") > 0


def _check_brute_vs_e1(r: BattleResult) -> None:
    assert _damage(r, "brute") > 0


def _check_virus_vs_e1(r: BattleResult) -> None:
    assert _damage(r, "virus") > 0


def _check_snipe_vs_e1(r: BattleResult) -> None:
    assert _damage(r, "snipe") > 0


def _check_ytnk_vs_e1(r: BattleResult) -> None:
    _assert_red_wins(r)
    assert _damage(r, "ytnk") > 0


def _check_schp_vs_e1(r: BattleResult) -> None:
    _assert_red_wins(r)
    assert _damage(r, "schp") > 0


def _check_shad_vs_e1(r: BattleResult) -> None:
    _assert_red_wins(r)
    assert _damage(r, "shad") > 0


# (spec, check_fn)
_MATCHUPS: list[tuple[MatchupSpec, object]] = [
    # 武器选择
    (MatchupSpec("apoc_对地只用主炮", [("apoc", 1)], [("htnk", 3)]), _check_apoc_vs_ground),
    (MatchupSpec("apoc_对空只用导弹", [("apoc", 1)], [("orca", 2)], seed=1), _check_apoc_vs_air),
    (MatchupSpec("海蝎_对海只用主炮", [("hyd", 5)], [("dlph", 9)]), _check_hyd_vs_dlph_weapons),
    (MatchupSpec("谭雅_对载具C4不用手枪", [("tany", 1)], [("htnk", 1)]), _check_tany_c4_vs_tank),
    (
        MatchupSpec("谭雅_对步兵用手枪", [("tany", 1)], [("e1", 5)], seed=1, max_ticks=4000),
        _check_tany_pistols_vs_inf,
    ),
    (MatchupSpec("海豹_有伤害时优先MP5", [("ghost", 1)], [("htnk", 1)]), _check_ghost_mp5_vs_tank),
    (MatchupSpec("飞碟_不用吸金", [("disk", 1)], [("htnk", 2)], seed=2), _check_disk_laser),
    # 持续伤害
    (MatchupSpec("海豚_声波多段伤害", [("hyd", 5)], [("dlph", 9)]), _check_dlph_beam),
    (MatchupSpec("海蝎_对海豚有实质输出", [("hyd", 5)], [("dlph", 9)]), _check_hyd_dlph_damage),
    # 特殊机制
    (
        MatchupSpec("尤里_心控犀牛", [("yuri", 1)], [("htnk", 1)], seed=3, max_ticks=6000, width=12, height=6),
        _check_yuri_mc,
    ),
    (
        MatchupSpec("心控车_控多个步兵", [("mind", 1)], [("e1", 1), ("e2", 1), ("init", 1), ("brute", 1)], seed=5),
        _check_mind_multi,
    ),
    (MatchupSpec("航母_放出黄蜂", [("carrier", 1)], [("e1", 4, 1)], seed=7), _check_carrier_hornet),
    (MatchupSpec("V3_发射导弹", [("v3", 2)], [("htnk", 2)]), _check_v3_spawn),
    (MatchupSpec("警犬_咬步兵", [("dog", 2)], [("e1", 5)], max_ticks=4000), _check_dog_vs_inf),
    # 防空
    (MatchupSpec("防空履带_打入侵者", [("htk", 3)], [("orca", 2)]), _check_htk_vs_orca),
    (MatchupSpec("神盾_打入侵者", [("aegis", 1)], [("orca", 2)]), _check_aegis_vs_orca),
    (MatchupSpec("火箭飞行兵_打步兵", [("jumpjet", 3)], [("e1", 6)]), _check_jumpjet_vs_e1),
    # 坦克
    (MatchupSpec("犀牛_打灰熊", [("htnk", 1)], [("mtnk", 1)], seed=42, max_ticks=3000), _assert_resolves),
    (MatchupSpec("轻坦_以多打少胜犀牛", [("ltnk", 2)], [("htnk", 1)]), _assert_red_wins),
    (MatchupSpec("磁能_对犀牛有输出", [("ttnk", 1)], [("htnk", 2)]), _check_ttnk_vs_htnk),
    (MatchupSpec("光棱_对犀牛有输出", [("sref", 1)], [("htnk", 2)], width=32, height=16), _check_sref_vs_htnk),
    (MatchupSpec("月球飞行兵_慢打犀牛", [("lunr", 1)], [("htnk", 2)]), _check_lunr_vs_htnk),
    (MatchupSpec("幻影_对犀牛有输出", [("mgtk", 1)], [("htnk", 2)], seed=1), _check_mgtk_vs_htnk),
    # 海军
    (MatchupSpec("潜艇_打驱逐舰", [("sub", 1)], [("dest", 1)], seed=3), _check_sub_vs_dest),
    (MatchupSpec("尤里潜艇_打驱逐舰", [("bsub", 1)], [("dest", 1)], seed=2), _check_bsub_vs_dest),
    # 步兵 / 英雄
    (MatchupSpec("鲍里斯_清步兵", [("boris", 1)], [("e1", 6)], max_ticks=4000), _check_boris_vs_e1),
    (MatchupSpec("辐射兵_有辐射输出", [("deso", 1)], [("e1", 6)]), _check_deso_vs_e1),
    (MatchupSpec("美国大兵_对步兵", [("ggi", 6)], [("e1", 8)]), _check_ggi_vs_e1),
    (MatchupSpec("狂兽人_对步兵", [("brute", 2)], [("e1", 6)]), _check_brute_vs_e1),
    (MatchupSpec("病毒狙击手_有输出", [("virus", 2)], [("e1", 6)]), _check_virus_vs_e1),
    (MatchupSpec("英国狙击手_有输出", [("snipe", 2)], [("e1", 6)]), _check_snipe_vs_e1),
    # YR
    (MatchupSpec("奴隶矿场_对步兵", [("slav", 3)], [("e2", 5)], seed=1), _assert_resolves),
    (MatchupSpec("盖特_对步兵", [("ytnk", 1)], [("e1", 8)]), _check_ytnk_vs_e1),
    (MatchupSpec("黑鹰直升机_对步兵", [("schp", 1)], [("e1", 6)]), _check_schp_vs_e1),
    (MatchupSpec("阴影_对步兵", [("shad", 1)], [("e1", 8)]), _check_shad_vs_e1),
]


@pytest.mark.parametrize("spec,check_fn", _MATCHUPS, ids=[m[0].id for m in _MATCHUPS])
def test_matchup(require_export, spec: MatchupSpec, check_fn):
    result = _run(
        spec.red,
        spec.blue,
        seed=spec.seed,
        max_ticks=spec.max_ticks,
        width=spec.width,
        height=spec.height,
    )
    check_fn(result)
