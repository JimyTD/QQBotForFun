"""AoE3 斗蛐蛐 —— 核心战斗模拟器。

一维直线场地，双方对冲，tick 驱动。
输出结构化事件流，供播报层消费。

设计文档：docs/games/aoe3-battle.md §三
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.plugins.aoe3.models import Unit

logger = logging.getLogger("aoe3_battle.simulator")

# =====================================================================
# 常量
# =====================================================================
TICK_INTERVAL = 0.1          # 秒/tick
MAX_TICKS = 600              # 最大 tick 数（60 秒）
FIELD_LENGTH = 30.0          # 场地长度
MELEE_RANGE = 1.5            # 近战射程
CLOSE_RANGE_PENALTY = 0.5    # 贴脸惩罚伤害系数
DEFAULT_ROF_RANGED = 3.0     # 远程 ROF 缺失默认值
DEFAULT_ROF_MELEE = 1.5      # 近战 ROF 缺失默认值


# =====================================================================
# 事件类型
# =====================================================================
class EventType(str, Enum):
    BATTLE_START = "BATTLE_START"
    MOVE = "MOVE"
    ATTACK = "ATTACK"
    DEATH = "DEATH"
    TARGET_LOCK = "TARGET_LOCK"
    AOE_SPLASH = "AOE_SPLASH"
    BATTLE_END = "BATTLE_END"


class Side(str, Enum):
    RED = "red"
    BLUE = "blue"


class AttackMode(str, Enum):
    RANGED = "ranged"
    MELEE = "melee"
    RANGED_PENALIZED = "ranged_penalized"  # 贴脸惩罚


class BattlePhase(str, Enum):
    """战况阶段（供播报层选词用）。"""
    APPROACHING = "approaching"  # 接近期：尚无任何攻击事件
    FIGHTING = "fighting"        # 对耗期
    STALEMATE = "stalemate"      # 僵持期：双方剩余 HP 比例都 < 30%


# =====================================================================
# 事件数据
# =====================================================================
@dataclass
class BattleEvent:
    """一条战斗事件。"""
    tick: int
    time: float                  # 模拟时间（秒）
    event_type: EventType
    data: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"[{self.time:.1f}s] {self.event_type.value} {self.data}"


# =====================================================================
# 士兵个体
# =====================================================================
@dataclass
class Soldier:
    """一个士兵个体。"""
    id: int                      # 全局唯一 ID
    side: Side
    unit: Unit                   # 兵种模板（共享引用）
    hp: float
    max_hp: float
    pos: float                   # 一维位置
    attack_cd: float = 0.0       # 攻击冷却剩余（秒）
    target_id: int | None = None # 锁定目标的 soldier.id
    alive: bool = True
    stopped: bool = False        # 是否已因 F2A 停下
    total_damage_dealt: float = 0.0  # 累计造成伤害
    kills: int = 0               # 击杀数

    # ---- 兵种能力缓存（初始化时从 Unit 提取）----
    has_ranged: bool = False     # 有远程攻击
    has_melee: bool = False      # 有近战攻击

    # 实际使用的远程参数
    effective_ranged_attack: float = 0.0
    effective_ranged_range: float = 0.0
    effective_ranged_rof: float = 0.0
    effective_ranged_range_min: float = 0.0

    @property
    def name(self) -> str:
        return self.unit.name or self.unit.name_en

    @property
    def hp_pct(self) -> float:
        return self.hp / self.max_hp if self.max_hp > 0 else 0.0


def _create_soldier(
    soldier_id: int, side: Side, unit: Unit, pos: float
) -> Soldier:
    """从 Unit 模板创建一个士兵个体，解析攻击能力。"""
    s = Soldier(
        id=soldier_id,
        side=side,
        unit=unit,
        hp=float(unit.hp),
        max_hp=float(unit.hp),
        pos=pos,
    )

    # ---- 解析攻击能力 ----
    has_ranged = unit.attack_ranged > 0 and unit.range > 0
    has_melee = unit.attack_melee > 0

    s.has_ranged = has_ranged
    s.has_melee = has_melee

    if has_ranged:
        s.effective_ranged_attack = unit.attack_ranged
        s.effective_ranged_range = unit.range
        s.effective_ranged_rof = unit.rof_ranged if unit.rof_ranged > 0 else DEFAULT_ROF_RANGED
        s.effective_ranged_range_min = unit.range_min

    return s


# =====================================================================
# 模拟器
# =====================================================================
@dataclass
class ArmySlot:
    """阵容中的一个兵种槽位（模拟器侧）。"""
    unit: Unit
    count: int


@dataclass
class BattleResult:
    """模拟结果。"""
    winner: Side | None          # None = 平局
    events: list[BattleEvent]
    ticks: int
    duration: float              # 模拟时长（秒）
    red_alive: list[Soldier]
    blue_alive: list[Soldier]
    red_dead: list[Soldier]
    blue_dead: list[Soldier]
    # 多兵种阵容信息
    red_army: list[ArmySlot]
    blue_army: list[ArmySlot]
    red_count: int               # 初始总个体数
    blue_count: int
    timeout: bool = False

    # ---- 向后兼容：单兵种场景 ----
    @property
    def red_unit(self) -> Unit:
        return self.red_army[0].unit

    @property
    def blue_unit(self) -> Unit:
        return self.blue_army[0].unit


class BattleSimulator:
    """一维对冲战斗模拟器。

    用法（多兵种）：
        sim = BattleSimulator(
            red_army=[(unit_a, 5), (unit_b, 3)],
            blue_army=[(unit_c, 10)],
        )
        result = sim.run()

    用法（单兵种，向后兼容）：
        sim = BattleSimulator(red_unit, red_count, blue_unit, blue_count)
        result = sim.run()
    """

    def __init__(
        self,
        red_unit: Unit | None = None,
        red_count: int = 0,
        blue_unit: Unit | None = None,
        blue_count: int = 0,
        *,
        red_army: list[tuple[Unit, int]] | None = None,
        blue_army: list[tuple[Unit, int]] | None = None,
        field_length: float = FIELD_LENGTH,
        max_ticks: int = MAX_TICKS,
        seed: int | None = None,
        duel_mode: bool = False,
    ) -> None:
        # 支持两种调用方式：
        # 1. 旧式：BattleSimulator(red_unit, red_count, blue_unit, blue_count)
        # 2. 新式：BattleSimulator(red_army=[...], blue_army=[...])
        if red_army is not None:
            self.red_army = [ArmySlot(u, c) for u, c in red_army]
        elif red_unit is not None:
            self.red_army = [ArmySlot(red_unit, red_count)]
        else:
            raise ValueError("必须提供 red_unit 或 red_army")

        if blue_army is not None:
            self.blue_army = [ArmySlot(u, c) for u, c in blue_army]
        elif blue_unit is not None:
            self.blue_army = [ArmySlot(blue_unit, blue_count)]
        else:
            raise ValueError("必须提供 blue_unit 或 blue_army")

        self.red_count = sum(s.count for s in self.red_army)
        self.blue_count = sum(s.count for s in self.blue_army)
        self.field_length = field_length
        self.max_ticks = max_ticks

        self._rng = random.Random(seed)
        self._events: list[BattleEvent] = []
        self._tick = 0
        self._soldiers: list[Soldier] = []
        self._soldier_map: dict[int, Soldier] = {}
        self._next_id = 1
        self._any_attack_happened = False  # 是否发生过攻击（判断阶段用）
        self._duel_mode = duel_mode          # 单挑模式超时判平局

    # ---- 初始化 ----
    def _init_soldiers(self) -> None:
        """创建所有士兵个体（支持多兵种）。"""
        for slot in self.red_army:
            for _ in range(slot.count):
                s = _create_soldier(self._next_id, Side.RED, slot.unit, 0.0)
                self._next_id += 1
                self._soldiers.append(s)
                self._soldier_map[s.id] = s
                logger.debug(
                    "初始化 %s #%d side=%s hp=%.0f pos=%.1f "
                    "ranged_atk=%.1f range=%.1f melee_atk=%.1f",
                    s.name, s.id, s.side.value, s.hp, s.pos,
                    s.effective_ranged_attack, s.effective_ranged_range,
                    s.unit.attack_melee,
                )

        for slot in self.blue_army:
            for _ in range(slot.count):
                s = _create_soldier(
                    self._next_id, Side.BLUE, slot.unit, self.field_length
                )
                self._next_id += 1
                self._soldiers.append(s)
                self._soldier_map[s.id] = s
                logger.debug(
                    "初始化 %s #%d side=%s hp=%.0f pos=%.1f "
                    "ranged_atk=%.1f range=%.1f melee_atk=%.1f",
                    s.name, s.id, s.side.value, s.hp, s.pos,
                    s.effective_ranged_attack, s.effective_ranged_range,
                    s.unit.attack_melee,
                )

    def _alive(self, side: Side | None = None) -> list[Soldier]:
        """返回存活士兵列表。"""
        if side is None:
            return [s for s in self._soldiers if s.alive]
        return [s for s in self._soldiers if s.alive and s.side == side]

    def _enemy_side(self, side: Side) -> Side:
        return Side.BLUE if side == Side.RED else Side.RED

    def _emit(self, event_type: EventType, data: dict[str, Any] | None = None) -> None:
        ev = BattleEvent(
            tick=self._tick,
            time=self._tick * TICK_INTERVAL,
            event_type=event_type,
            data=data or {},
        )
        self._events.append(ev)

    # ---- 距离计算 ----
    def _distance(self, a: Soldier, b: Soldier) -> float:
        return abs(a.pos - b.pos)

    def _nearest_enemy(self, s: Soldier) -> Soldier | None:
        """找最近的存活敌方。"""
        enemies = self._alive(self._enemy_side(s.side))
        if not enemies:
            return None
        return min(enemies, key=lambda e: abs(s.pos - e.pos))

    # ---- 移动 ----
    def _process_movement(self) -> None:
        """每 tick 移动处理。"""
        for s in self._alive():
            if s.stopped:
                continue

            # 检查是否能攻击任意敌方（F2A 停止条件）
            if self._can_attack_any_enemy(s):
                s.stopped = True
                logger.debug(
                    "tick=%d %s#%d 停止移动 pos=%.2f（F2A：能攻击敌方）",
                    self._tick, s.name, s.id, s.pos,
                )
                continue

            # 向最近敌方移动
            nearest = self._nearest_enemy(s)
            if nearest is None:
                continue

            direction = 1.0 if nearest.pos > s.pos else -1.0
            move_dist = s.unit.speed * TICK_INTERVAL
            old_pos = s.pos
            s.pos += direction * move_dist

            # 不超过场地边界
            s.pos = max(0.0, min(self.field_length, s.pos))

            if abs(s.pos - old_pos) > 0.001:
                logger.debug(
                    "tick=%d %s#%d 移动 %.2f → %.2f（最近敌方距离=%.2f）",
                    self._tick, s.name, s.id, old_pos, s.pos,
                    abs(s.pos - nearest.pos),
                )

    def _can_attack_any_enemy(self, s: Soldier) -> bool:
        """判断士兵是否能攻击任意敌方（F2A 停止条件）。"""
        enemies = self._alive(self._enemy_side(s.side))
        for e in enemies:
            dist = self._distance(s, e)
            # 有远程能力且在射程内
            if s.has_ranged and dist <= s.effective_ranged_range:
                return True
            # 有近战能力且在近战距离
            if s.has_melee and dist <= MELEE_RANGE:
                return True
            # 纯近战兵只看近战距离
            if not s.has_ranged and s.has_melee and dist <= MELEE_RANGE:
                return True
        return False

    # ---- 目标锁定 ----
    def _acquire_target(self, s: Soldier) -> None:
        """为士兵锁定目标。"""
        if not s.stopped:
            return
        # 当前目标还活着就不换
        if s.target_id is not None:
            target = self._soldier_map.get(s.target_id)
            if target is not None and target.alive:
                return

        # 重新锁定：射程内最近优先，距离相同随机
        enemies = self._alive(self._enemy_side(s.side))
        if not enemies:
            s.target_id = None
            return

        # 筛选射程内的敌方
        in_range: list[tuple[Soldier, float]] = []
        for e in enemies:
            dist = self._distance(s, e)
            if s.has_ranged and dist <= s.effective_ranged_range:
                in_range.append((e, dist))
            elif s.has_melee and dist <= MELEE_RANGE:
                in_range.append((e, dist))

        if not in_range:
            # 射程内没有敌方（不应该发生在 stopped 状态，但防御性处理）
            s.target_id = None
            logger.warning(
                "tick=%d %s#%d 已停止但射程内无敌方！pos=%.2f",
                self._tick, s.name, s.id, s.pos,
            )
            # 重新允许移动
            s.stopped = False
            return

        # 按距离排序
        in_range.sort(key=lambda x: x[1])
        min_dist = in_range[0][1]

        # 距离相同的候选
        candidates = [e for e, d in in_range if abs(d - min_dist) < 0.01]
        target = self._rng.choice(candidates)
        s.target_id = target.id

        self._emit(EventType.TARGET_LOCK, {
            "soldier_id": s.id,
            "soldier_name": s.name,
            "side": s.side.value,
            "target_id": target.id,
            "target_name": target.name,
            "distance": round(self._distance(s, target), 2),
        })
        logger.debug(
            "tick=%d %s#%d 锁定目标 %s#%d（距离=%.2f）",
            self._tick, s.name, s.id, target.name, target.id,
            self._distance(s, target),
        )

    # ---- 攻击模式判定 ----
    def _determine_attack_mode(
        self, s: Soldier, target: Soldier
    ) -> AttackMode | None:
        """根据与目标的距离判定攻击模式。返回 None 表示本 tick 无法攻击。"""
        dist = self._distance(s, target)

        # 情况1：近战距离
        if dist <= MELEE_RANGE:
            if s.has_melee:
                return AttackMode.MELEE
            # 无近战但有远程 → 远程（可能有贴脸惩罚）
            if s.has_ranged:
                if s.effective_ranged_range_min > 0 and dist < s.effective_ranged_range_min:
                    return AttackMode.RANGED_PENALIZED
                return AttackMode.RANGED

        # 情况2：远程有效射程内
        if s.has_ranged:
            if dist <= s.effective_ranged_range:
                if s.effective_ranged_range_min > 0 and dist < s.effective_ranged_range_min:
                    # 在 range_min 和 1.5 之间
                    if s.has_melee:
                        # 有近战 → 等敌方靠近（本 tick 不攻击）
                        return None
                    else:
                        return AttackMode.RANGED_PENALIZED
                return AttackMode.RANGED

        # 情况3：超出所有射程 → 不攻击（理论上不应发生在 stopped 状态）
        return None

    # ---- 伤害计算 ----
    def _calc_damage(
        self,
        attacker: Soldier,
        target: Soldier,
        mode: AttackMode,
    ) -> float:
        """计算单次攻击伤害。"""
        if mode == AttackMode.MELEE:
            base_atk = attacker.unit.attack_melee
            multipliers = attacker.unit.multipliers_melee
            # 近战伤害类型通常是 Hand → 吃近战护甲
            dtype = attacker.unit.damage_type_melee
            if dtype == "Ranged":
                armor = target.unit.armor_ranged
            elif dtype == "Siege":
                armor = target.unit.armor_siege
            else:
                armor = target.unit.armor_melee
        elif mode in (AttackMode.RANGED, AttackMode.RANGED_PENALIZED):
            base_atk = attacker.unit.attack_ranged
            multipliers = attacker.unit.multipliers_ranged
            # 根据 damage_type_ranged 选护甲
            dtype = attacker.unit.damage_type_ranged
            if dtype == "Siege":
                armor = target.unit.armor_siege
            elif dtype == "Hand":
                armor = target.unit.armor_melee
            else:
                armor = target.unit.armor_ranged
        else:
            return 0.0

        # 倍率叠乘
        mult = self._calc_multiplier(multipliers, target)

        damage = base_atk * mult * (1.0 - armor)

        # 贴脸惩罚
        if mode == AttackMode.RANGED_PENALIZED:
            damage *= CLOSE_RANGE_PENALTY

        # 最低伤害 1
        damage = max(1.0, damage)

        logger.debug(
            "tick=%d 伤害计算 %s#%d→%s#%d mode=%s base=%.1f mult=%.2f "
            "armor=%.2f penalty=%s → dmg=%.1f",
            self._tick, attacker.name, attacker.id,
            target.name, target.id, mode.value,
            base_atk, mult, armor,
            "Y" if mode == AttackMode.RANGED_PENALIZED else "N",
            damage,
        )
        return damage

    def _calc_multiplier(
        self, multipliers: list, target: Soldier
    ) -> float:
        """计算倍率乘积。目标可能属于多个类型，所有匹配的倍率叠乘。"""
        if not multipliers or not target.unit.type:
            return 1.0

        target_types = {t.lower() for t in target.unit.type}
        mult = 1.0
        for m in multipliers:
            if m.vs.lower() in target_types:
                mult *= m.value
                logger.debug(
                    "  倍率匹配: vs=%s value=%.2f（目标类型=%s）",
                    m.vs, m.value, target.unit.type,
                )
        return mult

    # ---- 攻击执行 ----
    def _process_attacks(self) -> None:
        """每 tick 攻击处理。"""
        for s in self._alive():
            if not s.stopped:
                continue

            # CD 冷却
            if s.attack_cd > 0:
                s.attack_cd -= TICK_INTERVAL
                if s.attack_cd > 0.001:
                    continue

            # 确保有目标
            self._acquire_target(s)
            if s.target_id is None:
                continue

            target = self._soldier_map.get(s.target_id)
            if target is None or not target.alive:
                s.target_id = None
                continue

            # 判定攻击模式
            mode = self._determine_attack_mode(s, target)
            if mode is None:
                continue  # 本 tick 无法攻击（等敌方靠近）

            self._any_attack_happened = True

            # 计算伤害
            damage = self._calc_damage(s, target, mode)

            # 应用伤害到主目标
            self._apply_damage(s, target, damage, mode)

            # AOE 溅射：按当前攻击模式取对应的 AOE 半径
            if mode == AttackMode.MELEE:
                aoe = s.unit.aoe_radius_melee
            else:
                aoe = s.unit.aoe_radius_ranged
            if aoe > 0:
                self._process_aoe(s, target, mode, aoe_override=aoe)

            # 进入 CD
            if mode == AttackMode.MELEE:
                rof = s.unit.rof_melee if s.unit.rof_melee > 0 else DEFAULT_ROF_MELEE
            else:
                rof = s.effective_ranged_rof if s.effective_ranged_rof > 0 else DEFAULT_ROF_RANGED
            s.attack_cd = rof

    def _apply_damage(
        self,
        attacker: Soldier,
        target: Soldier,
        damage: float,
        mode: AttackMode,
        *,
        is_splash: bool = False,
    ) -> None:
        """对目标应用伤害，处理死亡。"""
        old_hp = target.hp
        target.hp -= damage
        attacker.total_damage_dealt += damage

        self._emit(EventType.ATTACK, {
            "attacker_id": attacker.id,
            "attacker_name": attacker.name,
            "attacker_side": attacker.side.value,
            "target_id": target.id,
            "target_name": target.name,
            "target_side": target.side.value,
            "damage": round(damage, 1),
            "mode": mode.value,
            "target_hp_before": round(old_hp, 1),
            "target_hp_after": round(max(0, target.hp), 1),
            "is_splash": is_splash,
        })

        if target.hp <= 0:
            target.hp = 0
            target.alive = False
            attacker.kills += 1

            side_alive = len(self._alive(target.side))
            side_total = (
                self.red_count if target.side == Side.RED else self.blue_count
            )

            self._emit(EventType.DEATH, {
                "soldier_id": target.id,
                "soldier_name": target.name,
                "side": target.side.value,
                "killer_id": attacker.id,
                "killer_name": attacker.name,
                "killer_side": attacker.side.value,
                "remaining": side_alive,
                "total": side_total,
                "overkill": round(-target.hp + damage - old_hp, 1) if old_hp > 0 else 0,
            })

            logger.info(
                "tick=%d %s#%d 阵亡（被 %s#%d 击杀），%s 剩余 %d/%d",
                self._tick, target.name, target.id,
                attacker.name, attacker.id,
                target.side.value, side_alive, side_total,
            )

            # 所有锁定该目标的士兵需要重新锁定
            for s2 in self._alive():
                if s2.target_id == target.id:
                    s2.target_id = None

    # ---- AOE 溅射 ----
    def _process_aoe(
        self, attacker: Soldier, main_target: Soldier, mode: AttackMode,
        *, aoe_override: int = 0,
    ) -> None:
        """处理 AOE 溅射伤害。"""
        aoe_radius = aoe_override or attacker.unit.aoe_radius
        if aoe_radius <= 0:
            return

        # 溅射目标数上限 = round(aoe_radius)
        max_splash = round(aoe_radius)

        # 基础攻击力（用于 DamageCap）
        base_atk = attacker.unit.attack_ranged
        damage_cap = base_atk * 2.0

        # 筛选溅射候选：与主目标距离 ≤ aoe_radius 的存活敌方（排除主目标）
        enemies = self._alive(self._enemy_side(attacker.side))
        candidates = []
        for e in enemies:
            if e.id == main_target.id:
                continue
            # 距离判定：与主目标的距离
            dist_to_main = abs(e.pos - main_target.pos)
            if dist_to_main <= aoe_radius:
                candidates.append(e)

        if not candidates:
            return

        # 随机选取溅射目标
        splash_count = min(max_splash, len(candidates))
        splash_targets = self._rng.sample(candidates, splash_count)

        # 溅射伤害均匀分配，但单个目标不超过基础攻击力
        splash_dmg_each = min(damage_cap / splash_count, base_atk)

        logger.debug(
            "tick=%d AOE %s#%d aoe_radius=%d cap=%.1f 溅射%d个目标 每个%.1f",
            self._tick, attacker.name, attacker.id,
            aoe_radius, damage_cap, splash_count, splash_dmg_each,
        )

        for t in splash_targets:
            # 溅射伤害也应用倍率和抗性（根据 damage_type 选护甲）
            if mode == AttackMode.MELEE:
                multipliers = attacker.unit.multipliers_melee
                dtype = attacker.unit.damage_type_melee
                if dtype == "Ranged":
                    armor = t.unit.armor_ranged
                elif dtype == "Siege":
                    armor = t.unit.armor_siege
                else:
                    armor = t.unit.armor_melee
            else:
                multipliers = attacker.unit.multipliers_ranged
                dtype = attacker.unit.damage_type_ranged
                if dtype == "Siege":
                    armor = t.unit.armor_siege
                elif dtype == "Hand":
                    armor = t.unit.armor_melee
                else:
                    armor = t.unit.armor_ranged

            mult = self._calc_multiplier(multipliers, t)
            final_splash = max(1.0, splash_dmg_each * mult * (1.0 - armor))

            self._emit(EventType.AOE_SPLASH, {
                "attacker_id": attacker.id,
                "attacker_name": attacker.name,
                "main_target_id": main_target.id,
                "splash_target_id": t.id,
                "splash_target_name": t.name,
                "splash_damage": round(final_splash, 1),
            })

            self._apply_damage(attacker, t, final_splash, mode, is_splash=True)

    # ---- 死亡清算 ----
    def _process_deaths(self) -> None:
        """清算死亡单位（已在 _apply_damage 中处理，这里做防御性检查）。"""
        for s in self._soldiers:
            if s.hp <= 0 and s.alive:
                s.alive = False
                logger.error(
                    "tick=%d 发现未标记死亡的单位 %s#%d hp=%.1f！",
                    self._tick, s.name, s.id, s.hp,
                )

    # ---- 胜负判定 ----
    def _check_winner(self) -> Side | None:
        """检查是否有一方全灭。"""
        red_alive = len(self._alive(Side.RED))
        blue_alive = len(self._alive(Side.BLUE))
        if red_alive == 0 and blue_alive == 0:
            return None  # 同时全灭 → 平局
        if red_alive == 0:
            return Side.BLUE
        if blue_alive == 0:
            return Side.RED
        return None  # 战斗继续

    def _timeout_winner(self) -> Side | None:
        """超时判胜：单挑模式判平局，押注模式按剩余单位总资源价值。"""
        if self._duel_mode:
            logger.info("超时判胜：单挑模式 → 平局")
            return None
        red_value = sum(
            sum(s.unit.cost.values()) for s in self._alive(Side.RED)
        )
        blue_value = sum(
            sum(s.unit.cost.values()) for s in self._alive(Side.BLUE)
        )
        logger.info(
            "超时判胜：红方剩余价值=%d 蓝方剩余价值=%d",
            red_value, blue_value,
        )
        if red_value > blue_value:
            return Side.RED
        if blue_value > red_value:
            return Side.BLUE
        return None  # 价值相同 → 平局

    # ---- 战况阶段判定 ----
    def _current_phase(self) -> BattlePhase:
        """判定当前战况阶段。"""
        if not self._any_attack_happened:
            return BattlePhase.APPROACHING

        red_alive = self._alive(Side.RED)
        blue_alive = self._alive(Side.BLUE)

        if not red_alive or not blue_alive:
            return BattlePhase.FIGHTING

        red_hp_pct = sum(s.hp for s in red_alive) / sum(
            s.max_hp for s in red_alive
        )
        blue_hp_pct = sum(s.hp for s in blue_alive) / sum(
            s.max_hp for s in blue_alive
        )

        if red_hp_pct < 0.3 and blue_hp_pct < 0.3:
            return BattlePhase.STALEMATE

        return BattlePhase.FIGHTING

    # ---- 主循环 ----
    def run(self) -> BattleResult:
        """执行完整模拟，返回结果。"""
        red_desc = " + ".join(f"{s.unit.name}×{s.count}" for s in self.red_army)
        blue_desc = " + ".join(f"{s.unit.name}×{s.count}" for s in self.blue_army)
        logger.info(
            "=== 战斗开始 === 红方: [%s] (%d个) vs 蓝方: [%s] (%d个) 场地=%d tick间隔=%.1f 最大tick=%d",
            red_desc, self.red_count,
            blue_desc, self.blue_count,
            self.field_length, TICK_INTERVAL, self.max_ticks,
        )

        self._init_soldiers()

        self._emit(EventType.BATTLE_START, {
            "red_army": [{"name": s.unit.name, "count": s.count, "hp": s.unit.hp} for s in self.red_army],
            "blue_army": [{"name": s.unit.name, "count": s.count, "hp": s.unit.hp} for s in self.blue_army],
            "red_count": self.red_count,
            "blue_count": self.blue_count,
            "field_length": self.field_length,
        })

        winner: Side | None = None
        timeout = False

        for tick in range(self.max_ticks):
            self._tick = tick

            # 1. 移动
            self._process_movement()

            # 2. 目标锁定（在攻击前确保所有停下的兵都有目标）
            for s in self._alive():
                self._acquire_target(s)

            # 3. 攻击
            self._process_attacks()

            # 4. 死亡清算
            self._process_deaths()

            # 5. 胜负判定
            winner = self._check_winner()
            if winner is not None or (
                len(self._alive(Side.RED)) == 0
                and len(self._alive(Side.BLUE)) == 0
            ):
                break

        else:
            # 超时
            timeout = True
            winner = self._timeout_winner()

        duration = (self._tick + 1) * TICK_INTERVAL

        self._emit(EventType.BATTLE_END, {
            "winner": winner.value if winner else "draw",
            "duration": round(duration, 1),
            "ticks": self._tick + 1,
            "timeout": timeout,
            "red_alive": len(self._alive(Side.RED)),
            "red_total": self.red_count,
            "blue_alive": len(self._alive(Side.BLUE)),
            "blue_total": self.blue_count,
            "phase": self._current_phase().value,
        })

        logger.info(
            "=== 战斗结束 === 胜方=%s 时长=%.1fs ticks=%d 超时=%s "
            "红方存活=%d/%d 蓝方存活=%d/%d",
            winner.value if winner else "平局",
            duration, self._tick + 1, timeout,
            len(self._alive(Side.RED)), self.red_count,
            len(self._alive(Side.BLUE)), self.blue_count,
        )

        return BattleResult(
            winner=winner,
            events=self._events,
            ticks=self._tick + 1,
            duration=duration,
            red_alive=self._alive(Side.RED),
            blue_alive=self._alive(Side.BLUE),
            red_dead=[s for s in self._soldiers if not s.alive and s.side == Side.RED],
            blue_dead=[s for s in self._soldiers if not s.alive and s.side == Side.BLUE],
            red_army=list(self.red_army),
            blue_army=list(self.blue_army),
            red_count=self.red_count,
            blue_count=self.blue_count,
            timeout=timeout,
        )
