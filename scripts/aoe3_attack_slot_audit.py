"""AoE3 攻击槽缺失审计 —— 因动作名跳过规则而拿不到代表动作的单位。

背景（`docs/games/aoe3-battle.md` §3.9、`aoe3_gamedata_parser.py :: _parse_attacks`）：
parser 会跳过含 ``Charge`` / ``Trample`` / ``Ability`` / ``AutoGather`` / ``Heal``
关键词的动作，以及 `NON_DPS_RANGED_ATTACKS` 里的英雄技/一次性技能。
若某单位**只有**被跳过的动作，它在斗蛐蛐里就没有对应的 ranged/melee 槽。

本脚本列出这类单位，并对**新旧快照**做对比，标记 ``LOST!``（旧有槽、新无槽），
用于每次游戏数据刷新时判断「是游戏改了动作名」还是「parser 规则误伤」。

用法::

    uv run python scripts/aoe3_attack_slot_audit.py
    uv run python scripts/aoe3_attack_slot_audit.py --old data/aoe3/_prev/seeds/units.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location(
    "aoe3_gamedata_parser", ROOT / "scripts" / "crawler" / "aoe3_gamedata_parser.py"
)
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

PROTOY = ROOT / "data" / "aoe3" / "raw" / "protoy.xml"
UNITS = ROOT / "seeds" / "aoe3" / "units.json"
OLD_UNITS = ROOT / "data" / "aoe3" / "_prev" / "seeds" / "units.json"


def _load(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {d["id"]: d for d in json.loads(path.read_text(encoding="utf-8"))}


def main() -> None:
    ap = argparse.ArgumentParser(description="AoE3 attack slot audit")
    ap.add_argument("--protoy", default=str(PROTOY))
    ap.add_argument("--units", default=str(UNITS))
    ap.add_argument("--old", default=str(OLD_UNITS), help="上一版快照 units.json（可选，用于标记 LOST!）")
    args = ap.parse_args()

    old = _load(Path(args.old))
    new = _load(Path(args.units))
    tree = ET.parse(args.protoy)

    lost = 0
    for slot, kind in (("melee", "hand"), ("ranged", "ranged")):
        print(f"=== {slot} 槽为空，但 protoy 里有相关动作 ===")
        for el in tree.getroot().findall("unit"):
            types = {ut.text.strip() for ut in el.findall("unittype") if ut.text}
            if not P._is_combat_unit(el, types):
                continue
            uid = el.get("name", "").lower()
            if uid not in new:
                continue
            atk = P._parse_attacks(el, el.findtext("tactics", "").strip(), types)
            if atk.get(slot):
                continue

            actions = [
                (
                    a.findtext("name", "").strip(),
                    a.findtext("damage", "0"),
                    a.findtext("damagetype", "").strip(),
                )
                for a in el.findall("protoaction")
                if float(a.findtext("damage", "0") or "0") > 0
            ]
            if kind == "hand":
                cand = [a for a in actions if "Hand" in a[0] or "Charge" in a[0] or "Trample" in a[0]]
            else:
                cand = [a for a in actions if a[2] == "Ranged"]
            if not cand:
                continue

            old_v = old.get(uid, {}).get(f"attack_{slot}")
            new_v = new[uid].get(f"attack_{slot}")
            mark = "LOST!" if (old_v and not new_v) else (""
                   if uid in old else "new-unit")
            if mark == "LOST!":
                lost += 1
            print(f"  {uid:32s} {mark:9s} old={old_v} new={new_v} actions={cand}")
        print()

    print(f"LOST slots: {lost}")


if __name__ == "__main__":
    main()
