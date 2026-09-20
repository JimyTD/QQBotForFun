"""由 ``data/aoe3/balance_review.json`` 生成单页 HTML 平衡分析报告。

输入：``scripts/aoe3_balance_review.py`` 的产物。
输出：``docs/aoe3-balance-<版本>-.html``（自包含单文件，无外部依赖）。

用法：
    uv run python scripts/aoe3_balance_report.py
    uv run python scripts/aoe3_balance_report.py --out docs/report.html --open
"""

from __future__ import annotations

import argparse
import html
import io
import json
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------
# 变更摘要（人类可读中文）
# ---------------------------------------------------------------------
FIELD_CN = {
    "hp": "生命值", "attack_ranged": "远程攻击", "attack_melee": "近战攻击",
    "attack_siege": "攻城攻击", "rof_ranged": "远程射速", "rof_melee": "近战射速",
    "rof_siege": "攻城射速", "range": "远程射程", "range_min": "最小射程",
    "range_melee": "近战射程", "range_siege": "攻城射程",
    "armor_melee": "近战护甲", "armor_ranged": "远程护甲", "armor_siege": "攻城护甲",
    "aoe_radius": "AOE 半径", "aoe_radius_ranged": "远程 AOE", "aoe_radius_melee": "近战 AOE",
    "aoe_radius_siege": "攻城 AOE", "damage_cap_ranged": "远程溅射池",
    "damage_cap_melee": "近战溅射池", "damage_type_ranged": "远程伤害类型",
    "damage_type_melee": "近战伤害类型", "num_projectiles_ranged": "远程弹丸数",
    "num_projectiles_melee": "近战弹丸数", "multipliers": "克制倍率", "windups": "抬手表",
    "windup_ranged": "远程抬手", "windup_melee": "近战抬手",
    "protoaction_ranged": "远程代表动作", "protoaction_melee": "近战代表动作",
    "protoaction_siege": "攻城代表动作", "cost": "造价", "pop": "人口",
    "train_time": "训练时间", "los": "视野", "speed": "移速", "type": "类型标签",
    "age": "时代", "civs": "文明", "name": "中文名", "name_en": "英文名",
    "description": "描述", "description_en": "英文描述", "aliases": "别名",
    "trained_at": "训练建筑", "internal_name": "内部名", "icon_url": "图标",
    "wiki_url": "wiki", "trained_at_zh": "训练建筑",
}


def _num(v) -> str:
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _cost(v) -> str:
    if not isinstance(v, dict) or not v:
        return "—"
    icons = {"food": "食", "wood": "木", "gold": "金", "export": "出", "influence": "影"}
    return " ".join(f"{icons.get(k, k)}{_num(n)}" for k, n in v.items())


def _mults(o, n) -> str:
    parts: list[str] = []
    for slot in ("ranged", "melee", "siege"):
        a = {m["vs"]: m["value"] for m in ((o or {}).get(slot) or [])}
        b = {m["vs"]: m["value"] for m in ((n or {}).get(slot) or [])}
        bits = []
        for k in sorted(set(a) | set(b)):
            va, vb = a.get(k), b.get(k)
            if va == vb:
                continue
            if va is None:
                bits.append(f"+{k}×{_num(vb)}")
            elif vb is None:
                bits.append(f"−{k}")
            else:
                bits.append(f"{k}×{_num(va)}→×{_num(vb)}")
        if bits:
            parts.append(f"{slot} " + " ".join(bits))
    return "；".join(parts)


def _windups(o, n) -> str:
    a, b = o or {}, n or {}
    bits = []
    for k in sorted(set(a) | set(b)):
        if k not in b:
            bits.append(f"−{k}")
        elif k not in a:
            bits.append(f"+{k} {_num(b[k])}s")
        elif a[k] != b[k]:
            bits.append(f"{k} {_num(a[k])}→{_num(b[k])}s")
    return " ".join(bits)


MAX_SHOW = 6


def summarize(diffs: dict) -> list[str]:
    """把字段差异转成中文摘要行。"""
    out: list[str] = []
    for field in sorted(diffs):
        o, n = diffs[field]["old"], diffs[field]["new"]
        label = FIELD_CN.get(field, field)
        if field == "multipliers":
            out.append(f"{label}：{_mults(o, n) or '（结构调整）'}")
        elif field == "windups":
            out.append(f"{label}：{_windups(o, n)}")
        elif field == "cost":
            out.append(f"{label}：{_cost(o)} → {_cost(n)}")
        elif field in ("description", "description_en"):
            out.append(f"{label}：文案更新")
        elif field == "type":
            out.append(f"{label}：标签增减 {len(set(n or []) ^ set(o or []))} 项")
        elif field == "name":
            out.append(f"改名：「{o}」→「{n}」")
        elif field == "range_min":
            out.append(f"{label}：{_num(o)} → {_num(n)}")
        else:
            if isinstance(o, (list, dict)):
                out.append(f"{label}：结构变化")
            else:
                out.append(f"{label}：{_num(o) if o is not None else '—'} → {_num(n) if n is not None else '—'}")
    if len(out) > MAX_SHOW:
        extra = len(out) - MAX_SHOW
        out = out[:MAX_SHOW] + [f"…另有 {extra} 项"]
    return out


