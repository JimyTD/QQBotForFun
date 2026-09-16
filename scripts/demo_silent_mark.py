"""静夜标记 · 交互回放生成器。

**这里没有手写剧本**：脚本真的把 `SilentMarkGame` 跑起来，把
`broadcast` / `whisper` / `ask` / `delete_message` / `award` 全部拦下来，
按真实调用顺序录成事件流，再渲染成一个自包含的 HTML 回放页。
所以页面上看到的每一句机器人的话，都是**代码真的会发出去的那句**。

用法::

    uv run python scripts/demo_silent_mark.py            # 生成 docs/demo/silent-mark-demo.html
    uv run python scripts/demo_silent_mark.py --print    # 顺带把文字版打到终端（便于核对）

三个场景：
    A 完整一局（6 人神职局，含夜间私聊、触发链、标记、投票、结算）
    B 夜间超时（证明"群内一个字都不提"）
    C 猎人跳过（证明"跳过不公开"）
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core import game_base, session  # noqa: E402
from core.errors import PlayerQuitError  # noqa: E402
from core.errors import TimeoutError as GameTimeoutError  # noqa: E402
from core.types import EndReason, GameContext, User, new_session_id  # noqa: E402
from src.plugins.games.silent_mark.engine import constants as C  # noqa: E402
from src.plugins.games.silent_mark.engine.resolve import (  # noqa: E402
    get_evaluation_mark_count,
)
from src.plugins.games.silent_mark.engine.roles import create_role  # noqa: E402
from src.plugins.games.silent_mark.engine.types import find_player  # noqa: E402
from src.plugins.games.silent_mark.game import SilentMarkGame  # noqa: E402

GROUP_ID = 88888
PHASE_LABELS: dict[str, str] = {
    C.PHASE_NIGHT: "🌙 夜晚",
    C.PHASE_DAY_ANNOUNCEMENT: "☀️ 死讯",
    C.PHASE_DAY_TRIGGER: "⚡ 死亡触发",
    C.PHASE_DAY_KNIGHT: "⚔️ 骑士决斗",
    C.PHASE_DAY_MARKING: "📝 标记发言",
    C.PHASE_DAY_VOTING: "🗳 投票放逐",
    C.PHASE_GAME_OVER: "🏆 结算",
}

#: 玩家脚本用这个哨兵表示"我不回话"
QUIT = object()

#: 回放里的"旧行为对照"：key -> (定位字样, 旧文案模板, 为什么删掉)
#: 模板里的 ``{label}`` 用**真实座位与昵称**填充，避免写死座位号对不上。
GHOST_SPECS: dict[str, tuple[str, str, str]] = {
    "night_timeout": (
        "已超时未收到你的回复",
        "{label} 超时未响应，已按默认处理。",
        "旧行为：这句是**群内广播** —— 等于当众宣布「{label} 有夜间身份」。已删除。",
    ),
    "hunter_skip": (
        "你选择不开枪",
        "🔫 {label} 选择不开枪。",
        "旧行为：这句是**群内广播** —— 等于当众翻牌「{label} 是猎人」。已删除。",
    ),
}


@dataclass
class Event:
    """一条已发生的消息（真实调用顺序）。"""

    kind: str  # group_bot | group_player | private_bot | private_player | delete
    text: str
    qq: int | None = None
    phase: str | None = None
    round: int = 1


@dataclass
class Scenario:
    """一个回放场景 = 一份板子 + 一套确定性的玩家脚本。"""

    id: str
    title: str
    subtitle: str
    note: str = ""
    mode: str = "4standard"
    seed: int = 42
    roster: list[tuple[int, str]] = field(default_factory=list)
    # ---- 玩家脚本 ----
    wolf_target_role: str = C.VILLAGER
    witch: str = "不用"
    seer_target_role: str | None = None
    hunter_action: str = "shoot"  # shoot | skip
    hunter_target_role: str = C.WEREWOLF
    vote_target_role: str = C.WEREWOLF
    timeout_roles: set[str] = field(default_factory=set)
    quit_roles: set[str] = field(default_factory=set)
    stop_after: str | None = None  # 回放停在第一条包含该字样的群消息（含）之后
    #: 要在回放里插"旧行为对照"的位置：[(GHOST_SPECS 的 key, 造成该泄露的身份)]
    ghosts: list[tuple[str, str]] = field(default_factory=list)

    # ---------------------------------------------------------------
    def answer(self, state: dict[str, Any], qq: int, prompt: str) -> Any:
        """按提示关键词作答（全知脚本玩家：从 state 里读真值，和集成测试同思路）。

        ⚠️ 关键词必须**足够精确**：标记提示里列了"查验结论""用药结果"这些理由，
        用 "查验" 去匹配会把标记提示误判成预言家问询。
        """
        pid = str(qq)
        player = find_player(state, pid)
        if player is None:
            return ""

        if player["role"] in self.timeout_roles:
            return None
        if player["role"] in self.quit_roles:
            return QUIT

        role_impl = create_role(player["role"])
        allowed = role_impl.get_available_targets(state, player)

        if "女巫用药" in prompt:
            return self.witch
        if "请选择今晚的守护目标" in prompt or "请选择今晚的袭击目标" in prompt:
            return self._seat_of(state, self._pick(state, self.wolf_target_role, allowed, pid))
        if "请选择今晚要查验的玩家" in prompt:
            return self._seat_of(
                state, self._pick(state, self.seer_target_role or C.EVIL, allowed, pid)
            )
        if "请选择开枪带走的目标" in prompt or "请选择带走的目标" in prompt:
            if self.hunter_action == "skip":
                return "跳过"
            return self._seat_of(
                state, self._pick(state, self.hunter_target_role, allowed, pid)
            )
        if "请选择决斗目标" in prompt:
            return "跳过"
        if "请选择要放逐的玩家" in prompt:
            return self._seat_of(
                state, self._pick(state, self.vote_target_role, allowed, pid)
            )
        if "标记发言" in prompt:
            return self._mark_line(state, pid)
        if "引导：" in prompt:
            # 逐步引导（只会在玩家只发「标记」时进入）：脚本一律选第 1 项
            return "1"
        return ""

    # ---------------------------------------------------------------
    @staticmethod
    def _seat_of(state: dict[str, Any], pid: str | None) -> str:
        if pid is None:
            return "跳过"
        player = find_player(state, pid)
        return str(player["seat"]) if player else "跳过"

    @staticmethod
    def _pick(
        state: dict[str, Any], wanted: str, allowed: list[str], self_pid: str
    ) -> str | None:
        """优先挑指定角色/阵营的目标，挑不到就退回第一个合法目标。

        ⚠️ `allowed` 只对**夜间技能**有意义：猎人/白狼王/投票者都不是夜间角色，
        `get_available_targets` 对它们恒为空，必须按"存活且不是自己"来挑。
        """
        candidates = [
            p
            for p in state["players"]
            if p["alive"]
            and p["pid"] != self_pid
            and (not allowed or p["pid"] in allowed)
        ]
        for player in candidates:
            if wanted in {C.EVIL, C.GOOD}:
                if player["faction"] == wanted:
                    return player["pid"]
            elif player["role"] == wanted:
                return player["pid"]
        return candidates[0]["pid"] if candidates else None

    @staticmethod
    def _mark_line(state: dict[str, Any], pid: str) -> str:
        """声明好人 + 把狼标成狼人、其余标好人（数量和引擎要求一致）。"""
        alive_count = len([p for p in state["players"] if p["alive"]])
        need = get_evaluation_mark_count(alive_count)
        wolf = next(
            (
                p["pid"]
                for p in state["players"]
                if p["alive"] and p["role"] in C.WOLF_ROLES
            ),
            None,
        )
        others = [p for p in state["players"] if p["alive"] and p["pid"] != pid][:need]
        parts = ["好人 直觉判断"]
        for target in others:
            identity = "狼人" if target["pid"] == wolf else "好人"
            parts.append(f"{target['seat']}号 {identity} 标记分析")
        return "标记 " + " | ".join(parts)


# =====================================================================
# 驱动一局
# =====================================================================
async def run_scenario(scenario: Scenario) -> dict[str, Any]:
    players = [User(qq_id=qq, nickname=name) for qq, name in scenario.roster]
    ctx = GameContext(
        session_id=new_session_id(),
        game_id=SilentMarkGame.id,
        group_id=GROUP_ID,
        host_id=players[0].qq_id,
        players=players,
        started_at=datetime.utcnow(),
        config={"mode": scenario.mode, "seed": scenario.seed},
        state={},
    )
    game = SilentMarkGame()
    runner = game_base.GameRunner(game, ctx)
    game_base._runners[ctx.session_id] = runner
    game_base._runner_by_group[ctx.group_id] = runner

    events: list[Event] = []
    unknown_prompts: list[str] = []
    #: 消息 id 空间：群 1000+ / 私聊 5000+ / 玩家自己的群内发言 9000+
    counters = {"group": 1000, "private": 5000, "input": 9000}
    kind_of_id: dict[int, str] = {}
    last_prompt: dict[int, str] = {}
    #: 每个玩家"最近一条群内发言"的 id —— 真实环境里由 message_router 记账，
    #: 这里替它记账，好让"撤回玩家指令"这段也能演出来
    last_input_id: dict[int, int] = {}
    private_ids: dict[int, int] = {}

    def record(kind: str, text: str, *, qq: int | None = None) -> None:
        state = runner.ctx.state or {}
        events.append(
            Event(
                kind=kind,
                text=text,
                qq=qq,
                phase=state.get("phase"),
                round=int(state.get("round") or 1),
            )
        )

    def new_id(space: str) -> int:
        counters[space] += 1
        kind_of_id[counters[space]] = space
        return counters[space]

    async def fake_broadcast(_group_id: int, message: Any, *, at: Any = None) -> int:
        record("group_bot", str(message))
        if at is not None:
            ats = [at] if isinstance(at, int) else list(at)
            for qq in ats:
                last_prompt[qq] = str(message)
        return new_id("group")

    async def fake_whisper(qq_id: int, message: Any) -> int:
        record("private_bot", str(message), qq=qq_id)
        last_prompt[qq_id] = str(message)
        new = new_id("private")
        private_ids[qq_id] = new
        return new

    async def fake_delete_message(message_id: int) -> bool:
        space = kind_of_id.get(int(message_id))
        if space == "group":
            record("group_delete", "🗑 撤回上一条群消息（看板原地更新 / 提问换人）")
        elif space == "input":
            qq = next((q for q, mid in last_input_id.items() if mid == int(message_id)), None)
            record("input_delete", "🗑 撤回玩家刚才的指令", qq=qq)
        else:
            qq = next((q for q, mid in private_ids.items() if mid == int(message_id)), None)
            record("private_delete", "🗑 撤回上一条私聊提示", qq=qq)
        return True

    def fake_last_routed(session_id: str, qq_id: int) -> int | None:  # noqa: ARG001
        return last_input_id.get(qq_id)

    async def fake_ask(
        qq_id: int,
        prompt: str | None = None,
        *,
        group_id: int | None = None,
        timeout: float | None = None,  # noqa: ARG001
        **_kwargs: Any,
    ) -> str:
        """替代 `session.ask`：**如实记录回答**，但不真的等待。

        提示现在由游戏自己发（见交互层的消息生命周期），所以这里读的是
        "刚发给我的那条提示"——和真人看到的东西完全一致。
        """
        current = prompt or last_prompt.get(qq_id, "")
        answer = scenario.answer(runner.ctx.state, qq_id, current)
        if answer == "":
            # 脚本不认识这条提示：记下来，免得"演示跑过了"却没人发现脚本已过期
            unknown_prompts.append(current.splitlines()[0][:60])
        if answer is None:
            raise GameTimeoutError(f"scripted timeout qq={qq_id}")
        if answer is QUIT:
            raise PlayerQuitError(f"scripted quit qq={qq_id}")
        record(
            "group_player" if group_id is not None else "private_player",
            str(answer),
            qq=qq_id,
        )
        if group_id is not None:
            last_input_id[qq_id] = new_id("input")
        return str(answer)

    with (
        patch.object(session, "broadcast", AsyncMock(side_effect=fake_broadcast)),
        patch.object(session, "whisper", AsyncMock(side_effect=fake_whisper)),
        patch.object(session, "ask", AsyncMock(side_effect=fake_ask)),
        patch.object(session, "delete_message", AsyncMock(side_effect=fake_delete_message)),
        patch.object(session, "last_routed_message_id", fake_last_routed),
        patch.object(game_base.GameBase, "award", AsyncMock()),
    ):
        await runner.start()
        if not runner._ended:
            await runner.end(EndReason.ABORTED)

    state = runner.ctx.state or {}
    seats = [
        {
            "seat": player["seat"],
            "nickname": player["nickname"],
            "qq": int(player["pid"]),
            "role": player["role"],
            "role_label": C.ROLE_LABELS.get(player["role"], player["role"]),
            "faction": player["faction"],
            "faction_label": "狼人阵营" if player["faction"] == C.EVIL else "好人阵营",
            "alive": player["alive"],
        }
        for player in sorted(state.get("players") or [], key=lambda p: p["seat"])
    ]

    payload_events = [
        {
            "kind": e.kind,
            "text": e.text,
            "qq": e.qq,
            "phase": e.phase,
            "phaseLabel": PHASE_LABELS.get(e.phase or "", ""),
            "round": e.round,
        }
        for e in events
    ]

    stop_index: int | None = None
    if scenario.stop_after:
        for index, event in enumerate(payload_events):
            if event["kind"] == "group_bot" and scenario.stop_after in event["text"]:
                stop_index = index
                break

    ghosts: list[dict[str, Any]] = []
    for spec_key, actor_role in scenario.ghosts:
        anchor, text_tpl, why_tpl = GHOST_SPECS[spec_key]
        actor = next((s for s in seats if s["role"] == actor_role), None)
        label = f"{actor['seat']}号 {actor['nickname']}" if actor else "该座位"
        for index, event in enumerate(payload_events):
            if anchor in event["text"]:
                ghosts.append(
                    {
                        "after": index,
                        "text": text_tpl.format(label=label),
                        "why": why_tpl.format(label=label),
                    }
                )
                break

    # ---- 不刷屏指标：群里**净留下**多少条（发出 − 撤回），撤回多少次 ----
    group_sends = sum(1 for e in events if e.kind == "group_bot")
    group_deletes = sum(1 for e in events if e.kind == "group_delete")
    input_deletes = sum(1 for e in events if e.kind == "input_delete")
    private_deletes = sum(1 for e in events if e.kind == "private_delete")

    return {
        "id": scenario.id,
        "title": scenario.title,
        "subtitle": scenario.subtitle,
        "note": scenario.note,
        "mode": scenario.mode,
        "seats": seats,
        "events": payload_events,
        "stopAfter": stop_index,
        "ghosts": ghosts,
        "winner": state.get("winner"),
        "endReason": state.get("end_reason_code"),
        "stats": {
            "groupSent": group_sends,
            "groupDeleted": group_deletes,
            "groupNet": group_sends - group_deletes,
            "inputDeleted": input_deletes,
            "privateDeleted": private_deletes,
        },
        "unknownPrompts": unknown_prompts,
    }


# =====================================================================
# 三个场景
# =====================================================================
ROSTER_6 = [
    (1001, "小明"),
    (1002, "小红"),
    (1003, "小刚"),
    (1004, "小美"),
    (1005, "阿强"),
    (1006, "丽丽"),
]
ROSTER_4 = ROSTER_6[:4]


def build_scenarios() -> list[Scenario]:
    return [
        Scenario(
            id="full",
            title="场景 A · 完整一局",
            subtitle="6 人神职局（狼人×2 · 预言家 · 女巫 · 猎人 · 平民）· 好人阵营胜利",
            note=(
                "这一局把主要交互都走了一遍：群里报名面板 → 私聊身份牌 → 夜间逐个私聊 → "
                "死讯 → 猎人开枪（公开翻牌）→ 标记发言 → 投票 → 结算。"
                "左边是群里所有人看到的，右边是每个座位自己的私聊。"
            ),
            mode="6gods",
            seed=42,
            roster=ROSTER_6,
            wolf_target_role=C.HUNTER,  # 狼刀猎人 → 触发开枪
            witch="不用",
            hunter_action="shoot",  # 猎人开枪带走一只狼
            hunter_target_role=C.WEREWOLF,
            vote_target_role=C.WEREWOLF,
        ),
        Scenario(
            id="timeout",
            title="场景 B · 夜间超时（泄露已修）",
            subtitle="狼人整夜不回应 · 群内看不到任何点名",
            note=(
                "夜间被问到的只有守卫/狼人/女巫/预言家/守墓人。"
                "所以群内一句「X 超时未响应」就等于告诉全场 X 是这几类身份之一。"
                "修复后：本人只会收到一条私聊，群里一个字都不提。"
            ),
            mode="4standard",
            seed=7,
            roster=ROSTER_4,
            wolf_target_role=C.GUARD,
            witch="不用",
            timeout_roles={C.WEREWOLF},
            stop_after="天亮了",
            ghosts=[("night_timeout", C.WEREWOLF)],
        ),
        Scenario(
            id="skip",
            title="场景 C · 猎人跳过（泄露已修）",
            subtitle="猎人被刀但选择不开枪 · 群里不知道他是猎人",
            note=(
                "「猎人开枪」本身是公开的翻牌（源项目公开死因里就有「猎人射杀」）；"
                "但「猎人选择不开枪」没有任何理由公开——公开就等于白送狼人一个身份。"
            ),
            mode="6gods",
            seed=42,
            roster=ROSTER_6,
            wolf_target_role=C.HUNTER,
            witch="不用",
            hunter_action="skip",
            vote_target_role=C.WEREWOLF,
            stop_after="天亮了",
            ghosts=[("hunter_skip", C.HUNTER)],
        ),
    ]


# =====================================================================
# 文字版（终端核对用）
# =====================================================================
def format_transcript(scenario: dict[str, Any]) -> str:
    seats = {seat["qq"]: seat for seat in scenario["seats"]}
    lines = [
        f"===== {scenario['title']} =====",
        scenario["subtitle"],
        "座位：" + "　".join(
            f"{s['seat']}号 {s['nickname']}={s['role_label']}" for s in scenario["seats"]
        ),
    ]
    stop = scenario["stopAfter"]
    ghosts = {g["after"]: g for g in scenario["ghosts"]}
    for index, event in enumerate(scenario["events"]):
        if stop is not None and index > stop:
            lines.append("…（后续略）")
            break
        kind = event["kind"]
        who = seats.get(event["qq"] or -1)
        name = f"{who['seat']}号 {who['nickname']}" if who else "?"
        if kind == "group_delete":
            lines.append("      🗑（群里撤回：看板原地更新 / 提问换人）")
            continue
        if kind == "input_delete":
            lines.append(f"      🗑（撤回 {name} 的指令）")
            continue
        if kind == "private_delete":
            lines.append(f"      🗑（撤回 {name} 的上一条私聊提示）")
            continue
        if kind == "group_bot":
            tag = "[群] 机器人" + (f" → @{name}" if who else "")
        elif kind == "group_player":
            tag = f"[群] {name}"
        elif kind == "private_bot":
            tag = f"[私聊 {name}] 机器人"
        else:
            tag = f"[私聊 {name}] {name}"
        body = "\n      ".join(event["text"].splitlines())
        lines.append(f"{tag}: {body}")
        if index in ghosts:
            lines.append(f"      ✗ 旧行为会在这里发：{ghosts[index]['text']}")
    return "\n".join(lines)


# =====================================================================
# HTML 回放页
# =====================================================================
def render_html(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return HTML_TEMPLATE.replace("__PAYLOAD__", data)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>静夜标记 · 交互回放</title>
<style>
  :root{
    --bg:#0d1117; --bg2:#141b26; --bg3:#1b2433; --line:#243044;
    --fg:#dfe7f3; --dim:#7d8da6; --acc:#6ea8fe; --wolf:#f0736a;
    --good:#5fd39a; --warn:#f0c674; --night:#8b7ff0;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:14px/1.6 "Microsoft YaHei","PingFang SC",system-ui,sans-serif}
  header{padding:14px 18px;border-bottom:1px solid var(--line);
         background:linear-gradient(180deg,#151d2b,#0f1620);position:sticky;top:0;z-index:9}
  h1{margin:0 0 4px;font-size:17px;letter-spacing:.5px}
  h1 small{color:var(--dim);font-weight:400;font-size:12px;margin-left:8px}
  .tabs{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 6px}
  .tab{padding:5px 12px;border:1px solid var(--line);border-radius:99px;
       background:var(--bg2);color:var(--dim);cursor:pointer;font-size:13px}
  .tab.on{border-color:var(--acc);color:#fff;background:#1d2c46}
  .bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;color:var(--dim);font-size:12px}
  button{background:var(--bg3);color:var(--fg);border:1px solid var(--line);
         border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px}
  button:hover{border-color:var(--acc)}
  button:disabled{opacity:.4;cursor:default}
  select{background:var(--bg3);color:var(--fg);border:1px solid var(--line);
         border-radius:6px;padding:4px 8px;font-size:12px}
  .note{margin:8px 0 0;padding:9px 12px;background:#16202f;border-left:3px solid var(--acc);
        border-radius:0 6px 6px 0;color:#b9c8dd;font-size:12.5px}
  .seats{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
  .seat{border:1px solid var(--line);border-radius:8px;padding:4px 10px;background:var(--bg2);
        font-size:12px;display:flex;gap:6px;align-items:center}
  .seat b{color:#fff}
  .seat .r{color:var(--dim)}
  .seat.wolf .r{color:var(--wolf)}
  .seat.good .r{color:var(--good)}
  .seat.dead{opacity:.45;text-decoration:line-through}
  main{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:14px;padding:14px 18px 40px}
  @media (max-width:1100px){main{grid-template-columns:1fr}}
  .pane{background:var(--bg2);border:1px solid var(--line);border-radius:10px;overflow:hidden;
        display:flex;flex-direction:column;min-height:70vh}
  .pane>h2{margin:0;padding:10px 14px;font-size:13px;border-bottom:1px solid var(--line);
           background:#131a26;color:#c9d6e8;font-weight:600}
  .pane>h2 span{color:var(--dim);font-weight:400;font-size:12px;margin-left:6px}
  .scroll{overflow-y:auto;padding:12px 14px;flex:1;max-height:78vh}
  .msg{margin:0 0 10px;display:flex;gap:8px}
  .who{flex:0 0 84px;text-align:right;color:var(--dim);font-size:12px;padding-top:2px}
  .bubble{background:var(--bg3);border:1px solid var(--line);border-radius:8px;
          padding:7px 11px;white-space:pre-wrap;word-break:break-word;max-width:100%}
  .msg.bot .bubble{background:#16202e;border-color:#26344a}
  .msg.bot .who{color:var(--acc)}
  .msg.player .bubble{background:#20304a;border-color:#2f4770;color:#eaf2ff}
  .msg.player .who{color:#9fc0f5}
  .msg.priv .bubble{background:#1a2233;border-color:#2b3purple}
  .msg.system{margin:14px 0 10px;text-align:center;color:var(--dim);font-size:11.5px}
  .msg.system em{font-style:normal;background:#1a2332;border:1px solid var(--line);
                 border-radius:99px;padding:2px 12px;letter-spacing:.5px}
  .at{color:var(--acc);font-size:11.5px}
  .ghost{margin:0 0 10px;padding:7px 11px;border:1px dashed #8a4040;border-radius:8px;
         background:#221519;color:#e79b95;font-size:12.5px;white-space:pre-wrap}
  .ghost b{color:#ffb3ad}
  .locked{filter:blur(4px);opacity:.5;user-select:none}
  .locknote{color:var(--warn);font-size:11.5px;margin:-4px 0 10px 92px}
  .privgrid{display:grid;gap:12px}
  .privcard{border:1px solid var(--line);border-radius:9px;background:#121a26;overflow:hidden}
  .privhead{padding:6px 11px;background:#151e2c;border-bottom:1px solid var(--line);
            font-size:12px;display:flex;justify-content:space-between;gap:8px}
  .privhead b{color:#fff}
  .privhead i{font-style:normal;color:var(--dim)}
  .privbody{padding:10px 11px;max-height:340px;overflow-y:auto}
  .privbody .msg{margin-bottom:8px}
  .privbody .who{flex-basis:52px;font-size:11px}
  .privbody .bubble{font-size:12.5px}
  .foot{padding:8px 18px 22px;color:var(--dim);font-size:11.5px}
  .phasehdr{margin:16px 0 10px;text-align:center}
  .phasehdr em{font-style:normal;background:#1b2740;border:1px solid #2c3d5e;color:#a9c2e8;
               border-radius:99px;padding:2px 14px;font-size:11.5px;letter-spacing:.5px}
  .delrow{margin:0 0 8px 92px;color:#6b7a90;font-size:11.5px;font-style:italic;
          border-left:2px dotted #3a4a63;padding:1px 0 1px 9px}
  .delrow.locked{filter:blur(3px)}
  .stats{margin-top:9px;padding:7px 12px;background:#141d2a;border:1px solid #22303f;
         border-left:3px solid #5fd39a;border-radius:0 6px 6px 0;font-size:12px;color:#9fb3cc}
  .stats b{color:#5fd39a}
</style>
</head>
<body>
<header>
  <h1>🌙 静夜标记 · 交互回放<small id="src"></small></h1>
  <div class="tabs" id="tabs"></div>
  <div class="bar">
    <button id="play">▶ 播放</button>
    <button id="step">⏭ 下一条</button>
    <button id="reset">↺ 重置</button>
    <span id="prog"></span>
    <span style="margin-left:auto">视角：</span>
    <select id="view"></select>
  </div>
  <div class="note" id="note"></div>
  <div class="stats" id="stats"></div>
  <div class="seats" id="seats"></div>
</header>
<main>
  <section class="pane">
    <h2>群聊<span>群里所有人都能看到这些</span></h2>
    <div class="scroll" id="group"></div>
  </section>
  <section class="pane">
    <h2>私聊<span id="privhint">只有当事人能看到的私密消息</span></h2>
    <div class="scroll" id="priv"></div>
  </section>
</main>
<div class="foot" id="foot"></div>

<script>
const DATA = __PAYLOAD__;
let sIdx = 0, cursor = 0, timer = null, view = "god";

const el = id => document.getElementById(id);
const seatsOf = s => Object.fromEntries(s.seats.map(x => [x.qq, x]));

function initTabs(){
  el("tabs").innerHTML = DATA.scenarios.map((s,i)=>
    `<div class="tab${i===sIdx?" on":""}" data-i="${i}">${s.title}</div>`).join("");
  [...document.querySelectorAll(".tab")].forEach(t=>t.onclick=()=>{
    sIdx = +t.dataset.i; reset();
  });
}
function scenario(){ return DATA.scenarios[sIdx]; }

function renderSeats(){
  const s = scenario(), byQq = seatsOf(s);
  const mine = view === "god" ? null : +view;
  el("seats").innerHTML = s.seats.map(x=>{
    const known = view === "god" || x.qq === mine;
    const cls = x.faction === "wolf" ? "wolf" : "good";
    const role = known ? x.role_label : "？";
    const dead = cursor >= s.events.length && !x.alive ? " dead" : "";
    return `<div class="seat ${cls}${dead}"><b>${x.seat}号 ${x.nickname}</b>
            <span class="r">${known ? x.faction_label+" · "+role : "身份未知"}</span></div>`;
  }).join("");
  const opts = ['<option value="god">上帝视角（全部可见）</option>']
    .concat(s.seats.map(x=>`<option value="${x.qq}"${String(x.qq)===String(view)?" selected":""}>
      ${x.seat}号 ${x.nickname} 的视角</option>`));
  el("view").innerHTML = opts.join("");
  el("privhint").textContent = view === "god"
    ? "只有当事人能看到的私密消息"
    : `（${byQq[+view] ? byQq[+view].nickname : ""} 只能看到自己那部分，其他座位的私聊对他不存在）`;
}

function phaseHeader(label){
  return `<div class="msg system"><em>${label}</em></div>`;
}
function msgHtml(kind, who, text, atName, locked){
  const cls = kind.includes("player") ? "player" : "bot";
  const lock = locked ? " locked" : "";
  const at = atName ? `<span class="at">@${atName}</span> ` : "";
  return `<div class="msg ${cls}${lock}">
      <div class="who">${who}</div>
      <div class="bubble">${at}${escapeHtml(text)}</div>
    </div>`;
}
function escapeHtml(t){
  return String(t).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
}

function appendGroup(html){ const box = el("group"); box.insertAdjacentHTML("beforeend", html); box.scrollTop = box.scrollHeight; }
function appendPriv(html){ const box = el("priv"); box.insertAdjacentHTML("beforeend", html); box.scrollTop = box.scrollHeight; }

function privCardContainer(qq, headHtml){
  let card = document.querySelector(`.privcard[data-qq="${qq}"]`);
  if(!card){
    card = document.createElement("div");
    card.className = "privcard";
    card.dataset.qq = qq;
    card.innerHTML = `<div class="privhead">${headHtml}</div><div class="privbody"></div>`;
    el("priv").appendChild(card);
  }
  return card.querySelector(".privbody");
}

function step(){
  const s = scenario();
  if(cursor >= s.events.length) return false;
  const e = s.events[cursor];
  const byQq = seatsOf(s);
  const mine = view === "god" ? null : +view;
  const prev = cursor > 0 ? s.events[cursor-1] : null;

  if(e.phaseLabel && (!prev || prev.phaseLabel !== e.phaseLabel)){
    if(e.kind.startsWith("group")) appendGroup(phaseHeader(e.phaseLabel));
    else appendPriv(phaseHeader(e.phaseLabel));
  }

  if(e.kind === "group_delete"){
    appendGroup(`<div class="delrow">${e.text}</div>`);
  } else if(e.kind === "input_delete"){
    const who = byQq[e.qq];
    appendGroup(`<div class="delrow">🗑 已撤回 ${who ? who.seat+"号 "+who.nickname : ""} 的指令
      —— 群里不留原始命令，标记内容只看板</div>`);
  } else if(e.kind === "private_delete"){
    const who = byQq[e.qq];
    if(who){
      const locked = mine !== null && who.qq !== mine;
      const body = privCardContainer(who.qq,
        `<b>${who.seat}号 ${who.nickname}</b><i>${locked ? "🔒 你看不到" : "私聊"}</i>`);
      body.insertAdjacentHTML("beforeend",
        `<div class="delrow${locked ? " locked" : ""}">🗑 撤回上一条提示（每个座位只留最新一条）</div>`);
    }
  } else if(e.kind.startsWith("group")){
    const who = e.qq ? byQq[e.qq] : null;
    const nameLbl = e.kind === "group_bot" ? "机器人" : (who ? who.nickname : "？");
    const atName = e.kind === "group_bot" && who ? `${who.seat}号 ${who.nickname}` : "";
    appendGroup(msgHtml(e.kind, nameLbl, e.text, atName, false));
  } else if(e.kind.startsWith("private")){
    const who = byQq[e.qq];
    if(!who) { cursor++; return step(); }
    const locked = mine !== null && who.qq !== mine;
    const body = privCardContainer(who.qq,
      `<b>${who.seat}号 ${who.nickname}</b><i>${locked ? "🔒 你看不到" : "私聊"}</i>`);
    const nameLbl = e.kind === "private_bot" ? "机器人" : who.nickname;
    body.insertAdjacentHTML("beforeend", msgHtml(e.kind, nameLbl, e.text, "", locked));
    body.scrollTop = body.scrollHeight;
  }

  s.ghosts.filter(g=>g.after===cursor).forEach(g=>{
    appendGroup(`<div class="ghost"><b>✗ 旧行为会在这里发（已修复）：</b>\n${escapeHtml(g.text)}
      \n${escapeHtml(g.why)}</div>`);
  });

  cursor++;
  el("prog").textContent = `${cursor} / ${s.stopAfter!==null ? s.stopAfter+1 : s.events.length} 条` +
    (s.stopAfter!==null && cursor === s.stopAfter+1 ? "（后续略）" : "");
  return cursor < (s.stopAfter!==null ? s.stopAfter+1 : s.events.length);
}

function play(){
  if(timer){ stop(); return; }
  el("play").textContent = "⏸ 暂停";
  timer = setInterval(()=>{ if(!step()) stop(); }, 700);
}
function stop(){ clearInterval(timer); timer = null; el("play").textContent = "▶ 播放"; }

function reset(){
  stop(); cursor = 0;
  el("note").innerHTML = `<b>${scenario().title}</b> · ${scenario().subtitle}<br>${scenario().note}`;
  const st = scenario().stats;
  el("stats").innerHTML = st
    ? `📉 不刷屏指标：群里净留存 <b>${st.groupNet}</b> 条`
      + `（一共发出 ${st.groupSent} 条，其中 ${st.groupDeleted} 条是"原地更新"被撤回的）`
      + `　·　另撤回玩家指令 <b>${st.inputDeleted}</b> 条`
      + `　·　私聊提示替换 <b>${st.privateDeleted}</b> 次`
    : "";
  el("group").innerHTML = ""; el("priv").innerHTML = "";
  el("foot").innerHTML = "回放由 <code>scripts/demo_silent_mark.py</code> 驱动真实引擎生成："
    + "页面上每一句机器人的话都来自 <code>SilentMarkGame</code> 实际发出的消息。"
    + (scenario().winner ? ` 结局：${scenario().winner === "evil" ? "狼人阵营胜利" : "好人阵营胜利"}。` : "");
  renderSeats();
  el("prog").textContent = `0 / ${scenario().stopAfter!==null ? scenario().stopAfter+1 : scenario().events.length} 条`;
  initTabs();
  // 统计私聊条数，先把卡片建出来，避免"空白的私聊栏"看不出这里本该有东西
  const s = scenario();
  const counts = {};
  s.events.forEach(e=>{ if(e.kind.startsWith("private")) counts[e.qq] = (counts[e.qq]||0)+1; });
  Object.keys(counts).forEach(qq=>privCardContainer(+qq, ""));
  document.querySelectorAll(".privcard").forEach(card=>{
    const qq = +card.dataset.qq;
    const who = seatsOf(s)[qq];
    const mine = view === "god" || qq === +view;
    card.querySelector(".privhead").innerHTML =
      `<b>${who.seat}号 ${who.nickname}</b><i>${mine ? counts[qq]+" 条" : "🔒 你看不到"}</i>`;
  });
  el("source") ;
}

el("play").onclick = play;
el("step").onclick = ()=>{ stop(); step(); };
el("reset").onclick = reset;
el("view").onchange = e => { view = e.target.value; reset(); };
el("src").textContent = "由真实引擎生成 · " + DATA.generatedAt;
el("view").value = "god";
reset();
</script>
</body>
</html>
"""


