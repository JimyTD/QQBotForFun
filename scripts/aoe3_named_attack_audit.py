"""AoE3 具名攻击表 / 非 DPS 技能审计。

用法:
  uv run python scripts/aoe3_named_attack_audit.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "crawler"))

from aoe3_gamedata_parser import (  # noqa: E402
    NON_DPS_RANGED_ATTACKS,
)

UNITS = ROOT / "seeds" / "aoe3" / "units.json"


def main() -> None:
    units_json = {u["id"]: u for u in json.loads(UNITS.read_text(encoding="utf-8"))}

    print("NON_DPS_RANGED_ATTACKS (excluded from the attack list):")
    for name in sorted(NON_DPS_RANGED_ATTACKS):
        print(f"  - {name}")

    skill_selected = []
    for uid, u in units_json.items():
        for action in u.get("attack_actions", []):
            if action["name"] in NON_DPS_RANGED_ATTACKS:
                skill_selected.append(uid)
                break

    if skill_selected:
        print("\nERROR: skill still in the attack list:", skill_selected)
        raise SystemExit(1)

    print("\nOK: no NON_DPS skill in the attack list")
    for uid in ("explorer", "deincawarchief", "mercmanchu"):
        u = units_json[uid]
        print(
            f"  {uid}: "
            + ", ".join(a["name"] for a in u.get("attack_actions", []))
        )


if __name__ == "__main__":
    main()
