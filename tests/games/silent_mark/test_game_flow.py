"""单局端到端：4 人局跑通两种结局，以及几条硬约束。

做法：用 `src/testing/harness.py` 拦掉 broadcast/whisper，再给 `session.ask`
装一个"看得见状态"的假玩家。这样测试不依赖随机身份，也不会真的等 60 秒超时。

假玩家是**全知**的（直接读 ctx.state 决定怎么答），这在集成测试里是合理的：
它扮演"一个知道自己在干什么的玩家"。要验证真人视角的信息隔离，看
`test_private_info.py`。
"""

from __future__ import annotations

from unittest.mock import patch

from core import session
from src.plugins.games.silent_mark.ai import controller as ai_controller
from core.errors import PlayerQuitError, WhisperFailedError
from core.errors import TimeoutError as GameTimeoutError
from src.plugins.games.silent_mark.engine import constants as C  # noqa: N812
from src.plugins.games.silent_mark.engine.resolve import get_evaluation_mark_count
from src.plugins.games.silent_mark.engine.roles import create_role
from src.plugins.games.silent_mark.engine.types import find_player
from src.plugins.games.silent_mark.game import SilentMarkGame
from src.testing.harness import GameTestHarness

PLAYERS = [1001, 1002, 1003, 1004]

#: 各动作提示里的关键词（与 `syntax.TARGET_PROMPT_TITLES` 对应）
GUARD_HINT = "守护目标"
WOLF_HINT = "袭击目标"
WITCH_HINT = "女巫用药"
VOTE_HINT = "放逐"
MARK_HINT = "标记发言"


