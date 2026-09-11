"""生成深海任务进度提示全量演示页。

对 96 张任务各构造一个合理局面（真实卡组、真实规则函数），
调用 task_progress 算出真实文案，输出静态 HTML。
"""

from __future__ import annotations

import html
import json
import random

from src.plugins.games.deep_sea_mission.cards import (
    build_deck,
    display_card,
    suit_of,
    value_of,
)
from src.plugins.games.deep_sea_mission.rules import task_progress
from src.plugins.games.deep_sea_mission.tasks import TASK_CARDS

OWNER = 2
PLAYERS = [1, 2, 3, 4]
CAPTAIN = 1


def make_state(won_by_owner: list[str], other_wins: int = 0) -> dict:
    """构造局面：owner 逐墩用潜艇4 赢下 won_by_owner，另有 other_wins 墩被 1 号赢。

    潜艇4 是最大潜艇，垫任何牌都能赢，保证赢家恒为 owner。
    """
    deck = build_deck(random.Random(11))
    history: list[dict] = []
    used: set[str] = set()

    def take(card: str) -> None:
        used.add(card)

    take("sub:4")
    for i, card in enumerate(won_by_owner, 1):
        if card == "sub:4":
            continue
        take(card)
        history.append(
            {
                "no": i,
                "plays": [
                    {"player": OWNER, "card": "sub:4"},
                    {"player": 1, "card": card},
                ],
                "winner": OWNER,
            }
        )
    no = len(history) + 1
    fill = [c for c in deck if c not in used and suit_of(c) != "sub"]
    fill = [c for c in fill if c not in used]
    idx = 0
    for k in range(other_wins):
        card = fill[idx]
        idx += 1
        history.append(
            {
                "no": no + k,
                "plays": [
                    {"player": 1, "card": "sub:1"},
                    {"player": OWNER, "card": card},
                ],
                "winner": 1,
            }
        )
    hands = {str(p): [] for p in PLAYERS}
    rest = [c for c in deck if c not in used and c not in fill[:idx]]
    for i, c in enumerate(rest):
        hands[str(PLAYERS[i % len(PLAYERS)])].append(c)
    return {
        "order": PLAYERS,
        "captain_id": CAPTAIN,
        "trick_history": history,
        "hands": hands,
        "won_tricks": {},
    }


# 每张任务的示例局面：owner 已赢下的牌 + 1 号额外赢的墩数
SCENARIOS: dict[str, tuple[list[str], int]] = {
    "T001": (["pink:1", "pink:2", "pink:3"], 1),
    "T002": (["pink:1", "pink:2"], 0),
    "T003": (["pink:1"], 3),
    "T004": (["pink:1", "pink:2"], 1),
    "T005": (["pink:1"], 2),
    "T006": (["pink:1"], 1),
    "T007": (["pink:1"], 0),
    "T008": (["pink:9"], 0),
    "T009": (["pink:6"], 0),
    "T010": (["pink:5"], 0),
    "T011": (["pink:3"], 0),
    "T012": (["pink:5"], 0),
    "T013": (["pink:8"], 0),
    "T014": (["pink:6"], 0),
    "T015": (["pink:2"], 0),
    "T016": (["pink:3"], 0),
    "T017": (["yellow:1"], 0),
    "T018": (["blue:4"], 0),
    "T019": (["green:6"], 0),
    "T020": (["pink:3", "yellow:3"], 0),
    "T021": (["pink:5", "yellow:5"], 0),
    "T022": (["pink:9"], 0),
    "T023": (["pink:7"], 0),
    "T024": (["pink:9"], 0),
    "T025": (["pink:6", "yellow:6"], 0),
    "T026": (["pink:9"], 0),
    "T027": (["blue:1"], 0),
    "T028": (["blue:6"], 0),
    "T029": (["pink:5"], 0),
    "T030": (["green:5"], 0),
    "T031": (["blue:5"], 0),
    "T032": (["pink:9"], 0),
    "T033": (["pink:1"], 0),
    "T034": (["yellow:9"], 0),
    "T035": (["yellow:4"], 0),
    "T036": (["green:2"], 0),
    "T037": (["pink:1"], 0),
    "T038": (["yellow:1", "yellow:2", "yellow:3"], 0),
    "T039": (["pink:1", "pink:2"], 0),
    "T040": (["green:1"], 0),
    "T041": (["blue:1"], 0),
    "T042": ([], 0),
    "T043": (["green:1"], 0),
    "T044": (["pink:1", "yellow:2"], 0),
    "T045": (["pink:1", "pink:2", "pink:3"], 0),
    "T046": (["pink:2"], 0),
    "T047": (["pink:1"], 0),
    "T048": (["pink:9"], 0),
    "T049": (["pink:1"], 0),
    "T050": (["pink:9"], 0),
    "T051": (["pink:1"], 0),
    "T052": (["pink:1"], 0),
    "T053": (["pink:1"], 0),
    "T054": (["pink:1"], 0),
    "T055": (["pink:1"], 0),
    "T056": (["pink:1"], 0),
    "T057": (["pink:1"], 0),
    "T058": (["pink:1"], 0),
    "T059": (["pink:1"], 0),
    "T060": (["pink:1"], 0),
    "T061": (["pink:1"], 0),
    "T062": (["pink:1"], 0),
    "T063": (["pink:1"], 0),
    "T064": (["pink:1"], 0),
    "T065": (["pink:1"], 0),
    "T066": (["pink:1"], 0),
    "T067": (["pink:1"], 0),
    "T068": (["pink:1"], 0),
    "T069": (["pink:1"], 0),
    "T070": (["pink:1"], 0),
    "T071": (["pink:1"], 0),
    "T072": (["pink:1"], 0),
    "T073": (["pink:1"], 0),
    "T074": (["pink:1"], 0),
    "T075": (["pink:1", "pink:2"], 0),
    "T076": (["pink:1"], 0),
    "T077": (["pink:1", "pink:2"], 0),
    "T078": (["pink:1"], 0),
    "T079": (["pink:1"], 0),
    "T080": (["pink:1"], 0),
    "T081": (["pink:1"], 0),
    "T082": (["pink:1"], 0),
    "T083": (["pink:1"], 0),
    "T084": (["pink:1", "pink:2"], 0),
    "T085": (["pink:1", "pink:2"], 0),
    "T086": (["pink:1", "pink:2"], 0),
    "T087": (["pink:1"], 0),
    "T088": (["pink:1", "pink:2"], 0),
    "T089": (["pink:1", "pink:2"], 0),
    "T090": (["pink:1"], 0),
    "T091": (["pink:1"], 0),
    "T092": (["pink:1", "pink:2", "yellow:3"], 0),
    "T093": (["pink:1"], 0),
    "T094": (["pink:1"], 0),
    "T095": (["yellow:1", "blue:2"], 0),
    "T096": (["pink:1"], 0),
}


