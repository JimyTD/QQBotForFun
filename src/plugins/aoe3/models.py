"""AoE3 数据模型。"""

from __future__ import annotations

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
    wiki_url: str = ""
    icon_url: str = ""

    # 分类
    type: list[str] = field(default_factory=list)
    civs: list[str] = field(default_factory=list)
    age: str = ""

    # 训练
    cost: dict[str, int] = field(default_factory=dict)
    pop: int = 0
    train_time: int = 0
    trained_at: list[str] = field(default_factory=list)

    # 基础属性
    hp: int = 0
    speed: float = 0.0
    los: float = 0.0
    armor_melee: float = 0.0
    armor_ranged: float = 0.0

    # 远程攻击
    attack_ranged: float = 0.0
    range: float = 0.0
    range_min: float = 0.0
    rof_ranged: float = 0.0
    multipliers_ranged: list[Multiplier] = field(default_factory=list)

    # 近战攻击
    attack_melee: float = 0.0
    rof_melee: float = 0.0
    multipliers_melee: list[Multiplier] = field(default_factory=list)

    # 攻城攻击
    attack_siege: float = 0.0
    range_siege: float = 0.0
    rof_siege: float = 0.0
    multipliers_siege: list[Multiplier] = field(default_factory=list)

    # 杂项
    internal_name: str = ""

    @property
    def has_attack(self) -> bool:
        return bool(self.attack_ranged or self.attack_melee or self.attack_siege)

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

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Unit:
        """从 units.json 的字典构造。"""
        mults = d.get("multipliers", {})

        def _parse_mults(lst: list[dict] | None) -> list[Multiplier]:
            if not lst:
                return []
            return [Multiplier(vs=m["vs"], value=m["value"]) for m in lst]

        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            name_en=d.get("name_en", ""),
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
            attack_ranged=d.get("attack_ranged", 0.0),
            range=d.get("range", 0.0),
            range_min=d.get("range_min", 0.0),
            rof_ranged=d.get("rof_ranged", 0.0),
            multipliers_ranged=_parse_mults(
                mults.get("ranged") if isinstance(mults, dict) else None
            ),
            attack_melee=d.get("attack_melee", 0.0),
            rof_melee=d.get("rof_melee", 0.0),
            multipliers_melee=_parse_mults(
                mults.get("melee") if isinstance(mults, dict) else None
            ),
            attack_siege=d.get("attack_siege", 0.0),
            range_siege=d.get("range_siege", 0.0),
            rof_siege=d.get("rof_siege", 0.0),
            multipliers_siege=_parse_mults(
                mults.get("siege") if isinstance(mults, dict) else None
            ),
            internal_name=d.get("internal_name", ""),
        )