class FakePlayer:
    """按提示关键词作答的假玩家。"""

    def __init__(
        self,
        *,
        wolf_target_role: str = C.VILLAGER,
        witch: str = "不用",
        witch_poison_role: str | None = None,
        vote_wolf: bool = True,
        vote_target_role: str | None = None,
        quit_as_role: str | None = None,
        timeout_as_role: str | None = None,
        timeout_all: bool = False,
        hunter_shoots: bool = False,
        hunter_target_role: str = C.WEREWOLF,
        wolf_king_drag: bool = False,
        wolf_king_target_role: str = C.VILLAGER,
        knight_duels: bool = False,
        knight_target_role: str = C.WEREWOLF,
    ) -> None:
        self.wolf_target_role = wolf_target_role
        self.witch = witch
        #: 指定"毒某个角色"（座位号由当局座位决定，写死会飘）
        self.witch_poison_role = witch_poison_role
        self.vote_wolf = vote_wolf
        #: 指定投票目标角色（默认投狼；白痴/白狼王用例要投别人）
        self.vote_target_role = vote_target_role
        self.quit_as_role = quit_as_role
        self.timeout_as_role = timeout_as_role
        #: 所有座位都挂机（用来测"兜底必须一直推进，绝不原地等待"）
        self.timeout_all = timeout_all
        self.hunter_shoots = hunter_shoots
        self.hunter_target_role = hunter_target_role
        self.wolf_king_drag = wolf_king_drag
        self.wolf_king_target_role = wolf_king_target_role
        self.knight_duels = knight_duels
        self.knight_target_role = knight_target_role
        self.harness: GameTestHarness | None = None
        self.unknown_prompts: list[str] = []
        #: 每次被问时 `session.ask` 收到的时限（用来锁"真人无超时"）
        self.ask_timeouts: list[float | None] = []
        #: 见过的全部提问（不只是最后一次）——用来断言"某个座位什么时候被问过"
        self.prompts_seen: list[str] = []

    async def ask(
        self,
        qq_id: int,
        prompt: str | None = None,
        *,
        group_id: int | None = None,
        timeout: float | None = None,  # noqa: ASYNC109 — 与 session.ask 的真实签名保持一致
        **_kwargs: object,
    ) -> str:
        """替代 `session.ask`：不阻塞、按当前状态作答。

        提示由游戏侧自己发（见交互层的消息生命周期），所以这里像真人一样
        **去读刚发给自己的那条提示**，而不是从 `ask` 的参数里拿。
        """
        text = prompt or self._last_prompt(qq_id)
        self.ask_timeouts.append(timeout)
        self.prompts_seen.append(text)
        state = self._state()
        pid = str(qq_id)
        player = find_player(state, pid)

        if player is not None:
            if self.timeout_all or (
                self.timeout_as_role and player["role"] == self.timeout_as_role
            ):
                raise GameTimeoutError("fake timeout")
            if self.quit_as_role and player["role"] == self.quit_as_role:
                raise PlayerQuitError("fake quit")

        return self._answer(state, pid, text)

    # ---- 内部 ----
    def _last_prompt(self, qq_id: int) -> str:
        """最近一条发给我的提示（群内提问带 at / 私聊提问就是 whisper）。"""
        assert self.harness is not None
        return self.harness.prompts.get(qq_id, "")

    def _state(self) -> dict:
        assert self.harness is not None and self.harness.runner is not None
        return self.harness.runner.ctx.state

    def _seat_of(self, pid: str | None) -> str:
        if pid is None:
            return "跳过"
        player = find_player(self._state(), pid)
        return str(player["seat"]) if player else "跳过"

    def _pick_by_role(self, state: dict, self_pid: str, role: str) -> str | None:
        """挑一个存活的指定角色；挑不到就退回第一个存活的其他玩家。

        ⚠️ 不能用 `get_available_targets`：猎人/白狼王/骑士都不是夜间角色，
        那个函数对它们恒为空（M1c 里"玩家答了也不生效"就是踩在这里）。
        """
        others = [p for p in state["players"] if p["alive"] and p["pid"] != self_pid]
        for player in others:
            if player["role"] == role:
                return player["pid"]
        return others[0]["pid"] if others else None

    def _answer(self, state: dict, pid: str, prompt: str) -> str:
        player = find_player(state, pid)
        if player is None:
            self.unknown_prompts.append(prompt)
            return ""

        role_impl = create_role(player["role"])
        allowed = role_impl.get_available_targets(state, player)

        if WITCH_HINT in prompt:
            if self.witch_poison_role:
                return f"毒 {self._seat_of(self._pick_by_role(state, pid, self.witch_poison_role))}"
            return self.witch
        if GUARD_HINT in prompt:
            return self._seat_of(pid)  # 第一夜守自己：合法且确定性
        if WOLF_HINT in prompt:
            victim = next(
                (
                    p["pid"]
                    for p in state["players"]
                    if p["alive"] and p["role"] == self.wolf_target_role
                ),
                None,
            )
            if victim is None or victim not in allowed:
                victim = allowed[0] if allowed else None
            return self._seat_of(victim)
        if player["role"] == C.SEER and "查验" in prompt:
            return self._seat_of(allowed[0] if allowed else None)
        if player["role"] == C.GRAVEDIGGER and "验尸" in prompt:
            return "跳过"
        if VOTE_HINT in prompt:
            if self.vote_target_role:
                return self._seat_of(
                    self._pick_by_role(state, pid, self.vote_target_role)
                )
            wolf = next(
                (
                    p["pid"]
                    for p in state["players"]
                    if p["alive"] and p["role"] in C.WOLF_ROLES
                ),
                None,
            )
            # 投票不是"夜间技能"，`get_available_targets` 对平民/预言家等恒为空，
            # 所以这里按"存活且不是自己"来挑，不然会退化成弃票、测不到真实投票路径。
            others = [
                p["pid"] for p in state["players"] if p["alive"] and p["pid"] != pid
            ]
            if self.vote_wolf and wolf is not None and wolf in others:
                return self._seat_of(wolf)
            return self._seat_of(others[0] if others else None)
        # ⚠️ 顺序要紧：猎人标题是"开枪带走"，白狼王标题是"带走"，先判猎人
        if "开枪" in prompt:
            if not self.hunter_shoots:
                return "跳过"
            return self._seat_of(
                self._pick_by_role(state, pid, self.hunter_target_role)
            )
        if "带走" in prompt:
            if not self.wolf_king_drag:
                return "跳过"
            return self._seat_of(
                self._pick_by_role(state, pid, self.wolf_king_target_role)
            )
        if "决斗" in prompt:
            if not self.knight_duels:
                return "跳过"
            return self._seat_of(
                self._pick_by_role(state, pid, self.knight_target_role)
            )
        if MARK_HINT in prompt:
            return self._mark_line(state, pid)

        self.unknown_prompts.append(prompt)
        return ""

    @staticmethod
    def _mark_line(state: dict, pid: str) -> str:
        """按当局要求的数量生成一行式标记（把狼标成狼人）。"""
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


