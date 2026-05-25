"""Preset 阵容验收：宿敌（惨胜余量）/ 表演赛（战损悬殊）。

用法:
  uv run python scripts/ra2_preset_scan.py                    # 验收候选表
  uv run python scripts/ra2_preset_scan.py --seeds 8
  uv run python scripts/ra2_preset_scan.py --match htnk:15,mtnk:22
  uv run python scripts/ra2_preset_scan.py --sweep htnk:mtnk --red 14:16 --blue 20:24
  uv run python scripts/ra2_preset_scan.py --batch-sweep --merge-existing --write-validated --seeds 6
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from plugins.games.ra2_battle.simulator import BattleSimulator, Side

Army = list[tuple[str, int]]
OUT_PATH = _ROOT / "data" / "ra2" / "lineup_presets.json"

# 宿敌：胜方余量 25–40%，胜方伤亡 ≥55%，败方歼灭 ≥85%
RIVAL_SURV_LO, RIVAL_SURV_HI = 0.25, 0.40
RIVAL_CAS_MIN, RIVAL_WIPE_MIN = 0.55, 0.85

# 表演赛：专克方胜率 ≥85%，被克方歼灭 ≥90%（专克方可有损耗）
SPEC_CTR_MIN, SPEC_WIPE_MIN = 0.85, 0.90

COST = {
    "htnk": 900,
    "mtnk": 700,
    "apoc": 1750,
    "ltnk": 700,
    "ttnk": 1200,
    "sref": 1200,
    "e1": 200,
    "e2": 100,
    "ggi": 200,
    "brute": 500,
    "sub": 1000,
    "dest": 1000,
    "carrier": 2000,
    "sqd": 500,
    "hyd": 900,
    "dlph": 500,
    "mgtk": 1000,
    "boris": 1500,
    "deso": 200,
    "dog": 200,
    "htk": 500,
    "orca": 1200,
}

# (red_id, blue_id, red_counts, blue_counts, id_prefix, title_red, title_blue)
BATCH_SWEEPS: list[tuple[str, str, list[int], list[int], str, str, str]] = [
    ("htnk", "mtnk", [12, 14, 15, 16, 18, 20], [], "rival_tank", "犀牛", "灰熊"),
    ("e1", "e2", [20, 25, 30, 35, 40], [], "rival_inf", "美国大兵", "动员兵"),
    ("ggi", "e1", [15, 18, 20, 22], [20, 24, 28, 32], "rival_inf_ggi", "重装大兵", "美国大兵"),
    ("ltnk", "htnk", [15, 18, 20, 22, 24], [8, 10, 12, 14], "rival_tank_lt", "轻坦", "犀牛"),
    ("sub", "dest", [3, 4, 5, 6, 7, 8], [5, 6, 7, 8, 9, 10], "rival_nav_sub", "潜艇", "驱逐舰"),
    ("ttnk", "htnk", [4, 6, 8, 10], [10, 12, 14, 16], "rival_tank_mag", "磁能", "犀牛"),
    ("sref", "htnk", [3, 4, 5, 6, 8], [10, 12, 14, 16], "rival_tank_prism", "光棱", "犀牛"),
    ("mgtk", "htnk", [4, 6, 8, 10], [8, 10, 12, 14], "rival_tank_phantom", "幻影", "犀牛"),
    ("apoc", "htnk", [1, 2, 3, 4], [6, 8, 10, 12, 14], "rival_tank_apoc", "天启", "犀牛"),
]


@dataclass(frozen=True)
class PresetCase:
    id: str
    kind: str
    title: str
    red: Army
    blue: Army
    counter: Side = Side.RED
    note: str = ""
    weight: int = 10


@dataclass
class SideStats:
    wins: int = 0
    surv: list[float] = field(default_factory=list)
    cas: list[float] = field(default_factory=list)

    def avg_surv(self) -> float | None:
        return sum(self.surv) / len(self.surv) if self.surv else None

    def avg_cas(self) -> float | None:
        return sum(self.cas) / len(self.cas) if self.cas else None


@dataclass
class RunStats:
    seeds: int
    draws: int = 0
    red: SideStats = field(default_factory=SideStats)
    blue: SideStats = field(default_factory=SideStats)
    lose_wipe: list[float] = field(default_factory=list)
    elapsed_s: float = 0.0

    @property
    def resolved(self) -> int:
        return self.seeds - self.draws


def _count(army: Army) -> int:
    return sum(c for _, c in army)


def _scale_cost(red: Army, blue: Army) -> int:
    return sum(COST.get(a, 0) * c for a, c in red) + sum(COST.get(a, 0) * c for a, c in blue)


def _arena_for(units: int) -> tuple[int, int, int]:
    if units >= 50:
        return 18, 9, 4500
    if units >= 30:
        return 20, 10, 6000
    if units >= 18:
        return 18, 9, 7000
    return 16, 8, 8000


def run_case(red: Army, blue: Army, *, seeds: int) -> RunStats:
    units = _count(red) + _count(blue)
    w, h, max_ticks = _arena_for(units)
    st = RunStats(seeds=seeds)
    t0 = time.perf_counter()
    for seed in range(seeds):
        r = BattleSimulator(
            red, blue, seed=seed, max_ticks=max_ticks, width=w, height=h
        ).run()
        if r.winner is None:
            st.draws += 1
            continue
        if r.winner == Side.RED:
            w_start, l_start = _count(red), _count(blue)
            w_alive, w_dead = len(r.red_alive), len(r.red_dead)
            l_dead = len(r.blue_dead)
            side = st.red
        else:
            w_start, l_start = _count(blue), _count(red)
            w_alive, w_dead = len(r.blue_alive), len(r.blue_dead)
            l_dead = len(r.red_dead)
            side = st.blue
        side.wins += 1
        side.surv.append(w_alive / w_start)
        side.cas.append(w_dead / w_start)
        st.lose_wipe.append(l_dead / l_start)
    st.elapsed_s = time.perf_counter() - t0
    return st


def _pct(v: float | None) -> str:
    return f"{v:.0%}" if v is not None else "n/a"


def judge_rival(st: RunStats) -> tuple[str, str]:
    if st.draws / st.seeds >= 0.10:
        return "FAIL", f"平局 {st.draws}/{st.seeds}"
    if st.resolved == 0:
        return "FAIL", "无胜负"
    dom = Side.RED if st.red.wins >= st.blue.wins else Side.BLUE
    w = st.red if dom == Side.RED else st.blue
    surv, cas = w.avg_surv(), w.avg_cas()
    wipe = sum(st.lose_wipe) / len(st.lose_wipe) if st.lose_wipe else 0.0
    if surv is None:
        return "FAIL", "无胜方数据"
    side = "红" if dom == Side.RED else "蓝"
    detail = (
        f"主胜={side} R{st.red.wins}/B{st.blue.wins} "
        f"胜方余量={_pct(surv)} 伤亡={_pct(cas)} 败方歼={_pct(wipe)}"
    )
    if RIVAL_SURV_LO <= surv <= RIVAL_SURV_HI and cas >= RIVAL_CAS_MIN and wipe >= RIVAL_WIPE_MIN:
        return "PASS", detail
    if surv > RIVAL_SURV_HI:
        return "WARN", detail + " （赢太稳）"
    if surv < RIVAL_SURV_LO and cas >= 0.75:
        return "WARN", detail + " （赢太干净）"
    if wipe < RIVAL_WIPE_MIN:
        return "WARN", detail + " （败方未打光）"
    return "WARN", detail


def judge_spectacle(st: RunStats, counter: Side) -> tuple[str, str]:
    if st.draws / st.seeds >= 0.10:
        return "FAIL", f"平局 {st.draws}/{st.seeds}"
    ctr = st.red if counter == Side.RED else st.blue
    ctr_rate = ctr.wins / st.seeds
    surv, cas = ctr.avg_surv(), ctr.avg_cas()
    wipe = sum(st.lose_wipe) / len(st.lose_wipe) if st.lose_wipe else 0.0
    side = "红" if counter == Side.RED else "蓝"
    detail = (
        f"专克={side} 胜率={ctr_rate:.0%} 专克余量={_pct(surv)} "
        f"专克伤亡={_pct(cas)} 被克歼={_pct(wipe)} R{st.red.wins}/B{st.blue.wins}"
    )
    if ctr_rate < 0.50:
        return "FAIL", detail + " （专克反败）"
    if ctr_rate >= SPEC_CTR_MIN and wipe >= SPEC_WIPE_MIN:
        return "PASS", detail
    return "WARN", detail


# ── 候选表：验收通过后再写入 lineup_presets.json ──
CANDIDATES: list[PresetCase] = [
    # 主战（已验证 15v22 PASS）
    PresetCase("rival_tank_main_m", "rival", "苏盟主战", [("htnk", 15)], [("mtnk", 22)]),
    PresetCase("rival_tank_main_l", "rival", "苏盟主战·大会战", [("htnk", 18)], [("mtnk", 26)], note="加灰熊"),
    PresetCase("rival_tank_main_s", "rival", "苏盟主战·遭遇", [("htnk", 12)], [("mtnk", 18)]),
    # 步兵（25v32 / 18v24 已 PASS）
    PresetCase("rival_inf_blob_m", "rival", "步兵海", [("e1", 25)], [("e2", 32)]),
    PresetCase("rival_inf_blob_l", "rival", "步兵大会战", [("e1", 35)], [("e2", 45)]),
    PresetCase("rival_inf_ggi_m", "rival", "重装对射", [("ggi", 18)], [("e1", 24)]),
    PresetCase("rival_inf_brute_m", "rival", "兽人冲阵", [("brute", 6)], [("e1", 35)]),
    # 坦克特殊
    PresetCase("rival_tank_apoc_m", "rival", "钢铁洪峰", [("apoc", 2)], [("htnk", 10)]),
    PresetCase("rival_tank_apoc_l", "rival", "钢铁洪峰·大会战", [("apoc", 3)], [("htnk", 14)]),
    PresetCase("rival_tank_mag_m", "rival", "磁能群", [("ttnk", 6)], [("htnk", 14)]),
    PresetCase("rival_tank_light_m", "rival", "轻坦换命", [("ltnk", 18)], [("htnk", 10)]),
    # 海战
    PresetCase("rival_nav_sub_m", "rival", "水下猎杀", [("sub", 5)], [("dest", 8)]),
    PresetCase("rival_nav_sub_s", "rival", "水下遭遇", [("sub", 3)], [("dest", 5)]),
    PresetCase("rival_nav_carrier_m", "rival", "航母对决", [("carrier", 2)], [("dest", 4)]),
    # 表演赛
    PresetCase("spec_asw_hyd", "spectacle", "海蝎屠海豚", [("hyd", 8)], [("dlph", 20)], Side.RED, weight=12),
    PresetCase("spec_boris_inf", "spectacle", "鲍里斯清场", [("boris", 2)], [("e1", 35)], Side.RED, weight=10),
    PresetCase("spec_dog_inf", "spectacle", "犬治步兵", [("dog", 10)], [("e1", 40)], Side.RED, weight=8),
    PresetCase("spec_deso_inf", "spectacle", "辐射洗地", [("deso", 4)], [("e2", 45)], Side.RED, weight=8),
    # 模拟器未对齐 — 仅标记 SKIP，不入池
    PresetCase(
        "spec_aa_orca_blocked", "spectacle", "防空洗飞机",
        [("htk", 10)], [("orca", 30)], Side.RED,
        note="BLOCKED 模拟器飞机常胜", weight=0,
    ),
]


def parse_army(spec: str) -> Army:
    out: Army = []
    for part in spec.split(","):
        uid, cnt = part.strip().split(":")
        out.append((uid.strip(), int(cnt)))
    return out


def evaluate(case: PresetCase, st: RunStats) -> tuple[str, str]:
    if "BLOCKED" in case.note:
        return "SKIP", case.note
    if case.kind == "spectacle":
        return judge_spectacle(st, case.counter)
    return judge_rival(st)


def case_to_json(case: PresetCase, verdict: str, detail: str) -> dict:
    return {
        "id": case.id,
        "kind": case.kind,
        "title": case.title,
        "red": case.red,
        "blue": case.blue,
        "counter": case.counter.value if case.kind == "spectacle" else None,
        "scale_cost": _scale_cost(case.red, case.blue),
        "units": _count(case.red) + _count(case.blue),
        "weight": case.weight,
        "validation": verdict,
        "validation_detail": detail,
    }


def _blue_counts_for_pair(red_id: str, blue_id: str, hr: int, blue_list: list[int]) -> list[int]:
    if blue_list:
        return blue_list
    # htnk/mtnk, e1/e2：蓝方数量随红方偏移
    if red_id == "htnk" and blue_id == "mtnk":
        return [hr + d for d in (4, 6, 8, 10, 12)]
    if red_id == "e1" and blue_id == "e2":
        return [hr + d for d in (5, 7, 10, 12)]
    return blue_list


def sweep_pair_rival(
    red_id: str,
    blue_id: str,
    red_counts: list[int],
    blue_counts: list[int],
    *,
    id_prefix: str,
    title_red: str,
    title_blue: str,
    seeds: int,
    pass_only: bool = True,
) -> list[PresetCase]:
    found: list[PresetCase] = []
    print(f"\n>>> sweep {red_id} vs {blue_id}  seeds={seeds}", flush=True)
    for hr in red_counts:
        blues = _blue_counts_for_pair(red_id, blue_id, hr, blue_counts)
        for mr in blues:
            if mr <= 0:
                continue
            t0 = time.perf_counter()
            red, blue = [(red_id, hr)], [(blue_id, mr)]
            st = run_case(red, blue, seeds=seeds)
            verdict, detail = judge_rival(st)
            dt = time.perf_counter() - t0
            if pass_only and verdict != "PASS":
                continue
            line = f"  {verdict:4} {red_id}×{hr} vs {blue_id}×{mr}  u={hr+mr}  {dt:.0f}s  {detail}"
            print(line, flush=True)
            if verdict == "PASS":
                pid = f"{id_prefix}_{red_id}{hr}_{blue_id}{mr}"
                found.append(
                    PresetCase(
                        pid,
                        "rival",
                        f"{title_red}×{hr} vs {title_blue}×{mr}",
                        red,
                        blue,
                    )
                )
    print(f"  => {len(found)} PASS", flush=True)
    return found


def batch_sweep_all(seeds: int, *, pass_only: bool = True) -> list[PresetCase]:
    all_found: list[PresetCase] = []
    for red_id, blue_id, rc, bc, prefix, tr, tb in BATCH_SWEEPS:
        all_found.extend(
            sweep_pair_rival(
                red_id, blue_id, rc, bc,
                id_prefix=prefix, title_red=tr, title_blue=tb,
                seeds=seeds, pass_only=pass_only,
            )
        )
    return all_found


def _army_key(red: Army, blue: Army) -> tuple:
    return (tuple(red), tuple(blue))


def merge_presets(existing: list[dict], new_cases: list[PresetCase]) -> list[dict]:
    by_key: dict[tuple, dict] = {}
    for p in existing:
        key = (tuple(tuple(x) for x in p["red"]), tuple(tuple(x) for x in p["blue"]))
        by_key[key] = p
    for case in new_cases:
        key = _army_key(case.red, case.blue)
        row = case_to_json(case, "PASS", "")
        by_key[key] = {
            k: v for k, v in row.items() if k not in ("validation", "validation_detail")
        }
    return list(by_key.values())


def write_validated_file(presets: list[dict], *, seeds: int) -> None:
    payload = {
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "seeds_per_case": seeds,
        "criteria": {
            "rival": "胜方余量25-40%, 伤亡>=55%, 败方歼>=85%",
            "spectacle": "专克胜率>=85%, 被克歼>=90%",
        },
        "presets": presets,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {len(presets)} 条 -> {OUT_PATH}", flush=True)


def sweep_htnk_mtnk(red_lo: int, red_hi: int, blue_lo: int, blue_hi: int, seeds: int) -> None:
    print(f"sweep htnk [{red_lo}-{red_hi}] vs mtnk [{blue_lo}-{blue_hi}] seeds={seeds}", flush=True)
    print(f"{'hr':>3} {'mr':>3} {'R':>3} {'B':>3} {'d':>2} {'surv':>5} {'cas':>5} {'wipe':>5} {'v'}", flush=True)
    for hr in range(red_lo, red_hi + 1):
        for mr in range(blue_lo, blue_hi + 1):
            t0 = time.perf_counter()
            st = run_case([("htnk", hr)], [("mtnk", mr)], seeds=seeds)
            v, _ = judge_rival(st)
            dom = st.red if st.red.wins >= st.blue.wins else st.blue
            surv, cas = dom.avg_surv(), dom.avg_cas()
            wipe = sum(st.lose_wipe) / len(st.lose_wipe) if st.lose_wipe else 0
            print(
                f"{hr:3d} {mr:3d} {st.red.wins:3d} {st.blue.wins:3d} {st.draws:2d} "
                f"{surv:5.2f} {cas:5.2f} {wipe:5.2f} {v:4} ({time.perf_counter()-t0:.0f}s)",
                flush=True,
            )


def main() -> None:
    ap = argparse.ArgumentParser(description="Preset 阵容验收扫描")
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--batch-sweep", action="store_true", help="批量扫 archetype 比例，只输出 PASS")
    ap.add_argument("--merge-existing", action="store_true", help="与 lineup_presets.json 合并去重")
    ap.add_argument("--write-validated", action="store_true", help="将 PASS 项写入 data/ra2/lineup_presets.json")
    ap.add_argument("--match", type=str)
    ap.add_argument("--sweep", choices=["htnk:mtnk"])
    ap.add_argument("--red", type=str, default="14:16")
    ap.add_argument("--blue", type=str, default="20:24")
    ap.add_argument("--kind", choices=["rival", "spectacle"], default="rival")
    args = ap.parse_args()

    if args.batch_sweep:
        print(f"{'='*80}\n批量 sweep  seeds={args.seeds}\n{'='*80}", flush=True)
        found = batch_sweep_all(args.seeds, pass_only=True)
        print(f"\n批量 sweep 新发现 PASS: {len(found)}", flush=True)
        existing: list[dict] = []
        if args.merge_existing and OUT_PATH.is_file():
            existing = json.loads(OUT_PATH.read_text(encoding="utf-8")).get("presets", [])
        merged = merge_presets(existing, found)
        if args.write_validated:
            write_validated_file(merged, seeds=args.seeds)
        else:
            for p in merged:
                r = "+".join(f"{a}×{c}" for a, c in p["red"])
                b = "+".join(f"{a}×{c}" for a, c in p["blue"])
                print(f"  {p['id']:30} {r} vs {b}")
            print(f"合计 {len(merged)} 条（加 --write-validated 写入文件）", flush=True)
        return

    if args.sweep == "htnk:mtnk":
        rl, rh = (int(x) for x in args.red.split(":"))
        bl, bh = (int(x) for x in args.blue.split(":"))
        sweep_htnk_mtnk(rl, rh, bl, bh, args.seeds)
        return

    if args.match:
        parts = args.match.split(",")
        if len(parts) != 2:
            raise SystemExit("--match 格式: red_spec,blue_spec")
        red, blue = parse_army(parts[0]), parse_army(parts[1])
        st = run_case(red, blue, seeds=args.seeds)
        if args.kind == "spectacle":
            v, d = judge_spectacle(st, Side.RED)
        else:
            v, d = judge_rival(st)
        print(f"{v} {d}")
        return

    results: list[dict] = []
    validated: list[dict] = []
    print(f"{'='*80}\n验收候选 preset  seeds={args.seeds}\n{'='*80}", flush=True)
    for case in CANDIDATES:
        st = run_case(case.red, case.blue, seeds=args.seeds)
        verdict, detail = evaluate(case, st)
        row = case_to_json(case, verdict, detail)
        row["elapsed_s"] = round(st.elapsed_s, 1)
        results.append(row)
        if verdict == "PASS":
            validated.append(row)
        red_s = "+".join(f"{a}×{c}" for a, c in case.red)
        blue_s = "+".join(f"{a}×{c}" for a, c in case.blue)
        print(
            f"{verdict:4} {case.id:24} u={row['units']:3d} ${row['scale_cost']:5d} {st.elapsed_s:5.1f}s  "
            f"{red_s} vs {blue_s}  | {detail}",
            flush=True,
        )

    passed = sum(1 for r in results if r["validation"] == "PASS")
    skipped = sum(1 for r in results if r["validation"] == "SKIP")
    print(f"\n合计 PASS {passed}/{len(results)}  SKIP {skipped}", flush=True)

    if args.write_validated and validated:
        payload = {
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "seeds_per_case": args.seeds,
            "criteria": {
                "rival": "胜方余量25-40%, 伤亡>=55%, 败方歼>=85%",
                "spectacle": "专克胜率>=85%, 被克歼>=90%",
            },
            "presets": [
                {k: v for k, v in p.items() if k not in ("validation", "validation_detail", "elapsed_s")}
                for p in validated
            ],
        }
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写入 {len(validated)} 条 PASS -> {OUT_PATH}", flush=True)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
