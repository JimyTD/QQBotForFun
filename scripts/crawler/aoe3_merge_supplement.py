"""将 units_aoe_supplement.json 的数据合并回 units.json。

合并内容：
1. 保留完整 attacks 数组到 units.json（供未来技能扩展）
2. 从 attacks 中选出远程/近战各一个"常规攻击模式"用于斗蛐蛐
   - 排除 Charge / Explosion / Sabotage / Stun / Lasso 等特殊技能
   - 排除 Siege Attack / Building / Chop / Gather（拆建筑/采集）
   - 剩余攻击按 max_range > 2 → ranged, ≤ 2 → melee
   - 优先常规姿态（Volley > Stagger > Defend > Melee/Ranged > 其他）
   - 同等优先级取伤害最高
3. 覆写 attack_ranged/melee, range, rof, damage_type, aoe_radius, multipliers

设计文档：docs/games/aoe3-battle.md §3.9

用法：
    uv run python scripts/crawler/aoe3_merge_supplement.py
    uv run python scripts/crawler/aoe3_merge_supplement.py --dry-run  # 只预览不写入
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

_SEEDS = Path(__file__).resolve().parent.parent.parent / "seeds" / "aoe3"
_UNITS_FILE = _SEEDS / "units.json"
_SUPPLEMENT_FILE = _SEEDS / "units_aoe_supplement.json"

# ── 攻击模式过滤 ──

# 特殊技能关键词（排除，不代表持续战斗行为）
_SPECIAL_KEYWORDS = [
    "charge", "explosion", "explosive", "sabotage", "stun",
    "chaos", "lasso", "death strike", "dynamite", "trample",
]

# 非战斗攻击关键词（排除）
_IGNORE_KEYWORDS = ["building", "chop", "gather", "crate", "ship attack"]

# 掩体攻击前缀（排除，需要掩体才能使用，斗蛐蛐无掩体）
_COVER_PREFIX = "cover "


def _is_siege_attack_name(name: str) -> bool:
    """判断是否是通用拆建筑攻击（名称完全等于 "Siege Attack"）。"""
    return name.strip().lower() == "siege attack"


def _is_special_attack(name: str) -> bool:
    """判断是否为特殊技能攻击（Charge 等一次性技能）。"""
    name_lower = name.lower()
    return any(kw in name_lower for kw in _SPECIAL_KEYWORDS)


def _should_ignore(atk: dict) -> bool:
    """判断一个攻击是否应被完全忽略（拆建筑/采集/特殊技能/掩体攻击）。"""
    name = atk.get("name", "").lower()
    if _is_siege_attack_name(name):
        return True
    if _is_special_attack(atk.get("name", "")):
        return True
    if name.startswith(_COVER_PREFIX):
        return True
    return any(kw in name for kw in _IGNORE_KEYWORDS)


def _classify_attack(atk: dict) -> str | None:
    """按 damage_type + max_range 判断属于 ranged / melee。

    分类规则：
    1. 被 _should_ignore 排除的 → None
    2. damage_type = "Hand" → melee（无论 max_range 多少）
    3. damage_type = "Ranged" 或 "Siege"：
       - max_range > 6 → ranged（真远程攻击）
       - max_range ≤ 6 → melee（近距离攻城类攻击，如草原骑兵攻城 range=6）
    4. damage_type 缺失 → 按 max_range > 6 兜底

    阈值 6 的依据：AOE3 中近战武器最大 range 约 4~6（长矛、流星锤等），
    远程攻击通常 range ≥ 10。6 是安全分界线。
    """
    if _should_ignore(atk):
        return None

    dtype = (atk.get("damage_type") or "").strip()
    max_range = atk.get("max_range") or 0

    if dtype == "Hand":
        return "melee"

    if dtype in ("Ranged", "Siege"):
        return "ranged" if max_range > 6 else "melee"

    # damage_type 缺失 → 按 max_range 兜底
    if max_range > 6:
        return "ranged"
    if max_range > 0:
        return "melee"

    return None


# 常规姿态优先级（越小越优先）
# 注意：Barrage Attack 是臼炮系打兵的常规攻击模式（低伤害+AOE+对兵惩罚倍率），
# 而臼炮的 Cannon Attack 是打建筑模式（高伤害+对墙/船倍率）。
# Barrage 必须优先于 Cannon，否则臼炮会被当成 500 攻击无惩罚轰步兵。
# 对鹰炮等没有 Barrage 的兵种不影响（它们的 Cannon Attack 就是正确的主攻击）。
_STANCE_PRIORITY: dict[str, int] = {
    "volley attack": 0,
    "stagger attack": 1,
    "defend attack": 2,
    "melee attack": 3,
    "ranged attack": 4,
    "stand ground attack": 5,
    "repeating attack": 6,        # 加特林连射模式（rof=0.5，优先于 cannon）
    "barrage attack": 7,          # 臼炮打兵模式（优先于通用 cannon）
    "solid attack": 8,            # 塞瓦斯托波尔臼炮打兵模式
    "cannon attack": 9,           # 通用炮击（鹰炮/长管炮此即主攻击，臼炮则被 barrage 压过）
}


def _attack_sort_key(atk: dict) -> tuple[int, float]:
    """排序键：(姿态优先级, -伤害)。优先级越低越好，同优先级取伤害高的。"""
    name = atk.get("name", "").lower()
    priority = _STANCE_PRIORITY.get(name, 50)  # 未知姿态排最后
    damage = -(atk.get("damage", 0) or 0)  # 负数，伤害越高越前
    return (priority, damage)


def _pick_best_attack(attacks: list[dict], category: str) -> dict | None:
    """从 attacks 列表中选出指定类别的最佳常规攻击。

    优先常规姿态（Volley > Stagger > Defend > Melee/Ranged），
    同姿态取伤害最高。
    """
    candidates = []
    for atk in attacks:
        cls = _classify_attack(atk)
        if cls != category:
            continue
        candidates.append(atk)

    if not candidates:
        return None
    return min(candidates, key=_attack_sort_key)


def _pick_fallback_ranged(attacks: list[dict]) -> dict | None:
    """兜底：从被忽略的攻击中提升 max_range 最大的那条为 ranged。

    用于纯攻城兵种（如缴获臼炮），所有攻击都是 "Siege Attack" 系列。
    """
    ignored = [atk for atk in attacks
               if _is_siege_attack_name(atk.get("name", ""))
               and not _is_special_attack(atk.get("name", ""))]
    if not ignored:
        return None
    return max(ignored, key=lambda a: a.get("max_range", 0) or 0)


def _bonuses_to_multipliers(bonuses: list[dict]) -> list[dict]:
    """将 supplement 的 bonuses 格式转换为 units.json 的 multipliers 格式。"""
    result = []
    for b in bonuses:
        vs = b.get("type", "")
        value = b.get("multiplier", 1.0)
        if vs and value != 1.0:
            result.append({"vs": vs, "value": value})
    return result


def merge() -> dict:
    """执行合并，返回统计信息。"""
    units = json.loads(_UNITS_FILE.read_text(encoding="utf-8"))
    supplement = json.loads(_SUPPLEMENT_FILE.read_text(encoding="utf-8"))
    supp_by_id = {s["unit_id"]: s for s in supplement}

    stats = {
        "matched": 0,
        "unmatched": 0,
        "ranged_set": 0,
        "melee_set": 0,
        "fallback_ranged": 0,
        "aoe_ranged": 0,
        "aoe_melee": 0,
    }

    for u in units:
        uid = u["id"]
        supp = supp_by_id.get(uid)
        if not supp:
            stats["unmatched"] += 1
            continue

        stats["matched"] += 1
        attacks = supp.get("attacks", [])
        if not attacks:
            continue

        # ---- 保留完整 attacks 数组供未来扩展 ----
        u["attacks_all"] = attacks

        # ---- 清理旧的 AOE 字段（防止残留错误数据）----
        for key in ("aoe_radius", "aoe_radius_ranged", "aoe_radius_melee"):
            u.pop(key, None)

        # ---- 清理旧的攻击字段（supplement 会重新写入正确值）----
        # 防止 wiki 原始数据残留错误的 attack_ranged/range
        for key in ("attack_ranged", "range", "range_min", "rof_ranged",
                     "damage_type_ranged", "multipliers_ranged",
                     "attack_melee", "range_melee", "rof_melee",
                     "damage_type_melee", "multipliers_melee"):
            u.pop(key, None)

        # ---- 分类攻击 ----
        # 掩体配对过滤：如果存在 "Cover Ranged Attack"，
        # 说明 "Ranged Attack" 也是掩体限定的（非Cover版是掩体正常伤害）
        has_cover_ranged = any(
            a.get("name", "").lower().startswith("cover ranged")
            for a in attacks
        )

        def _is_cover_paired(atk: dict) -> bool:
            """判断是否为掩体配对的非Cover版远程攻击。"""
            if not has_cover_ranged:
                return False
            name = atk.get("name", "").lower()
            return name == "ranged attack"

        # 过滤掉掩体配对攻击后再分类
        filtered_attacks = [a for a in attacks if not _is_cover_paired(a)]

        ranged_atk = _pick_best_attack(filtered_attacks, "ranged")
        melee_atk = _pick_best_attack(filtered_attacks, "melee")
        used_fallback = False

        # 兜底：纯攻城兵种
        if ranged_atk is None and melee_atk is None:
            ranged_atk = _pick_fallback_ranged(filtered_attacks)
            if ranged_atk:
                used_fallback = True
                stats["fallback_ranged"] += 1

        # ---- 写入 ranged 字段 ----
        if ranged_atk:
            u["attack_ranged"] = ranged_atk.get("damage", 0)
            u["range"] = ranged_atk.get("max_range", 0) or 0
            u["range_min"] = ranged_atk.get("min_range") or 0
            rof = ranged_atk.get("rof", 0) or 0
            if rof > 0:
                u["rof_ranged"] = rof
            dtype = ranged_atk.get("damage_type", "")
            if dtype:
                u["damage_type_ranged"] = dtype
            aoe = ranged_atk.get("aoe_radius") or 0
            if aoe > 0:
                u["aoe_radius_ranged"] = aoe
                stats["aoe_ranged"] += 1
            bonuses = ranged_atk.get("bonuses", [])
            mults = _bonuses_to_multipliers(bonuses)
            if mults:
                u["multipliers_ranged"] = mults
            stats["ranged_set"] += 1

        # ---- 写入 melee 字段 ----
        if melee_atk:
            u["attack_melee"] = melee_atk.get("damage", 0)
            melee_range = melee_atk.get("max_range") or 0
            if melee_range > 0:
                u["range_melee"] = melee_range
            rof = melee_atk.get("rof", 0) or 0
            if rof > 0:
                u["rof_melee"] = rof
            dtype = melee_atk.get("damage_type", "")
            if dtype:
                u["damage_type_melee"] = dtype
            aoe = melee_atk.get("aoe_radius") or 0
            if aoe > 0:
                u["aoe_radius_melee"] = aoe
                stats["aoe_melee"] += 1
            bonuses = melee_atk.get("bonuses", [])
            mults = _bonuses_to_multipliers(bonuses)
            if mults:
                u["multipliers_melee"] = mults
            stats["melee_set"] += 1

        # ---- 兼容旧代码：aoe_radius = 所有攻击中最大 ----
        aoe_r = u.get("aoe_radius_ranged", 0)
        aoe_m = u.get("aoe_radius_melee", 0)
        max_aoe = max(aoe_r, aoe_m)
        if max_aoe > 0:
            u["aoe_radius"] = max_aoe

        # ---- 清理旧的 attack_siege 字段（如果 supplement 覆盖了） ----
        # 不主动删除，保留原始数据作为参考

    # ---- 多弹丸/连射兵种修正 ----
    # supplement 数据只包含单发伤害，但部分兵种每次攻击发射多发弹丸。
    # 这里乘以弹丸数得到每次攻击的总伤害（projectile count 来自 wiki）。
    _PROJECTILE_COUNT: dict[str, int] = {
        "chu_ko_nu_age_of_empires_iii": 3,  # 诸葛弩手：射 3 箭
        "organ_gun_age_of_empires_iii": 8,  # 管风琴炮：射 8 管（DE 2024.10 更新）
        "gatling_camel": 3,                 # 加特林骆驼：burst 3 发
    }
    units_by_id = {u["id"]: u for u in units}
    for uid, count in _PROJECTILE_COUNT.items():
        u = units_by_id.get(uid)
        if u and "attack_ranged" in u:
            u["attack_ranged"] = round(u["attack_ranged"] * count, 1)
            stats.setdefault("projectile_fixed", 0)
            stats["projectile_fixed"] += 1

    # 写回文件
    _UNITS_FILE.write_text(
        json.dumps(units, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return stats, units


def main(dry_run: bool = False) -> None:
    print("=" * 60)
    print("合并 supplement 攻击数据到 units.json")
    print("=" * 60)

    # 先读取原始数据用于 dry-run 对比
    units_orig = json.loads(_UNITS_FILE.read_text(encoding="utf-8"))

    stats, units = merge()

    print(f"\n  匹配: {stats['matched']} / {len(units)}")
    print(f"  未匹配: {stats['unmatched']}")
    print(f"  设置 ranged: {stats['ranged_set']}")
    print(f"  设置 melee: {stats['melee_set']}")
    print(f"  兜底 ranged（纯攻城）: {stats['fallback_ranged']}")
    print(f"  新增 aoe_ranged: {stats['aoe_ranged']}")
    print(f"  新增 aoe_melee: {stats['aoe_melee']}")
    print(f"  多弹丸修正: {stats.get('projectile_fixed', 0)}")

    # 预览代表性兵种
    check_ids = [
        "falconet", "musketeer", "hussar", "grenadier",
        "cree_tracker", "conquistador_age_of_empires_iii",
        "deli", "cuirassier", "bolas_warrior",
        "captured_mortar", "abus_gunner",
        # 多弹丸 / 连射兵种
        "gatling_gun", "gatling_camel",
        "chu_ko_nu_age_of_empires_iii", "organ_gun_age_of_empires_iii",
        # 近战射程验证（cover过滤 + range_melee）
        "pirate_age_of_empires_iii", "winged_hussar_age_of_empires_iii",
        "steppe_rider",
    ]
    units_by_id = {u["id"]: u for u in units}
    print("\n  代表性兵种验证:")
    for uid in check_ids:
        u = units_by_id.get(uid)
        if not u:
            continue
        atk_r = u.get("attack_ranged", 0)
        atk_m = u.get("attack_melee", 0)
        rng = u.get("range", 0)
        rng_m = u.get("range_melee", 0)
        dtype_r = u.get("damage_type_ranged", "-")
        dtype_m = u.get("damage_type_melee", "-")
        aoe_r = u.get("aoe_radius_ranged", 0)
        aoe_m = u.get("aoe_radius_melee", 0)
        print(f"    {u['name']:20s} ranged={atk_r:>5} (rng={rng}, dt={dtype_r}, aoe_r={aoe_r}) "
              f"melee={atk_m:>5} (rng_m={rng_m}, dt={dtype_m}, aoe_m={aoe_m})")

    if dry_run:
        # 还原文件
        _UNITS_FILE.write_text(
            json.dumps(units_orig, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("\n  [dry-run] 已还原文件，未保存更改")
    else:
        print(f"\n  已写入 {_UNITS_FILE}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(args.dry_run)
