"""AoE3 具名攻击表 / 非 DPS 技能审计。

用法:
  uv run python scripts/aoe3_named_attack_audit.py
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "crawler"))

from aoe3_gamedata_parser import (  # noqa: E402
    NAMED_MELEE_ATTACK_ORDER,
    NAMED_RANGED_ATTACK_ORDER,
    NON_DPS_RANGED_ATTACKS,
    _is_combat_unit,
    _parse_attacks,
)

PROTOY = ROOT / "data" / "aoe3" / "raw" / "protoy.xml"
UNITS = ROOT / "seeds" / "aoe3" / "units.json"


def main() -> None:
    tree = ET.parse(PROTOY)
    units_json = {u["id"]: u for u in json.loads(UNITS.read_text(encoding="utf-8"))}

    print("NON_DPS_RANGED_ATTACKS (excluded from斗蛐蛐代表动作):")
    for name in sorted(NON_DPS_RANGED_ATTACKS):
        print(f"  - {name}")

    print("\nNAMED_RANGED_ATTACK_ORDER:")
    for name in NAMED_RANGED_ATTACK_ORDER:
        print(f"  - {name}")

    skill_selected = []
    for el in tree.getroot().findall("unit"):
        types = {ut.text.strip() for ut in el.findall("unittype") if ut.text}
        if not _is_combat_unit(el, types):
            continue
        uid = el.get("name", "").lower()
        tactics = el.findtext("tactics", "").strip()
        atk = _parse_attacks(el, tactics, types)
        r = atk.get("ranged", {}).get("name")
        if r in NON_DPS_RANGED_ATTACKS:
            skill_selected.append(uid)

    if skill_selected:
        print("\nERROR: skill still selected as ranged:", skill_selected)
        raise SystemExit(1)

    print("\nOK: no NON_DPS skill selected as ranged rep")
    for uid in ("explorer", "deincawarchief", "mercmanchu"):
        u = units_json[uid]
        print(
            f"  {uid}: ranged={u.get('protoaction_ranged')} "
            f"melee={u.get('protoaction_melee')}"
        )


if __name__ == "__main__":
    main()