def build_rows() -> list[dict]:
    rows: list[dict] = []
    for card in TASK_CARDS:
        won, other = SCENARIOS.get(card.id, ([], 0))
        state = make_state(won, other)
        task = {
            "id": card.id,
            "text": card.text,
            "difficulty": card.difficulty_for(4),
            "assigned_to": OWNER,
            "prediction": 3 if card.id in {"T090", "T091"} else None,
        }
        progress = task_progress(state, task)
        rows.append(
            {
                "id": card.id,
                "text": card.text,
                "difficulty": card.difficulty_for(4),
                "progress": progress,
                "state": "□",
                "won": [display_card(c) for c in won],
            }
        )
    return rows


HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>深海任务 · 进度提示全量演示</title>
<style>
  * { box-sizing: border-box; }
  body { margin:0; padding:32px; background:#0d1b2a; color:#e0e6ed;
         font-family:"PingFang SC","Microsoft YaHei",system-ui,sans-serif; }
  h1 { font-size:24px; margin:0 0 8px; color:#7fd7ff; }
  .sub { color:#8fa8bf; font-size:14px; margin-bottom:24px; line-height:1.7; }
  .stats { display:flex; gap:16px; margin-bottom:24px; flex-wrap:wrap; }
  .stat { background:#16283d; border:1px solid #24405c; border-radius:8px;
          padding:12px 18px; }
  .stat b { display:block; font-size:22px; color:#7fd7ff; }
  .stat span { font-size:12px; color:#8fa8bf; }
  .filters { margin-bottom:20px; display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  .filters button { background:#16283d; color:#e0e6ed; border:1px solid #24405c;
                    border-radius:6px; padding:7px 14px; cursor:pointer; font-size:13px; }
  .filters button:hover { border-color:#7fd7ff; }
  .filters button.on { background:#1d4e6e; border-color:#7fd7ff; color:#fff; }
  .filters input { background:#16283d; color:#e0e6ed; border:1px solid #24405c;
                   border-radius:6px; padding:7px 12px; font-size:13px; width:180px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(400px,1fr)); gap:14px; }
  .card { background:#132337; border:1px solid #24405c; border-radius:10px; padding:14px 16px; }
  .card.none { opacity:.55; }
  .head { display:flex; align-items:center; gap:8px; margin-bottom:8px; flex-wrap:wrap; }
  .tid { color:#7fd7ff; font-weight:700; font-family:ui-monospace,monospace; }
  .diff { background:#24405c; color:#cfe6f5; border-radius:4px;
          padding:1px 7px; font-size:12px; }
  .tasktext { font-size:15px; line-height:1.5; margin-bottom:10px; }
  .prog { background:#0a1725; border-left:3px solid #7fd7ff; border-radius:0 6px 6px 0;
          padding:8px 12px; font-family:ui-monospace,monospace; font-size:14px;
          color:#9fe8b5; }
  .prog.none { border-left-color:#456; color:#7b8fa3; }
  .scen { margin-top:8px; font-size:12px; color:#6f8499; }
  .none-badge { background:#3a2a2a; color:#e0a0a0; border-radius:4px;
                padding:1px 7px; font-size:12px; }
  .panel { background:#0a1725; border:1px solid #24405c; border-radius:10px;
           padding:16px 18px; margin-bottom:26px; }
  .panel-title { color:#7fd7ff; font-size:15px; margin-bottom:10px; }
  .panel pre { margin:0; white-space:pre-wrap; font-family:ui-monospace,monospace;
               font-size:13px; line-height:1.75; color:#cfe6f5; }
</style>
</head>
<body>
<h1>🌊 深海任务 · 进度提示全量演示</h1>
<div class="sub">
  全部 __TOTAL__ 张任务，每张构造一个合理局面，调用真实 <code>task_progress()</code> 计算。<br>
  玩家为 2 号（P2），队长为 1 号（P1）。「示例局面」是该演示中 2 号已赢下的牌。
</div>
<div class="stats">
  <div class="stat"><b id="s-total">0</b><span>任务总数</span></div>
  <div class="stat"><b id="s-has">0</b><span>有进度提示</span></div>
  <div class="stat"><b id="s-none">0</b><span>无进度（终局判定）</span></div>
</div>
<div class="filters">
  <button class="on" data-f="all">全部</button>
  <button data-f="has">仅看有进度</button>
  <button data-f="none">仅看无进度</button>
  <input id="q" placeholder="搜索任务号或文本…">
</div>

<div class="panel">
  <div class="panel-title">📋 群内实际观感（4 人局 · 6 个任务）</div>
  <pre>🌊 深海任务 · 本墩结果
━━━━━━━━━━━━━━
第 6 墩结束
赢家：@小明
下一墩起手：@小明

本墩出牌：
@小红：黄3
@小刚：黄7
@小李：黄2
@小明：潜艇1

当前吃墩数：
@小明 3 · @小红 1 · @小刚 1 · @小李 1

当前任务：
1. □ [4] 赢得相同数量的粉牌和黄牌（都必须大于 0）（@小明）
   └ 粉 2 · 黄 1
2. □ [3] 赢得至少七张黄牌（@小红）
   └ 黄 3/7
3. □ [4] 恰好赢得三张 6（@小刚）
   └ 6点 2/3（超 3 失败）
4. □ [2] 赢得 X 墩（公开预测准确数字）（@小李）
   └ 已赢 1 / 预测 3
5. □ [3] 赢得蓝1、蓝2、蓝3（@小明）
   └ 蓝1✅ 蓝2□ 蓝3□
6. ✅ [1] 赢得绿6（@小红）</pre>
</div>

<div class="grid" id="grid"></div>
<script>
const DATA = __DATA__;
const grid = document.getElementById('grid');
let filter = 'all', query = '';

function render() {
  const q = query.trim().toLowerCase();
  grid.innerHTML = DATA.filter(d => {
    if (filter === 'has' && !d.progress) return false;
    if (filter === 'none' && d.progress) return false;
    if (q && !(d.id.toLowerCase().includes(q) || d.text.toLowerCase().includes(q))) return false;
    return true;
  }).map(d => `
    <div class="card ${d.progress ? '' : 'none'}">
      <div class="head">
        <span class="tid">${d.id}</span>
        <span class="diff">难度 ${d.difficulty}</span>
        ${d.progress ? '' : '<span class="none-badge">无进度</span>'}
      </div>
      <div class="tasktext">□ ${d.text}</div>
      <div class="prog ${d.progress ? '' : 'none'}">└ ${d.progress ? d.progress : '（终局判定，局中不提示）'}</div>
      <div class="scen">示例局面 · 已赢：${d.won.length ? d.won.join(' ') : '（无）'}</div>
    </div>`).join('');
}

document.querySelectorAll('.filters button').forEach(b => {
  b.onclick = () => {
    document.querySelectorAll('.filters button').forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    filter = b.dataset.f;
    render();
  };
});
document.getElementById('q').oninput = e => { query = e.target.value; render(); };

document.getElementById('s-total').textContent = DATA.length;
document.getElementById('s-has').textContent = DATA.filter(d => d.progress).length;
document.getElementById('s-none').textContent = DATA.filter(d => !d.progress).length;
render();
</script>
</body>
</html>
"""


def main() -> None:
    rows = build_rows()
    out = (
        HTML.replace("__TOTAL__", str(len(rows)))
        .replace("__DATA__", json.dumps(rows, ensure_ascii=False))
    )
    path = "docs/_tmp_task_progress_demo.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    has = sum(1 for r in rows if r["progress"])
    print(f"total={len(rows)} has={has} none={len(rows)-has} -> {path}")
    for r in rows:
        if not r["progress"]:
            print("  无进度:", r["id"], r["text"])


if __name__ == "__main__":
    main()
