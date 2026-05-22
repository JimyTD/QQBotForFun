"""斗蛐蛐可随机阵容单位池与黑名单（与 export 全量 actors 区分）。"""

from __future__ import annotations

from .repo import ActorDef, load_actors

# 明确不参与斗蛐蛐随机/押注阵容的 actor_id → 原因（文档 §3.4 同步）
LINEUP_BLACKLIST: dict[str, str] = {
    "engineer": "工程师，无武器，仅占领建筑",
    "spy": "间谍，无武器，仅渗透",
    "amcv": "盟军基地车（MCV），无武器",
    "smcv": "苏军基地车（MCV），无武器",
    "cmin": "盟军超时空采矿车（Chrono Miner），无武器",
    "lcrf": "登陆艇 / 两栖运输，无武器",
    "sapc": "装甲运兵船，无武器",
}

# spawn_only（如 hornet、asw 子机）由 is_lineup_eligible 单独排除

# 勿用 "Miner" 模糊匹配：苏军 harv（War Miner）有炮，应入池；仅黑名单 cmin
_NAME_HINTS_EXCLUDE = ("Engineer", "Construction", "Transport")

# 纯空军编制（斗蛐蛐平地舞台，不随机到仅空中机动的飞机；航母/海军仍入池）
_PURE_AIR_LOCOMOTORS = frozenset({"aircraft"})


def is_lineup_eligible(actor: ActorDef) -> bool:
    """是否可进入斗蛐蛐随机阵容（能开战且含武器）。"""
    if actor.spawn_only:
        return False
    if actor.id in LINEUP_BLACKLIST:
        return False
    if not actor.armaments:
        return False
    if actor.cost <= 0:
        return False
    if any(h in actor.name for h in _NAME_HINTS_EXCLUDE):
        return False
    if "Aircraft" in actor.categories and actor.locomotor in _PURE_AIR_LOCOMOTORS:
        return False
    return True


def lineup_eligible_actors(
    actors: dict[str, ActorDef] | None = None,
) -> list[ActorDef]:
    actors = actors or load_actors()
    return sorted(
        (a for a in actors.values() if is_lineup_eligible(a)),
        key=lambda x: x.id,
    )


def lineup_eligible_ids(actors: dict[str, ActorDef] | None = None) -> tuple[str, ...]:
    return tuple(a.id for a in lineup_eligible_actors(actors))