async def _play(
    fake: FakePlayer,
    *,
    mode: str = "4standard",
    seed: int = 7,
    players: list[int] | None = None,
) -> GameTestHarness:
    harness = GameTestHarness(
        SilentMarkGame,
        players=players or PLAYERS,
        config={"mode": mode, "seed": seed},
    )
    fake.harness = harness
    async with harness:
        with patch.object(session, "ask", fake.ask):
            await harness.start()
    return harness


# =====================================================================
# 两种结局
# =====================================================================
async def test_wolf_wins_by_eliminating_the_last_villager():
    """4 人标准局（屠边）里狼人杀掉唯一的平民 → 首夜结算即狼人胜。"""
    fake = FakePlayer(wolf_target_role=C.VILLAGER, witch="不用")
    harness = await _play(fake)

    assert fake.unknown_prompts == []
    assert harness.broadcasts_contain("游戏结束")
    assert harness.broadcasts_contain("狼人阵营胜利")
    assert harness.broadcasts_contain("所有平民已出局")
    # 首夜就结束：不应该进入标记阶段
    assert not harness.broadcasts_contain("标记发言")


async def test_good_wins_by_exiling_the_wolf():
    """狼人砍到自己守住的守卫（平安夜），白天全员投票放逐狼人 → 好人胜。"""
    fake = FakePlayer(wolf_target_role=C.GUARD, witch="不用", vote_wolf=True)
    harness = await _play(fake)

    assert fake.unknown_prompts == []
    assert harness.broadcasts_contain("平安夜")
    assert harness.broadcasts_contain("标记发言")
    assert harness.broadcasts_contain("被放逐出局")
    assert harness.broadcasts_contain("好人阵营胜利")
    assert harness.broadcasts_contain("所有狼人已出局")


# =====================================================================
# 开局与硬约束
# =====================================================================
async def test_every_player_gets_a_private_role_card():
    fake = FakePlayer()
    harness = await _play(fake)

    cards = [(qq, text) for qq, text in harness.whispers if "你的身份牌" in text]
    assert {qq for qq, _ in cards} == set(PLAYERS)


async def test_whisper_failure_aborts_before_the_first_night():
    """私聊不可达 → 点名劝退整局，绝不带着"没收到身份牌"的人开局。"""
    fake = FakePlayer()
    harness = GameTestHarness(
        SilentMarkGame, players=PLAYERS, config={"mode": "4standard"}
    )
    fake.harness = harness

    async with harness:
        with (
            patch.object(
                session, "whisper", side_effect=WhisperFailedError("对方未添加机器人为好友")
            ),
            patch.object(session, "ask", fake.ask),
        ):
            await harness.start()

    assert harness.broadcasts_contain("身份牌私聊失败")
    assert not harness.broadcasts_contain("天黑请闭眼")
    assert harness.runner is not None and harness.runner._ended is True


