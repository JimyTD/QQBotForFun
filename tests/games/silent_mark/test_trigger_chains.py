"""死亡触发链的**连锁**与交互边界（M2）。

引擎层的角色语义在 `test_roles.py` / `test_resolve.py` 里已经锁死了；
这里锁的是只有跑完整主循环才暴露的东西：

- 谁能触发谁（猎人的枪 / 白狼王的带人 / 骑士的决斗）；
- **技能造成死亡之后必须立刻判胜负**（源项目曾漏）；
- "认输 / 挂机 / 已出局的人"这些边界（认输也是出局，必须走同一条死亡链）；
- "绝不原地等待"：所有座位全挂机时，兜底也必须把局面推到分胜负。
"""

from __future__ import annotations

from unittest.mock import patch

from core import session
from src.plugins.games.silent_mark.engine import constants as C  # noqa: N812
from src.plugins.games.silent_mark.engine.types import find_player
from src.plugins.games.silent_mark.game import SilentMarkGame
from src.testing.harness import GameTestHarness

from .test_game_flow import FakePlayer

PLAYERS6 = [1001, 1002, 1003, 1004, 1005, 1006]
PLAYERS8 = [*PLAYERS6, 1007, 1008]
PLAYERS9 = [*PLAYERS8, 1009]


async def _play_chain(
    fake: FakePlayer, *, mode: str, players: list[int]
) -> GameTestHarness:
    """跑一局并返回 harness（与 `test_game_flow._play` 同构，只是能指定人数）。"""
    harness = GameTestHarness(
        SilentMarkGame, players=players, config={"mode": mode, "seed": 7}
    )
    fake.harness = harness
    async with harness:
        with patch.object(session, "ask", fake.ask):
            await harness.start()
    return harness


def _causes(harness: GameTestHarness) -> list[str]:
    assert harness.runner is not None
    return [death["cause"] for death in harness.runner.ctx.state["history"]["deaths"]]


def _state(harness: GameTestHarness) -> dict:
    assert harness.runner is not None
    return harness.runner.ctx.state


# =====================================================================
# 触发链的连锁
# =====================================================================
async def test_wolf_king_drag_chains_into_the_hunters_shot():
    """三连链：白狼王被放逐 → 带走猎人 → 猎人开枪带走一只狼。

    这条锁的是"技能造成的死亡**继续触发**"：源项目把新触发插到队首，
    所以在同一天里可以连着结算下去，不会漏掉第二个技能。
    """
    fake = FakePlayer(
        wolf_target_role=C.VILLAGER,
        vote_target_role=C.WOLF_KING,
        wolf_king_drag=True,
        wolf_king_target_role=C.HUNTER,
        hunter_shoots=True,
        hunter_target_role=C.WEREWOLF,
    )
    harness = await _play_chain(fake, mode="8wolfking", players=PLAYERS8)

    causes = _causes(harness)
    assert C.DEATH_EXILED in causes  # 白狼王被放逐
    assert C.DEATH_WOLF_KING_DRAG in causes  # 白狼王带走了猎人
    assert C.DEATH_SHOT in causes  # 猎人反手带走一只狼

    state = _state(harness)
    shot = next(d for d in state["history"]["deaths"] if d["cause"] == C.DEATH_SHOT)
    victim = find_player(state, shot["pid"])
    assert victim is not None and victim["role"] in C.WOLF_ROLES


async def test_hunter_shot_does_not_let_the_wolf_king_drag():
    """**只有被放逐**的白狼王能带人：被开枪打死不能带（源项目 `onDeath` 只认 exiled）。"""
    fake = FakePlayer(
        wolf_target_role=C.HUNTER,
        hunter_shoots=True,
        hunter_target_role=C.WOLF_KING,
        vote_target_role=C.WEREWOLF,
    )
    harness = await _play_chain(fake, mode="8wolfking", players=PLAYERS8)

    causes = _causes(harness)
    assert C.DEATH_SHOT in causes
    assert C.DEATH_WOLF_KING_DRAG not in causes

    state = _state(harness)
    shot = next(d for d in state["history"]["deaths"] if d["cause"] == C.DEATH_SHOT)
    victim = find_player(state, shot["pid"])
    assert victim is not None and victim["role"] == C.WOLF_KING


