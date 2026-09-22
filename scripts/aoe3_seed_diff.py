"""AoE3 数据快照对比工具 —— 生成"拉取前后改动名单"，供人工核实单位。

对比两份快照：
  - 旧：`--prev`（默认 ``data/aoe3/_prev``，含 seeds/ + raw/ + icon_manifest.json）
  - 新：`--cur`（默认项目根，即当前 ``seeds/aoe3`` 等）

产出：
  - ``docs/aoe3-data-refresh-<yyyymmdd>.md``  人工核实名单（主产物）
  - ``data/aoe3/diff_report.txt``             轻量摘要（取代历史手工报告）

对比维度：
  1. units.json            新增 / 消失 / 字段级变更（含代表动作 protoaction_* 结构性变更高亮）
  2. unit_upgrades.json    单位改良数据变化
  4. icon_manifest.json    icon 来源变化 / 新增 / 消失
  5. 人工干预清单核查       源码中的 BLACKLIST / BATTLE_BLACKLIST / _EXCLUDED_IDS / icon_overrides
  6. 兵种池体检             复用 lineup.py 真实筛选逻辑，对比三种池子的进出

用法::

    uv run python scripts/aoe3_seed_diff.py
    uv run python scripts/aoe3_seed_diff.py --prev data/aoe3/_prev --tag 20260917
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))  # aoe3_battle/game.py 会 import core

from src.plugins.aoe3.models import Unit  # noqa: E402
from src.plugins.aoe3.repository import is_excluded_unit  # noqa: E402
from src.plugins.games.aoe3_battle import lineup as lineup_mod  # noqa: E402

# ---------------------------------------------------------------- 字段分组
FIELD_GROUPS: list[tuple[str, list[str]]] = [
    ("基础", ["hp", "speed", "los", "armor_melee", "armor_ranged", "armor_siege"]),
    ("费用/时代", ["cost", "pop", "train_time", "age", "civs", "type", "trained_at"]),
    (
        "远程槽",
        [
            "protoaction_ranged", "attack_ranged", "range", "range_min", "rof_ranged",
            "damage_type_ranged", "num_projectiles_ranged", "aoe_radius_ranged",
            "aoe_radius", "damage_cap_ranged", "windup_ranged",
        ],
    ),
    (
        "近战槽",
        [
            "protoaction_melee", "attack_melee", "range_melee", "rof_melee",
            "damage_type_melee", "num_projectiles_melee", "aoe_radius_melee",
            "damage_cap_melee", "windup_melee",
        ],
    ),
    ("攻城槽", ["protoaction_siege", "attack_siege", "range_siege", "rof_siege", "aoe_radius_siege"]),
    ("倍率", ["multipliers"]),
    ("抬手", ["windups"]),
    ("文本", ["name", "name_en", "description", "description_en", "internal_name", "aliases"]),
]

# 代表动作字段：变更 = 结构性变更（换了攻击包，比数值变动严重）
STRUCTURAL_FIELDS = {"protoaction_ranged", "protoaction_melee", "protoaction_siege"}


# ---------------------------------------------------------------- 工具函数
def _load_json(p: Path):
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _load_units(p: Path) -> dict[str, dict]:
    data = _load_json(p)
    if data is None:
        return {}
    return {d["id"]: d for d in data}


def _canon(v) -> str:
    """把任意值规范化为可比字符串。"""
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def _fmt(v, limit: int = 120) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return f"{v:g}" if isinstance(v, float) else str(v)
    s = v if isinstance(v, str) else _canon(v)
    s = s.replace("\n", " ")
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _diff_fields(old: dict, new: dict) -> dict[str, tuple]:
    """并集字段级深比较，返回 {field: (old, new)}。"""
    out: dict[str, tuple] = {}
    for k in sorted(set(old) | set(new)):
        a, b = old.get(k), new.get(k)
        if _canon(a) != _canon(b):
            out[k] = (a, b)
    return out


def _group_of(field: str) -> str:
    for gname, fields in FIELD_GROUPS:
        if field in fields:
            return gname
    return "其他"


def _mults_summary(old, new) -> str:
    """倍率逐槽对比摘要。"""
    old = old or {}
    new = new or {}
    parts: list[str] = []
    for slot in ("ranged", "melee", "siege"):
        o = {m["vs"]: m["value"] for m in (old.get(slot) or [])}
        n = {m["vs"]: m["value"] for m in (new.get(slot) or [])}
        if o == n:
            continue
        bits = []
        for vs in sorted(set(o) | set(n)):
            if vs not in n:
                bits.append(f"-{vs}")
            elif vs not in o:
                bits.append(f"+{vs} x{n[vs]:g}")
            elif o[vs] != n[vs]:
                bits.append(f"{vs} x{o[vs]:g}→x{n[vs]:g}")
        if bits:
            parts.append(f"{slot}: " + ", ".join(bits))
    return "; ".join(parts) or "—"


def _windups_summary(old, new) -> str:
    old = old or {}
    new = new or {}
    bits = []
    for k in sorted(set(old) | set(new)):
        if k not in new:
            bits.append(f"-{k}")
        elif k not in old:
            bits.append(f"+{k} {new[k]:g}s")
        elif abs(float(old[k]) - float(new[k])) > 1e-9:
            bits.append(f"{k} {float(old[k]):g}→{float(new[k]):g}s")
    return ", ".join(bits) or "—"


def _mults_changed(old, new) -> bool:
    return _canon(old) != _canon(new)


def _attach(bits: list[str], label: str, old, new) -> None:
    """把某个字段的变化描述追加到 bits。"""
    if label == "multipliers":
        bits.append(_mults_summary(old, new))
    elif label == "windups":
        bits.append(_windups_summary(old, new))
    else:
        bits.append(f"{label}: {_fmt(old)} → {_fmt(new)}")


# ---------------------------------------------------------------- 人工清单
def _block_strings(text: str, marker: str, keys_only: bool = False) -> list[str]:
    """提取 ``marker = { ... }`` 代码块中的字符串字面量（括号配平）。"""
    idx = text.find(marker)
    if idx < 0:
        return []
    start = text.find("{", idx)
    if start < 0:
        return []
    depth = 0
    end = start
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    block = text[start : end + 1]
    # 剥离行注释：注释里常出现示例 id（如 `"Guardian" 规则排除`），否则会被误当成清单条目
    block = "\n".join(line.split("#", 1)[0] for line in block.splitlines())
    if keys_only:
        return re.findall(r'"([A-Za-z0-9_]+)"\s*:', block)
    return re.findall(r'"([A-Za-z0-9_]+)"', block)


def collect_manual_lists() -> dict[str, dict[str, list[str]]]:
    """从源码 / 覆盖文件提取人工干预的全部 id。"""
    repo_py = (ROOT / "src" / "plugins" / "aoe3" / "repository.py").read_text(encoding="utf-8")
    lineup_py = (ROOT / "src" / "plugins" / "games" / "aoe3_battle" / "lineup.py").read_text(
        encoding="utf-8"
    )
    ov = _load_json(ROOT / "data" / "aoe3" / "icon_overrides.json") or {}

    return {
        "BLACKLIST（永久禁用）": {"lineup.py": _block_strings(lineup_py, "BLACKLIST: set[str] = {")},
        "BATTLE_BLACKLIST（普通对战禁用）": {
            "lineup.py": _block_strings(lineup_py, "BATTLE_BLACKLIST: dict[str, str] = {", keys_only=True)
        },
        "_EXCLUDED_IDS（全局排除）": {
            "repository.py": _block_strings(repo_py, "_EXCLUDED_IDS: frozenset[str] = frozenset({")
        },
        "icon_overrides（人工图标覆盖）": {"icon_overrides.json": sorted(ov.get("overrides", {}))},
    }


# ---------------------------------------------------------------- 池子体检
class _SlimRepo:
    """只满足 lineup 池函数所需接口的轻量 repo（all_units / get_by_id）。"""

    def __init__(self, units_path: Path) -> None:
        data = _load_json(units_path) or []
        self.all_units = [Unit.from_dict(d) for d in data]
        self._by_id = {u.id: u for u in self.all_units}

    def get_by_id(self, uid: str) -> Unit | None:
        return self._by_id.get(uid)


def pool_snapshot(units_path: Path) -> dict[str, list[str]]:
    repo = _SlimRepo(units_path)

    def ids(fn, *a, **kw) -> list[str]:
        try:
            return sorted(u.id for u in fn(repo, *a, **kw))
        except Exception as ex:  # pragma: no cover - 池子异常不应中断报告
            print(f"    WARN pool failed ({fn.__name__}): {ex}")
            return []

    return {
        "押注池": ids(lineup_mod.get_bet_pool),
        "单挑池": ids(lineup_mod.get_duel_pool),
        "黑名单乱斗池": ids(lineup_mod.get_blacklist_pool),
    }


# ---------------------------------------------------------------- 报告渲染
def _resolve_seeds(base: Path) -> Path:
    """兼容 ``<base>/seeds/aoe3`` 与 ``<base>/seeds`` 两种快照布局。"""
    for cand in (base / "seeds" / "aoe3", base / "seeds"):
        if (cand / "units.json").exists():
            return cand
    return base / "seeds" / "aoe3"


def build_report(prev: Path, cur: Path) -> tuple[str, str]:
    prev_seeds, cur_seeds = _resolve_seeds(prev), _resolve_seeds(cur)
    old_u = _load_units(prev_seeds / "units.json")
    new_u = _load_units(cur_seeds / "units.json")
    if not old_u:
        raise SystemExit(f"ERROR: previous units.json not found under {prev}")
    if not new_u:
        raise SystemExit(f"ERROR: current units.json not found under {cur}")

    added = sorted(set(new_u) - set(old_u))
    removed = sorted(set(old_u) - set(new_u))
    common = sorted(set(old_u) & set(new_u))

    structural: list[tuple[str, dict[str, tuple]]] = []
    changed: list[tuple[str, dict[str, tuple]]] = []
    for uid in common:
        d = _diff_fields(old_u[uid], new_u[uid])
        if not d:
            continue
        if STRUCTURAL_FIELDS & set(d) or (("attack_melee" in d) ^ ("attack_ranged" in d)):
            structural.append((uid, d))
        else:
            changed.append((uid, d))

    # 人工清单核查
    manual = collect_manual_lists()
    manual_check: dict[str, list[tuple[str, str, str]]] = {}
    for group, source in manual.items():
        rows = []
        for src, ids in source.items():
            for uid in sorted(set(ids)):
                o, n = old_u.get(uid), new_u.get(uid)
                if n is None:
                    state = "**已消失**" if o else "**从未存在**"
                elif o is None:
                    state = "新增"
                else:
                    d = _diff_fields(o, n)
                    state = f"变更 {len(d)} 项" if d else "无变化"
                key = (
                    f"hp {_fmt(n.get('hp'))} / 远 {_fmt(n.get('attack_ranged'))} / "
                    f"近 {_fmt(n.get('attack_melee'))}"
                    if n
                    else "—"
                )
                rows.append((uid, state, key + f"  `[{src}]`"))
        manual_check[group] = rows

    # 池子体检
    prev_pools = pool_snapshot(prev_seeds / "units.json")
    cur_pools = pool_snapshot(cur_seeds / "units.json")

    # 单位改良
    old_up = _load_json(prev_seeds / "unit_upgrades.json") or {}
    new_up = _load_json(cur_seeds / "unit_upgrades.json") or {}
    old_civ_up = _load_json(prev_seeds / "civ_unit_upgrades.json") or {}
    new_civ_up = _load_json(cur_seeds / "civ_unit_upgrades.json") or {}

    # icon
    old_icon = (_load_json(prev / "icon_manifest.json") or {}).get("entries", {})
    new_icon = (_load_json(cur / "data" / "aoe3" / "icon_manifest.json") or {}).get("entries", {})
    icon_added = sorted(set(new_icon) - set(old_icon))
    icon_removed = sorted(set(old_icon) - set(new_icon))
    icon_src_changed = sorted(
        i for i in set(old_icon) & set(new_icon)
        if old_icon[i].get("source") != new_icon[i].get("source")
    )

    old_man = _load_json(prev / "manifest.json") or {}
    new_man = _load_json(cur / "data" / "aoe3" / "manifest.json") or {}

    L: list[str] = []
    A = L.append
    A("# AoE3 数据刷新对比报告")
    A("")
    A(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    A(f"- 旧快照：`generated_at {old_man.get('generated_at', '?')}` / `git_head {old_man.get('git_head', '?')}`")
    A(f"- 新快照：`generated_at {new_man.get('generated_at', '?')}` / `git_head {new_man.get('git_head', '?')}`")
    A(f"- 旧 raw：protoy {old_man.get('protoy_bytes', 0) / 1024 / 1024:.2f} MB / tactics {old_man.get('tactics_files')}")
    A(f"- 新 raw：protoy {new_man.get('protoy_bytes', 0) / 1024 / 1024:.2f} MB / tactics {new_man.get('tactics_files')}")
    A("")

    # ---- 1 总览
    A("## 1. 总览")
    A("")
    A("| 指标 | 旧 | 新 | 变化 |")
    A("|---|---|---|---|")
    for label, key in [
        ("战斗单位", "combat_units"), ("protoy 字节", "protoy_bytes"),
        ("tactics 文件", "tactics_files"), ("anim 文件", "anim_files"),
    ]:
        o, n = old_man.get(key), new_man.get(key)
        delta = f"{n - o:+}" if isinstance(o, (int, float)) and isinstance(n, (int, float)) else "—"
        A(f"| {label} | {o} | {n} | {delta} |")
    for label, pred in [
        ("有远程攻击", lambda u: bool(u.get("attack_ranged"))),
        ("有近战攻击", lambda u: bool(u.get("attack_melee"))),
        ("有 AOE", lambda u: bool(u.get("aoe_radius"))),
        ("有 damage_cap", lambda u: bool(u.get("damage_cap_ranged") or u.get("damage_cap_melee"))),
        ("有 windup", lambda u: bool(u.get("windups"))),
        ("有三槽代表动作", lambda u: bool(u.get("protoaction_ranged") and u.get("protoaction_melee"))),
    ]:
        o = sum(1 for u in old_u.values() if pred(u))
        n = sum(1 for u in new_u.values() if pred(u))
        A(f"| {label} | {o} | {n} | {n - o:+} |")
    A(f"| 单位总量 | {len(old_u)} | {len(new_u)} | {len(new_u) - len(old_u):+} |")
    o_up, n_up = len(old_up.get("units", {})), len(new_up.get("units", {}))
    A(f"| 有改良数据的单位 | {o_up} | {n_up} | {n_up - o_up:+} |")
    A("")

    # ---- 2 新增
    A(f"## 2. 新增单位（{len(added)}）")
    A("")
    if added:
        A("| id | 中文名 | 英文名 | type 摘要 | hp | 远/近/攻 | 代表动作 | 备注 |")
        A("|---|---|---|---|---|---|---|---|")
        for uid in added:
            u = new_u[uid]
            notes = []
            if not u.get("name") or u.get("name") == u.get("name_en"):
                notes.append("缺中文名")
            if not (u.get("attack_ranged") or u.get("attack_melee")):
                notes.append("**无远/近攻击槽**")
            if not u.get("cost"):
                notes.append("无费用")
            if not u.get("windups"):
                notes.append("无 windup")
            A(
                f"| `{uid}` | {u.get('name', '')} | {u.get('name_en', '')} | "
                f"{'/'.join(u.get('type', [])[:3])} | {_fmt(u.get('hp'))} | "
                f"{_fmt(u.get('attack_ranged'))}/{_fmt(u.get('attack_melee'))}/{_fmt(u.get('attack_siege'))} | "
                f"{u.get('protoaction_ranged') or '—'} / {u.get('protoaction_melee') or '—'} | "
                f"{'、'.join(notes) or ''} |"
            )
    else:
        A("（无）")
    A("")

    # ---- 3 消失
    A(f"## 3. 消失单位（{len(removed)}）")
    A("")
    if removed:
        A("| id | 中文名 | 英文名 | hp | 备注 |")
        A("|---|---|---|---|---|")
        for uid in removed:
            u = old_u[uid]
            A(f"| `{uid}` | {u.get('name', '')} | {u.get('name_en', '')} | {_fmt(u.get('hp'))} | 旧数据独有 |")
    else:
        A("（无）")
    A("")

    # ---- 4 结构性变更
    A(f"## 4. 结构性变更（代表动作 / 攻击槽增删）（{len(structural)}）")
    A("")
    A("> 代表动作变更意味着整包攻击数据（damage/rof/aoe/倍率/windup）换了一套，比单纯数值变动严重，需重点核对。")
    A("")
    if structural:
        A("| id | 中文名 | 变更 | 旧 → 新 |")
        A("|---|---|---|---|")
        for uid, d in structural:
            bits = []
            for f in sorted(d):
                o, n = d[f]
                if f in STRUCTURAL_FIELDS:
                    bits.append(f"**{f}**: {_fmt(o)} → {_fmt(n)}")
                else:
                    _attach(bits, f, o, n)
            A(f"| `{uid}` | {new_u[uid].get('name', '')} | {len(d)} 项 | {'<br>'.join(bits)} |")
    else:
        A("（无）")
    A("")

    # ---- 5 数值变更
    A(f"## 5. 数值 / 文本变更（{len(changed)}）")
    A("")
    if changed:
        A("| id | 中文名 | 变更 | 旧 → 新 |")
        A("|---|---|---|---|")
        for uid, d in changed:
            bits = []
            for f in sorted(d, key=lambda x: (_group_of(x), x)):
                o, n = d[f]
                _attach(bits, f, o, n)
            A(f"| `{uid}` | {new_u[uid].get('name', '')} | {len(d)} 项 | {'<br>'.join(bits)} |")
    else:
        A("（无）")
    A("")

    # ---- 6 人工清单核查
    A("## 6. 人工干预清单核查")
    A("")
    A("> 以下是历史上人工加进代码 / 覆盖文件的名字。刷新后必须逐条确认：还在不在、入榜理由是否仍成立。")
    A("")
    for group, rows in manual_check.items():
        A(f"### 6.{list(manual_check).index(group) + 1} {group}")
        A("")
        A("| id | 状态 | 新数据关键值 |")
        A("|---|---|---|")
        for uid, state, key in rows:
            A(f"| `{uid}` | {state} | {key} |")
        A("")

    # ---- 7 池子
    A("## 7. 兵种池变化")
    A("")
    A("| 池子 | 旧 | 新 | 变化 | 进池（新增） | 出池（消失） |")
    A("|---|---|---|---|---|---|")
    for name in prev_pools:
        o, n = set(prev_pools[name]), set(cur_pools[name])
        enter = ", ".join(f"`{i}`" for i in sorted(n - o)[:25]) or "—"
        leave = ", ".join(f"`{i}`" for i in sorted(o - n)[:25]) or "—"
        A(f"| {name} | {len(o)} | {len(n)} | {len(n) - len(o):+} | {enter} | {leave} |")
    A("")
    A("当前黑名单乱斗池内容：")
    A("")
    A("```")
    A(", ".join(cur_pools["黑名单乱斗池"]) or "（空池！）")
    A("```")
    A("")

    # ---- 8 icon
    A("## 8. icon 变化")
    A("")
    A(f"- 旧 icon 记录：{len(old_icon)}；新 icon 记录：{len(new_icon)}")
    A(f"- 新增：{len(icon_added)}；消失：{len(icon_removed)}；来源变化：{len(icon_src_changed)}")
    if icon_added:
        A(f"- 新增 id（前 40）：{', '.join('`' + i + '`' for i in icon_added[:40])}")
    if icon_removed:
        A(f"- 消失 id：{', '.join('`' + i + '`' for i in icon_removed[:40])}")
    if icon_src_changed:
        A(f"- 来源变化 id（前 40）：{', '.join('`' + i + '`' for i in icon_src_changed[:40])}")
    A("")

    # ---- 9 单位改良
    A("## 9. 单位改良变化")
    A("")
    A("### 9.1 单位改良（unit_upgrades.json）")
    A("")
    ou, nu = old_up.get("units", {}), new_up.get("units", {})
    added_up, lost_up = sorted(set(nu) - set(ou)), sorted(set(ou) - set(nu))
    chg_up = [k for k in sorted(set(ou) & set(nu)) if _canon(ou[k]) != _canon(nu[k])]
    A(
        f"- 覆盖单位：{len(ou)} → {len(nu)}"
        f"（新增覆盖 {len(added_up)}，失去覆盖 {len(lost_up)}，数据变化 {len(chg_up)}）"
    )
    if added_up:
        A(f"- 新增覆盖：{', '.join('`' + i + '`' for i in added_up[:40])}")
    if lost_up:
        A(f"- 失去覆盖：{', '.join('`' + i + '`' for i in lost_up[:40])}")
    A("")
    if chg_up:
        A("| 单位 | 变化明细（按时代） |")
        A("|---|---|")
        for uid in chg_up:
            bits = []
            for age in sorted(set(ou[uid]) | set(nu[uid]), key=lambda x: str(x)):
                ov, nv = ou[uid].get(age), nu[uid].get(age)
                if _canon(ov) == _canon(nv):
                    continue
                if ov is None:
                    bits.append(f"**+{age}** {_fmt(nv, 110)}")
                elif nv is None:
                    bits.append(f"**-{age}**")
                else:
                    sub = [
                        f"{k}: {_fmt(ov.get(k))} → {_fmt(nv.get(k))}"
                        for k in sorted(set(ov) | set(nv))
                        if _canon(ov.get(k)) != _canon(nv.get(k))
                    ]
                    bits.append(f"**{age}** " + "; ".join(sub))
            A(f"| `{uid}` | {'<br>'.join(bits)} |")
        A("")

    oc, nc = old_up.get("category", {}), new_up.get("category", {})
    A("### 9.2 类别科技（土著 / 亡命徒 / 佣兵）")
    A("")
    for k in sorted(set(oc) | set(nc)):
        ov, nv = oc.get(k), nc.get(k)
        mark = "（新增）" if ov is None else ("（消失）" if nv is None else None)
        if mark is None:
            mark = "**数据变化**" if _canon(ov) != _canon(nv) else "无变化"
        A(f"- `{k}`：{mark}")
    A("")

    A("### 9.3 文明专属改良（civ_unit_upgrades.json）")
    A("")
    ocu, ncu = old_civ_up.get("civs", {}), new_civ_up.get("civs", {})
    old_pairs = {(civ, uid): value for civ, units in ocu.items() for uid, value in units.items()}
    new_pairs = {(civ, uid): value for civ, units in ncu.items() for uid, value in units.items()}
    added_civ_up = sorted(set(new_pairs) - set(old_pairs))
    lost_civ_up = sorted(set(old_pairs) - set(new_pairs))
    changed_civ_up = sorted(
        key
        for key in set(old_pairs) & set(new_pairs)
        if _canon(old_pairs[key]) != _canon(new_pairs[key])
    )
    A(
        f"- 文明：{len(ocu)} → {len(ncu)}；文明-单位覆盖："
        f"{len(old_pairs)} → {len(new_pairs)}（新增 {len(added_civ_up)}，"
        f"消失 {len(lost_civ_up)}，变化 {len(changed_civ_up)}）"
    )
    for label, rows in (
        ("新增", added_civ_up),
        ("消失", lost_civ_up),
        ("变化", changed_civ_up),
    ):
        if rows:
            A(f"- {label}（前 40）：{', '.join(f'`{civ}/{uid}`' for civ, uid in rows[:40])}")
    A("")

    # ---- 10 待决
    A("## 10. 待决问题（自动汇总）")
    A("")
    todo: list[str] = []
    manual_ids = {uid for rows in manual_check.values() for uid, _, _ in rows}
    no_zh = [i for i in added if not new_u[i].get("name") or new_u[i].get("name") == new_u[i].get("name_en")]
    if no_zh:
        todo.append(f"- [ ] {len(no_zh)} 个新单位缺中文名：{', '.join('`' + i + '`' for i in no_zh[:30])}")
    no_atk = [i for i in added if not (new_u[i].get("attack_ranged") or new_u[i].get("attack_melee"))]
    if no_atk:
        pending = [i for i in no_atk if i not in manual_ids]
        handled = [i for i in no_atk if i in manual_ids]
        if pending:
            todo.append(
                f"- [ ] {len(pending)} 个新单位无远/近攻击槽（只有攻城攻击 → 池子会剔除）："
                f"{', '.join('`' + i + '`' for i in pending[:30])}"
            )
        if handled:
            todo.append(
                f"- [x] {len(handled)} 个新单位无远/近攻击槽，但已列入人工名单（黑名单/排除规则）："
                f"{', '.join('`' + i + '`' for i in handled[:30])}"
            )
    missing_manual = [
        f"`{uid}`({group})" for group, rows in manual_check.items() for uid, state, _ in rows
        if state.startswith("**")
    ]
    if missing_manual:
        todo.append(f"- [ ] 人工清单中已失效的 id，需清理或说明：{', '.join(missing_manual[:40])}")
    for uid, _ in structural:
        todo.append(f"- [ ] 结构性变更需确认代表动作是否仍正确：`{uid}`")
    if not todo:
        todo.append("- 无")
    L.extend(todo)
    A("")
    A("> 以上为工具自动汇总；人工核对结论与处置记录见 "
      "`docs/games/aoe3-battle.md` §「2026-09-17 追加决议（游戏大版本更新 · 数据快照刷新）」。")
    A("")

    md = "\n".join(L)

    # 轻量 txt 摘要
    T: list[str] = []
    T.append("=" * 60)
    T.append("AOE3 DATA DIFF REPORT")
    T.append("=" * 60)
    T.append(f"prev snapshot: {old_man.get('generated_at', '?')} ({len(old_u)} units)")
    T.append(f"cur  snapshot: {new_man.get('generated_at', '?')} ({len(new_u)} units)")
    T.append("")
    T.append(f"[ADDED]   {len(added)}")
    for uid in added:
        T.append(f"  + {uid}  ({new_u[uid].get('name', '')})")
    T.append(f"[GONE]    {len(removed)}")
    for uid in removed:
        T.append(f"  - {uid}  ({old_u[uid].get('name', '')})")
    T.append(f"[STRUCTURAL] {len(structural)}")
    for uid, d in structural:
        for f in sorted(d):
            if f in STRUCTURAL_FIELDS:
                T.append(f"  ~ {uid}: {f} {_fmt(d[f][0], 40)} -> {_fmt(d[f][1], 40)}")
    T.append(f"[CHANGED] {len(changed)}")
    for uid, d in changed[:80]:
        T.append(f"  ~ {uid}: {len(d)} fields ({', '.join(sorted(d)[:6])})")
    T.append("")
    T.append("[POOLS]")
    for name in prev_pools:
        T.append(f"  {name}: {len(prev_pools[name])} -> {len(cur_pools[name])}")
    T.append("")
    T.append("[UPGRADES / TECHS]")
    T.append(f"  unit_upgrades: {len(ou)} -> {len(nu)} units (new {len(added_up)}, lost {len(lost_up)}, changed {len(chg_up)})")
    for uid in chg_up[:40]:
        T.append(f"    ~ {uid}")
    for name_t in added_t[:40]:
        T.append(f"    + {name_t}")
    for name_t in chg_t[:20]:
        T.append(f"    ~ {name_t}")
    T.append("")
    T.append("[MANUAL LISTS]")
    for group, rows in manual_check.items():
        bad = [uid for uid, state, _ in rows if state.startswith("**")]
        T.append(f"  {group}: {len(rows)} ids, stale={len(bad)} {bad if bad else ''}")
    txt = "\n".join(T)

    return md, txt


def main() -> None:
    ap = argparse.ArgumentParser(description="AoE3 data snapshot diff")
    ap.add_argument("--prev", default="data/aoe3/_prev", help="previous snapshot dir")
    ap.add_argument("--cur", default=".", help="current snapshot dir (repo root)")
    ap.add_argument("--tag", default=datetime.now().strftime("%Y%m%d"), help="output tag")
    ap.add_argument("--md", default=None, help="markdown output path")
    ap.add_argument("--txt", default="data/aoe3/diff_report.txt", help="txt summary output path")
    args = ap.parse_args()

    prev = (ROOT / args.prev).resolve() if not Path(args.prev).is_absolute() else Path(args.prev)
    cur = (ROOT / args.cur).resolve() if not Path(args.cur).is_absolute() else Path(args.cur)

    print(f"prev: {prev}")
    print(f"cur : {cur}")

    md, txt = build_report(prev, cur)

    md_path = Path(args.md) if args.md else ROOT / "docs" / f"aoe3-data-refresh-{args.tag}.md"
    if not md_path.is_absolute():
        md_path = ROOT / md_path
    txt_path = Path(args.txt)
    if not txt_path.is_absolute():
        txt_path = ROOT / txt_path

    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.write_text(txt, encoding="utf-8")

    print(f"wrote {md_path}")
    print(f"wrote {txt_path}")


if __name__ == "__main__":
    main()
