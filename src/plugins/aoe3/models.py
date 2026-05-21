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
    train_time: int = 0
    trained_at: list[str] = field(default_factory=list)

    # 基础属性
    hp: int = 0
    speed: float = 0.0
    los: float = 0.0
    armor_melee: float = 0.0
    armor_ranged: float = 0.0
    armor_siege: float = 0.0        # 攻城抗性（极少见）

    # 远程攻击
    attack_ranged: float = 0.0
    range: float = 0.0
    range_min: float = 0.0
    rof_ranged: float = 0.0
    multipliers_ranged: list[Multiplier] = field(default_factory=list)

    # 近战攻击
    attack_melee: float = 0.0
    range_melee: float = 0.0            # 近战射程（0 表示使用模拟器默认值 1.5）
    rof_melee: float = 0.0
    multipliers_melee: list[Multiplier] = field(default_factory=list)

    # 攻城攻击
    attack_siege: float = 0.0
    range_siege: float = 0.0
    rof_siege: float = 0.0
    multipliers_siege: list[Multiplier] = field(default_factory=list)

    # AOE / 伤害类型（从 aoe3explorer 补充）
    aoe_radius: int = 0              # 兼容：所有攻击中最大的 AOE
    aoe_radius_ranged: int = 0       # 远程攻击 AOE 半径
    aoe_radius_melee: int = 0        # 近战攻击 AOE 半径
    aoe_radius_siege: int = 0        # 攻城攻击 AOE 半径
    damage_type_ranged: str = ""     # "Ranged" / "Siege" / "Hand"
    damage_type_melee: str = ""      # "Hand" / 其他

    # 杂项
    internal_name: str = ""

    @property
    def has_attack(self) -> bool:
        """是否有"对兵作战"的攻击能力。

        **只算 attack_ranged / attack_melee**，不算 attack_siege。

        理由：``attack_siege`` 是拆建筑专用槽位（``BuildingAttack`` 系列），
        斗蛐蛐一维场地上没有建筑可拆，模拟器也不读这个字段（详见
        ``docs/games/aoe3-battle.md`` §3.9）。如果一个单位**只有** ``attack_siege``
        没有 melee/ranged，它在斗蛐蛐里就是个站桩木桩，必须排除：
          - 木制牛 ``deeggwoodcattle`` —— 彩蛋单位，attack_siege=20000
          - 审判官 ``desalooninquisitor`` —— 治疗师，仅有拆建筑攻击

        > ⚠️ 已知遗漏：沙漠突袭者 ``deoutlawdesertraider`` 当前数据里也只有 attack_siege，
        > 但游戏里它**确实能打兵**——疑似 parser 的 BuildingAttack 名字识别误把它的
        > 真攻击丢进了 siege 桶（见 ``TODO.md`` 中"沙漠突袭者反兵攻击缺失"条目）。
        > 修好 parser 后它会自然回到战斗池，不需要单独加白名单。
        """
        return bool(self.attack_ranged or self.attack_melee)

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
        # 旧格式 fallback：multipliers: {ranged: [...], melee: [...], siege: [...]}
        mults_legacy = d.get("multipliers", {})

        def _parse_mults(lst: list[dict] | None) -> list[Multiplier]:
            if not lst:
                return []
            return [Multiplier(vs=m["vs"], value=m["value"]) for m in lst]

        # 优先用顶层 multipliers_ranged/melee/siege（supplement 合并后写入）
        # fallback 到旧的 multipliers.ranged/melee/siege
        mults_ranged = d.get("multipliers_ranged") or (
            mults_legacy.get("ranged") if isinstance(mults_legacy, dict) else None
        )
        mults_melee = d.get("multipliers_melee") or (
            mults_legacy.get("melee") if isinstance(mults_legacy, dict) else None
        )
        mults_siege = d.get("multipliers_siege") or (
            mults_legacy.get("siege") if isinstance(mults_legacy, dict) else None
        )

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
            attack_ranged=d.get("attack_ranged", 0.0),
            range=d.get("range", 0.0),
            range_min=d.get("range_min", 0.0),
            rof_ranged=d.get("rof_ranged", 0.0),
            multipliers_ranged=_parse_mults(mults_ranged),
            attack_melee=d.get("attack_melee", 0.0),
            range_melee=d.get("range_melee", 0.0),
            rof_melee=d.get("rof_melee", 0.0),
            multipliers_melee=_parse_mults(mults_melee),
            attack_siege=d.get("attack_siege", 0.0),
            range_siege=d.get("range_siege", 0.0),
            rof_siege=d.get("rof_siege", 0.0),
            multipliers_siege=_parse_mults(mults_siege),
            aoe_radius=d.get("aoe_radius", 0),
            aoe_radius_ranged=d.get("aoe_radius_ranged", 0),
            aoe_radius_melee=d.get("aoe_radius_melee", 0),
            aoe_radius_siege=d.get("aoe_radius_siege", 0),
            damage_type_ranged=d.get("damage_type_ranged", ""),
            damage_type_melee=d.get("damage_type_melee", ""),
            internal_name=d.get("internal_name", ""),
        )