async def test_skill_death_is_checked_for_win_immediately():
    """技能造成死亡后**立刻**判胜负：白狼王带走最后一个平民 → 屠边，当场结束。

    源项目曾漏掉"触发后再判一次"，于是要靠下一夜才结束（多跑一整个白天）。
    """
    fake = FakePlayer(
        wolf_target_role=C.VILLAGER,  # 夜里杀一个平民（还剩 1 个）
        vote_target_role=C.WOLF_KING,  # 白天把白狼王投出去
        wolf_king_drag=True,
        wolf_king_target_role=C.VILLAGER,  # 带走最后一个平民 → 屠边成立
    )
    harness = await _play_chain(fake, mode="8wolfking", players=PLAYERS8)

    state = _state(harness)
    assert state["winner"] == C.EVIL
    assert state["end_reason_code"] == "villagers_eliminated"
    assert harness.broadcasts_contain("所有平民已出局")
    # 只跑过第 1 轮的标记：第 2 轮还没开始就结束了
    rounds = {mark["round"] for mark in state["history"]["marks"]}
    assert rounds == {1}


async def test_knight_duel_kills_the_wolf_and_only_once():
    """骑士决斗狼 → 狼死、骑士活；而且**全局只问一次**。"""
    fake = FakePlayer(
        wolf_target_role=C.VILLAGER,
        knight_duels=True,
        knight_target_role=C.WEREWOLF,
        vote_target_role=C.WEREWOLF,
    )
    harness = await _play_chain(fake, mode="8knight", players=PLAYERS8)

    state = _state(harness)
    duels = [d for d in state["history"]["deaths"] if d["cause"] == C.DEATH_DUEL]
    assert len(duels) == 1
    victim = find_player(state, duels[0]["pid"])
    assert victim is not None and victim["role"] in C.WOLF_ROLES

    knight = next(p for p in state["players"] if p["role"] == C.KNIGHT)
    assert knight["alive"] is True
    assert sum(1 for prompt in fake.prompts_seen if "决斗" in prompt) == 1


async def test_knight_duel_against_a_good_player_kills_the_knight():
    """决斗好人 → 骑士自己出局（源项目：目标是狼则对方死，否则自己死）。"""
    fake = FakePlayer(
        wolf_target_role=C.VILLAGER,
        knight_duels=True,
        knight_target_role=C.VILLAGER,
    )
    harness = await _play_chain(fake, mode="8knight", players=PLAYERS8)

    state = _state(harness)
    knight = next(p for p in state["players"] if p["role"] == C.KNIGHT)
    duels = [d for d in state["history"]["deaths"] if d["cause"] == C.DEATH_DUEL]
    assert len(duels) == 1 and duels[0]["pid"] == knight["pid"]
    assert knight["alive"] is False


# =====================================================================
# 出局后的边界
# =====================================================================
async def test_poisoned_hunter_never_shoots_and_is_never_mentioned():
    """被毒死的猎人不能开枪，而且**群内一句都不提**（提了就等于公开"他是猎人"）。"""
    fake = FakePlayer(
        wolf_target_role=C.SEER,
        witch_poison_role=C.HUNTER,
    )
    harness = await _play_chain(fake, mode="6gods", players=PLAYERS6)

    state = _state(harness)
    hunter = next(p for p in state["players"] if p["role"] == C.HUNTER)
    assert hunter["alive"] is False
    assert hunter["role_state"]["can_shoot"] is False
    assert C.DEATH_SHOT not in _causes(harness)
    assert not harness.broadcasts_contain("开枪")


