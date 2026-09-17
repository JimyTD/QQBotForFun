"""单位数据体检 —— 扫描极端数值单位，供人工判断是否需要干预。

每次数据刷新后跑一次，分组列出值得人工看一眼的单位：
  1. 无远/近攻击槽（斗蛐蛐池会直接剔除）
  2. hp 达阈值
  3. 单次最大攻击达阈值
  4. 高血低攻（肉盾型：打不死也打不动，容易拖到超时按 HP 判胜）
  5. 不占人口 且 在池中

每条附三项上下文，帮助对照既有先例而不是凭空判断：
  - `pool`：是否在押注池里
  - `excluded`：是否已被人工排除（全局排除 / 黑名单）
  - `like`：池中 type 有交集、hp 最接近的几个单位（同型先例）

用法::

    uv run python scripts/aoe3_unit_anomaly_scan.py
    uv run python scripts/aoe3_unit_anomaly_scan.py --only-new        # 只看相对上一版快照新增的单位
    uv run python scripts/aoe3_unit_anomaly_scan.py --hp 800 --atk 80
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.plugins.aoe3.models import Unit  # noqa: E402
from src.plugins.aoe3.repository import is_excluded_unit  # noqa: E402
from src.plugins.games.aoe3_battle import lineup as L  # noqa: E402

UNITS = ROOT / "seeds" / "aoe3" / "units.json"
OLD_CANDIDATES = (
    ROOT / "data" / "aoe3" / "_prev" / "seeds" / "aoe3" / "units.json",
    ROOT / "data" / "aoe3" / "_prev" / "seeds" / "units.json",
)


def _load(path: Path) -> dict[str, Unit]:
    if not path.exists():
        return {}
    return {d["id"]: Unit.from_dict(d) for d in json.loads(path.read_text(encoding="utf-8"))}


class _Repo:
    """满足 lineup 池函数所需的最小接口。"""

    def __init__(self, units: dict[str, Unit]) -> None:
        self.all_units = list(units.values())
        self._by_id = units

    def get_by_id(self, uid: str) -> Unit | None:
        return self._by_id.get(uid)


def main() -> None:
    ap = argparse.ArgumentParser(description="AoE3 unit anomaly scan")
    ap.add_argument("--units", default=str(UNITS))
    ap.add_argument("--old", default=None, help="上一版 units.json（--only-new 时用；默认自动找 _prev）")
    ap.add_argument("--only-new", action="store_true")
    ap.add_argument("--hp", type=float, default=1000.0, help="hp 阈值")
    ap.add_argument("--atk", type=float, default=100.0, help="单次最大攻击阈值")
    ap.add_argument("--tank-hp", type=float, default=400.0, help="肉盾型 hp 阈值")
    ap.add_argument("--tank-atk", type=float, default=12.0, help="肉盾型攻击上限")
    args = ap.parse_args()

    units = _load(Path(args.units))
    if not units:
        raise SystemExit(f"units.json not found: {args.units}")

    old_path = Path(args.old) if args.old else next((p for p in OLD_CANDIDATES if p.exists()), None)
    old = _load(old_path) if old_path else {}
    targets = {i: u for i, u in units.items() if not args.only_new or i not in old}

    pool = {u.id for u in L.get_bet_pool(_Repo(units))}
    pool_units = {u.id: u for u in units.values() if u.id in pool}

    def excluded(u: Unit) -> bool:
        return is_excluded_unit(u) or u.id in L.BLACKLIST or u.id in L.BATTLE_BLACKLIST

    def alike(u: Unit, n: int = 3) -> str:
        cands = [
            p for p in pool_units.values()
            if p.id != u.id and set(p.type) & set(u.type) and abs(p.hp - u.hp) <= max(200.0, u.hp * 0.5)
        ]
        cands.sort(key=lambda p: abs(p.hp - u.hp))
        return ", ".join(f"{p.id}(hp{p.hp}/atk{max(p.attack_ranged, p.attack_melee):g})" for p in cands[:n]) or "-"

    def row(u: Unit) -> str:
        return (
            f"  {u.id:34s} hp={u.hp:<7g} 远={u.attack_ranged:<6g} 近={u.attack_melee:<6g} "
            f"pop={u.pop} cost={u.cost} pool={'Y' if u.id in pool else 'n'} "
            f"excluded={'Y' if excluded(u) else 'n'} like={alike(u)}"
        )

    print(f"单位 {len(units)} 个（{old_path and '对比 ' + str(old_path.name) or '无旧快照'}）")
    print(f"阈值：hp>={args.hp:g} / atk>={args.atk:g} / 肉盾 hp>={args.tank_hp:g} 且 atk<={args.tank_atk:g}")
    print()

    groups = [
        ("无远/近攻击槽", [u for u in targets.values() if not u.has_attack]),
        ("hp 达阈值", [u for u in targets.values() if u.hp >= args.hp]),
        ("攻击达阈值", [u for u in targets.values() if max(u.attack_ranged, u.attack_melee) >= args.atk]),
        (
            "高血低攻（肉盾型）",
            [u for u in targets.values() if u.hp >= args.tank_hp and max(u.attack_ranged, u.attack_melee) <= args.tank_atk],
        ),
        ("不占人口且在池", [u for u in targets.values() if u.pop == 0 and u.id in pool]),
    ]
    for title, items in groups:
        print(f"=== {title}（{len(items)}）===")
        for u in sorted(items, key=lambda x: -x.hp):
            print(row(u))
        print()


if __name__ == "__main__":
    main()