# ---------------------------------------------------------------------
# 榜单
# ---------------------------------------------------------------------
def sim_of(r: dict):
    s = r.get("sim") or {}
    wr = s.get("winrate_new")
    return None if wr is None else wr


def vsref_brief(r: dict, k: int = 2) -> list[str]:
    items = [(v["name"], v["old"], v["new"], v["delta"])
             for v in (r.get("vs_ref") or {}).values() if v.get("delta")]
    items.sort(key=lambda x: -abs(x[3]))
    out = []
    for name, o, n, d in items[:k]:
        arrow = "↑" if d > 0 else "↓"
        out.append(f"{name} {int(round((o or 0) * 100))}%{arrow}{int(round((n or 0) * 100))}%")
    return out


def _render(tpl: str, **kw) -> str:
    """占位符替换。

    不用 ``str.format``：模板里含 CSS / JS，花括号会被误当占位符。
    占位符统一写成 ``{name}``，逐个字面替换。
    """
    out = tpl
    for k, v in kw.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="生成 AoE3 平衡分析网页")
    ap.add_argument("--data", default="data/aoe3/balance_review.json")
    ap.add_argument("--out", default="docs/aoe3-balance-review.html")
    ap.add_argument("--open", action="store_true", help="生成后打开浏览器")
    args = ap.parse_args()

    data = json.loads((ROOT / args.data).read_text(encoding="utf-8"))
    rows = data["changed"]
    meta = data["meta"]

    combat = [r for r in rows if r["has_combat_change"] or "economy" in r["groups"]]

    # 静态口径榜
    static_gain = sorted([r for r in combat if r["score_delta_pct"] is not None],
                         key=lambda r: -r["score_delta_pct"])[:15]
    static_loss = sorted([r for r in combat if r["score_delta_pct"] is not None],
                         key=lambda r: r["score_delta_pct"])[:15]

    # 实证口径榜
    with_sim = [r for r in combat if sim_of(r) is not None]
    sim_gain = sorted(with_sim, key=lambda r: -sim_of(r))[:15]
    sim_loss = sorted(with_sim, key=lambda r: sim_of(r))[:15]

    # 两口径矛盾（公式看不见、实战差异大）
    conflicts = []
    for r in with_sim:
        sd, wr = r["score_delta_pct"], sim_of(r)
        if sd is None:
            continue
        if sd >= 3 and wr <= 0.35:
            conflicts.append((r, "公式偏强 / 实战偏弱"))
        elif sd <= -3 and wr >= 0.65:
            conflicts.append((r, "公式偏弱 / 实战偏强"))
        elif abs(sd) >= 5 and 0.4 <= wr <= 0.6:
            conflicts.append((r, "公式显示大变化 / 实战无位移"))
        elif abs(sd) < 3 and abs(wr - 0.5) >= 0.3:
            conflicts.append((r, "公式几乎没动 / 实战大位移"))
    def _conflict_key(t):
        r = t[0]
        a = abs(sim_of(r) - 0.5) * 2                      # 实战位移
        b = min(1.0, abs(r["score_delta_pct"] or 0) / 25)  # 公式幅度
        return -(a + b)

    conflicts.sort(key=_conflict_key)

    # 公式盲区：变化字段全在公式覆盖之外，但实战有明显位移
    blind = [r for r in with_sim
             if r["blind_fields"] and not (set(r["fields"]) & ({"hp", "attack_ranged", "attack_melee",
                                                                "rof_ranged", "rof_melee",
                                                                "aoe_radius_ranged", "aoe_radius_melee"}))
             and abs(sim_of(r) - 0.5) >= 0.15]
    blind.sort(key=lambda r: -abs(sim_of(r) - 0.5))

    # 结构性变更（代表动作变化）
    struct = [r for r in rows
              if any(f.startswith("protoaction") for f in r["fields"])]
    struct.sort(key=lambda r: -len(r["fields"]))

    # ---------------------------------------------------------------
    # HTML
    # ---------------------------------------------------------------
    summary = data["summary"]
    n_strong_sim = sum(1 for r in with_sim if sim_of(r) >= 0.65)
    n_weak_sim = sum(1 for r in with_sim if sim_of(r) <= 0.35)

    def kpi(v, label, tone="") -> str:
        return f'<div class="kpi {tone}"><div class="v">{v}</div><div class="l">{label}</div></div>'

    def attrib_bar(r: dict) -> str:
        pct = r.get("attrib_pct") or {}
        segs = [("hp", "生命值", "#4ade80"), ("atk", "单击伤害", "#f472b6"),
                ("aoe", "AOE", "#fbbf24"), ("rof", "射速", "#60a5fa"),
                ("proj", "弹丸数", "#a78bfa")]
        total = sum(abs(pct.get(k, 0)) for k, _, _ in segs) or 1.0
        bars = ""
        for k, label, color in segs:
            v = pct.get(k, 0)
            if abs(v) < 0.005:
                continue
            w = abs(v) / total * 100
            bars += (f'<span class="seg" style="width:{w:.1f}%;background:{color}" '
                     f'title="{label} {v * 100:+.0f}%"></span>')
        return bars or '<span class="seg muted" style="width:100%"></span>'

    def delta_chip(v, invert=False) -> str:
        if v is None:
            return '<span class="chip">—</span>'
        good = (v < 0) if invert else (v > 0)
        cls = "up" if good else ("down" if abs(v) >= 0.5 else "flat")
        return f'<span class="chip {cls}">{v:+.1f}%</span>'

    def mirror_chip(wr) -> str:
        if wr is None:
            return '<span class="chip">未测</span>'
        cls = "up" if wr >= 0.65 else ("down" if wr <= 0.35 else "flat")
        return f'<span class="chip {cls}">{wr * 100:.0f}%</span>'

    def row_html(r: dict) -> str:
        brief = " · ".join(vsref_brief(r)) or "—"
        blame = "、".join(FIELD_CN.get(f, f) for f in r["blind_fields"]) or "—"
        return (
            f'<tr data-delta="{r["score_delta_pct"] if r["score_delta_pct"] is not None else 0}" '
            f'data-wr="{sim_of(r) if sim_of(r) is not None else -1}" '
            f'data-combat="{"1" if r["has_combat_change"] else "0"}" '
            f'data-search="{html.escape((r["name"] + " " + r["id"] + " " + (r["name_en"] or "")).lower())}">'
            f'<td class="u"><b>{html.escape(r["name"])}</b>'
            f'<span class="en">{html.escape(r["id"])}</span></td>'
            f'<td>{html.escape(r["age"] or "—")}</td>'
            f'<td class="n">{_num(r["score_old"])} → <b>{_num(r["score_new"])}</b></td>'
            f'<td>{delta_chip(r["score_delta_pct"])}</td>'
            f'<td>{delta_chip(r["dps_delta_pct"])}</td>'
            f'<td>{mirror_chip(sim_of(r))}</td>'
            f'<td class="ref">{html.escape(brief)}</td>'
            f'<td class="blame">{html.escape(blame)}</td>'
            f'<td class="ms">{len(r["fields"])} 项</td>'
            f'<td class="sum">' + "".join(f"<div>{html.escape(s)}</div>" for s in summarize(r["diffs"])) + "</td>"
            f'<td class="attr">{attrib_bar(r)}</td>'
            "</tr>"
        )

    def board_table(items: list[dict], mode: str) -> str:
        head = ("单位", "评分口径", "实证口径", "关键变更", "公式盲区")
        ths = "".join(f"<th>{h}</th>" for h in head)
        trs = ""
        for r in items:
            if mode == "static":
                mid = f'{delta_chip(r["score_delta_pct"])} <span class="n">{_num(r["score_old"])} → {_num(r["score_new"])}</span>'
            else:
                mid = mirror_chip(sim_of(r))
            second = mirror_chip(sim_of(r)) if mode == "static" else delta_chip(r["score_delta_pct"])
            changes = "；".join(summarize(r["diffs"])[:2])
            blame = "、".join(FIELD_CN.get(f, f) for f in r["blind_fields"]) or "—"
            trs += (
                f'<tr><td class="u"><b>{html.escape(r["name"])}</b><span class="en">{html.escape(r["id"])}</span></td>'
                f"<td>{mid}</td><td>{second}</td>"
                f'<td class="sum">{html.escape(changes)}</td>'
                f'<td class="blame">{html.escape(blame)}</td></tr>'
            )
        return f"<table class='board'><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>"

    # 新增单位表
    added = [a for a in data["added_units"] if not a["excluded"]]
    added.sort(key=lambda a: -a["score"])
    add_rows = "".join(
        f'<tr><td class="u"><b>{html.escape(a["name"])}</b><span class="en">{html.escape(a["id"])}</span></td>'
        f'<td>{html.escape(a["age"] or "—")}</td><td class="n">{_num(a["hp"])}</td>'
        f'<td class="n">食{a["cost"].get("food", 0)} 木{a["cost"].get("wood", 0)} 金{a["cost"].get("gold", 0)}</td>'
        f'<td class="n">{_num(a["atk_r"])} / {_num(a["atk_m"])} / {_num(a["atk_s"])}</td>'
        f'<td class="n"><b>{_num(a["score"])}</b></td>'
        f'<td class="n">{a["percentile"] * 100:.0f}%</td></tr>'
        for a in added
    )
    removed = data["removed_units"]
    rm_rows = "".join(
        f'<tr><td class="u"><b>{html.escape(r["name"])}</b><span class="en">{html.escape(r["id"])}</span></td>'
        f'<td class="n">{_num(r["hp"])}</td><td class="n">{_num(r["score"])}</td>'
        f'<td class="blame">旧数据独有（新版 protoy 已无此 id）</td></tr>'
        for r in removed
    )

    struct_rows = "".join(
        f'<tr><td class="u"><b>{html.escape(r["name"])}</b><span class="en">{html.escape(r["id"])}</span></td>'
        f'<td class="sum">{html.escape("；".join(summarize(r["diffs"])))}</td>'
        f'<td>{mirror_chip(sim_of(r))}</td></tr>'
        for r in struct[:24]
    )

    conflict_rows = "".join(
        f'<tr><td class="u"><b>{html.escape(r["name"])}</b><span class="en">{html.escape(r["id"])}</span></td>'
        f'<td class="blame">{tag}</td>'
        f'<td>{delta_chip(r["score_delta_pct"])}</td><td>{mirror_chip(sim_of(r))}</td>'
        f'<td class="sum">{html.escape("；".join(summarize(r["diffs"])))}</td></tr>'
        for r, tag in conflicts[:18]
    )

    blind_rows = "".join(
        f'<tr><td class="u"><b>{html.escape(r["name"])}</b><span class="en">{html.escape(r["id"])}</span></td>'
        f'<td class="blame">{html.escape("、".join(FIELD_CN.get(f, f) for f in r["blind_fields"]))}</td>'
        f'<td>{mirror_chip(sim_of(r))}</td>'
        f'<td class="sum">{html.escape("；".join(summarize(r["diffs"])))}</td></tr>'
        for r in blind[:20]
    )

    detail_rows = "".join(row_html(r) for r in sorted(rows, key=lambda r: -(r["score_delta_pct"] or 0)))

    payload = json.dumps([
        {"id": r["id"], "name": r["name"], "d": r["score_delta_pct"], "wr": sim_of(r)}
        for r in combat
    ], ensure_ascii=False).replace("<", "\\u003c")

    html_doc = _render(
        _TEMPLATE,
        kpi_changed=kpi(meta["changed"], "字段有变动的单位"),
        kpi_combat=kpi(len(combat), "其中战斗/成本侧变化", "warn"),
        kpi_strong=kpi(n_strong_sim, "镜像实证：明显变强", "good"),
        kpi_weak=kpi(n_weak_sim, "镜像实证：明显变弱", "bad"),
        kpi_added=kpi(meta["added"], "新增单位"),
        kpi_removed=kpi(meta["removed"], "消失单位"),
        old_units=meta["old_units"], new_units=meta["new_units"],
        sim_count=meta["sim_count"], sim_battles=meta["sim_battles_each"],
        old_rev=meta["old_rev"],
        summary_static=json.dumps(summary, ensure_ascii=False),
        board_gain=board_table(static_gain, "static"),
        board_loss=board_table(static_loss, "static"),
        board_sim_gain=board_table(sim_gain, "sim"),
        board_sim_loss=board_table(sim_loss, "sim"),
        conflict_rows=conflict_rows or "<tr><td colspan='5'>无</td></tr>",
        blind_rows=blind_rows or "<tr><td colspan='4'>无</td></tr>",
        struct_rows=struct_rows or "<tr><td colspan='3'>无</td></tr>",
        add_rows=add_rows, rm_rows=rm_rows,
        detail_rows=detail_rows, detail_count=len(rows), detail_combat=len(combat),
        kpi_added_num=meta["added"], kpi_removed_num=meta["removed"],
        payload=payload,
    )

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_doc, encoding="utf-8")
    print(f"[✓] 写出 {out}")
    if args.open:
        webbrowser.open(out.as_uri())


