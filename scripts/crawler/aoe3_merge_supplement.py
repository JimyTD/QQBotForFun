"""将 units_aoe_supplement.json 的数据合并回 units.json。

合并内容：
1. 攻击分类：从 supplement 的 attacks 数组重新分出 ranged / melee
   - 过滤 "Siege Attack" / "Building" / "Chop" / "Gather"（拆建筑/采集）
   - 剩余攻击按 max_range > 2 → ranged, ≤ 2 → melee
   - 纯攻城兵种（过滤后无任何攻击）兜底提升为 ranged
2. 覆写 attack_ranged/melee, range, rof, damage_type, aoe_radius, multipliers
3. 不再写 attack_siege / range_siege / rof_siege 等独立攻城字段

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

# 被忽略的攻击名关键词（拆建筑 / 采集）
_IGNORE_KEYWORDS = ["building", "chop", "gather"]


def _is_siege_attack_name(name: str) -> bool:
    """判断是否是通用拆建筑攻击（名称完全等于 "Siege Attack"）。"""
    return name.strip().lower() == "siege attack"


def _should_ignore(atk: dict) -> bool:
    """判断一个攻击是否应被忽略（拆建筑 / 采集）。"""
    name = atk.get("name", "").lower()
    if _is_siege_attack_name(name):
        return True
    return any(kw in name for kw in _IGNORE_KEYWORDS)


def _classify_attack(atk: dict) -> str | None:
    """判断一个攻击属于 ranged / melee。

    返回 None 表示应忽略（拆建筑/采集）。
    """
    if _should_ignore(atk):
        return None

    max_range = atk.get("max_range") or 0
    if max_range > 2:
        return "ranged"
    return "melee"


def _pick_best_attack(attacks: list[dict], category: str) -> dict | None:
    """从 attacks 列表中选出指定类别的最佳攻击（伤害最高）。"""
    candidates = []
    for atk in attacks:
        cls = _classify_attack(atk)
        if cls != category:
            continue
        candidates.append(atk)

    if not candidates:
        return None
    # 选伤害最高的
    return max(candidates, key=lambda a: a.get("damage", 0))


def _pick_fallback_ranged(attacks: list[dict]) -> dict | None:
    """兜底：从被忽略的攻击中提升 max_range 最大的那条为 ranged。

    用于纯攻城兵种（如缴获臼炮），所有攻击都是 "Siege Attack" 系列。
    """
    ignored = [atk for atk in attacks if _should_ignore(atk)]
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

        # ---- 分类攻击 ----
        ranged_atk = _pick_best_attack(attacks, "ranged")
        melee_atk = _pick_best_attack(attacks, "melee")
        used_fallback = False

        # 兜底：纯攻城兵种
        if ranged_atk is None and melee_atk is None:
            ranged_atk = _pick_fallback_ranged(attacks)
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

    # 预览代表性兵种
    check_ids = [
        "falconet", "disciple", "captured_mortar", "musketeer",
        "abus_gunner", "grenadier", "hussar",
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
        dtype_r = u.get("damage_type_ranged", "-")
        dtype_m = u.get("damage_type_melee", "-")
        aoe_r = u.get("aoe_radius_ranged", 0)
        print(f"    {u['name']:20s} ranged={atk_r:>5} (rng={rng}, dt={dtype_r}, aoe={aoe_r}) "
              f"melee={atk_m:>5} (dt={dtype_m})")

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
