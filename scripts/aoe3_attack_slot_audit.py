"""AoE3 攻击列表缺失审计 —— 拿不到对兵攻击模式的单位。

背景（`docs/games/aoe3-battle.md` §3.9）：
出生阵型决定攻击列表。若某单位没有任何打得中普通单位的动作，
它在斗蛐蛐里就打不动人。本脚本列出这类单位，并对**新旧快照**做对比，
标记 ``LOST!``（旧有对兵攻击、新无），用于每次游戏数据刷新时判断
「是游戏改了动作」还是「parser 规则误伤」。

用法::

    uv run python scripts/aoe3_attack_slot_audit.py
    uv run python scripts/aoe3_attack_slot_audit.py --old data/aoe3/_prev/seeds/units.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
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
    ap = argparse.ArgumentParser(description="AoE3 attack list audit")
    ap.add_argument("--protoy", default=str(PROTOY))
    ap.add_argument("--units", default=str(UNITS))
    ap.add_argument("--old", default=str(OLD_UNITS), help="上一版快照 units.json（可选，用于标记 LOST!）")
    args = ap.parse_args()

    old = _load(Path(args.old))
    new = _load(Path(args.units))
    if not Path(args.protoy).is_file():
        raise SystemExit(f"protoy not found: {args.protoy}")

    lost = 0
    print("=== 没有对兵攻击模式的单位 ===")
    for uid, u in sorted(new.items()):
        actions = u.get("attack_actions") or []
        usable = [
            a
            for a in actions
            if a.get("hits_soldiers", True) and a.get("damage", 0) > 0 and a.get("range_max", 0) > 0
        ]
        if usable:
            continue
        old_actions = (old.get(uid) or {}).get("attack_actions") or []
        old_usable = [
            a
            for a in old_actions
            if a.get("hits_soldiers", True) and a.get("damage", 0) > 0 and a.get("range_max", 0) > 0
        ]
        mark = "LOST!" if old_usable else ("" if uid in old else "new-unit")
        if mark == "LOST!":
            lost += 1
        names = ", ".join(a["name"] for a in actions) or "（无）"
        print(f"  {uid:32s} {mark:9s} actions={names}")
    print()

    print(f"LOST attack lists: {lost}")


if __name__ == "__main__":
    main()