_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>帝国时代3 DE · 2026-09 版本更新 单位平衡量化分析</title>
<style>
:root{
  --bg:#0b0f17; --panel:#121826; --panel2:#182131; --line:#26324a;
  --fg:#e6edf7; --dim:#93a1b8; --gold:#e8c07d; --cyan:#5fd3f3;
  --good:#4ade80; --bad:#f87171; --warn:#fbbf24;
}
*{box-sizing:border-box}
body{margin:0;background:linear-gradient(180deg,#080b12,#0b0f17 240px);color:var(--fg);
  font:15px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
a{color:var(--cyan);text-decoration:none}
header{padding:44px 28px 28px;border-bottom:1px solid var(--line);
  background:radial-gradient(1200px 320px at 18% -40%,rgba(232,192,125,.16),transparent)}
h1{margin:0 0 6px;font-size:30px;letter-spacing:.4px}
h1 span{color:var(--gold)}
.sub{color:var(--dim);font-size:13.5px}
.kpis{display:flex;flex-wrap:wrap;gap:12px;margin-top:22px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 18px;min-width:150px}
.kpi .v{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums}
.kpi .l{font-size:12.5px;color:var(--dim);margin-top:2px}
.kpi.good .v{color:var(--good)} .kpi.bad .v{color:var(--bad)} .kpi.warn .v{color:var(--warn)}
nav{position:sticky;top:0;z-index:9;background:rgba(11,15,23,.93);backdrop-filter:blur(8px);
  border-bottom:1px solid var(--line);padding:10px 28px;display:flex;gap:18px;flex-wrap:wrap;font-size:13.5px}
nav a{color:var(--dim)} nav a:hover{color:var(--gold)}
main{max-width:1500px;margin:0 auto;padding:28px}
section{margin:0 0 40px;scroll-margin-top:64px}
h2{font-size:21px;margin:0 0 6px;padding-left:11px;border-left:3px solid var(--gold)}
h3{font-size:16px;margin:26px 0 8px;color:var(--cyan)}
p.note{color:var(--dim);font-size:13.5px;margin:6px 0 16px}
ul.note{color:var(--dim);font-size:13.5px;margin:6px 0 16px;padding-left:22px}
ul.note li{margin:5px 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
@media(max-width:1100px){.grid2,.grid3{grid-template-columns:1fr}}
.card h4{margin:0 0 8px;font-size:14.5px;color:var(--gold)}
.card p,.card li{font-size:13.5px;color:#c7d2e2}
table{width:100%;border-collapse:collapse;font-size:13px}
th{position:sticky;top:52px;background:#16202f;text-align:left;padding:9px 10px;
  border-bottom:1px solid var(--line);color:var(--dim);font-weight:600;white-space:nowrap}
td{padding:9px 10px;border-bottom:1px solid #1c2637;vertical-align:top}
tbody tr:hover{background:#16202f}
td.u b{display:block;font-weight:600}
td.u .en{display:block;color:#6d7d96;font-size:11.5px;font-family:ui-monospace,Consolas,monospace}
td.n{font-variant-numeric:tabular-nums;white-space:nowrap}
td.sum{color:#b9c6d9;font-size:12.5px;max-width:420px}
td.sum div{padding:1px 0}
td.blame{color:#e0b184;font-size:12px;max-width:190px}
td.ref{color:#9fb3cc;font-size:12px;white-space:nowrap}
td.attr{width:150px}
.attr .seg{display:inline-block;height:9px;border-radius:3px;margin-right:1px;vertical-align:middle}
.attr .seg.muted{background:#2a3548}
.chip{display:inline-block;padding:1.5px 7px;border-radius:999px;font-size:12px;
  font-variant-numeric:tabular-nums;border:1px solid var(--line);color:var(--dim)}
.chip.up{background:rgba(74,222,128,.16);border-color:rgba(74,222,128,.35);color:#8ef0b0}
.chip.down{background:rgba(248,113,113,.16);border-color:rgba(248,113,113,.35);color:#ffb4b4}
.chip.flat{color:#cbd5e1}
table.board td.sum{max-width:360px}
.controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:12px 0}
input[type=search],select{background:var(--panel2);border:1px solid var(--line);color:var(--fg);
  border-radius:9px;padding:8px 11px;font-size:13.5px;outline:none}
input[type=search]{min-width:260px}
button{background:var(--panel2);border:1px solid var(--line);color:var(--fg);border-radius:9px;
  padding:8px 13px;font-size:13px;cursor:pointer}
button.on{background:rgba(232,192,125,.16);border-color:var(--gold);color:var(--gold)}
.tag{display:inline-block;font-size:11.5px;padding:1px 6px;border-radius:5px;
  background:#1d2941;color:#8fa6c6;margin-right:4px}
.wrap{max-height:760px;overflow:auto;border:1px solid var(--line);border-radius:12px}
footer{color:#5b6a80;font-size:12.5px;padding:26px 28px;border-top:1px solid var(--line)}
code{background:#1a2436;padding:1px 5px;border-radius:5px;font-size:12.5px;color:#9fd0e6}
.hl{color:var(--gold)}
</style>
</head>
<body>
<header>
  <h1>帝国时代3 DE · <span>2026-09-11 版本更新</span> 单位平衡量化分析</h1>
  <div class="sub">
    基线：<code>{old_rev}</code>（{old_units} 战斗单位）→ 当前 <code>seeds/aoe3/units.json</code>（{new_units} 单位）·
    镜像对战每单位 {sim_battles} 场（{sim_count} v {sim_count}，双向交换红蓝）
  </div>
  <div class="kpis">
    {kpi_changed}{kpi_combat}{kpi_strong}{kpi_weak}{kpi_added}{kpi_removed}
  </div>
</header>

<nav>
  <a href="#method">方法论</a><a href="#board">榜单</a><a href="#conflict">口径分歧</a>
  <a href="#blind">公式盲区</a><a href="#struct">结构性变更</a><a href="#detail">逐单位明细</a>
  <a href="#newgone">新增 / 消失</a><a href="#tech">改良与科技</a><a href="#impact">对斗蛐蛐的影响</a>
</nav>

<main>

<section id="method">
  <h2>一、口径说明：这份报告怎么算「强 / 弱」</h2>
  <p class="note">平衡改动的原始数据只是一堆字段差异（<code>attack_ranged: 36 → 34</code>）。要判断强弱，必须先把字段差异
  换算到可比较的量纲上。本报告同时用三套口径，互不替代：</p>
  <div class="grid3">
    <div class="card">
      <h4>① 静态战力分（有幅度）</h4>
      <p>复用斗蛐蛐黑名单乱斗配兵用的 <code>lineup.power_score</code>：
      <code>√(HP_eff × DPS_eff)</code>，其中 HP 含护甲轻微增益，DPS 对单击伤害与射速各做一次 sqrt 溢出减益。</p>
      <p><b>能答</b>：改完值不值得多派两个。<b>不能答</b>：抬手、射程、克制倍率、伤害类型、溅射池的改动它看不见。</p>
    </div>
    <div class="card">
      <h4>② 归因分解（说清来源）</h4>
      <p>在 ln 空间把总变化拆成 <b>生命值 / 单击伤害 / AOE / 射速</b> 四份贡献（数值差分，各项可加和到 100%）。</p>
      <p><b>能答</b>：变强是「血厚了」还是「输出快了」。<b>不能答</b>：非线性阈值效应（例如伤害刚好越过对手血线）。</p>
    </div>
    <div class="card">
      <h4>③ 模拟器实证（看真实结果）</h4>
      <p>新版 {sim_count} 个 vs 旧版 {sim_count} 个的镜像对战，每单位 {sim_battles} 场，双向交换红蓝消除阵营偏差；
      另有对四类固定陪练（火枪兵 / 轻骑兵 / 弩手 / 鹰炮）各 20 场的胜率迁移。</p>
      <p><b>能答</b>：所有字段综合起来，实战到底谁赢。<b>不能答</b>：幅度。对冲战斗有滚雪球效应，
      4% 的血量优势也可能被放大成 90% 胜率，所以<b>胜率只能当方向信号，不当强弱倍数</b>。</p>
    </div>
  </div>
  <p class="note">复现：<code>uv run python scripts/aoe3_balance_review.py</code> →
  <code>uv run python scripts/aoe3_balance_report.py</code>。</p>
</section>

<section id="board">
  <h2>二、增强 / 削弱榜</h2>
  <p class="note">分两个口径各出两侧榜单。同一单位若在两边都在榜，说明“数值变强”与“实战变强”互相印证；
  只在一边出现，多半是公式盲区字段（见下一节）。</p>

  <h3>2.1 静态战力分：增强最多</h3>
  {board_gain}
  <h3>2.2 静态战力分：削弱最多</h3>
  {board_loss}
  <h3>2.3 镜像实证：新版胜率最高</h3>
  <p class="note">注意口径：镜像战有滚雪球效应 —— 静态分只涨 4% 的单位也可能拿到 90%+ 胜率。
  所以胜率列只用于<b>判断方向</b>，幅度请看静态分列；两列同时上榜才是「双口径互证」。</p>
  {board_sim_gain}
  <h3>2.4 镜像实证：新版胜率最低</h3>
  {board_sim_loss}
</section>

<section id="conflict">
  <h2>三、口径分歧：公式与实战打架的单位</h2>
  <p class="note">这是本次更新最值得看的一类改动 —— 战力分几乎没动，实战却天翻地覆。共同原因有三：</p>
  <ul class="note">
    <li><b>伤害类型 / 护甲类型</b>：静态公式只取 <code>max(近战护甲, 远程护甲)</code>，而攻城护甲、
      伤害类型（Hand / Ranged / Siege）只在“打特定护甲”时才生效。新增 <code>armor_siege</code>
      的单位会表现为“内战大赢、对外不变”。</li>
    <li><b>类型标签（type）</b>：标签是克制倍率的匹配键。删掉 <code>AbstractHandCavalry</code>
      这类标签，会让所有“克制手骑兵”的单位失去加成 —— 战力公式看不见，实战里却等于被全场克制。</li>
    <li><b>代表动作 / 槽位增删</b>：公式只算“有没有攻击”，不算“用哪个槽”。近战槽消失的单位若本来靠远程输出，
      公式会扣分而实战毫无变化。</li>
  </ul>
  <table class="board"><thead><tr><th>单位</th><th>分歧类型</th><th>静态分</th><th>镜像胜率</th><th>关键变更</th></tr></thead>
  <tbody>{conflict_rows}</tbody></table>
</section>

<section id="blind">
  <h2>四、公式盲区：改动全在战力公式覆盖之外</h2>
  <p class="note">这些单位的改动字段里<b>没有任何一项</b>被战力分公式读取（抬手 windup、最小射程、克制倍率、伤害类型、
  代表动作），但镜像对战出现了明显位移。典型：只增加 0.5 秒近战抬手就会让镜像胜率从 50% 掉到个位数 ——
  因为对冲战里谁先出手谁滚雪球。</p>
  <table class="board"><thead><tr><th>单位</th><th>盲区字段</th><th>镜像胜率</th><th>关键变更</th></tr></thead>
  <tbody>{blind_rows}</tbody></table>
</section>

<section id="struct">
  <h2>五、结构性变更：代表攻击动作被换掉</h2>
  <p class="note">代表动作（<code>protoaction_*</code>）一换，整包攻击数据（伤害 / ROF / AOE / 溅射池 / 抬手 / 伤害类型）
  就换了一套。这类改动比单纯调数值严重得多，也最容易造成「查不到原因的手感变化」。</p>
  <table class="board"><thead><tr><th>单位</th><th>变更明细</th><th>镜像胜率</th></tr></thead>
  <tbody>{struct_rows}</tbody></table>
</section>

<section id="detail">
  <h2>六、逐单位明细（{detail_count} 个，其中 {detail_combat} 个涉及战斗或成本）</h2>
  <p class="note">其余单位是纯文本 / 标签层面的改动（改名、描述、类型标签增删、时代调整），不影响模拟器行为，
  但在游戏内可见，因此一并列出。</p>
  <div class="controls">
    <input type="search" id="q" placeholder="搜索中文名 / id / 英文名…">
    <button data-filter="all" class="on">全部</button>
    <button data-filter="combat">仅战斗/成本变化</button>
    <button data-filter="up">仅增强</button>
    <button data-filter="down">仅削弱</button>
    <button data-filter="sim">实证有位移</button>
    <select id="sort">
      <option value="delta">按战力分变化排序</option>
      <option value="wr">按镜像胜率排序</option>
      <option value="abs">按变化绝对值排序</option>
    </select>
  </div>
  <div class="wrap">
    <table id="detail">
      <thead><tr>
        <th>单位</th><th>时代</th><th>战力分</th><th>Δ战力</th><th>Δ主槽 DPS</th>
        <th>镜像胜率</th><th>对陪练迁移</th><th>公式盲区</th><th>改动</th><th>变更明细</th><th>归因</th>
      </tr></thead>
      <tbody>{detail_rows}</tbody>
    </table>
  </div>
</section>

<section id="newgone">
  <h2>七、新增单位（{kpi_added_num}）与消失单位（{kpi_removed_num}）</h2>
  <p class="note">新增单位直接改变斗蛐蛐池子的构成；这里的战力分与分位是相对全库 815 个单位的定位。
  已被全局排除的召唤占位符 / 守护者未列入下表。</p>
  <table class="board"><thead><tr>
    <th>单位</th><th>时代</th><th>HP</th><th>造价</th><th>远/近/攻</th><th>战力分</th><th>全库分位</th>
  </tr></thead><tbody>{add_rows}</tbody></table>
  <h3>消失单位</h3>
  <table class="board"><thead><tr><th>单位</th><th>HP</th><th>战力分</th><th>说明</th></tr></thead>
  <tbody>{rm_rows}</tbody></table>
</section>

<section id="tech">
  <h2>八、改良与通用科技</h2>
  <div class="grid2">
    <div class="card">
      <h4>单位改良（三/四/五档升级）</h4>
      <ul>
        <li><b>strelet 俄国长枪兵</b>：三/四/五档新增射程 +1 / +2 / +3（旧版无射程加成）—— 集体远程的射程曲线被拉长。</li>
        <li><b>mercswisspikeman 瑞士长枪兵</b>：兵档加成 +10% 提到 +20%，并新增移速 +0.25。</li>
        <li><b>deuscavalry 美国骑兵</b>：三档射程加成 +2.0 → +1.0（削弱）。</li>
        <li><b>spahi 西帕希 / mortar 迫击炮 / dopplesoldner 双酬剑士</b>：档位名称随官方改名更新，数值未动。</li>
      </ul>
    </div>
    <div class="card">
      <h4>通用科技（roguelike 横向加成）</h4>
      <ul>
        <li>科技条数 66 → <b>73</b>：新增 8 条<b>丹麦系</b>兵种科技（<code>RGDanish*</code>、<code>RGLeiciaiCrossbowmen</code>）。</li>
        <li>消失 1 条：<code>ChurchKapikuluCorps</code>。</li>
        <li>43 条科技数据发生变化（Caracole、Flintlock、Rifling、PaperCartridge、HCCaballeros 等）——
          这批改动直接改变斗蛐蛐里「打上改良后」的对局强度。</li>
      </ul>
    </div>
  </div>
  <p class="note">详见 <code>docs/aoe3-data-refresh-20260917.md</code> §9。</p>
</section>

<section id="impact">
  <h2>九、这版更新对斗蛐蛐意味着什么</h2>
  <div class="grid2">
    <div class="card">
      <h4>1. 池子变大，强弱跨度变大</h4>
      <p>新增 {kpi_added_num} 个单位，其中一批是「原住民 / 佣兵 / 革命兵」系列。押注池与单挑池同步扩容，
      抽到极端单位的概率上升，配兵的战力锚点也更分散。</p>
    </div>
    <div class="card">
      <h4>2. 手感类改动集中在抬手与射程</h4>
      <p>本次最容易被忽略的是 <code>windups</code> 与 <code>range_min / range_melee</code> 的变化：
      它们在战力公式里权重为零，但在对冲战斗里直接决定谁先出手。</p>
    </div>
    <div class="card">
      <h4>3. 攻城护甲与伤害类型成为暗线</h4>
      <p>投石索兵、里尔火炮等新增 <code>armor_siege</code>，只影响「被攻城伤害打」的场合。
      这类改动在混编阵容里会被放大，在单兵镜像里则表现为内战大赢、对外不变。</p>
    </div>
    <div class="card">
      <h4>4. 结论口径提醒</h4>
      <p>本报告的所有胜率来自 10 v 10 一维对冲模型，不含地形、微操、经济。它衡量的是
      <b>「同等数量、正面互殴」</b>下的强弱，不能直接外推到实战。</p>
    </div>
  </div>
</section>

</main>
<footer>
  数据来源：<code>seeds/aoe3/units.json</code>（游戏 2026-09-11 版本）vs git <code>{old_rev}</code> ·
  引擎：<code>src/plugins/games/aoe3_battle/simulator.py</code> ·
  战力分：<code>src/plugins/games/aoe3_battle/lineup.py :: power_score</code> ·
  原始变更清单：<code>docs/aoe3-data-refresh-20260917.md</code>
</footer>

<script>
const ROWS = {payload};
const tbody = document.querySelector('#detail tbody');
const q = document.getElementById('q');
const sortSel = document.getElementById('sort');
let filter = 'all';

function apply(){
  const kw = q.value.trim().toLowerCase();
  const rows = Array.from(tbody.querySelectorAll('tr'));
  rows.forEach(tr=>{
    const d = parseFloat(tr.dataset.delta) || 0;
    const wr = parseFloat(tr.dataset.wr);
    let ok = true;
    if(kw && !tr.dataset.search.includes(kw)) ok = false;
    if(ok && filter==='combat' && tr.dataset.combat!=='1') ok = false;
    if(ok && filter==='up' && !(d>0.5)) ok = false;
    if(ok && filter==='down' && !(d<-0.5)) ok = false;
    if(ok && filter==='sim' && !(wr>=0 && (wr>=0.65 || wr<=0.35) && wr!==0.5)) ok = false;
    tr.style.display = ok ? '' : 'none';
  });
}
function sortRows(){
  const mode = sortSel.value;
  const rows = Array.from(tbody.querySelectorAll('tr'));
  rows.sort((a,b)=>{
    const da = parseFloat(a.dataset.delta)||0, db = parseFloat(b.dataset.delta)||0;
    const wa = (parseFloat(a.dataset.wr)>=0? parseFloat(a.dataset.wr):0.5);
    const wb = (parseFloat(b.dataset.wr)>=0? parseFloat(b.dataset.wr):0.5);
    if(mode==='wr') return wb-wa;
    if(mode==='abs') return Math.abs(db)-Math.abs(da);
    return db-da;
  });
  rows.forEach(r=>tbody.appendChild(r));
}
q.addEventListener('input', apply);
sortSel.addEventListener('change', ()=>{sortRows(); apply();});
document.querySelectorAll('[data-filter]').forEach(btn=>{
  btn.addEventListener('click',()=>{
    document.querySelectorAll('[data-filter]').forEach(b=>b.classList.remove('on'));
    btn.classList.add('on');
    filter = btn.dataset.filter;
    apply();
  });
});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
