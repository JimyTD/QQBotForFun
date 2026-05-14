"""将 units_aoe_supplement.json 的数据合并回 units.json。

合并内容：
1. main_attack_aoe → 新字段 aoe_radius
2. main_attack_damage_type → 新字段 damage_type_ranged / damage_type_melee / damage_type_siege
3. 更完整的倍率数据（supplement 中的 bonuses 比原始 fandom 爬虫更准确）
4. 完整 attacks 列表保留为 attacks_detail（供斗蛐蛐引擎使用）

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


def _classify_attack(atk: dict) -> str | None:
    """判断一个攻击模式属于 ranged/melee/siege 中的哪一种。"""
    name = atk.get("name", "").lower()
    max_range = atk.get("max_range", 0) or 0
    damage_type = atk.get("damage_type", "")

    # 近战：range <= 2 且 damage_type 为 Hand
    if max_range <= 2 and damage_type == "Hand":
        return "melee"
    # 远程：range > 2
    if max_range > 2:
        return "ranged"
    # 攻城：damage_type 为 Siege 且短距离（如手持臼炮）
    if damage_type == "Siege" and max_range <= 6:
        return "siege"
    if damage_type == "Siege":
        return "ranged"  # 远距离攻城视为远程

    return None


def _pick_best_attack(attacks: list[dict], category: str) -> dict | None:
    """从 attacks 列表中选出指定类别（ranged/melee）的最佳攻击。
    排除特殊模式名称（Defend/Stagger/Volley 是姿态变体，选伤害最高的）。
    """
    candidates = []
    for atk in attacks:
        cls = _classify_attack(atk)
        if cls != category:
            continue
        name = atk.get("name", "").lower()
        # 跳过建筑/砍伐攻击
        if any(kw in name for kw in ["chop", "build", "gather"]):
            continue
        candidates.append(atk)

    if not candidates:
        return None
    # 选伤害最高的
    return max(candidates, key=lambda a: a.get("damage", 0))


def merge() -> dict:
    """执行合并，返回统计信息。"""
    units = json.loads(_UNITS_FILE.read_text(encoding="utf-8"))
    supplement = json.loads(_SUPPLEMENT_FILE.read_text(encoding="utf-8"))
    supp_by_id = {s["unit_id"]: s for s in supplement}

    stats = {"matched": 0, "aoe_added": 0, "dtype_added": 0, "unmatched": 0}

    for u in units:
        uid = u["id"]
        supp = supp_by_id.get(uid)
        if not supp:
            stats["unmatched"] += 1
            continue

        stats["matched"] += 1
        attacks = supp.get("attacks", [])

        # 1. AOE 半径：按攻击方式分别提取
        aoe_ranged = 0
        aoe_melee = 0
        aoe_siege = 0
        for atk in attacks:
            aoe = atk.get("aoe_radius") or 0
            if aoe <= 0:
                continue
            cls = _classify_attack(atk)
            if cls == "ranged":
                aoe_ranged = max(aoe_ranged, aoe)
            elif cls == "melee":
                aoe_melee = max(aoe_melee, aoe)
            elif cls == "siege":
                aoe_siege = max(aoe_siege, aoe)

        if aoe_ranged > 0:
            u["aoe_radius_ranged"] = aoe_ranged
            stats["aoe_added"] += 1
        if aoe_melee > 0:
            u["aoe_radius_melee"] = aoe_melee
            stats["aoe_added"] += 1
        if aoe_siege > 0:
            u["aoe_radius_siege"] = aoe_siege
            stats["aoe_added"] += 1
        # 兼容旧代码：保留 aoe_radius = 所有攻击中最大的
        max_aoe = max(aoe_ranged, aoe_melee, aoe_siege)
        if max_aoe > 0:
            u["aoe_radius"] = max_aoe

        # 2. 伤害类型
        # 远程攻击的伤害类型
        ranged_atk = _pick_best_attack(attacks, "ranged")
        if ranged_atk:
            dtype = ranged_atk.get("damage_type", "")
            if dtype:
                u["damage_type_ranged"] = dtype
                stats["dtype_added"] += 1

        # 近战攻击的伤害类型
        melee_atk = _pick_best_attack(attacks, "melee")
        if melee_atk:
            dtype = melee_atk.get("damage_type", "")
            if dtype:
                u["damage_type_melee"] = dtype

    return stats


def main(dry_run: bool = False) -> None:
    print("=" * 60)
    print("合并 AOE 补充数据到 units.json")
    print("=" * 60)

    stats = merge()

    units = json.loads(_UNITS_FILE.read_text(encoding="utf-8"))
    supplement = json.loads(_SUPPLEMENT_FILE.read_text(encoding="utf-8"))
    supp_by_id = {s["unit_id"]: s for s in supplement}

    # 重新执行合并（上面只是统计）
    for u in units:
        supp = supp_by_id.get(u["id"])
        if not supp:
            continue

        attacks = supp.get("attacks", [])

        # AOE：按攻击方式分别提取
        aoe_ranged = 0
        aoe_melee = 0
        aoe_siege = 0
        for atk in attacks:
            aoe = atk.get("aoe_radius") or 0
            if aoe <= 0:
                continue
            cls = _classify_attack(atk)
            if cls == "ranged":
                aoe_ranged = max(aoe_ranged, aoe)
            elif cls == "melee":
                aoe_melee = max(aoe_melee, aoe)
            elif cls == "siege":
                aoe_siege = max(aoe_siege, aoe)

        if aoe_ranged > 0:
            u["aoe_radius_ranged"] = aoe_ranged
        if aoe_melee > 0:
            u["aoe_radius_melee"] = aoe_melee
        if aoe_siege > 0:
            u["aoe_radius_siege"] = aoe_siege
        max_aoe = max(aoe_ranged, aoe_melee, aoe_siege)
        if max_aoe > 0:
            u["aoe_radius"] = max_aoe

        # 伤害类型
        ranged_atk = _pick_best_attack(attacks, "ranged")
        if ranged_atk and ranged_atk.get("damage_type"):
            u["damage_type_ranged"] = ranged_atk["damage_type"]
        melee_atk = _pick_best_attack(attacks, "melee")
        if melee_atk and melee_atk.get("damage_type"):
            u["damage_type_melee"] = melee_atk["damage_type"]

    print(f"  匹配: {stats['matched']} / {len(units)}")
    print(f"  未匹配: {stats['unmatched']}")
    print(f"  新增 aoe_radius: {stats['aoe_added']}")
    print(f"  新增 damage_type: {stats['dtype_added']}")

    # 预览几个有 AOE 的兵种
    print("\n  预览（AOE 兵种）:")
    aoe_units = [u for u in units if u.get("aoe_radius")]
    for u in sorted(aoe_units, key=lambda x: -(x.get("aoe_radius") or 0))[:10]:
        print(f"    {u['name']:15s} AOE r={u.get('aoe_radius_ranged', 0)} "
              f"m={u.get('aoe_radius_melee', 0)} s={u.get('aoe_radius_siege', 0)} "
              f"(max={u.get('aoe_radius', 0)})")

    if dry_run:
        print("\n  [dry-run] 未写入文件")
    else:
        _UNITS_FILE.write_text(
            json.dumps(units, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n  已写入 {_UNITS_FILE}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(args.dry_run)
