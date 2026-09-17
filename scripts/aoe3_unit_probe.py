"""单位攻击动作探针 —— 列出某单位在 protoy 里的全部 protoaction 与 parser 的选取得分。

用途：核对「代表动作」是否选对。换代表动作意味着整包攻击数据（damage/rof/aoe/倍率/windup）
换了一套，比单纯数值变动严重。当某单位攻击槽为空或发生变化时，用它区分两种原因：

  - 游戏把动作改名了（例如 `MeleeHandAttack` → `ChargeAttack`）
  - parser 的跳过/优先级规则把它剔除了

用法::

    uv run python scripts/aoe3_unit_probe.py musketeer cavalryarcher
    uv run python scripts/aoe3_unit_probe.py --protoy <protoy.xml> <id> <id>...

输出中 `skip` 列非空表示该动作会被 parser 跳过；`ranged` / `melee` 分数越小越优先
（99 = 未命名动作，只能在没有更好候选时兜底）。
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "aoe3_gamedata_parser", ROOT / "scripts" / "crawler" / "aoe3_gamedata_parser.py"
)
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

DEFAULT_PROTOY = ROOT / "data" / "aoe3" / "raw" / "protoy.xml"
SKIP_KEYWORDS = ("Charge", "Trample", "Ability", "AutoGather", "Heal")


def skip_reason(name: str, uid: str) -> str:
    """复现 parser 的跳过判定，返回原因（空串 = 不跳过）。"""
    if name in P.NON_DPS_RANGED_ATTACKS:
        return "NON_DPS 技能"
    if "Build" in name and "Attack" not in name:
        return "非攻击动作"
    for kw in SKIP_KEYWORDS:
        if kw in name:
            if kw == "Trample" and uid in P.TRAMPLE_ONLY_ATTACK_UNITS:
                return ""  # 白名单放行
            return f"含 {kw}"
    return ""


def main() -> None:
    ap = argparse.ArgumentParser(description="AoE3 unit attack-action probe")
    ap.add_argument("units", nargs="+", help="unit id（units.json 里的小写 id）")
    ap.add_argument("--protoy", default=str(DEFAULT_PROTOY))
    args = ap.parse_args()

    tree = ET.parse(args.protoy)
    blocks: dict[str, ET.Element] = {
        (el.get("name") or "").lower(): el for el in tree.getroot().findall("unit")
    }

    for uid in args.units:
        el = blocks.get(uid.lower())
        if el is None:
            print(f"### {uid}: NOT FOUND in protoy")
            continue
        types = {ut.text.strip() for ut in el.findall("unittype") if ut.text}
        print(f"### {uid}  (protoy name={el.get('name')})")
        print(f"    types: {', '.join(sorted(types)[:10])}")
        rows = []
        for action in el.findall("protoaction"):
            name = action.findtext("name", "").strip()
            dmg = action.findtext("damage", "0")
            if float(dmg or 0) <= 0:
                continue
            rows.append(
                (
                    name,
                    dmg,
                    action.findtext("maxrange", "0"),
                    action.findtext("damagetype", ""),
                    action.findtext("rof", ""),
                    action.findtext("damagearea", "0"),
                    action.findtext("damagecap", "0"),
                    P._ranged_attack_priority(name, types),
                    P._melee_hand_priority(name),
                    skip_reason(name, uid),
                )
            )
        for name, dmg, rng, dtype, rof, area, cap, rs, ms, skip in sorted(rows):
            print(
                f"    {name:26s} dmg={float(dmg):<9g} range={rng:<5s} type={dtype:8s} "
                f"rof={rof:<5s} area={area:<4s} cap={cap:<6s} "
                f"| ranged={rs} melee={ms} | skip={skip or '-'}"
            )

        atk = P._parse_attacks(el, el.findtext("tactics", "").strip(), types)
        picked = " | ".join(
            f"{slot}={atk[slot]['name']} (dmg {atk[slot]['damage']:g})"
            for slot in ("ranged", "melee", "siege")
            if atk.get(slot)
        )
        print(f"    => parser 选择: {picked or '（无可用攻击动作）'}")
        print()


if __name__ == "__main__":
    main()
