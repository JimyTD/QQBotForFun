"""王中王锦标赛核心逻辑测试。

覆盖：Tournament 状态机、12 场比赛完整推进、BracketData/RankingData 生成、渲染器输出。
"""

from __future__ import annotations

import random

import pytest

from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.lineup import generate_tournament_lineup
from plugins.games.aoe3_battle.tournament import (
    Tournament,
    TournamentStage,
)


@pytest.fixture(scope="module")
def repo():
    return UnitRepo.get()


@pytest.fixture(scope="module")
def tournament(repo) -> Tournament:
    """创建一个用于测试的锦标赛实例。"""
    rng = random.Random(42)
    result = generate_tournament_lineup(repo, "musketeer", age=3, rng=rng)
    assert not isinstance(result, str), f"生成失败: {result}"
    assert len(result) == 8
    return Tournament.create(result, "火枪王", age=3, rng=rng)


class TestTournamentCreation:
    """测试锦标赛创建。"""

    def test_create_8_units(self, tournament):
        assert len(tournament.units) == 8
        assert tournament.stage == TournamentStage.DRAW

    def test_qf_matches_initialized(self, tournament):
        for i in range(1, 5):
            m = tournament.matches[f"QF{i}"]
            assert m.unit_a_idx >= 0
            assert m.unit_b_idx >= 0
            assert m.winner_idx is None

    def test_bracket_data_pre_stage(self, tournament):
        data = tournament.get_bracket_data(hint="测试提示")
        assert data.stage == "pre"
        assert "火枪王" in data.title
        assert data.hint == "测试提示"
        assert len(data.units) == 8

    def test_serialization_roundtrip(self, tournament):
        d = tournament.to_dict()
        assert d["stage"] == "draw"
        assert len(d["units"]) == 8
        assert len(d["matches"]) == 12
        assert d["age"] == 3


class TestTournamentFullRun:
    """完整锦标赛推进：12 场比赛。"""

    @pytest.fixture()
    def t(self, repo) -> Tournament:
        """每个测试方法独立的锦标赛实例。"""
        rng = random.Random(123)
        result = generate_tournament_lineup(repo, "musketeer", age=3, rng=rng)
        assert not isinstance(result, str)
        return Tournament.create(result, "火枪王", age=3, rng=rng)

    def test_full_12_matches(self, t: Tournament):
        """完整跑完 12 场比赛，验证最终排名。"""
        rng = random.Random(999)

        # DRAW → QF
        assert t.try_advance()
        assert t.stage == TournamentStage.QF

        # 八强 4 场
        pending = t.get_current_round_matches()
        assert len(pending) == 4
        for m in pending:
            winner = rng.choice([m.unit_a_idx, m.unit_b_idx])
            t.record_result(m.match_id, winner)

        # QF → QF_DONE
        assert t.try_advance()
        assert t.stage == TournamentStage.QF_DONE

        # QF_DONE → LOSERS
        assert t.try_advance()
        assert t.stage == TournamentStage.LOSERS

        # 败者组：LR1/LR2
        pending = t.get_current_round_matches()
        lr_matches = [m for m in pending if m.match_id.startswith("LR")]
        assert len(lr_matches) == 2
        for m in lr_matches:
            winner = rng.choice([m.unit_a_idx, m.unit_b_idx])
            t.record_result(m.match_id, winner)
            t.try_advance()  # 中间推进填充 7TH/5TH

        # 7TH/5TH
        pending = t.get_current_round_matches()
        rank_matches = [m for m in pending if m.match_id in ("7TH", "5TH")]
        assert len(rank_matches) == 2
        for m in rank_matches:
            winner = rng.choice([m.unit_a_idx, m.unit_b_idx])
            t.record_result(m.match_id, winner)

        # LOSERS → LOSERS_DONE
        assert t.try_advance()
        assert t.stage == TournamentStage.LOSERS_DONE

        # LOSERS_DONE → SF
        assert t.try_advance()
        assert t.stage == TournamentStage.SF

        # 半决赛 2 场
        pending = t.get_current_round_matches()
        assert len(pending) == 2
        for m in pending:
            winner = rng.choice([m.unit_a_idx, m.unit_b_idx])
            t.record_result(m.match_id, winner)

        # SF → SF_DONE
        assert t.try_advance()
        assert t.stage == TournamentStage.SF_DONE

        # SF_DONE → THIRD_PLACE
        assert t.try_advance()
        assert t.stage == TournamentStage.THIRD_PLACE

        # 季军战
        pending = t.get_current_round_matches()
        third_match = [m for m in pending if m.match_id == "3RD"]
        assert len(third_match) == 1
        m = third_match[0]
        t.record_result(m.match_id, rng.choice([m.unit_a_idx, m.unit_b_idx]))

        # THIRD_PLACE → FINAL
        assert t.try_advance()
        assert t.stage == TournamentStage.FINAL

        # 决赛
        pending = t.get_current_round_matches()
        final_match = [m for m in pending if m.match_id == "FINAL"]
        assert len(final_match) == 1
        m = final_match[0]
        t.record_result(m.match_id, rng.choice([m.unit_a_idx, m.unit_b_idx]))

        # FINAL → FINISHED
        assert t.try_advance()
        assert t.stage == TournamentStage.FINISHED

        # 验证排名
        assert len(t.final_ranks) == 8
        assert len(set(t.final_ranks)) == 8  # 每个兵种恰好出现一次

    def test_bracket_data_at_each_stage(self, t: Tournament):
        """验证各阶段的 BracketData 正确生成。"""
        rng = random.Random(456)

        # pre
        data = t.get_bracket_data()
        assert data.stage == "pre"
        assert not data.qf_results

        # 跑完八强
        t.try_advance()  # QF
        for m in t.get_current_round_matches():
            t.record_result(m.match_id, rng.choice([m.unit_a_idx, m.unit_b_idx]))
        t.try_advance()  # QF_DONE

        data = t.get_bracket_data()
        assert data.stage == "qf_done"
        assert len(data.qf_results) == 4

    def test_is_bracket_stage(self, t: Tournament):
        """验证 is_bracket_stage 标记。"""
        assert t.is_bracket_stage()  # DRAW

        t.try_advance()  # QF
        assert not t.is_bracket_stage()


