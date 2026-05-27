"""斗蛐蛐模拟器 —— 伤害计算单元测试。

验证内容：
1. 倍率标签匹配（_calc_multiplier）
2. 完整伤害公式：base × mult × (1 - armor)
3. 真实兵种克制场景（用 units.json 实际数据）
4. 多倍率叠乘
5. 贴脸惩罚
6. 伤害类型→护甲类型选择
7. 不存在的倍率关系 → mult = 1.0
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 确保能 import
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from plugins.aoe3.models import Multiplier, Unit
from plugins.games.aoe3_battle.simulator import (
    CLOSE_RANGE_PENALTY,
    AttackMode,
    BattleSimulator,
    EventType,
    Side,
    Soldier,
    ArmySlot,
    _combat_slot_stats,
    _create_soldier,
)


# =====================================================================
# 辅助工厂
# =====================================================================

def _make_unit(
    *,
    name: str = "TestUnit",
    unit_type: list[str] | None = None,
    hp: int = 100,
    speed: float = 4.0,
    attack_ranged: float = 0,
    attack_melee: float = 0,
    range_: float = 0,
    rof_ranged: float = 1.5,
    rof_melee: float = 1.5,
    damage_type_ranged: str = "Ranged",
    damage_type_melee: str = "Hand",
    armor_ranged: float = 0.0,
    armor_melee: float = 0.0,
    armor_siege: float = 0.0,
    multipliers_ranged: list[Multiplier] | None = None,
    multipliers_melee: list[Multiplier] | None = None,
    aoe_radius_ranged: int = 0,
    aoe_radius_melee: int = 0,
    damage_cap_ranged: float = 0.0,
    damage_cap_melee: float = 0.0,
) -> Unit:
    """创建测试用 Unit。"""
    return Unit(
        id="test_unit",
        name=name,
        name_en=name,
        type=unit_type or [],
        hp=hp,
        speed=speed,
        attack_ranged=attack_ranged,
        attack_melee=attack_melee,
        range=range_,
        rof_ranged=rof_ranged,
        rof_melee=rof_melee,
        damage_type_ranged=damage_type_ranged,
        damage_type_melee=damage_type_melee,
        armor_ranged=armor_ranged,
        armor_melee=armor_melee,
        armor_siege=armor_siege,
        multipliers_ranged=multipliers_ranged or [],
        multipliers_melee=multipliers_melee or [],
        aoe_radius_ranged=aoe_radius_ranged,
        aoe_radius_melee=aoe_radius_melee,
        damage_cap_ranged=damage_cap_ranged,
        damage_cap_melee=damage_cap_melee,
    )


def _make_soldier(unit: Unit, side: Side = Side.RED, pos: float = 0.0) -> Soldier:
    """创建测试用 Soldier。"""
    return _create_soldier(soldier_id=1, side=side, unit=unit, pos=pos)


def _get_simulator() -> BattleSimulator:
    """创建一个最小模拟器实例（用于调用 _calc_damage 等方法）。"""
    dummy = _make_unit(name="Dummy", hp=100, attack_melee=10)
    sim = BattleSimulator(
        red_army=[(dummy, 1)],
        blue_army=[(dummy, 1)],
    )
    return sim


# =====================================================================
# 1. 倍率标签匹配
# =====================================================================

class TestCalcMultiplier:
    """测试 _calc_multiplier 倍率匹配逻辑。"""

    def setup_method(self):
        self.sim = _get_simulator()

    def test_exact_match(self):
        """精确匹配：vs="Cavalry" 命中 type=["Cavalry"]。"""
        attacker_mults = [Multiplier(vs="Cavalry", value=3.0)]
        target = _make_soldier(
            _make_unit(name="Hussar", unit_type=["Cavalry", "Heavy cavalry"])
        )
        result = self.sim._calc_multiplier(attacker_mults, target)
        assert result == 3.0

    def test_case_insensitive(self):
        """大小写不敏感匹配。"""
        attacker_mults = [Multiplier(vs="Heavy infantry", value=2.0)]
        target = _make_soldier(
            _make_unit(name="Musketeer", unit_type=["Infantry", "Heavy infantry"])
        )
        result = self.sim._calc_multiplier(attacker_mults, target)
        assert result == 2.0

    def test_no_match(self):
        """无匹配 → 返回 1.0。"""
        attacker_mults = [Multiplier(vs="Artillery", value=5.0)]
        target = _make_soldier(
            _make_unit(name="Musketeer", unit_type=["Infantry", "Heavy infantry"])
        )
        result = self.sim._calc_multiplier(attacker_mults, target)
        assert result == 1.0

    def test_multiple_multipliers_stack(self):
        """多倍率叠乘：目标同时是骑兵和重骑兵，两个倍率都命中。"""
        attacker_mults = [
            Multiplier(vs="Cavalry", value=2.0),
            Multiplier(vs="Heavy cavalry", value=1.5),
        ]
        target = _make_soldier(
            _make_unit(name="Cuirassier", unit_type=["Cavalry", "Heavy cavalry"])
        )
        result = self.sim._calc_multiplier(attacker_mults, target)
        assert result == pytest.approx(3.0)  # 2.0 * 1.5

    def test_partial_match(self):
        """部分匹配：只有一个倍率命中。"""
        attacker_mults = [
            Multiplier(vs="Cavalry", value=3.0),
            Multiplier(vs="Ship", value=0.5),
        ]
        target = _make_soldier(
            _make_unit(name="Hussar", unit_type=["Cavalry", "Light ranged cavalry"])
        )
        result = self.sim._calc_multiplier(attacker_mults, target)
        assert result == 3.0

    def test_empty_multipliers(self):
        """空倍率列表 → 1.0。"""
        target = _make_soldier(
            _make_unit(name="Hussar", unit_type=["Cavalry"])
        )
        result = self.sim._calc_multiplier([], target)
        assert result == 1.0

    def test_empty_target_type(self):
        """目标无 type → 1.0。"""
        attacker_mults = [Multiplier(vs="Cavalry", value=3.0)]
        target = _make_soldier(_make_unit(name="Unknown", unit_type=[]))
        result = self.sim._calc_multiplier(attacker_mults, target)
        assert result == 1.0


# =====================================================================
# 2. 完整伤害公式
# =====================================================================

class TestCalcDamage:
    """测试 _calc_damage 完整伤害公式。"""

    def setup_method(self):
        self.sim = _get_simulator()

    def test_melee_basic(self):
        """近战基础伤害：base × (1 - armor_melee)。"""
        attacker = _make_soldier(
            _make_unit(name="Swordsman", attack_melee=20)
        )
        target = _make_soldier(
            _make_unit(name="Target", unit_type=["Infantry"], armor_melee=0.2)
        )
        damage = self.sim._calc_damage(attacker, target, AttackMode.MELEE)
        # 20 * 1.0 * (1 - 0.2) = 16.0
        assert damage == pytest.approx(16.0)

    def test_melee_with_multiplier(self):
        """近战 + 倍率：base × mult × (1 - armor)。"""
        attacker = _make_soldier(
            _make_unit(
                name="Musketeer",
                attack_melee=13,
                multipliers_melee=[Multiplier(vs="Cavalry", value=3.0)],
            )
        )
        target = _make_soldier(
            _make_unit(
                name="Hussar",
                unit_type=["Cavalry", "Heavy cavalry"],
                armor_melee=0.0,
            )
        )
        damage = self.sim._calc_damage(attacker, target, AttackMode.MELEE)
        # 13 * 3.0 * (1 - 0) = 39.0
        assert damage == pytest.approx(39.0)

    def test_ranged_basic(self):
        """远程基础伤害：base × (1 - armor_ranged)。"""
        attacker = _make_soldier(
            _make_unit(name="Archer", attack_ranged=15, range_=12)
        )
        target = _make_soldier(
            _make_unit(name="Target", unit_type=["Infantry"], armor_ranged=0.1)
        )
        damage = self.sim._calc_damage(attacker, target, AttackMode.RANGED)
        # 15 * 1.0 * (1 - 0.1) = 13.5
        assert damage == pytest.approx(13.5)

    def test_ranged_with_multiplier(self):
        """远程 + 倍率。"""
        attacker = _make_soldier(
            _make_unit(
                name="Skirmisher",
                attack_ranged=18,
                range_=20,
                multipliers_ranged=[Multiplier(vs="Heavy infantry", value=2.0)],
            )
        )
        target = _make_soldier(
            _make_unit(
                name="Musketeer",
                unit_type=["Infantry", "Heavy infantry"],
                armor_ranged=0.2,
            )
        )
        damage = self.sim._calc_damage(attacker, target, AttackMode.RANGED)
        # 18 * 2.0 * (1 - 0.2) = 28.8
        assert damage == pytest.approx(28.8)

    def test_ranged_penalized(self):
        """贴脸惩罚：base × mult × (1 - armor) × 0.5。"""
        attacker = _make_soldier(
            _make_unit(name="Archer", attack_ranged=20, range_=12)
        )
        target = _make_soldier(
            _make_unit(name="Target", unit_type=["Infantry"], armor_ranged=0.0)
        )
        damage = self.sim._calc_damage(attacker, target, AttackMode.RANGED_PENALIZED)
        # 20 * 1.0 * 1.0 * 0.5 = 10.0
        assert damage == pytest.approx(10.0)

    def test_minimum_damage(self):
        """最低伤害保底 1.0。"""
        attacker = _make_soldier(
            _make_unit(name="Weak", attack_melee=1)
        )
        target = _make_soldier(
            _make_unit(name="Tank", unit_type=["Infantry"], armor_melee=0.99)
        )
        damage = self.sim._calc_damage(attacker, target, AttackMode.MELEE)
        # 1 * 1.0 * (1 - 0.99) = 0.01 → 保底 1.0
        assert damage == 1.0

    def test_siege_damage_uses_siege_armor(self):
        """攻城伤害类型 → 使用攻城抗性。"""
        attacker = _make_soldier(
            _make_unit(
                name="Cannon",
                attack_ranged=100,
                range_=26,
                damage_type_ranged="Siege",
            )
        )
        target = _make_soldier(
            _make_unit(
                name="Target",
                unit_type=["Infantry"],
                armor_ranged=0.3,
                armor_siege=0.0,
            )
        )
        damage = self.sim._calc_damage(attacker, target, AttackMode.RANGED)
        # 100 * 1.0 * (1 - 0.0) = 100（用 armor_siege=0，不是 armor_ranged=0.3）
        assert damage == pytest.approx(100.0)

    def test_hand_damage_type_ranged_uses_melee_armor(self):
        """远程攻击但 damage_type=Hand → 使用近战抗性。"""
        attacker = _make_soldier(
            _make_unit(
                name="HandRanged",
                attack_ranged=20,
                range_=10,
                damage_type_ranged="Hand",
            )
        )
        target = _make_soldier(
            _make_unit(
                name="Target",
                unit_type=["Infantry"],
                armor_ranged=0.5,
                armor_melee=0.1,
            )
        )
        damage = self.sim._calc_damage(attacker, target, AttackMode.RANGED)
        # 20 * 1.0 * (1 - 0.1) = 18（用 armor_melee=0.1，不是 armor_ranged=0.5）
        assert damage == pytest.approx(18.0)


# =====================================================================
# 3. 真实兵种数据验证（从 units.json 加载）
# =====================================================================

class TestRealUnitDamage:
    """用 units.json 的真实数据验证经典克制场景。"""

    @pytest.fixture(autouse=True)
    def _load_repo(self):
        from plugins.aoe3.repository import UnitRepo
        self.repo = UnitRepo.get()
        self.sim = _get_simulator()

    def _get_unit(self, name: str) -> Unit:
        results = self.repo.search(name, limit=1)
        assert results, f"未找到兵种: {name}"
        return results[0]

    def test_musketeer_melee_vs_cavalry(self):
        """火枪手近战打骑兵 → x3 倍率生效。"""
        musketeer = self.repo.get_by_id("musketeer")
        assert musketeer, "未找到 musketeer"
        hussar = self.repo.get_by_id("hussar")
        assert hussar, "未找到 hussar"

        attacker = _make_soldier(musketeer)
        target = _make_soldier(hussar, side=Side.BLUE)

        damage = self.sim._calc_damage(attacker, target, AttackMode.MELEE)

        # 验证倍率命中
        mult = self.sim._calc_multiplier(musketeer.multipliers_melee, target)
        assert mult >= 3.0, f"火枪手 vs 骑兵倍率应 >=3，实际={mult}"

        # 验证公式：base × num_proj × mult × (1 - armor)
        num_proj = musketeer.num_projectiles_melee
        expected = musketeer.attack_melee * num_proj * mult * (1 - hussar.armor_melee)
        assert damage == pytest.approx(expected)

    def test_skirmisher_vs_heavy_infantry(self):
        """散兵远程打重步兵 → 有克制倍率。"""
        skirm = self.repo.get_by_id("skirmisher")
        assert skirm, "未找到 skirmisher"
        musketeer = self.repo.get_by_id("musketeer")
        assert musketeer, "未找到 musketeer"

        attacker = _make_soldier(skirm)
        target = _make_soldier(musketeer, side=Side.BLUE)

        # 散兵应有对重步兵的倍率
        mult = self.sim._calc_multiplier(skirm.multipliers_ranged, target)
        assert mult > 1.0, f"散兵 vs 重步兵倍率应 >1，实际={mult}"

        damage = self.sim._calc_damage(attacker, target, AttackMode.RANGED)
        num_proj = skirm.num_projectiles_ranged
        expected = skirm.attack_ranged * num_proj * mult * (1 - musketeer.armor_ranged)
        assert damage == pytest.approx(expected)

    def test_counter_dragoon_vs_cavalry(self):
        """反龙骑兵远程打重骑兵 → 有克制倍率。"""
        dragoon = self.repo.get_by_id("dragoon")
        assert dragoon, "未找到 dragoon"
        hussar = self.repo.get_by_id("hussar")
        assert hussar, "未找到 hussar"

        attacker = _make_soldier(dragoon)
        target = _make_soldier(hussar, side=Side.BLUE)

        # 反龙骑兵有对骑兵的倍率
        mult = self.sim._calc_multiplier(dragoon.multipliers_ranged, target)
        assert mult > 1.0, f"反龙骑兵 vs 轻骑兵倍率应 >1，实际={mult}"

        damage = self.sim._calc_damage(attacker, target, AttackMode.RANGED)
        num_proj = dragoon.num_projectiles_ranged
        expected = dragoon.attack_ranged * num_proj * mult * (1 - hussar.armor_ranged)
        assert damage == pytest.approx(expected)

    def test_no_counter_relation(self):
        """无克制关系时倍率 = 1.0。"""
        musketeer = self.repo.get_by_id("musketeer")
        assert musketeer, "未找到 musketeer"
        # 火枪手 vs 火枪手（同类型）—— 火枪手没有对重步兵的远程倍率
        attacker = _make_soldier(musketeer)
        target = _make_soldier(musketeer, side=Side.BLUE)

        mult = self.sim._calc_multiplier(musketeer.multipliers_ranged, target)
        # 火枪手远程没有对重步兵倍率（只有近战有对骑兵和轻步兵）
        assert mult == 1.0

    def test_falconet_vs_infantry(self):
        """鹰炮打步兵 → 攻城伤害用攻城抗性（通常为 0）。"""
        falconet = self.repo.get_by_id("falconet")
        assert falconet, "未找到 falconet"
        musketeer = self.repo.get_by_id("musketeer")
        assert musketeer, "未找到 musketeer"

        attacker = _make_soldier(falconet)
        target = _make_soldier(musketeer, side=Side.BLUE)

        damage = self.sim._calc_damage(attacker, target, AttackMode.RANGED)

        # 鹰炮 damage_type_ranged = Siege → 用 armor_siege
        mult = self.sim._calc_multiplier(falconet.multipliers_ranged, target)
        num_proj = falconet.num_projectiles_ranged
        expected = falconet.attack_ranged * num_proj * mult * (1 - musketeer.armor_siege)
        assert damage == pytest.approx(expected)
        # 步兵攻城抗性通常为 0，所以伤害 = base × mult
        assert musketeer.armor_siege == 0.0

    def test_abus_gunner_vs_iron_troop_bypasses_ranged_resist(self):
        """奥斯曼枪手(Siege)打铁军 → 无视 60% 远程抗性，用 armor_siege=0。"""
        abus = self.repo.get_by_id("abusgun")
        iron = self.repo.get_by_id("ypmercirontroop")
        assert abus and iron

        assert abus.damage_type_ranged == "Siege"
        assert iron.armor_ranged == pytest.approx(0.6)
        assert iron.armor_siege == 0.0

        attacker = _make_soldier(abus)
        target = _make_soldier(iron, side=Side.BLUE)

        damage = self.sim._calc_damage(attacker, target, AttackMode.RANGED)
        mult = self.sim._calc_multiplier(abus.multipliers_ranged, target)
        expected = abus.attack_ranged * abus.num_projectiles_ranged * mult * (
            1 - iron.armor_siege
        )
        assert damage == pytest.approx(expected)
        assert damage == pytest.approx(36.0)

        # 若错误地使用远程抗性，伤害会被严重低估
        wrong = abus.attack_ranged * mult * (1 - iron.armor_ranged)
        assert wrong == pytest.approx(14.4)
        assert damage != pytest.approx(wrong)

    def test_iron_troop_vs_abus_gunner_uses_ranged_resist(self):
        """反向：铁军(Ranged)打枪手 → 正常吃 20% 远程抗性。"""
        abus = self.repo.get_by_id("abusgun")
        iron = self.repo.get_by_id("ypmercirontroop")
        assert abus and iron

        attacker = _make_soldier(iron)
        target = _make_soldier(abus, side=Side.RED)

        damage = self.sim._calc_damage(attacker, target, AttackMode.RANGED)
        mult = self.sim._calc_multiplier(iron.multipliers_ranged, target)
        expected = iron.attack_ranged * iron.num_projectiles_ranged * mult * (
            1 - abus.armor_ranged
        )
        assert damage == pytest.approx(expected)
        assert damage == pytest.approx(20.0)

    def test_abus_vs_iron_battle_applies_full_siege_damage(self):
        """整局模拟：枪手每一发远程命中铁军均为 36（非 14.4）。"""
        from plugins.aoe3.repository import UnitRepo

        repo = UnitRepo.get()
        abus = repo.get_by_id("abusgun")
        iron = repo.get_by_id("ypmercirontroop")
        assert abus and iron

        result = BattleSimulator(abus, 1, iron, 1, seed=0).run()
        abus_hits = [
            ev.data["damage"]
            for ev in result.events
            if ev.event_type == EventType.ATTACK
            and ev.data.get("attacker_name") == abus.name
            and ev.data.get("damage_type") == "Siege"
        ]
        assert abus_hits, "应有枪手 Siege 远程命中记录"
        assert all(d == pytest.approx(36.0) for d in abus_hits)


# =====================================================================
# 4. 倍率数据完整性验证
# =====================================================================

class TestMultiplierDataIntegrity:
    """验证 units.json 中的倍率标签都能被模拟器正确匹配。"""

    @pytest.fixture(autouse=True)
    def _load_repo(self):
        from plugins.aoe3.repository import UnitRepo
        self.repo = UnitRepo.get()

    def test_no_bare_abstract_in_multipliers(self):
        """multipliers 中裸 'Abstract' 标签会失效（精确匹配不到），统计数量。

        注：游戏源数据(protoy.xml)中确实存在 type='Abstract' 的 damagebonus，
        这是引擎特性而非坏数据。在我们的精确匹配模型中它们不生效，但不应断言
        它们不存在。此处仅做统计记录。
        """
        bare_count = 0
        for unit in self.repo.all_units:
            for m in unit.multipliers_ranged + unit.multipliers_melee:
                if m.vs == "Abstract":
                    bare_count += 1
        # 仅确认数量不超出预期（当前 1 个：derevvaquero）
        assert bare_count <= 5, (
            f"裸 'Abstract' 标签数量异常多: {bare_count}，可能是解析错误"
        )

    def test_common_counters_have_matching_types(self):
        """常见克制倍率的 vs 标签必须在某些兵种的 type 中存在。"""
        # 收集所有 unit.type 标签
        all_types: set[str] = set()
        for unit in self.repo.all_units:
            for t in unit.type:
                all_types.add(t)

        # 这些是战斗中最重要的克制标签，必须能匹配到
        must_match = [
            "AbstractCavalry", "AbstractHeavyCavalry", "AbstractHeavyInfantry",
            "AbstractLightInfantry", "AbstractInfantry", "AbstractArtillery",
            "AbstractCoyoteMan", "AbstractRangedShockInfantry",
            "AbstractSiegeTrooper",
        ]
        for label in must_match:
            assert label in all_types, (
                f"倍率标签 '{label}' 在所有兵种的 type 中找不到匹配！"
            )

    def test_multiplier_vs_labels_are_matchable(self):
        """所有实际使用的 vs 标签中，战斗相关的应该在 type 池中可匹配。"""
        # 收集所有 type
        all_types: set[str] = set()
        for unit in self.repo.all_units:
            for t in unit.type:
                all_types.add(t)

        # 非战斗标签（对建筑/动物等的倍率，斗蛐蛐中不参与战斗）
        non_combat = {
            "Building", "AbstractWall", "AbstractDock", "Ship",
            "AbstractVillager", "Guardian", "Huntable", "Herdable",
            "Llama", "AbstractPet", "Hero", "AbstractResourceEnclosure",
            "LogicalTypeLandEconomy", "LogicalTypeLandMilitary",
            "Abstract",  # 坏数据残留
            "TradingPost", "SPCFountainOfYouth",
        }

        # 特定兵种专属倍率（不在通用 type 池中，只对特定 unit 生效）
        specific_unit_vs = {
            "xpArrowKnight", "xpLakotaWarchief", "deIncaWarChief",
            "deMalteseGun", "deMercGatlingCamel", "deREVGranadero",
            "xpRifleRider",
        }

        # 收集所有 vs 标签
        unmatched: list[tuple[str, str]] = []
        for unit in self.repo.all_units:
            for m in unit.multipliers_ranged + unit.multipliers_melee:
                if m.vs in non_combat:
                    continue
                if m.vs in specific_unit_vs:
                    continue
                if m.vs not in all_types:
                    unmatched.append((unit.name, m.vs))

        assert not unmatched, (
            f"以下倍率标签无法匹配任何兵种 type（计算将失效）:\n"
            + "\n".join(f"  {name}: vs='{vs}'" for name, vs in unmatched[:20])
        )


# =====================================================================
# AOE DamageCap（protoy damagecap + 2× fallback）
# =====================================================================

class TestAoeDamageCap:
    """验证溅射：同槽 proto damage_cap 优先；缺字段时 2× 合并基础攻 fallback。"""

    def _splash_raw_damages(self, sim: BattleSimulator) -> list[float]:
        return [
            e.data["splash_damage"]
            for e in sim._events
            if e.event_type == EventType.AOE_SPLASH
        ]

    def test_proto_cap_mortar_splash_pool(self):
        """迫击炮 Barrage：cap=90（非 2×30=60），溅 3 人时每人 30。"""
        mortar = _make_unit(
            name="Mortar",
            attack_ranged=30.0,
            range_=30.0,
            damage_type_ranged="Siege",
            aoe_radius_ranged=4,
            damage_cap_ranged=90.0,
        )
        musk = _make_unit(name="Musk", hp=5000, armor_ranged=0.0)
        sim = BattleSimulator(
            red_unit=mortar, red_count=1,
            blue_unit=musk, blue_count=4,
            seed=0,
        )
        sim._init_soldiers()
        sim._rebuild_sorted_cache()
        red = next(s for s in sim._soldiers if s.side == Side.RED)
        blues = [s for s in sim._soldiers if s.side == Side.BLUE]
        slot = _combat_slot_stats(red.unit, AttackMode.RANGED)
        sim._process_aoe(red, blues[0], AttackMode.RANGED, slot_stats=slot)
        splashes = self._splash_raw_damages(sim)
        assert len(splashes) == 3
        assert all(d == pytest.approx(30.0) for d in splashes)

    def test_fallback_2x_when_cap_missing(self):
        """无 damage_cap 字段时 fallback 合并基础攻 × 2。"""
        cannon = _make_unit(
            name="Cannon",
            attack_ranged=10.0,
            range_=20.0,
            aoe_radius_ranged=2,
            damage_cap_ranged=0.0,
        )
        target = _make_unit(name="Target", hp=5000)
        sim = BattleSimulator(
            red_unit=cannon, red_count=1,
            blue_unit=target, blue_count=2,
            seed=0,
        )
        sim._init_soldiers()
        sim._rebuild_sorted_cache()
        red = next(s for s in sim._soldiers if s.side == Side.RED)
        blue = next(s for s in sim._soldiers if s.side == Side.BLUE)
        slot = _combat_slot_stats(red.unit, AttackMode.RANGED)
        sim._process_aoe(red, blue, AttackMode.RANGED, slot_stats=slot)
        splashes = self._splash_raw_damages(sim)
        # 无 proto cap → fallback 池=20；范围内 1 人 → min(20/1, base10)=10
        assert splashes == [pytest.approx(10.0)]

    def test_mortar_in_seeds_has_proto_cap(self):
        """数据管线：seeds 迫击炮含 damage_cap_ranged=90。"""
        from plugins.aoe3.repository import UnitRepo

        mortar = UnitRepo.get().get_by_id("mortar")
        assert mortar is not None
        assert mortar.damage_cap_ranged == pytest.approx(90.0)
        assert mortar.aoe_radius_ranged == 4
