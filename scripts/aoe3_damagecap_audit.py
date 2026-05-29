"""AoE3 溅射 damagecap 审计：变更清单 + basedamagecap 调研。

用法:
  uv run python scripts/aoe3_damagecap_audit.py
  uv run python scripts/aoe3_damagecap_audit.py --write docs/aoe3-damagecap-audit.md
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

UNITS_PATH = ROOT / "seeds" / "aoe3" / "units.json"
PROTOY_PATH = ROOT / "data" / "aoe3" / "raw" / "protoy.xml"
if not PROTOY_PATH.is_file():
    PROTOY_PATH = Path(__import__("os").environ.get("AOE3_EXTRACTED_DIR", r"E:\aoe3_extracted")) / "protoy.xml"


def _slot_cap_old_new(u: dict, slot: str) -> dict | None:
    if slot == "ranged":
        aoe = u.get("aoe_radius_ranged") or 0
        if aoe <= 0:
            return None
        dmg = u.get("attack_ranged") or 0
        np = u.get("num_projectiles_ranged", 1)
        proto = u.get("damage_cap_ranged") or 0
        name = u.get("name") or u.get("name_en")
    else:
        aoe = u.get("aoe_radius_melee") or 0
        if aoe <= 0:
            return None
        dmg = u.get("attack_melee") or 0
        np = u.get("num_projectiles_melee", 1)
        proto = u.get("damage_cap_melee") or 0
        name = u.get("name") or u.get("name_en")

    base = dmg * np
    old_cap = base * 2
    new_cap = proto if proto > 0 else old_cap
    n = round(aoe)
    old_each = min(old_cap / n, base) if n > 0 else 0
    new_each = min(new_cap / n, base) if n > 0 else 0
    return {
        "id": u["id"],
        "name": name,
        "slot": slot,
        "damage": dmg,
        "projectiles": np,
        "aoe_radius": aoe,
        "max_splash_targets": n,
        "old_cap": old_cap,
        "new_cap": new_cap,
        "cap_delta": new_cap - old_cap,
        "old_splash_each_max": round(old_each, 2),
        "new_splash_each_max": round(new_each, 2),
        "splash_each_delta": round(new_each - old_each, 2),
        "has_proto_cap": proto > 0,
        "proto_differs_from_2x": proto > 0 and abs(proto - old_cap) > 0.5,
    }


def audit_cap_changes(units: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for u in units:
        for slot in ("ranged", "melee"):
            row = _slot_cap_old_new(u, slot)
            if row and row["proto_differs_from_2x"]:
                rows.append(row)
    rows.sort(key=lambda r: (-abs(r["cap_delta"]), r["id"], r["slot"]))
    return rows


def audit_basedamagecap(protoy: Path) -> dict:
    stats = {
        "aoe_actions": 0,
        "with_damagecap": 0,
        "with_basedamagecap": 0,
        "basedamagecap_values": {},
        "aoe_area_no_cap": 0,
        "samples_bdcap_not_1": [],
    }
    tree = ET.parse(protoy)
    for el in tree.getroot().iter("unit"):
        uid = el.get("name", "")
        for a in el.findall("protoaction"):
            area = float(a.findtext("damagearea") or 0)
            if area <= 0:
                continue
            stats["aoe_actions"] += 1
            cap = float(a.findtext("damagecap") or 0)
            bdc = a.findtext("basedamagecap")
            if cap > 0:
                stats["with_damagecap"] += 1
            else:
                stats["aoe_area_no_cap"] += 1
            if bdc is not None and bdc.strip() != "":
                stats["with_basedamagecap"] += 1
                key = bdc.strip()
                stats["basedamagecap_values"][key] = stats["basedamagecap_values"].get(key, 0) + 1
                if key != "1" and len(stats["samples_bdcap_not_1"]) < 12:
                    stats["samples_bdcap_not_1"].append(
                        (uid, a.findtext("name"), float(a.findtext("damage") or 0), area, cap, key)
                    )
    return stats


def format_report(changed: list[dict], bdc: dict, units: list[dict]) -> str:
    aoe_units = sum(
        1
        for u in units
        if (u.get("aoe_radius_ranged") or 0) > 0 or (u.get("aoe_radius_melee") or 0) > 0
    )
    unchanged = aoe_units - len({(r["id"], r["slot"]) for r in changed})
    # units with aoe but no proto cap field still use 2x — count separately
    aoe_no_proto = 0
    for u in units:
        for slot in ("ranged", "melee"):
            row = _slot_cap_old_new(u, slot)
            if row and not row["has_proto_cap"]:
                aoe_no_proto += 1

    lines = [
        "# AoE3 damagecap 审计报告",
        "",
        "## 1. 本次修改后溅射池变化的单位",
        "",
        f"- seeds 中带 AOE 的条目（ranged/melee 槽）约 **{aoe_units}** 条",
        f"- **溅射池与旧模拟器（一律 2×合并基础攻）不同**的槽位：**{len(changed)}** 条",
        f"- 有 AOE 但 JSON 无 `damage_cap_*`、仍走 2× fallback 的槽位：**{aoe_no_proto}** 条",
        "",
        "旧模拟器：`damage_cap = 合并基础攻 × 2`。",
        "新模拟器：有 `damage_cap_*` 用 protoy；否则仍 2× fallback。",
        "",
        "下表「满溅射每人伤害」按 `min(cap / round(aoe_radius), 合并基础攻)` 在满人数溅射时的上限估算。",
        "",
        "| id | 中文名 | 槽 | 伤害×弹丸 | aoe | 旧cap | 新cap | Δcap | 旧溅射/人 | 新溅射/人 | Δ |",
        "|----|--------|-----|-----------|-----|-------|-------|------|-----------|-----------|---|",
    ]
    for r in changed:
        lines.append(
            f"| {r['id']} | {r['name']} | {r['slot']} | {r['damage']}×{r['projectiles']} "
            f"| {r['aoe_radius']} | {r['old_cap']:.0f} | {r['new_cap']:.0f} | {r['cap_delta']:+.0f} "
            f"| {r['old_splash_each_max']} | {r['new_splash_each_max']} | {r['splash_each_delta']:+.1f} |"
        )

    lines.extend([
        "",
        "## 2. basedamagecap 调研（protoy.xml）",
        "",
        f"- 含 `damagearea` 的 protoaction：**{bdc['aoe_actions']}**",
        f"- 同时有 `damagecap`：**{bdc['with_damagecap']}**",
        f"- 有 `damagearea` 但无 `damagecap`：**{bdc['aoe_area_no_cap']}**（斗蛐蛐用 2× fallback）",
        f"- 含 `basedamagecap` 子节点：**{bdc['with_basedamagecap']}**",
        f"- `basedamagecap` 取值分布：`{bdc['basedamagecap_values']}`",
        "",
        "### 含义（结合 techtreey `subtype=\"DamageCap\"` + `relativity=\"BasePercent\"`）",
        "",
        "- `basedamagecap` **不是**「溅射池 = 1×攻击力」的意思。",
        "- 多为 `1`，表示该动作的 DamageCap 会随科技/升级按**基础值百分比**缩放（与 `damage` 升级方式同类）。",
        "- 斗蛐蛐当前**不模拟**科技升级，单局内 cap 用 protoy 静态 `damagecap` 即可。",
        "",
        "### 是否把 fallback 从 2× 改成 1×？",
        "",
        "**不建议。** 理由：",
        "",
        "1. `basedamagecap=1` 是升级缩放标记，不是 fallback 倍数。",
        "2. 无 `damagecap` 的 AOE 动作在数据里很少；有 cap 时绝大多数 `damagecap ≈ 2×damage`（与社区一致）。",
        "3. 改成 1× 会使「无 cap 字段」的少数单位溅射减半，与 DE 常见 2× 默认不符。",
        "",
    ])
    if bdc["samples_bdcap_not_1"]:
        lines.append("### basedamagecap ≠ 1 的样本")
        lines.append("")
        for row in bdc["samples_bdcap_not_1"]:
            lines.append(f"- `{row[0]}` / `{row[1]}`: damage={row[2]}, area={row[3]}, cap={row[4]}, basedamagecap={row[5]}")
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", type=Path, help="写入 markdown 报告路径")
    args = parser.parse_args()

    units = json.loads(UNITS_PATH.read_text(encoding="utf-8"))
    changed = audit_cap_changes(units)
    bdc = audit_basedamagecap(PROTOY_PATH)
    report = format_report(changed, bdc, units)
    print(report)
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(report, encoding="utf-8")
        print(f"Wrote {args.write}", file=sys.stderr)


if __name__ == "__main__":
    main()