class TestBracketRenderer:
    """对阵图渲染器基本测试（不验证视觉，只验证输出有效 PNG bytes）。"""

    def test_render_bracket_returns_png(self, tournament):
        from plugins.games.aoe3_battle.bracket_renderer import render_bracket

        data = tournament.get_bracket_data(hint="测试")
        png = render_bracket(data)
        assert isinstance(png, bytes)
        assert len(png) > 1000
        # PNG magic bytes
        assert png[:8] == b"\x89PNG\r\n\x1a\n"

    def test_render_ranking_returns_png(self, repo):
        """需要一个完整跑完的锦标赛来测试排名图。"""
        from plugins.games.aoe3_battle.bracket_renderer import render_ranking

        rng = random.Random(789)
        result = generate_tournament_lineup(repo, "musketeer", age=3, rng=rng)
        assert not isinstance(result, str)
        t = Tournament.create(result, "火枪王", age=3, rng=rng)

        # 快速跑完 12 场
        t.try_advance()
        for m in t.get_current_round_matches():
            t.record_result(m.match_id, rng.choice([m.unit_a_idx, m.unit_b_idx]))
        t.try_advance()  # QF_DONE
        t.try_advance()  # LOSERS

        for m in t.get_current_round_matches():
            if m.match_id.startswith("LR"):
                t.record_result(m.match_id, rng.choice([m.unit_a_idx, m.unit_b_idx]))
                t.try_advance()
        for m in t.get_current_round_matches():
            if m.match_id in ("7TH", "5TH"):
                t.record_result(m.match_id, rng.choice([m.unit_a_idx, m.unit_b_idx]))

        t.try_advance()  # LOSERS_DONE
        t.try_advance()  # SF

        for m in t.get_current_round_matches():
            t.record_result(m.match_id, rng.choice([m.unit_a_idx, m.unit_b_idx]))
        t.try_advance()  # SF_DONE
        t.try_advance()  # THIRD_PLACE

        for m in t.get_current_round_matches():
            if m.match_id == "3RD":
                t.record_result(m.match_id, rng.choice([m.unit_a_idx, m.unit_b_idx]))
        t.try_advance()  # FINAL

        for m in t.get_current_round_matches():
            if m.match_id == "FINAL":
                t.record_result(m.match_id, rng.choice([m.unit_a_idx, m.unit_b_idx]))
        t.try_advance()  # FINISHED

        assert t.stage == TournamentStage.FINISHED
        data = t.get_ranking_data()
        png = render_ranking(data)
        assert isinstance(png, bytes)
        assert len(png) > 500
        assert png[:8] == b"\x89PNG\r\n\x1a\n"


class TestGenerateTournamentLineup:
    """锦标赛阵容生成测试。"""

    def test_generates_8_units(self, repo):
        result = generate_tournament_lineup(
            repo, "musketeer", age=3, rng=random.Random(42)
        )
        assert not isinstance(result, str)
        assert len(result) == 8
        # 每个元素是 (unit_id, display_name, Unit)
        for uid, name, unit in result:
            assert uid
            assert name
            assert unit.hp > 0

    def test_all_unique(self, repo):
        result = generate_tournament_lineup(
            repo, "musketeer", age=3, rng=random.Random(42)
        )
        assert not isinstance(result, str)
        ids = [uid for uid, _, _ in result]
        assert len(set(ids)) == 8

    def test_invalid_theme_returns_error(self, repo):
        result = generate_tournament_lineup(
            repo, "nonexistent_theme", age=3,
        )
        assert isinstance(result, str)
        assert "未知主题" in result

    def test_small_pool_theme(self, repo):
        """如果某主题不够 8 个兵种，应返回错误。"""
        # grenadier 主题可能不够 8 个，取决于数据
        result = generate_tournament_lineup(
            repo, "grenadier", age=3, rng=random.Random(42)
        )
        # 不管成功还是失败，类型必须正确
        assert isinstance(result, (list, str))
        if isinstance(result, str):
            assert "不足 8 个" in result