def main() -> None:
    # Windows 控制台默认 GBK，正文里有 emoji；不重配就会在打印时抛 UnicodeEncodeError
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    scenarios = build_scenarios()
    import asyncio

    payload: dict[str, Any] = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "scenarios": [asyncio.run(run_scenario(s)) for s in scenarios],
    }

    transcript = "\n\n".join(format_transcript(s) for s in payload["scenarios"])

    out = _ROOT / "docs" / "demo" / "silent-mark-demo.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(payload), encoding="utf-8")
    text_out = out.parent / "silent-mark-demo-transcript.txt"
    text_out.write_text(transcript, encoding="utf-8")

    if "--print" in sys.argv:
        print(transcript)

    print(f"\n✅ 回放页已生成：{out}")
    print(f"✅ 文字版已生成：{text_out}")
    for scenario in payload["scenarios"]:
        stats = scenario["stats"]
        print(
            f"   · {scenario['title']}：{len(scenario['events'])} 条事件，"
            f"{len(scenario['seats'])} 名玩家，胜方={scenario['winner']}"
        )
        print(
            f"     不刷屏：群里净留存 {stats['groupNet']} 条"
            f"（发出 {stats['groupSent']} / 撤回 {stats['groupDeleted']}）"
            f"，撤回玩家指令 {stats['inputDeleted']} 条"
        )
        if scenario["unknownPrompts"]:
            # 脚本没认出来的提示 = 脚本过期了，必须让人看见
            print(f"     ⚠️ 脚本未识别的提示 {len(scenario['unknownPrompts'])} 条：")
            for prompt in dict.fromkeys(scenario["unknownPrompts"]):
                print(f"        · {prompt}")


if __name__ == "__main__":
    main()
