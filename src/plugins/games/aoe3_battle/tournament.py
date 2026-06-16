"""王中王锦标赛 —— 赛制状态机 + 比赛调度。

8 兵种单败淘汰 + 败者排位，共 12 场比赛：
  QF1-4 → LR1/LR2 → 7/8名战 → 5/6名战 → SF1/SF2 → 季军战 → 决赛

纯逻辑层，不涉及消息发送。
设计文档：docs/games/aoe3-battle.md §3.12 (Mode F)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.plugins.aoe3.models import Unit

from .bracket_renderer import BracketData, RankingData


# =====================================================================
# 数据结构
# =====================================================================


class TournamentStage(Enum):
    """锦标赛阶段。"""

    DRAW = "draw"  # 抽签完成，等待开战
    QF = "qf"  # 八强战进行中
    QF_DONE = "qf_done"  # 八强战结束，出图，等待「开战」
    LOSERS = "losers"  # 败者组排位进行中（LR1/LR2 + 7/8th + 5/6th）
    LOSERS_DONE = "losers_done"  # 败者排位结束
    SF = "sf"  # 半决赛进行中
    SF_DONE = "sf_done"  # 半决赛结束，出图，等待「开战」
    THIRD_PLACE = "third_place"  # 季军战进行中
    FINAL = "final"  # 决赛进行中
    FINISHED = "finished"  # 锦标赛结束


@dataclass
class TournamentMatch:
    """一场比赛。"""

    match_id: str  # "QF1"/"LR1"/"7TH"/"5TH"/"SF1"/"3RD"/"FINAL"
    label: str  # 人类可读标签："八强第1场"
    unit_a_idx: int  # units[] 中的索引
    unit_b_idx: int
    winner_idx: int | None = None
    loser_idx: int | None = None


@dataclass
class TournamentUnit:
    """锦标赛中的一个参赛兵种。"""

    idx: int  # 0-7
    unit_id: str
    display_name: str
    unit: "Unit"


@dataclass
class Tournament:
    """锦标赛状态机。"""

    units: list[TournamentUnit]  # 8 个参赛兵种
    theme_title: str  # "火枪王" 等
    stage: TournamentStage = TournamentStage.DRAW
    matches: dict[str, TournamentMatch] = field(default_factory=dict)
    final_ranks: list[int] = field(default_factory=list)  # unit idx, 1st to 8th
    _age: int = 3  # 锁定的时代

    # ── 工厂方法 ──

    @classmethod
    def create(
        cls,
        units: list[tuple[str, str, "Unit"]],
        theme_title: str,
        *,
        age: int = 3,
        rng: random.Random | None = None,
    ) -> "Tournament":
        """抽签配对，初始化 12 场比赛骨架。

        Parameters
        ----------
        units : 8 个 (unit_id, display_name, Unit) 元组
        theme_title : 主题展示名
        age : 锁定时代
        rng : 随机源（用于打乱配对）
        """
        if len(units) != 8:
            raise ValueError(f"锦标赛需要恰好 8 个兵种，实际 {len(units)}")

        rng = rng or random.Random()

        # 构建参赛单位列表
        tu_list = [
            TournamentUnit(idx=i, unit_id=uid, display_name=name, unit=u)
            for i, (uid, name, u) in enumerate(units)
        ]

        # 打乱顺序决定配对（shuffle idx 映射，保持 tu_list 位置不变）
        indices = list(range(8))
        rng.shuffle(indices)
        # 重新排列 tu_list 使得配对自然形成：0v1, 2v3, 4v5, 6v7
        shuffled = [tu_list[i] for i in indices]
        # 重新赋 idx
        for new_idx, tu in enumerate(shuffled):
            tu.idx = new_idx

        # 初始化比赛骨架
        matches: dict[str, TournamentMatch] = {}

        # 八强 QF1-4
        for m in range(4):
            a, b = m * 2, m * 2 + 1
            matches[f"QF{m + 1}"] = TournamentMatch(
                match_id=f"QF{m + 1}",
                label=f"八强第{m + 1}场",
                unit_a_idx=a,
                unit_b_idx=b,
            )

        # 败者组 LR1/LR2（对手在 QF 结束后确定）
        matches["LR1"] = TournamentMatch(
            match_id="LR1", label="败者组第1场", unit_a_idx=-1, unit_b_idx=-1,
        )
        matches["LR2"] = TournamentMatch(
            match_id="LR2", label="败者组第2场", unit_a_idx=-1, unit_b_idx=-1,
        )
        matches["7TH"] = TournamentMatch(
            match_id="7TH", label="7/8名战", unit_a_idx=-1, unit_b_idx=-1,
        )
        matches["5TH"] = TournamentMatch(
            match_id="5TH", label="5/6名战", unit_a_idx=-1, unit_b_idx=-1,
        )

        # 半决赛 SF1/SF2（对手在 QF 结束后确定）
        matches["SF1"] = TournamentMatch(
            match_id="SF1", label="半决赛第1场", unit_a_idx=-1, unit_b_idx=-1,
        )
        matches["SF2"] = TournamentMatch(
            match_id="SF2", label="半决赛第2场", unit_a_idx=-1, unit_b_idx=-1,
        )
        matches["3RD"] = TournamentMatch(
            match_id="3RD", label="季军战", unit_a_idx=-1, unit_b_idx=-1,
        )
        matches["FINAL"] = TournamentMatch(
            match_id="FINAL", label="决赛", unit_a_idx=-1, unit_b_idx=-1,
        )

        return cls(
            units=shuffled,
            theme_title=theme_title,
            stage=TournamentStage.DRAW,
            matches=matches,
            _age=age,
        )

    # ── 查询方法 ──

    def get_current_round_matches(self) -> list[TournamentMatch]:
        """获取当前阶段待打的比赛列表。"""
        stage = self.stage

        if stage == TournamentStage.DRAW or stage == TournamentStage.QF:
            return [self.matches[f"QF{i}"] for i in range(1, 5)
                    if self.matches[f"QF{i}"].winner_idx is None]

        if stage in (TournamentStage.QF_DONE, TournamentStage.LOSERS):
            # 败者组：LR1 → LR2 → 7/8th → 5/6th
            order = ["LR1", "LR2", "7TH", "5TH"]
            return [self.matches[mid] for mid in order
                    if self.matches[mid].winner_idx is None]

        if stage in (TournamentStage.LOSERS_DONE, TournamentStage.SF):
            return [self.matches[f"SF{i}"] for i in range(1, 3)
                    if self.matches[f"SF{i}"].winner_idx is None]

        if stage in (TournamentStage.SF_DONE, TournamentStage.THIRD_PLACE):
            pending = []
            if self.matches["3RD"].winner_idx is None:
                pending.append(self.matches["3RD"])
            if self.matches["FINAL"].winner_idx is None:
                pending.append(self.matches["FINAL"])
            return pending

        if stage == TournamentStage.FINAL:
            if self.matches["FINAL"].winner_idx is None:
                return [self.matches["FINAL"]]
            return []

        return []

    def record_result(self, match_id: str, winner_idx: int) -> None:
        """记录一场比赛结果。"""
        m = self.matches[match_id]
        if winner_idx not in (m.unit_a_idx, m.unit_b_idx):
            raise ValueError(
                f"Winner {winner_idx} 不在比赛 {match_id} 中 "
                f"(a={m.unit_a_idx}, b={m.unit_b_idx})"
            )
        m.winner_idx = winner_idx
        m.loser_idx = m.unit_b_idx if winner_idx == m.unit_a_idx else m.unit_a_idx

    def try_advance(self) -> bool:
        """尝试推进到下一阶段，返回是否成功推进。

        每个阶段在所有当前比赛结束后可推进。推进时自动填充下一轮的对阵。
        """
        stage = self.stage

        # ── DRAW → QF ──
        if stage == TournamentStage.DRAW:
            self.stage = TournamentStage.QF
            return True

        # ── QF → QF_DONE ──
        if stage == TournamentStage.QF:
            if any(self.matches[f"QF{i}"].winner_idx is None for i in range(1, 5)):
                return False
            self._setup_after_qf()
            self.stage = TournamentStage.QF_DONE
            return True

        # ── QF_DONE → LOSERS ──
        if stage == TournamentStage.QF_DONE:
            self.stage = TournamentStage.LOSERS
            return True

        # ── LOSERS → LOSERS_DONE ──
        if stage == TournamentStage.LOSERS:
            # LR1/LR2 先打完 → 自动填充 7TH/5TH 对手
            lr1 = self.matches["LR1"]
            lr2 = self.matches["LR2"]
            if lr1.winner_idx is not None and lr2.winner_idx is not None:
                # 填充 7TH/5TH（幂等）
                if self.matches["7TH"].unit_a_idx == -1:
                    self._setup_after_losers()

            losers_ids = ["LR1", "LR2", "7TH", "5TH"]
            if any(self.matches[mid].winner_idx is None for mid in losers_ids):
                return False
            self.stage = TournamentStage.LOSERS_DONE
            return True

        # ── LOSERS_DONE → SF ──
        if stage == TournamentStage.LOSERS_DONE:
            self.stage = TournamentStage.SF
            return True

        # ── SF → SF_DONE ──
        if stage == TournamentStage.SF:
            if any(self.matches[f"SF{i}"].winner_idx is None for i in range(1, 3)):
                return False
            self._setup_after_sf()
            self.stage = TournamentStage.SF_DONE
            return True

        # ── SF_DONE → THIRD_PLACE ──
        if stage == TournamentStage.SF_DONE:
            self.stage = TournamentStage.THIRD_PLACE
            return True

        # ── THIRD_PLACE → FINAL → FINISHED ──
        if stage == TournamentStage.THIRD_PLACE:
            if self.matches["3RD"].winner_idx is None:
                return False
            # 季军战打完，直接进决赛
            self.stage = TournamentStage.FINAL
            return True

        if stage == TournamentStage.FINAL:
            if self.matches["FINAL"].winner_idx is None:
                return False
            self._compute_final_ranks()
            self.stage = TournamentStage.FINISHED
            return True

        return False

    # ── 内部：QF 后填充下一轮对阵 ──

    def _setup_after_qf(self) -> None:
        """八强全部结束后，填充败者组 + 半决赛的对手。"""
        qf = [self.matches[f"QF{i}"] for i in range(1, 5)]

        # 胜者 → 半决赛
        # SF1: QF1 胜者 vs QF2 胜者
        # SF2: QF3 胜者 vs QF4 胜者
        assert qf[0].winner_idx is not None
        assert qf[1].winner_idx is not None
        assert qf[2].winner_idx is not None
        assert qf[3].winner_idx is not None
        self.matches["SF1"].unit_a_idx = qf[0].winner_idx
        self.matches["SF1"].unit_b_idx = qf[1].winner_idx
        self.matches["SF2"].unit_a_idx = qf[2].winner_idx
        self.matches["SF2"].unit_b_idx = qf[3].winner_idx

        # 败者 → 败者组
        # LR1: QF1 败者 vs QF2 败者
        # LR2: QF3 败者 vs QF4 败者
        assert qf[0].loser_idx is not None
        assert qf[1].loser_idx is not None
        assert qf[2].loser_idx is not None
        assert qf[3].loser_idx is not None
        self.matches["LR1"].unit_a_idx = qf[0].loser_idx
        self.matches["LR1"].unit_b_idx = qf[1].loser_idx
        self.matches["LR2"].unit_a_idx = qf[2].loser_idx
        self.matches["LR2"].unit_b_idx = qf[3].loser_idx

    def _setup_after_losers(self) -> None:
        """败者组排位全部结束后，填充 7/8 和 5/6 名战的对手。

        实际上 LR1/LR2 的结果已经在进行中逐步填充了 7TH/5TH，
        但这个方法可以作为安全的一次性填充。
        """
        lr1 = self.matches["LR1"]
        lr2 = self.matches["LR2"]

        assert lr1.winner_idx is not None
        assert lr1.loser_idx is not None
        assert lr2.winner_idx is not None
        assert lr2.loser_idx is not None

        # 7/8名战：LR1 败者 vs LR2 败者
        self.matches["7TH"].unit_a_idx = lr1.loser_idx
        self.matches["7TH"].unit_b_idx = lr2.loser_idx

        # 5/6名战：LR1 胜者 vs LR2 胜者
        self.matches["5TH"].unit_a_idx = lr1.winner_idx
        self.matches["5TH"].unit_b_idx = lr2.winner_idx

    def _setup_after_sf(self) -> None:
        """半决赛全部结束后，填充季军战和决赛的对手。"""
        sf1 = self.matches["SF1"]
        sf2 = self.matches["SF2"]

        assert sf1.winner_idx is not None
        assert sf1.loser_idx is not None
        assert sf2.winner_idx is not None
        assert sf2.loser_idx is not None

        # 季军战：SF1 败者 vs SF2 败者
        self.matches["3RD"].unit_a_idx = sf1.loser_idx
        self.matches["3RD"].unit_b_idx = sf2.loser_idx

        # 决赛：SF1 胜者 vs SF2 胜者
        self.matches["FINAL"].unit_a_idx = sf1.winner_idx
        self.matches["FINAL"].unit_b_idx = sf2.winner_idx

    def _compute_final_ranks(self) -> None:
        """计算最终 1-8 名排名。"""
        final = self.matches["FINAL"]
        third = self.matches["3RD"]
        fifth = self.matches["5TH"]
        seventh = self.matches["7TH"]

        assert final.winner_idx is not None
        assert final.loser_idx is not None
        assert third.winner_idx is not None
        assert third.loser_idx is not None
        assert fifth.winner_idx is not None
        assert fifth.loser_idx is not None
        assert seventh.winner_idx is not None
        assert seventh.loser_idx is not None

        self.final_ranks = [
            final.winner_idx,   # 1st
            final.loser_idx,    # 2nd
            third.winner_idx,   # 3rd
            third.loser_idx,    # 4th
            fifth.winner_idx,   # 5th
            fifth.loser_idx,    # 6th
            seventh.winner_idx,  # 7th
            seventh.loser_idx,  # 8th
        ]

    # ── 对阵图数据 ──

    def get_bracket_data(
        self,
        *,
        hint: str = "",
        icon_paths: list | None = None,
    ) -> BracketData:
        """生成当前状态的对阵图数据。"""
        from pathlib import Path

        units_tuples = [(tu.unit_id, tu.display_name) for tu in self.units]
        _icon_paths = icon_paths or [None] * len(self.units)

        # 映射 stage → bracket stage
        if self.stage in (TournamentStage.DRAW, TournamentStage.QF):
            b_stage = "pre"
        elif self.stage in (
            TournamentStage.QF_DONE,
            TournamentStage.LOSERS,
            TournamentStage.LOSERS_DONE,
            TournamentStage.SF,
        ):
            b_stage = "qf_done"
        elif self.stage in (
            TournamentStage.SF_DONE,
            TournamentStage.THIRD_PLACE,
        ):
            b_stage = "sf_done"
        elif self.stage == TournamentStage.FINISHED:
            b_stage = "final"
        else:
            # FINAL 进行中也不算 final 阶段图（还没出结果）
            b_stage = "sf_done"

        # 阶段标签
        stage_labels = {
            "pre": "抽签",
            "qf_done": "八强战",
            "sf_done": "半决赛",
            "final": "决赛",
        }

        # QF 结果
        qf_results: dict[int, int] = {}
        for i in range(4):
            m = self.matches[f"QF{i + 1}"]
            if m.winner_idx is not None:
                qf_results[i] = m.winner_idx

        # SF 结果
        sf_results: dict[int, int] = {}
        for i in range(2):
            m = self.matches[f"SF{i + 1}"]
            if m.winner_idx is not None:
                sf_results[i] = m.winner_idx

        # 冠亚军
        champion_idx = self.matches["FINAL"].winner_idx
        runner_up_idx = self.matches["FINAL"].loser_idx

        return BracketData(
            title=f"王中王锦标赛 · {self.theme_title}",
            stage_label=stage_labels.get(b_stage, ""),
            hint=hint,
            units=units_tuples,
            icon_paths=_icon_paths,
            stage=b_stage,
            qf_results=qf_results,
            sf_results=sf_results,
            champion_idx=champion_idx,
            runner_up_idx=runner_up_idx,
        )

    def get_ranking_data(
        self,
        *,
        icon_paths: list | None = None,
    ) -> RankingData:
        """生成最终排名图数据。需要在 FINISHED 阶段调用。"""
        if not self.final_ranks:
            raise RuntimeError("锦标赛尚未结束，无法生成排名")

        _icon_paths = icon_paths or [None] * len(self.units)
        ranks = [
            (idx, self.units[idx].display_name)
            for idx in self.final_ranks
        ]

        return RankingData(
            title="最终排名",
            ranks=ranks,
            icon_paths=_icon_paths,
        )

    # ── 序列化（state 持久化用）──

    def to_dict(self) -> dict:
        """序列化为可 JSON 的字典。"""
        return {
            "units": [
                {"idx": tu.idx, "unit_id": tu.unit_id, "display_name": tu.display_name}
                for tu in self.units
            ],
            "theme_title": self.theme_title,
            "stage": self.stage.value,
            "matches": {
                mid: {
                    "match_id": m.match_id,
                    "label": m.label,
                    "unit_a_idx": m.unit_a_idx,
                    "unit_b_idx": m.unit_b_idx,
                    "winner_idx": m.winner_idx,
                    "loser_idx": m.loser_idx,
                }
                for mid, m in self.matches.items()
            },
            "final_ranks": self.final_ranks,
            "age": self._age,
        }

    # ── 辅助 ──

    @property
    def age(self) -> int:
        return self._age

    def get_unit(self, idx: int) -> TournamentUnit:
        """按 idx 获取参赛兵种。"""
        return self.units[idx]

    def is_bracket_stage(self) -> bool:
        """当前阶段是否需要出对阵图。"""
        return self.stage in (
            TournamentStage.DRAW,
            TournamentStage.QF_DONE,
            TournamentStage.SF_DONE,
            TournamentStage.FINISHED,
        )

    def format_match_result_text(self, match_id: str) -> str:
        """格式化单场比赛结果文本。"""
        m = self.matches[match_id]
        if m.winner_idx is None:
            return f"📋 {m.label}：{self.units[m.unit_a_idx].display_name} vs {self.units[m.unit_b_idx].display_name}"

        winner = self.units[m.winner_idx]
        loser = self.units[m.loser_idx]  # type: ignore[arg-type]
        return f"🏆 {m.label}：{winner.display_name} 胜 {loser.display_name}"