async def test_resigning_hunter_does_not_shoot():
    """认输**不触发任何技能**（源项目 `handleResign` 的明示意图）。

    认输是主动弃权，不能反过来当成一次"死亡触发"去开枪/带人。
    （我在 M2 一度按"死亡链对所有出局方式一视同仁"改成会开枪，核对源项目后改回。）
    遗物公开那一半仍然成立，另见 `test_quit_token_resigns_and_reveals_relics`。
    """
    fake = FakePlayer(
        wolf_target_role=C.SEER,
        quit_as_role=C.HUNTER,
        hunter_shoots=True,
        hunter_target_role=C.WEREWOLF,
    )
    harness = await _play_chain(fake, mode="6gods", players=PLAYERS6)

    causes = _causes(harness)
    assert C.DEATH_RESIGNED in causes
    assert C.DEATH_SHOT not in causes

    # 弃权出局的人不该再"被默认标记"
    state = _state(harness)
    hunter = next(p for p in state["players"] if p["role"] == C.HUNTER)
    assert all(mark["player"] != hunter["pid"] for mark in state["history"]["marks"])


async def test_resigning_guard_produces_no_night_action():
    """认输发生在夜里：死人不能再守护别人（否则守卫死了还能保护）。"""
    fake = FakePlayer(quit_as_role=C.GUARD)  # 4 人标准局：守卫是第一个夜间行动者
    harness = await _play_chain(fake, mode="4standard", players=PLAYERS6[:4])

    state = _state(harness)
    guard = next(p for p in state["players"] if p["role"] == C.GUARD)
    assert guard["alive"] is False
    assert state["history"]["rounds"][0].get("guard") is None


async def test_gravedigger_is_only_asked_when_someone_is_dead():
    """守墓人：当夜无人可验就**不打搅**；有死者时必须验一个人。"""
    fake = FakePlayer(wolf_target_role=C.VILLAGER)
    harness = await _play_chain(fake, mode="9grave", players=PLAYERS9)

    state = _state(harness)
    rounds = state["history"]["rounds"]
    # 第 1 夜开局前没有死者 → 自动跳过（记为 target=None，表示"问过了、无事可做"）
    assert rounds[0]["gravedigger"] == {"target": None}
    # 第 2 夜有人可验了 → 必须验一个
    assert rounds[1]["gravedigger"]["target"] is not None
    assert any("验尸" in prompt for prompt in fake.prompts_seen)


async def test_fool_immunity_blocks_one_exile_then_he_dies_normally():
    """白痴：第一次被放逐免疫（**不算出局、不进触发链**），第二次正常出局。"""
    fake = FakePlayer(
        wolf_target_role=C.SEER,  # 夜里别把平民杀光，好让白天能投两次
        vote_target_role=C.FOOL,
    )
    harness = await _play_chain(fake, mode="8knight", players=PLAYERS8)

    state = _state(harness)
    fool = next(p for p in state["players"] if p["role"] == C.FOOL)
    assert fool["role_state"]["immunity_used"] is True
    assert fool["alive"] is False
    exiles = [
        d
        for d in state["history"]["deaths"]
        if d["pid"] == fool["pid"] and d["cause"] == C.DEATH_EXILED
    ]
    assert len(exiles) == 1  # 免疫那次没被记成出局
    assert harness.broadcasts_contain("免疫")


# =====================================================================
# 绝不原地等待
# =====================================================================
async def test_all_seats_timing_out_still_reaches_a_verdict():
    """所有座位全挂机（等同于 AI 座位全部超时）：兜底必须把局面推到分胜负。

    真人不设超时，所以"僵住"是可接受的；但**兜底本身不能卡**——
    源项目曾经因为"兜底也被拒"而阶段永久停摆。
    """
    fake = FakePlayer(timeout_all=True)
    harness = await _play_chain(fake, mode="4standard", players=PLAYERS6[:4])

    assert harness.runner is not None
    assert harness.runner._ended is True
    # 兜底有界：不能靠无限重问卡住（每个动作最多问 1+retry_rounds 次）
    assert len(fake.ask_timeouts) < 200
