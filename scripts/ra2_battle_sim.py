"""红警2斗蛐蛐 —— 无 GUI 二维模拟 CLI。

用法:
    uv run python scripts/crawler/openra_ra2_export.py
    uv run python scripts/ra2_battle_sim.py --red htnk:3 --blue mtank:3
    uv run python scripts/ra2_battle_sim.py --red mtnk:1:3 --blue e1:2:1
    uv run python scripts/ra2_battle_sim.py --red e1:10 --blue e2:10
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for p in (str(_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from plugins.games.ra2_battle.repo import load_actors  # noqa: E402
from plugins.games.ra2_battle.simulator import (  # noqa: E402
    BattleSimulator,
    EventType,
    Side,
)


def _parse_army(spec: str) -> list[tuple[str, int] | tuple[str, int, int]]:
    army: list[tuple[str, int] | tuple[str, int, int]] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split(":")
        if len(bits) < 2:
            raise ValueError(f"无效阵容 {part}，格式 id:数量 或 id:数量:星级(0/1/3)")
        uid = bits[0].strip()
        cnt = int(bits[1])
        if len(bits) >= 3:
            stars = int(bits[2])
            if stars not in (0, 1, 3):
                raise ValueError(f"星级须为 0/1/3，收到 {stars}")
            army.append((uid, cnt, stars))
        else:
            army.append((uid, cnt))
    return army


def _print_events(result) -> None:
    for ev in result.events:
        p = ev.payload
        if ev.type == EventType.ATTACK:
            print(
                f"[{ev.tick:4d}] 攻击 {p['attacker']} → {p['target']} "
                f"({p['weapon']}) -{p['damage']} HP={p['target_hp']}"
            )
        elif ev.type == EventType.DEATH:
            print(f"[{ev.tick:4d}] 阵亡 {p['actor_id']}")
        elif ev.type == EventType.CRUSH:
            print(f"[{ev.tick:4d}] 碾压 {p['crusher']} → {p['victim']}")
        elif ev.type == EventType.BATTLE_END:
            print(f"\n=== 结束 === 胜方={p['winner']} 时长={p['duration']}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="红警2斗蛐蛐模拟（OpenRA 数据）")
    parser.add_argument("--red", default="htnk:1", help="红方 id:数量,...")
    parser.add_argument("--blue", default="mtank:1", help="蓝方 id:数量,...")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--height", type=int, default=16)
    parser.add_argument("--list", action="store_true", help="列出可斗蛐蛐单位")
    args = parser.parse_args()

    actors = load_actors()
    if args.list:
        for aid in sorted(actors):
            a = actors[aid]
            if a.armaments:
                print(f"{aid:12} {a.name:24} cost={a.cost:5} hp={a.hp:4}")
        return

    red = _parse_army(args.red)
    blue = _parse_army(args.blue)
    sim = BattleSimulator(
        red, blue, width=args.width, height=args.height, seed=args.seed
    )
    result = sim.run()
    print(f"红方存活 {len(result.red_alive)} / 阵亡 {len(result.red_dead)}")
    print(f"蓝方存活 {len(result.blue_alive)} / 阵亡 {len(result.blue_dead)}")
    _print_events(result)


if __name__ == "__main__":
    main()