async def test_night_timeout_goes_to_fallback_without_leaking_in_the_group():
    """夜间超时：兜底继续推进，但**群内一个字都不能提**。

    公开一句"X 超时未响应"等于宣布 X 是守卫/狼人/女巫/预言家/守墓人之一——
    这是信息防火墙里最容易被忽略、后果最严重的一条（12 人局直接锁死一片身份）。
    """
    fake = FakePlayer(timeout_as_role=C.WEREWOLF)
    harness = await _play(fake)

    assert harness.runner is not None and harness.runner._ended is True
    wolf = next(
        p for p in harness.runner.ctx.state["players"] if p["role"] == C.WEREWOLF
    )
    assert any(
        qq == int(wolf["pid"]) and "超时未收到你的回复" in text
        for qq, text in harness.whispers
    )
    # 精确窗口断言：**到"第 1 夜结算"为止**一条公开超时都不能有。
    # （之后进入标记/投票，狼人超时是要公开点名的——那是公开动作，不算泄露。）
    assert not harness.broadcasts_contain("无法私聊")
    night_end = next(
        (
            index
            for index, text in enumerate(harness.broadcasts)
            if "第 1 夜" in text and "结算" in text
        ),
        len(harness.broadcasts),
    )
    leaked = [text for text in harness.broadcasts[:night_end] if "超时" in text]
    assert not leaked, f"夜间泄露了公开点名：{leaked}"


async def test_public_timeout_is_still_announced_in_the_group():
    """公开动作（标记）超时照旧群内点名：这不是泄露，也是催人的手段。"""
    fake = FakePlayer(wolf_target_role=C.GUARD, witch="不用", timeout_as_role=C.VILLAGER)
    harness = await _play(fake)

    assert harness.broadcasts_contain("超时未响应，已按默认处理")
    assert harness.broadcasts_contain("已按默认标记处理")


async def test_hunter_skip_is_confirmed_privately_and_never_announced():
    """猎人"选择不开枪"不能公开：公开 = 当众给这个座位翻牌"他是猎人"。

    真的开枪带走人才公开——那时公开是设计预期的翻牌（源项目公开死因里就有"猎人射杀"）。
    """
    fake = FakePlayer(wolf_target_role=C.HUNTER, witch="不用")
    harness = await _play(fake, mode="6gods", players=[1001, 1002, 1003, 1004, 1005, 1006])

    assert harness.runner is not None and harness.runner._ended is True
    hunter = next(p for p in harness.runner.ctx.state["players"] if p["role"] == C.HUNTER)
    assert not harness.broadcasts_contain("选择不开枪")
    assert any(
        qq == int(hunter["pid"]) and "你选择不开枪" in text
        for qq, text in harness.whispers
    )


async def test_hunter_actually_shoots_after_dying():
    """猎人**真的开了枪**：死亡触发链里"本人已出局"绝不能把输入作废掉。

    这条锁的是一个真实 bug：`_ask` 曾经把"该座位当前已出局"当成"输入作废"，
    可死亡触发链（猎人开枪 / 白狼王带人）本身就是"死后才行动"——
    于是技能永远拿不到输入，玩家答了也不生效，触发链形同虚设。
    （旧测试全是答"跳过"，正好把这个洞盖住了。）
    """
    fake = FakePlayer(wolf_target_role=C.HUNTER, witch="不用", hunter_shoots=True)
    harness = await _play(
        fake, mode="6gods", players=[1001, 1002, 1003, 1004, 1005, 1006]
    )

    assert harness.runner is not None
    state = harness.runner.ctx.state
    shot = [d for d in state["history"]["deaths"] if d["cause"] == C.DEATH_SHOT]
    assert len(shot) == 1
    victim = next(p for p in state["players"] if p["pid"] == shot[0]["pid"])
    assert victim["role"] in C.WOLF_ROLES
    assert victim["alive"] is False
    # 开枪是**公开**翻牌：群内必须有死讯（与"跳过"必须静默正好相反）
    assert harness.broadcasts_contain("开枪")


async def test_quit_token_resigns_and_reveals_relics():
    """`退出` 会被 `session.ask` 翻成 PlayerQuitError → 视为认输出局，**遗物必须公开**。

    这条锁的是源项目 502ef26 的教训：认输路径曾漏掉遗物公开，变成"用认输藏遗物"。
    """
    fake = FakePlayer(quit_as_role=C.GUARD)
    harness = await _play(fake)

    assert harness.runner is not None
    state = harness.runner.ctx.state
    guard = next(p for p in state["players"] if p["role"] == C.GUARD)

    assert guard["alive"] is False
    assert any(d["cause"] == C.DEATH_RESIGNED for d in state["history"]["deaths"])
    assert all(item["revealed"] for item in guard["items"])
    assert harness.broadcasts_contain("遗物")


