"""AoE3 数据模型。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Multiplier:
    """克制倍率。"""
    vs: str
    value: float

    def __str__(self) -> str:
        return f"{self.vs} x{self.value}"


@dataclass
class Unit:
    """AoE3 单位。"""

    id: str
    name: str           # 中文名（可能等于 name_en）
    name_en: str        # 英文名
    aliases: list[str] = field(default_factory=list)  # 别名（用于搜索）
    wiki_url: str = ""
    icon_url: str = ""

    # 分类
    type: list[str] = field(default_factory=list)
    civs: list[str] = field(default_factory=list)
    age: str = ""

    # 训练
    cost: dict[str, int] = field(default_factory=dict)
    pop: int = 0
    train_time: float = 0.0
    trained_at: list[str] = field(default_factory=list)

    # 基础属性
    hp: float = 0.0
    speed: float = 0.0
    los: float = 0.0
    armor_melee: float = 0.0
    armor_ranged: float = 0.0
    armor_siege: float = 0.0        # 攻城抗性（极少见）
    obstruction_radius_x: float = 0.0  # 原版 protoy obstructionradiusx
    obstruction_radius_z: float = 0.0  # 原版 protoy obstructionradiusz
    obstruction_radius_equiv: float = 0.0  # 等面积圆半径 sqrt(x*z)

    # 默认阵型的攻击模式。战斗、展示与科技都读这一份。
    attack_actions: list = field(default_factory=list)
    attack_actions_by_tactic: dict = field(default_factory=dict)
    inflicts_no_damage: bool = False

    # 抬手（秒），按动作名。
    windups: dict[str, float] = field(default_factory=dict)

    # 炮兵架设：开局移动，首次交火后永久部署。
    has_limber_stance: bool = False
    deploy_time: float = 0.0
    deployed_speed_multiplier: float = 1.0

    # 官方 tooltip（stringtable ← protoy rollovertextid）
    description: str = ""
    description_en: str = ""

    # 杂项
    internal_name: str = ""

    @property
    def has_attack(self) -> bool:
        """是否有打得到普通单位的攻击。

        只算打得中人的攻击模式。``InflictsNoDamage`` 不算。只拆建筑的不算。
        """
        if self.inflicts_no_damage:
            return False
        return any(
            action.hits_soldiers and action.damage > 0 and action.range_max > 0
            for action in self.attack_actions
        )

    @property
    def is_trainable(self) -> bool:
        """有费用、有攻击、非英雄 → 可训练的常规/雇佣兵种。"""
        is_hero = "Hero" in self.type
        return bool(self.cost) and self.has_attack and not is_hero

    @property
    def cost_str(self) -> str:
        """格式化费用。"""
        icons = {"food": "🍖", "wood": "🪵", "gold": "🪙",
                 "export": "📦", "influence": "💎"}
        parts = []
        for res, amount in self.cost.items():
            icon = icons.get(res, res)
            parts.append(f"{amount}{icon}")
        return " ".join(parts)

    @property
    def type_str(self) -> str:
        return " / ".join(self.type) if self.type else ""

    @property
    def collision_radius(self) -> float:
        """Return the equivalent circular collision radius.

        Missing or malformed obstruction data returns ``0.0`` so callers can
        apply their own data fallback.
        """
        if self.obstruction_radius_equiv > 0:
            return self.obstruction_radius_equiv
        if self.obstruction_radius_x > 0 and self.obstruction_radius_z > 0:
            return math.sqrt(self.obstruction_radius_x * self.obstruction_radius_z)
        return 0.0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Unit:
        """从 units.json 的字典构造。"""
        from .attack_actions import attack_action_from_dict

        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            name_en=d.get("name_en", ""),
            aliases=d.get("aliases", []),
            wiki_url=d.get("wiki_url", ""),
            icon_url=d.get("icon_url", ""),
            type=d.get("type", []),
            civs=d.get("civs", []),
            age=d.get("age", ""),
            cost=d.get("cost", {}),
            pop=d.get("pop", 0),
            train_time=d.get("train_time", 0),
            trained_at=d.get("trained_at", []),
            hp=d.get("hp", 0),
            speed=d.get("speed", 0.0),
            los=d.get("los", 0.0),
            armor_melee=d.get("armor_melee", 0.0),
            armor_ranged=d.get("armor_ranged", 0.0),
            armor_siege=d.get("armor_siege", 0.0),
            obstruction_radius_x=d.get("obstruction_radius_x", 0.0),
            obstruction_radius_z=d.get("obstruction_radius_z", 0.0),
            obstruction_radius_equiv=d.get("obstruction_radius_equiv", 0.0),
            attack_actions=[
                attack_action_from_dict(item)
                for item in d.get("attack_actions") or []
                if isinstance(item, dict) and item.get("name")
            ],
            attack_actions_by_tactic={
                str(name): [
                    attack_action_from_dict(item)
                    for item in actions
                    if isinstance(item, dict) and item.get("name")
                ]
                for name, actions in (d.get("attack_actions_by_tactic") or {}).items()
                if isinstance(actions, list)
            },
            inflicts_no_damage=bool(d.get("inflicts_no_damage", False)),
            windups={k: float(v) for k, v in d.get("windups", {}).items()},
            has_limber_stance=bool(d.get("has_limber_stance", False)),
            deploy_time=float(d.get("deploy_time", 0) or 0),
            deployed_speed_multiplier=float(
                d.get("deployed_speed_multiplier", 1) or 1
            ),
            description=d.get("description", ""),
            description_en=d.get("description_en", ""),
            internal_name=d.get("internal_name", ""),
        )
