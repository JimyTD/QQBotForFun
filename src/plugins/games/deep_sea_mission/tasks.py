"""深海任务：任务卡数据与抽取。"""

from __future__ import annotations

from dataclasses import dataclass
import random


@dataclass(frozen=True)
class TaskCard:
    id: str
    difficulty_3p: int
    difficulty_4p: int
    difficulty_5p: int
    text: str

    def difficulty_for(self, player_count: int) -> int:
        if player_count == 3:
            return self.difficulty_3p
        if player_count == 4:
            return self.difficulty_4p
        if player_count == 5:
            return self.difficulty_5p
        raise ValueError("deep sea mission supports 3-5 players")


TASK_CARDS: tuple[TaskCard, ...] = (
    TaskCard("T001", 2, 3, 3, "赢得的墩数比其他任意一名玩家都多"),
    TaskCard("T002", 3, 4, 5, "赢得的墩数比其他所有玩家合计还多"),
    TaskCard("T003", 2, 2, 3, "赢得的墩数比其他任意一名玩家都少"),
    TaskCard("T004", 2, 2, 3, "赢得的墩数比队长多（队长不能领取）"),
    TaskCard("T005", 2, 2, 2, "赢得的墩数比队长少（队长不能领取）"),
    TaskCard("T006", 4, 3, 3, "赢得的墩数与队长相同（队长不能领取）"),
    TaskCard("T007", 2, 3, 3, "赢得一墩：所有牌点数都小于 7，且不含潜艇"),
    TaskCard("T008", 2, 3, 4, "赢得一墩：所有牌点数都大于 5"),
    TaskCard("T009", 2, 3, 3, "赢得一墩，里面有一张 6"),
    TaskCard("T010", 2, 3, 4, "赢得一墩，里面有一张 5"),
    TaskCard("T011", 3, 4, 5, "赢得一墩，里面有一张 3"),
    TaskCard("T012", 1, 2, 2, "用 7 赢下一张 5"),
    TaskCard("T013", 3, 4, 5, "用 4 赢下一张 8"),
    TaskCard("T014", 2, 3, 4, "赢得任意一张 6，同时这一墩里还有另一张 6"),
    TaskCard("T015", 3, 4, 5, "赢得一墩，里面有一张 2"),
    TaskCard("T016", 1, 1, 1, "赢得粉3"),
    TaskCard("T017", 1, 1, 1, "赢得黄1"),
    TaskCard("T018", 1, 1, 1, "赢得蓝4"),
    TaskCard("T019", 1, 1, 1, "赢得绿6"),
    TaskCard("T020", 3, 4, 5, "赢得全部四张 3"),
    TaskCard("T021", 3, 4, 5, "赢得至少三张 5"),
    TaskCard("T022", 3, 4, 5, "赢得至少三张 9"),
    TaskCard("T023", 2, 2, 2, "赢得至少两张 7"),
    TaskCard("T024", 4, 5, 6, "赢得全部四张 9"),
    TaskCard("T025", 3, 4, 4, "恰好赢得三张 6"),
    TaskCard("T026", 2, 3, 3, "恰好赢得两张 9"),
    TaskCard("T027", 2, 3, 3, "赢得蓝1、蓝2、蓝3"),
    TaskCard("T028", 2, 2, 3, "赢得蓝6和黄7"),
    TaskCard("T029", 2, 2, 3, "赢得粉5和黄6"),
    TaskCard("T030", 2, 2, 3, "赢得绿5和蓝8"),
    TaskCard("T031", 2, 2, 3, "赢得蓝5和粉8"),
    TaskCard("T032", 2, 2, 3, "赢得粉9和黄8"),
    TaskCard("T033", 2, 2, 2, "赢得粉1和绿7"),
    TaskCard("T034", 2, 3, 3, "赢得黄9和蓝7"),
    TaskCard("T035", 3, 4, 4, "赢得绿3、黄4、黄5"),
    TaskCard("T036", 3, 4, 5, "在最后一墩赢得绿2"),
    TaskCard("T037", 4, 4, 4, "恰好赢得一张粉牌和一张绿牌"),
    TaskCard("T038", 3, 3, 3, "赢得至少七张黄牌"),
    TaskCard("T039", 2, 3, 3, "赢得至少五张粉牌"),
    TaskCard("T040", 3, 4, 4, "恰好赢得两张绿牌"),
    TaskCard("T041", 3, 4, 4, "恰好赢得两张蓝牌"),
    TaskCard("T042", 3, 3, 4, "恰好赢得一张粉牌"),
    TaskCard("T043", 2, 2, 2, "不赢得任何粉牌"),
    TaskCard("T044", 2, 3, 4, "赢得每种颜色至少一张牌（不含潜艇）"),
    TaskCard("T045", 3, 4, 5, "赢得至少一种颜色的全部牌（不含潜艇）"),
    TaskCard("T046", 2, 5, 6, "赢得一墩：只包含偶数牌（2、4、6、8）"),
    TaskCard("T047", 2, 4, 5, "赢得一墩：只包含奇数牌（1、3、5、7、9）"),
    TaskCard("T048", 3, 3, 4, "赢得一墩：总点数高于 23/28/31（3/4/5 人），且不含潜艇"),
    TaskCard("T049", 3, 3, 4, "赢得一墩：总点数低于 8/12/16（3/4/5 人），且不含潜艇"),
    TaskCard("T050", 3, 3, 4, "赢得一墩：总点数为 22 或 23"),
    TaskCard("T051", 3, 3, 3, "恰好赢得一张潜艇"),
    TaskCard("T052", 3, 3, 3, "只赢得潜艇1，不赢得其他潜艇"),
    TaskCard("T053", 3, 3, 3, "只赢得潜艇2，不赢得其他潜艇"),
    TaskCard("T054", 1, 1, 1, "赢得潜艇3"),
    TaskCard("T055", 3, 3, 4, "恰好赢得两张潜艇"),
    TaskCard("T056", 3, 4, 4, "恰好赢得三张潜艇"),
    TaskCard("T057", 1, 1, 1, "不赢得任何潜艇"),
    TaskCard("T058", 3, 3, 3, "用潜艇赢得粉7"),
    TaskCard("T059", 3, 3, 3, "用潜艇赢得绿9"),
    TaskCard("T060", 4, 3, 3, "不要用粉牌、黄牌或蓝牌开墩"),
    TaskCard("T061", 2, 1, 1, "不要用粉牌或绿牌开墩"),
    TaskCard("T062", 2, 2, 2, "不要赢得任何绿牌"),
    TaskCard("T063", 2, 2, 2, "不要赢得任何黄牌"),
    TaskCard("T064", 3, 3, 3, "不要赢得任何粉牌或蓝牌"),
    TaskCard("T065", 3, 3, 3, "不要赢得任何黄牌或绿牌"),
    TaskCard("T066", 3, 3, 2, "不要赢得任何 8 或 9"),
    TaskCard("T067", 1, 1, 1, "不要赢得任何 9"),
    TaskCard("T068", 1, 2, 2, "不要赢得任何 5"),
    TaskCard("T069", 2, 2, 2, "不要赢得任何 1"),
    TaskCard("T070", 3, 3, 3, "不要赢得任何 1、2 或 3"),
    TaskCard("T071", 1, 2, 3, "不要赢得前四墩中的任何一墩"),
    TaskCard("T072", 1, 2, 2, "不要赢得前三墩中的任何一墩"),
    TaskCard("T073", 2, 3, 3, "不要赢得前五墩中的任何一墩"),
    TaskCard("T074", 4, 3, 3, "不要赢得任何墩"),
    TaskCard("T075", 3, 2, 2, "不要连续赢得两墩"),
    TaskCard("T076", 2, 3, 3, "赢得最后一墩"),
    TaskCard("T077", 2, 3, 4, "赢得前三墩"),
    TaskCard("T078", 1, 1, 2, "赢得前两墩"),
    TaskCard("T079", 1, 1, 1, "赢得第一墩"),
    TaskCard("T080", 3, 4, 4, "赢得第一墩和最后一墩"),
    TaskCard("T081", 4, 4, 4, "只赢得最后一墩"),
    TaskCard("T082", 4, 3, 3, "只赢得第一墩"),
    TaskCard("T083", 3, 2, 2, "恰好赢得一墩"),
    TaskCard("T084", 2, 2, 2, "恰好赢得两墩"),
    TaskCard("T085", 1, 1, 1, "连续赢得两墩"),
    TaskCard("T086", 2, 3, 4, "连续赢得三墩"),
    TaskCard("T087", 2, 3, 5, "恰好赢得四墩"),
    TaskCard("T088", 3, 3, 4, "恰好连续赢得三墩"),
    TaskCard("T089", 3, 3, 3, "恰好连续赢得两墩"),
    TaskCard("T090", 3, 2, 2, "赢得 X 墩（公开预测准确数字）"),
    TaskCard("T091", 4, 3, 3, "赢得 X 墩（秘密预测准确数字）"),
    TaskCard("T092", 4, 4, 4, "赢得相同数量的粉牌和黄牌（都必须大于 0）"),
    TaskCard("T093", 2, 3, 3, "赢得一墩：其中绿牌和黄牌数量相同（都必须大于 0）"),
    TaskCard("T094", 2, 3, 3, "赢得一墩：其中粉牌和蓝牌数量相同（都必须大于 0）"),
    TaskCard("T095", 1, 1, 1, "赢得的黄牌数量多于蓝牌数量（蓝牌可以为 0）"),
    TaskCard("T096", 1, 1, 1, "赢得的粉牌数量多于绿牌数量（绿牌可以为 0）"),
)


def draw_tasks(
    target_difficulty: int,
    player_count: int,
    rng: random.Random | None = None,
) -> list[dict[str, int | str | bool | None]]:
    """随机抽任务，直到难度合计等于目标值。

    按规则：超过目标的卡跳过。若一轮牌库扫完仍无法凑齐，则抛错。
    """
    if target_difficulty <= 0:
        raise ValueError("任务难度必须大于 0")
    rand = rng or random
    pool = list(TASK_CARDS)
    rand.shuffle(pool)
    selected: list[TaskCard] = []
    total = 0
    while pool and total < target_difficulty:
        card = pool.pop(0)
        diff = card.difficulty_for(player_count)
        if total + diff > target_difficulty:
            continue
        selected.append(card)
        total += diff
    if total != target_difficulty:
        raise ValueError(f"无法用任务卡凑出难度 {target_difficulty}")
    return [
        {
            "id": card.id,
            "text": card.text,
            "difficulty": card.difficulty_for(player_count),
            "assigned_to": None,
            "completed": False,
            "failed": False,
            "prediction": None,
        }
        for card in selected
    ]