# =====================================================================
# 超时原则：AI 有超时，真实玩家没有
# =====================================================================
async def test_humans_are_never_timed_out():
    """大原则：**真人没有超时** —— 每个真人座位的等待时限都必须是 None。"""
    fake = FakePlayer()
    await _play(fake)

    assert fake.ask_timeouts, "假玩家一次都没被问过？"
    assert set(fake.ask_timeouts) == {None}


async def test_ai_seats_are_bounded_and_never_touch_the_human_channel():
    """AI 补位必须有界，而且**不经过真人的 `session.ask` 通道**。

    机制在 M4 变了，这条测试跟着改口径（原来断言"AI 的 ask 超时不为 None"）：

    - AI 不走 `session.ask` —— 那通道问了也没人回（AI 没有 QQ 号）；
    - AI 的时限由 `_ai_budget()` + `controller.with_budget()` 负责（有单测）；
    - 这里**刻意不 mock `llm.chat`**：真实环境就是"没有可用 LLM"，
      用来验证 LLM 全程不可用时，对局照样能靠确定性兜底收场。
    """
    original = SilentMarkGame._assign_players

    def assign_all_ai(self, ctx, settings, rng):
        players = original(self, ctx, settings, rng)
        for player in players:
            player["ai"] = True
        return players

    fake = FakePlayer()
    with (
        patch.object(SilentMarkGame, "_assign_players", assign_all_ai),
        patch.object(ai_controller, "delay_seconds", lambda *a, **k: 0.0),
    ):
        harness = await _play(fake)

    assert harness.runner is not None and harness.runner._ended is True
    assert fake.ask_timeouts == [], "AI 座位跑到真人通道上去了"


# =====================================================================
# 不刷屏（群里：看板原地更新 + 关键事件才单独发）
# =====================================================================
async def test_group_messages_do_not_accumulate():
    """群消息**净条数**（发出 − 撤回）必须很少：状态靠"原地更新的看板"表达。

    两条硬指标：
    ① 看板真的被反复替换（有撤回），否则说明还是每条状态新发一条消息；
    ② 净留存量有上限（不随回合增长）。
    """
    fake = FakePlayer(wolf_target_role=C.GUARD, witch="不用")
    harness = await _play(fake)

    assert len(harness.deletes) >= 3, "看板没有被原地更新过？"
    net = len(harness.broadcasts) - len(harness.deletes)
    assert net <= 10, f"群里净留下 {net} 条消息，还是太多：{harness.broadcasts}"


async def test_no_idle_chatter_in_the_group():
    """可回的废话一律不发（用户点名要求删掉的就是"✅ X 已投票"）。"""
    fake = FakePlayer(wolf_target_role=C.GUARD, witch="不用")
    harness = await _play(fake)

    assert not any("已投票" in text for text in harness.broadcasts)
    # 投票进度同样是废话：中间态对玩家零信息量，票型在明细里一次性公布
    assert not any("已收" in text for text in harness.broadcasts)
    # 标记结果也不再逐人播报——它们进看板（看板里能看到"本轮标记"）
    assert not any(text.startswith("📌") for text in harness.broadcasts)
    board = next((m for m in harness.broadcasts if "本轮标记" in m), "")
    assert "声明好人" in board, "标记记录没有进看板"


async def test_player_command_message_is_recalled():
    """玩家自己的指令消息发完就撤回（群里不留原始命令）——深海任务的同款做法。"""
    fake = FakePlayer()
    harness = GameTestHarness(
        SilentMarkGame, players=PLAYERS, config={"mode": "4standard", "seed": 7}
    )
    fake.harness = harness

    async with harness:
        with patch.object(session, "ask", fake.ask):
            await harness.start()
        assert harness.runner is not None
        with patch.object(session, "last_routed_message_id", lambda *_args: 4242):
            await SilentMarkGame()._delete_user_input(harness.runner.ctx, PLAYERS[0])

    assert 4242 in harness.deletes
