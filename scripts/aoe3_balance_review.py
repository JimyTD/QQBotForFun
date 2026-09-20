"""AoE3 单位平衡变更量化分析（辅助审查，不输出官方强度结论）。

与 ``aoe3_seed_diff.py`` 的分工：

- ``aoe3_seed_diff.py``：回答「**改了什么**」——逐字段列出 old → new 的差异清单。
- 本脚本：把字段差异换算成可供人工复核的信号，并明确标出公式盲区：

  1. **辅助公式分**（复用 ``lineup.power_score``，仅供配兵与排序参考，
     不是官方强度评分，也不能覆盖倍率 / 射程 / 抬手 / 攻击槽等机制）；
  2. **ln 空间归因分解**：把战力分变化拆成 HP / 单击伤害 / AOE / 射速 四类来源，
     说明「变强是因为血量还是因为输出」；
  3. **模拟器镜像对战**：新版 N 个 vs 旧版 N 个（双向交换红蓝消除阵营偏差），
     给出实证胜率，用来交叉验证静态公式的判断。

产物：一份 JSON（默认写到被 gitignore 的 data/aoe3/ 中间目录，供分析消费）。

用法：
    uv run python scripts/aoe3_balance_review.py
    uv run python scripts/aoe3_balance_review.py --old-rev b6c8f08^ --out data/aoe3/balance_review.json
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import math
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

logging.disable(logging.CRITICAL)

from plugins.aoe3.models import Unit  # noqa: E402
from plugins.games.aoe3_battle.lineup import power_score  # noqa: E402
from plugins.games.aoe3_battle.simulator import BattleSimulator, Side  # noqa: E402

# 数据刷新前的 seeds 快照（2026-05-29 快照派生，见 docs/aoe3-data-refresh-20260917.md）
DEFAULT_OLD_REV = "b6c8f08^"

# 参照陪练单位：覆盖「重步兵 / 重骑兵 / 远程轻步兵 / 炮兵」四类，
# 用第三人称对手测胜率，避免镜像战的对称抖动。
REF_UNITS = ["musketeer", "hussar", "crossbowman", "falconet"]

# 静态战力公式覆盖不到的字段（power_score 只看 hp / armor / atk / rof / aoe / 弹丸数）
FORMULA_BLIND = {
    "windups", "windup_ranged", "windup_melee",
    "range", "range_min", "range_melee", "range_siege",
    "multipliers", "damage_type_ranged", "damage_type_melee",
    "protoaction_ranged", "protoaction_melee", "protoaction_siege",
    "damage_cap_ranged", "damage_cap_melee",
    # type 标签决定倍率匹配（对手的 "+AbstractHandCavalry ×2" 之类），
    # 增减标签会静默改变克制关系，公式完全看不到。
    "type",
    # 公式只取 max(近战护甲, 远程护甲)；攻城护甲只在被 Siege 伤害打时生效。
    "armor_siege",
}

# ---------------------------------------------------------------------
# 字段分组
# ---------------------------------------------------------------------
# 影响模拟器行为的字段（改动会真实改变战斗表现）
COMBAT_FIELDS = {
    "hp",
    "attack_ranged", "attack_melee", "attack_siege",
    "rof_ranged", "rof_melee", "rof_siege",
    "range", "range_min", "range_melee", "range_siege",
    "armor_melee", "armor_ranged", "armor_siege",
    "aoe_radius", "aoe_radius_ranged", "aoe_radius_melee", "aoe_radius_siege",
    "damage_cap_ranged", "damage_cap_melee",
    "damage_type_ranged", "damage_type_melee",
    "num_projectiles_ranged", "num_projectiles_melee",
    "multipliers", "windups", "windup_ranged", "windup_melee",
    "protoaction_ranged", "protoaction_melee", "protoaction_siege",
}
# 成本侧（同样影响"值不值"）
ECON_FIELDS = {"cost", "pop", "train_time"}
# 纯文本
TEXT_FIELDS = {"name", "name_en", "description", "description_en"}

CN_FIELD = {
    "hp": "生命值",
    "attack_ranged": "远程攻击",
    "attack_melee": "近战攻击",
    "attack_siege": "攻城攻击",
    "rof_ranged": "远程射速(ROF)",
    "rof_melee": "近战射速(ROF)",
    "rof_siege": "攻城射速(ROF)",
    "range": "远程射程",
    "range_min": "远程最小射程",
    "range_melee": "近战射程",
    "armor_melee": "近战护甲",
    "armor_ranged": "远程护甲",
    "armor_siege": "攻城护甲",
    "aoe_radius": "AOE 半径",
    "aoe_radius_ranged": "远程 AOE 半径",
    "aoe_radius_melee": "近战 AOE 半径",
    "damage_cap_ranged": "远程溅射池",
    "damage_cap_melee": "近战溅射池",
    "damage_type_ranged": "远程伤害类型",
    "damage_type_melee": "近战伤害类型",
    "num_projectiles_ranged": "远程弹丸数",
    "num_projectiles_melee": "近战弹丸数",
    "multipliers": "克制倍率",
    "windups": "抬手表",
    "windup_ranged": "远程抬手",
    "windup_melee": "近战抬手",
    "protoaction_ranged": "远程代表动作",
    "protoaction_melee": "近战代表动作",
    "protoaction_siege": "攻城代表动作",
    "cost": "造价",
    "pop": "人口",
    "train_time": "训练时间",
    "los": "视野",
    "speed": "移速",
    "type": "类型标签",
    "age": "时代",
    "civs": "文明",
    "name": "中文名",
    "name_en": "英文名",
    "description": "描述",
    "description_en": "英文描述",
}


def _canon(v) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def _load_units_from_rev(rev: str) -> list[dict]:
    """从 git 历史取出某一版 seeds/aoe3/units.json。"""
    out = subprocess.run(
        ["git", "show", f"{rev}:seeds/aoe3/units.json"],
        cwd=str(ROOT), capture_output=True,
    )
    if out.returncode != 0:
        raise SystemExit(f"ERROR: git show {rev}:seeds/aoe3/units.json 失败：{out.stderr.decode('utf-8', 'replace')}")
    return json.loads(out.stdout.decode("utf-8"))


def _to_unit(d: dict) -> Unit:
    return Unit.from_dict(d)


# ---------------------------------------------------------------------
# 战力模型：与 lineup.power_score 同构，但拆开中间量以便归因
# ---------------------------------------------------------------------
ARMOR_WEIGHT = 0.3
AOE_HIT_MULT = 0.3
HIT_BASELINE = 50.0
DPS_BASELINE = 20.0


def _soft(x: float, base: float) -> float:
    if x <= base:
        return x
    return base + math.sqrt(max(0.0, (x - base) * base))


def _hit(atk: float, proj: float, aoe: float) -> float:
    """单击合并伤害（含 AOE 加成）。"""
    return (atk or 0.0) * (proj or 1) * (1.0 + (aoe or 0) * AOE_HIT_MULT)


def _parts(u: Unit) -> dict:
    """抽出战力公式的中间量。"""
    hp_eff = (u.hp or 0.0) * (1.0 + max(u.armor_ranged or 0.0, u.armor_melee or 0.0) * ARMOR_WEIGHT)
    rof_r = u.rof_ranged or 3.0
    rof_m = u.rof_melee or 1.5
    hit_r = _hit(u.attack_ranged, u.num_projectiles_ranged, u.aoe_radius_ranged)
    hit_m = _hit(u.attack_melee, u.num_projectiles_melee, u.aoe_radius_melee)
    return {"hp_eff": hp_eff, "hit_r": hit_r, "hit_m": hit_m, "rof_r": rof_r, "rof_m": rof_m}


def _score_from(hp_eff: float, hit_r: float, hit_m: float, rof_r: float, rof_m: float) -> float:
    dps = max(_soft(hit_r, HIT_BASELINE) / max(0.1, rof_r),
              _soft(hit_m, HIT_BASELINE) / max(0.1, rof_m))
    return math.sqrt(max(0.0, hp_eff) * _soft(dps, DPS_BASELINE))


def _dps_eff(hit_r: float, hit_m: float, rof_r: float, rof_m: float) -> float:
    return _soft(max(_soft(hit_r, HIT_BASELINE) / max(0.1, rof_r),
                     _soft(hit_m, HIT_BASELINE) / max(0.1, rof_m)), DPS_BASELINE)


def attribute(old_u: Unit, new_u: Unit) -> dict:
    """把 ln(战力分) 的变化拆成 HP / 单击伤害 / AOE / 射速 四类来源。

    分解方式（ln 空间，数值差分，各项可加和到 100%）：
        ln(score) = 0.5·ln(HP_eff) + 0.5·ln(DPS_eff)
        ln(DPS_eff) 再按 单击伤害 → AOE → 射速 顺序做单变量回代分解。
    """
    o, n = _parts(old_u), _parts(new_u)

    def lnscore(p):
        return math.log(max(1e-9, _score_from(p["hp_eff"], p["hit_r"], p["hit_m"], p["rof_r"], p["rof_m"])))

    total = lnscore(n) - lnscore(o)
    if abs(total) < 1e-12:
        return {"total_ln": 0.0, "contrib": {}, "pct": {}}

    # 1) HP 项
    hp_new_eff = n["hp_eff"]
    hp_old_eff = o["hp_eff"]
    c_hp = 0.5 * (math.log(max(1e-9, hp_new_eff)) - math.log(max(1e-9, hp_old_eff)))

    # 2) DPS 项，总变化
    dps_new_eff = _dps_eff(n["hit_r"], n["hit_m"], n["rof_r"], n["rof_m"])
    dps_old_eff = _dps_eff(o["hit_r"], o["hit_m"], o["rof_r"], o["rof_m"])
    c_dps_total = 0.5 * (math.log(max(1e-9, dps_new_eff)) - math.log(max(1e-9, dps_old_eff)))

    # 3) 单击伤害 vs AOE：先整体回代 hit，剩下的归 AOE
    dps_hit_old = _dps_eff(o["hit_r"], o["hit_m"], n["rof_r"], n["rof_m"])
    c_hit_total = 0.5 * (math.log(max(1e-9, dps_new_eff)) - math.log(max(1e-9, dps_hit_old)))

    # 4) 射速项 = DPS 总变化 - 单击项
    c_rof = c_dps_total - c_hit_total

    # AOE / 弹丸细项（用单变量回代：把新版该项换成旧值，看 DPS 掉多少）
    def _dps_with(hit_r, hit_m):
        return _dps_eff(hit_r, hit_m, n["rof_r"], n["rof_m"])

    hit_r_no_aoe = (new_u.attack_ranged or 0.0) * (new_u.num_projectiles_ranged or 1) * (
        1.0 + (old_u.aoe_radius_ranged or 0) * AOE_HIT_MULT)
    hit_m_no_aoe = (new_u.attack_melee or 0.0) * (new_u.num_projectiles_melee or 1) * (
        1.0 + (old_u.aoe_radius_melee or 0) * AOE_HIT_MULT)
    dps_no_aoe = _dps_with(hit_r_no_aoe, hit_m_no_aoe)
    c_aoe = 0.5 * (math.log(max(1e-9, dps_new_eff)) - math.log(max(1e-9, dps_no_aoe)))

    hit_r_no_proj = (new_u.attack_ranged or 0.0) * (old_u.num_projectiles_ranged or 1) * (
        1.0 + (new_u.aoe_radius_ranged or 0) * AOE_HIT_MULT)
    hit_m_no_proj = (new_u.attack_melee or 0.0) * (old_u.num_projectiles_melee or 1) * (
        1.0 + (new_u.aoe_radius_melee or 0) * AOE_HIT_MULT)
    dps_no_proj = _dps_with(hit_r_no_proj, hit_m_no_proj)
    c_proj = 0.5 * (math.log(max(1e-9, dps_new_eff)) - math.log(max(1e-9, dps_no_proj)))

    c_atk = c_hit_total - c_aoe - c_proj

    contrib = {"hp": c_hp, "atk": c_atk, "proj": c_proj, "aoe": c_aoe, "rof": c_rof}
    pct = {k: (v / total if abs(total) > 1e-12 else 0.0) for k, v in contrib.items()}
    pct["unexplained"] = 1.0 - sum(pct.values())
    return {"total_ln": total, "contrib": contrib, "pct": pct}


def _slot_dps(u: Unit) -> tuple[float, str]:
    """主战槽（模拟器实际会用的 raw DPS + 槽名）。"""
    r = (u.attack_ranged or 0.0) * (u.num_projectiles_ranged or 1) / max(0.1, u.rof_ranged or 3.0)
    m = (u.attack_melee or 0.0) * (u.num_projectiles_melee or 1) / max(0.1, u.rof_melee or 1.5)
    if r >= m and r > 0:
        return r, "ranged"
    if m > 0:
        return m, "melee"
    return 0.0, ""


def _cost_value(u: Unit) -> float:
    """资源总量（人口按 5 资源折算，与 lineup 一致）。"""
    return float(sum(u.cost.values()) + 5 * (u.pop or 0))


# ---------------------------------------------------------------------
# 镜像对战
# ---------------------------------------------------------------------
def sim_mirror(new_u: Unit, old_u: Unit, count: int, seeds: list[int]) -> dict:
    """新版 N 个 vs 旧版 N 个，双向交换红蓝以消除阵营/站位偏差。"""
    st = Counter()
    for s in seeds:
        for red, blue, tag in ((new_u, old_u, "new"), (old_u, new_u, "old")):
            try:
                res = BattleSimulator(red, count, blue, count, seed=s).run()
            except Exception:  # pragma: no cover - 单场异常不中断整体
                st["error"] += 1
                continue
            st["battles"] += 1
            if res.timeout:
                st["timeout"] += 1
            if res.winner is None:
                st["draw"] += 1
            elif (res.winner == Side.RED) == (tag == "new"):
                st["new_wins"] += 1
            else:
                st["old_wins"] += 1
    decided = st["new_wins"] + st["old_wins"]
    return {
        "battles": st["battles"],
        "new_wins": st["new_wins"],
        "old_wins": st["old_wins"],
        "draw": st["draw"],
        "timeout": st["timeout"],
        "error": st["error"],
        "winrate_new": round(st["new_wins"] / decided, 4) if decided else None,
    }


def sim_vs_ref(unit_ver: Unit, ref: Unit, count: int, seeds: list[int]) -> dict:
    """该单位（某一版本数据）vs 固定参照对手，双向跑，返回胜率。"""
    wins = losses = draws = 0
    for s in seeds:
        for a, b, mine_is_red in ((unit_ver, ref, True), (ref, unit_ver, False)):
            try:
                res = BattleSimulator(a, count, b, count, seed=s).run()
            except Exception:  # pragma: no cover
                continue
            if res.winner is None:
                draws += 1
            elif (res.winner == Side.RED) == mine_is_red:
                wins += 1
            else:
                losses += 1
    decided = wins + losses
    return {
        "winrate": round(wins / decided, 4) if decided else None,
        "wins": wins, "losses": losses, "draw": draws,
    }


# ---------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------
def build(old_rev: str, count: int, seeds: list[int], do_sim: bool) -> dict:
    old_raw = _load_units_from_rev(old_rev)
    new_raw = json.loads((ROOT / "seeds" / "aoe3" / "units.json").read_text(encoding="utf-8"))

    old_map = {d["id"]: d for d in old_raw}
    new_map = {d["id"]: d for d in new_raw}
    old_units = {k: _to_unit(v) for k, v in old_map.items()}
    new_units = {k: _to_unit(v) for k, v in new_map.items()}

    added = sorted(set(new_map) - set(old_map))
    removed = sorted(set(old_map) - set(new_map))
    common = sorted(set(old_map) & set(new_map))

    # 战力分基准（用全量单位算分位，方便定位强弱）
    all_scores = sorted(power_score(u) for u in new_units.values() if power_score(u) > 0)

    def pctile(score: float) -> float:
        if not all_scores or score <= 0:
            return 0.0
        lo, hi = 0, len(all_scores)
        while lo < hi:
            mid = (lo + hi) // 2
            if all_scores[mid] < score:
                lo = mid + 1
            else:
                hi = mid
        return round(lo / len(all_scores), 4)

    changed: list[dict] = []
    for uid in common:
        o_raw, n_raw = old_map[uid], new_map[uid]
        diffs = {}
        for k in sorted(set(o_raw) | set(n_raw)):
            if _canon(o_raw.get(k)) != _canon(n_raw.get(k)):
                diffs[k] = {"old": o_raw.get(k), "new": n_raw.get(k)}
        if not diffs:
            continue
        fields = set(diffs)
        groups = []
        if fields & COMBAT_FIELDS:
            groups.append("combat")
        if fields & ECON_FIELDS:
            groups.append("economy")
        if fields & TEXT_FIELDS:
            groups.append("text")
        if not groups:
            groups.append("meta")

        o_u, n_u = old_units[uid], new_units[uid]
        s_old, s_new = power_score(o_u), power_score(n_u)
        attr = attribute(o_u, n_u)
        dps_old, slot = _slot_dps(o_u)
        dps_new, _ = _slot_dps(n_u)
        cv_old, cv_new = _cost_value(o_u), _cost_value(n_u)

        rec = {
            "id": uid,
            "name": n_u.name or n_u.name_en,
            "name_old": o_u.name or o_u.name_en,
            "name_en": n_u.name_en,
            "age": n_u.age,
            "type": n_u.type,
            "groups": groups,
            "fields": sorted(fields),
            "diffs": diffs,
            "score_old": round(s_old, 2),
            "score_new": round(s_new, 2),
            "score_delta_pct": round((s_new / s_old - 1.0) * 100, 2) if s_old else None,
            "slot": slot,
            "dps_old": round(dps_old, 2),
            "dps_new": round(dps_new, 2),
            "dps_delta_pct": round((dps_new / dps_old - 1.0) * 100, 2) if dps_old else None,
            "hp_old": o_u.hp, "hp_new": n_u.hp,
            "cost_old": dict(o_u.cost), "cost_new": dict(n_u.cost),
            "cost_value_old": cv_old, "cost_value_new": cv_new,
            "cost_eff_old": round(s_old / cv_old, 4) if cv_old else None,
            "cost_eff_new": round(s_new / cv_new, 4) if cv_new else None,
            "attrib_pct": {k: round(v, 4) for k, v in attr["pct"].items()},
            "percentile_new": pctile(s_new),
            "has_combat_change": bool(fields & COMBAT_FIELDS),
            "blind_fields": sorted(fields & FORMULA_BLIND),
        }
        if diffs.get("cost") or diffs.get("pop"):
            rec["cost_delta_pct"] = round((cv_new / cv_old - 1.0) * 100, 2) if cv_old else None
        changed.append(rec)

    # 只对"战斗/成本侧真的变了"的单位跑模拟（纯文本/标签改动跑不出差异）
    sim_targets = [r for r in changed if r["has_combat_change"] or "economy" in r["groups"]]
    print(f"[i] 变更单位 {len(changed)}，其中参与模拟 {len(sim_targets)}（数量 {count} v {count}，seed {seeds}）")
    if do_sim:
        ref_seeds = seeds[:10]
        refs = {rid: new_units[rid] for rid in REF_UNITS if rid in new_units}
        print(f"    参照陪练：{ {k: v.name for k, v in refs.items()} }（各 {len(ref_seeds) * 2} 场）")
        for i, r in enumerate(sim_targets, 1):
            uid = r["id"]
            r["sim"] = sim_mirror(new_units[uid], old_units[uid], count, seeds)
            r["vs_ref"] = {}
            for rid, ref_u in refs.items():
                new_res = sim_vs_ref(new_units[uid], ref_u, count, ref_seeds)
                old_res = sim_vs_ref(old_units[uid], ref_u, count, ref_seeds)
                r["vs_ref"][rid] = {
                    "name": ref_u.name,
                    "new": new_res["winrate"],
                    "old": old_res["winrate"],
                    "delta": (round(new_res["winrate"] - old_res["winrate"], 4)
                              if new_res["winrate"] is not None and old_res["winrate"] is not None else None),
                }
            if i % 25 == 0:
                print(f"    模拟进度 {i}/{len(sim_targets)}")

    # ---- 新增 / 消失单位 ----
    add_rows = []
    for uid in added:
        u = new_units[uid]
        add_rows.append({
            "id": uid, "name": u.name or u.name_en, "name_en": u.name_en, "age": u.age,
            "type": u.type, "hp": u.hp, "cost": dict(u.cost), "pop": u.pop,
            "atk_r": u.attack_ranged, "atk_m": u.attack_melee, "atk_s": u.attack_siege,
            "score": round(power_score(u), 2), "percentile": pctile(power_score(u)),
            "excluded": bool(
                "AbstractBannerArmy" in u.type or "Guardian" in u.type
                or uid.endswith("batch") or uid.endswith("armyspawn")
                or uid.startswith("igc") or uid.startswith("yphc")
            ),
        })
    rm_rows = []
    for uid in removed:
        u = old_units[uid]
        rm_rows.append({
            "id": uid, "name": u.name or u.name_en, "name_en": u.name_en,
            "hp": u.hp, "score": round(power_score(u), 2),
        })

    # ---- 汇总统计 ----
    def bucket(r: dict) -> str:
        if not (r["has_combat_change"] or "economy" in r["groups"]):
            return "纯文本/标签"
        g = r["score_delta_pct"]
        if g is None:
            return "无法评分"
        if g >= 20:
            return "显著增强"
        if g >= 5:
            return "小幅增强"
        if g > -5:
            return "基本持平"
        if g > -20:
            return "小幅削弱"
        return "显著削弱"

    summary = Counter(bucket(r) for r in changed)
    combat_changed = [r for r in changed if r["has_combat_change"]]
    sim_rows = [r for r in sim_targets if r.get("sim") and r["sim"].get("winrate_new") is not None]
    strong = [r for r in sim_rows if r["sim"]["winrate_new"] >= 0.65]
    weak = [r for r in sim_rows if r["sim"]["winrate_new"] <= 0.35]

    return {
        "meta": {
            "old_rev": old_rev,
            "old_units": len(old_raw),
            "new_units": len(new_raw),
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "combat_changed": len(combat_changed),
            "sim_count": count,
            "sim_seeds": seeds,
            "sim_battles_each": len(seeds) * 2,
        },
        "summary": dict(summary),
        "sim_strong": len(strong),
        "sim_weak": len(weak),
        "changed": changed,
        "added_units": add_rows,
        "removed_units": rm_rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="AoE3 平衡变更量化分析")
    ap.add_argument("--old-rev", default=DEFAULT_OLD_REV,
                    help="旧版 units.json 的 git rev（默认数据刷新前的快照）")
    ap.add_argument("--count", type=int, default=10, help="镜像对战每方数量")
    ap.add_argument("--seeds", default="0,1,2,3,4,5", help="镜像对战 seed 列表")
    ap.add_argument("--no-sim", action="store_true", help="只做静态分析，不跑模拟")
    ap.add_argument("--out", default="data/aoe3/balance_review.json")
    args = ap.parse_args()

    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]
    data = build(args.old_rev, args.count, seeds, not args.no_sim)

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"[✓] 写出 {out.relative_to(ROOT)}")
    print(f"    变更 {data['meta']['changed']} / 其中战斗或成本侧 {data['meta']['combat_changed']}")
    print(f"    分类：{data['summary']}")
    print(f"    镜像实证显著增强 {data['sim_strong']} / 显著削弱 {data['sim_weak']}")


if __name__ == "__main__":
    main()
