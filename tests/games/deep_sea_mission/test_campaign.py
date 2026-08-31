"""深海任务 · 战役模式测试。"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

from core.types import GameContext, User, new_session_id
from src.plugins.games.deep_sea_mission.campaign import (
    ASG_ALL_ONE_CREW,
    ASG_CAPTAIN_ALL,
    ASG_HARDEST_TO_CAPTAIN,
    ASG_SELF_NOMINATE_1,
    ASG_SELF_NOMINATE_2,
    MOD_CURRENTS,
    MOD_RAPTURE,
    MOD_SILENCE,
    CAMPAIGN_MISSIONS,
    fixed_tasks_m32,
    get_mission,
    parse_campaign_arg,
    parse_campaign_progress,
)
from src.plugins.games.deep_sea_mission.game import DeepSeaMissionGame
from src.testing.harness import GameTestHarness


FIXED_HANDS = {
    "1": ["blue:1", "blue:2"],
    "2": ["blue:3", "yellow:1"],
    "3": ["sub:4", "yellow:2"],
}
FIXED_TASKS = [
    {"id": "T001", "text": "任务A", "difficulty": 1, "assigned_to": None, "completed": False},
    {"id": "T002", "text": "任务B", "difficulty": 2, "assigned_to": None, "completed": False},
]


def _patch_common(monkeypatch, *, hands: dict | None = None):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "src.plugins.games.deep_sea_mission.game.build_deck",
        lambda rng=None: [],
    )
    monkeypatch.setattr(
        "src.plugins.games.deep_sea_mission.game.deal",
        lambda deck, player_ids: {k: list(v) for k, v in (hands or FIXED_HANDS).items()},
    )
    monkeypatch.setattr(
        "src.plugins.games.deep_sea_mission.game.draw_tasks",
        lambda difficulty, player_count, rng=None: [dict(t) for t in FIXED_TASKS],
    )
    monkeypatch.setattr(
        "src.plugins.games.deep_sea_mission.game.get_group_config",
        AsyncMock(return_value="1"),
    )
    set_cfg = AsyncMock()
    monkeypatch.setattr(
        "src.plugins.games.deep_sea_mission.game.set_group_config",
        set_cfg,
    )
    return set_cfg


def _make_ctx(state: dict) -> GameContext:
    return GameContext(
        session_id=new_session_id(),
        game_id="deep_sea_mission",
        group_id=9999,
        host_id=1,
        players=[User(qq_id=p, nickname=f"P{p}", group_id=9999) for p in (1, 2, 3)],
        started_at=datetime.utcnow(),
        config={},
        state=state,
    )


# ==================== 数据层 ====================


def test_campaign_has_32_missions() -> None:
    assert len(CAMPAIGN_MISSIONS) == 32
    assert sorted(CAMPAIGN_MISSIONS) == list(range(1, 33))


def test_no_difficulty_missions() -> None:
    for no in (8, 12, 21, 23, 27):
        m = get_mission(no)
        assert m.difficulty is None
        assert m.task_source == "none"
        assert m.special


def test_special_symbols() -> None:
    assert MOD_CURRENTS in get_mission(9).modifiers
    assert MOD_RAPTURE in get_mission(11).modifiers
    assert MOD_SILENCE in get_mission(16).modifiers
    assert "unfamiliar" in get_mission(20).modifiers


def test_assignments() -> None:
    assert get_mission(6).assignment == ASG_ALL_ONE_CREW
    assert get_mission(10).assignment == ASG_CAPTAIN_ALL
    assert get_mission(14).assignment == ASG_SELF_NOMINATE_1
    assert get_mission(19).assignment == ASG_HARDEST_TO_CAPTAIN
    assert get_mission(26).assignment == ASG_SELF_NOMINATE_2


def test_m32_fixed_tasks() -> None:
    tasks = fixed_tasks_m32(4)
    assert len(tasks) == 4
    assert [t["id"] for t in tasks] == ["T074", "T088", "T085", "T080"]


def test_parse_campaign_progress() -> None:
    assert parse_campaign_progress("1") == (1, None)
    assert parse_campaign_progress("32") == (32, None)
    assert parse_campaign_progress("epilogue:18") == (None, 18)
    assert parse_campaign_progress("") == (1, None)
    assert parse_campaign_progress("33") == (1, None)
    assert parse_campaign_progress("abc") == (1, None)


def test_parse_campaign_arg() -> None:
    assert parse_campaign_arg("5") == (5, None)
    assert parse_campaign_arg("32") == (32, None)
    assert parse_campaign_arg("epilogue:18") == (None, 18)
    assert parse_campaign_arg("33") is None
    assert parse_campaign_arg("abc") is None
    assert parse_campaign_arg("") is None


# ==================== 无难度关约束校验 ====================


def test_check_value_gap_m8() -> None:
    game = DeepSeaMissionGame()
    ctx = _make_ctx(
        {
            "mode": "campaign",
            "mission": {"no": 8},
            "order": ["1", "2", "3"],
            "won_tricks": {
                "1": [{"no": 1, "cards": ["pink:9", "blue:9"]}],
                "2": [{"no": 2, "cards": ["blue:1"]}],
                "3": [],
            },
        }
    )
    result = game._check_no_difficulty_constraints(ctx)
    assert result is not None
    assert "9" in result


def test_check_no_pink_or_sub_lead_m12() -> None:
    game = DeepSeaMissionGame()
    ctx = _make_ctx(
        {
            "mode": "campaign",
            "mission": {"no": 12},
            "order": ["1", "2", "3"],
            "trick_history": [
                {"no": 1, "plays": [{"player": 1, "card": "pink:3"}], "winner": 1},
            ],
        }
    )
    assert game._check_no_difficulty_constraints(ctx) is not None


def test_check_first_winner_always_lead_m23() -> None:
    game = DeepSeaMissionGame()
    ctx = _make_ctx(
        {
            "mode": "campaign",
            "mission": {"no": 23},
            "order": ["1", "2", "3"],
            "trick_history": [
                {"no": 1, "plays": [], "winner": 1},
                {"no": 2, "plays": [], "winner": 2},
                {"no": 3, "plays": [], "winner": 2},
            ],
        }
    )
    assert game._check_no_difficulty_constraints(ctx) is not None


def test_check_yellow5_last_m27() -> None:
    game = DeepSeaMissionGame()
    ctx = _make_ctx(
        {
            "mode": "campaign",
            "mission": {"no": 27},
            "order": ["1", "2", "3"],
            "trick_history": [
                {
                    "no": 1,
                    "plays": [
                        {"player": 1, "card": "blue:1"},
                        {"player": 2, "card": "blue:2"},
                        {"player": 3, "card": "sub:1"},
                    ],
                    "winner": 3,
                },
            ],
        }
    )
    assert game._check_no_difficulty_constraints(ctx) is not None


# ==================== 流程 ====================


async def test_campaign_no_difficulty_mission_skips_selection(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_common(monkeypatch)
    async with GameTestHarness(
        DeepSeaMissionGame,
        players=[1, 2, 3],
        config={"mode": "campaign", "mission_no": 8},
    ) as h:
        await h.start()
        assert h.runner is not None
        assert h.runner.ctx.state["phase"] == "playing"
        assert h.runner.ctx.state["tasks"] == []
        assert h.broadcasts_contain("第 8 关")
        assert h.broadcasts_contain("不得有玩家比其他玩家多赢 2 张 9")


async def test_campaign_captain_all(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_common(monkeypatch)
    async with GameTestHarness(
        DeepSeaMissionGame,
        players=[1, 2, 3],
        config={"mode": "campaign", "mission_no": 10},
    ) as h:
        await h.start()
        assert h.runner is not None
        tasks = h.runner.ctx.state["tasks"]
        assert all(t["assigned_to"] == 3 for t in tasks)
        assert h.runner.ctx.state["phase"] == "playing"


async def test_campaign_self_nominate(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_common(monkeypatch)
    async with GameTestHarness(
        DeepSeaMissionGame,
        players=[1, 2, 3],
        config={"mode": "campaign", "mission_no": 14},
    ) as h:
        await h.start()
        assert h.runner is not None
        assert h.runner.ctx.state["phase"] == "task_selection"
        assert h.runner.ctx.state["nomination"] is not None
        assert h.runner.ctx.state["sonar_mode"] == "currents"
        await h.send(3, "包揽")
        tasks = h.runner.ctx.state["tasks"]
        assert all(t["assigned_to"] == 3 for t in tasks)
        assert h.runner.ctx.state["phase"] == "playing"


async def test_campaign_free_selection(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_common(monkeypatch)
    async with GameTestHarness(
        DeepSeaMissionGame,
        players=[1, 2, 3],
        config={"mode": "campaign", "mission_no": 17},
    ) as h:
        await h.start()
        assert h.runner is not None
        await h.send(1, "选 1")
        assert h.runner.ctx.state["tasks"][0]["assigned_to"] == 1


async def test_campaign_silence_blocks_sonar(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_common(monkeypatch)
    async with GameTestHarness(
        DeepSeaMissionGame,
        players=[1, 2, 3],
        config={"mode": "campaign", "mission_no": 16},
    ) as h:
        await h.start()
        assert h.runner is not None
        await h.send(3, "包揽")
        assert h.runner.ctx.state["phase"] == "playing"
        assert h.runner.ctx.state["sonar_mode"] == "silence"
        await h.send(3, "声呐 蓝4 最高")
        assert h.broadcasts_contain("本关禁止交流")


async def test_campaign_rapture_shared_quota(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_common(monkeypatch)
    async with GameTestHarness(
        DeepSeaMissionGame,
        players=[1, 2, 3],
        config={"mode": "campaign", "mission_no": 11},
    ) as h:
        await h.start()
        assert h.runner is not None
        await h.send(3, "选 1")
        await h.send(1, "选 2")
        assert h.runner.ctx.state["phase"] == "playing"
        assert h.runner.ctx.state["sonar_mode"] == "rapture"
        await h.send(3, "声呐 黄2 唯一")
        assert h.broadcasts_contain("剩余共享声呐 0 次")
        await h.send(3, "声呐 黄2 唯一")
        assert h.broadcasts_contain("全队共享声呐次数已用完")


async def test_campaign_progress_advance(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    set_cfg = _patch_common(monkeypatch)
    monkeypatch.setattr(DeepSeaMissionGame, "award", AsyncMock())
    async with GameTestHarness(
        DeepSeaMissionGame,
        players=[1, 2, 3],
        config={"mode": "campaign", "mission_no": 5},
    ) as h:
        await h.start()
        assert h.runner is not None
        await h.send(3, "选 1")
        await h.send(1, "选 2")
        await h.send(3, "胜利")
        assert h.runner.ctx.state["completed"] is True
        set_cfg.assert_awaited_with(9999, "deep_sea_mission.campaign.level", "6")


async def test_campaign_m32_finishes_to_epilogue(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    set_cfg = _patch_common(monkeypatch)
    monkeypatch.setattr(DeepSeaMissionGame, "award", AsyncMock())
    async with GameTestHarness(
        DeepSeaMissionGame,
        players=[1, 2, 3],
        config={"mode": "campaign", "mission_no": 32},
    ) as h:
        await h.start()
        assert h.runner is not None
        assert len(h.runner.ctx.state["tasks"]) == 4
        await h.send(3, "选 1")
        await h.send(1, "选 2")
        await h.send(2, "选 3")
        await h.send(3, "选 4")
        await h.send(3, "胜利")
        assert h.runner.ctx.state["completed"] is True
        set_cfg.assert_awaited_with(9999, "deep_sea_mission.campaign.level", "epilogue:18")


async def test_campaign_self_nominate_two(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_common(monkeypatch)
    async with GameTestHarness(
        DeepSeaMissionGame,
        players=[1, 2, 3],
        config={"mode": "campaign", "mission_no": 26},
    ) as h:
        await h.start()
        assert h.runner is not None
        assert h.runner.ctx.state["nomination"]["target"] == 2
        await h.send(3, "包揽")
        await h.send(1, "包揽")
        tasks = h.runner.ctx.state["tasks"]
        assert len(tasks) == 4
        assert {t["assigned_to"] for t in tasks} == {3, 1}
        assert h.runner.ctx.state["phase"] == "playing"


async def test_campaign_hardest_to_captain(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_common(monkeypatch)
    async with GameTestHarness(
        DeepSeaMissionGame,
        players=[1, 2, 3],
        config={"mode": "campaign", "mission_no": 19},
    ) as h:
        await h.start()
        assert h.runner is not None
        tasks = h.runner.ctx.state["tasks"]
        assert tasks[1]["assigned_to"] == 3  # 难度 2 的任务给队长
        assert tasks[0]["assigned_to"] is None


async def test_campaign_epilogue_flow(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    set_cfg = _patch_common(monkeypatch)
    monkeypatch.setattr(DeepSeaMissionGame, "award", AsyncMock())
    async with GameTestHarness(
        DeepSeaMissionGame,
        players=[1, 2, 3],
        config={"mode": "campaign", "epilogue_difficulty": 18},
    ) as h:
        await h.start()
        assert h.runner is not None
        assert h.runner.ctx.state["mission_no"] is None
        assert h.runner.ctx.state["epilogue_difficulty"] == 18
        assert h.runner.ctx.state["difficulty"] == 18
        assert "free_selection" in h.runner.ctx.state["mission"]["modifiers"]
        await h.send(3, "选 1")
        await h.send(1, "选 2")
        await h.send(3, "胜利")
        set_cfg.assert_awaited_with(9999, "deep_sea_mission.campaign.level", "epilogue:19")


async def test_campaign_distress_pass(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_common(monkeypatch)
    async with GameTestHarness(
        DeepSeaMissionGame,
        players=[1, 2, 3],
        config={"mode": "campaign", "mission_no": 1},
    ) as h:
        await h.start()
        assert h.runner is not None
        assert h.runner.ctx.state["phase"] == "task_selection"
        await h.send(1, "求救")
        assert h.runner.ctx.state["phase"] == "distress"
        # 潜艇不能传
        await h.send(3, "传 潜艇4")
        assert h.broadcasts_contain("潜艇不能作为求救信号传牌")
        # 三人各传一张给左邻
        await h.send(1, "传 蓝1")
        await h.send(2, "传 蓝3")
        await h.send(3, "传 黄2")
        assert h.runner.ctx.state["phase"] == "task_selection"
        hands = h.runner.ctx.state["hands"]
        assert "blue:1" in hands["2"]
        assert "blue:1" not in hands["1"]
        assert "yellow:2" in hands["1"]
        assert "blue:3" in hands["3"]


async def test_campaign_no_difficulty_task_review_hint(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_common(monkeypatch)
    async with GameTestHarness(
        DeepSeaMissionGame,
        players=[1, 2, 3],
        config={"mode": "campaign", "mission_no": 12},
    ) as h:
        await h.start()
        assert h.runner is not None
        assert h.runner.ctx.state["phase"] == "playing"
        # 第 1 墩：队长用潜艇开墩（违反 M12 约束）
        await h.send(3, "潜艇4")
        await h.send(1, "蓝1")
        await h.send(2, "蓝3")
        # 第 2 墩
        await h.send(3, "黄2")
        await h.send(1, "蓝2")
        await h.send(2, "黄1")
        assert h.runner.ctx.state["phase"] == "task_review"
        assert h.broadcasts_contain("禁止粉牌或潜艇开墩")
