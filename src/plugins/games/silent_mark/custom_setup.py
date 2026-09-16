"""自定义板子的分步向导（**Bot 与 CLI 共用这一份**）。

为什么单独成文件：这是**交互**，不是规则。`docs/13-cli-bot-parity.md` 要求
CLI 与群里走同一段问答，所以这里只允许依赖 `session` 的原语
（`choose` / `whisper`），调用方决定它跑在群里还是终端上：

- **Bot**：房主在报名阶段发 `@我 板子 自定义` → 向导在**私聊**里跑
  （群里不该出现"房主在配板子"的问答刷屏）；
- **CLI**：`play_cli.py silent_mark custom` → 同一个函数，IO 被 adapter 接到终端。

流程（源项目 `CreateRoomModal` 的等价物，只是把 12 个下拉换成分步选择）：

1. 选人数（4~12）
2. **逐位落座**：每个座位选一个角色
3. 胜负条件（屠边 / 屠城）
4. 物品开 / 关
5. 总览 → 确认 / 重来 / 取消

最后**一定**过一遍 `resolve.validate_game_settings`：不合法就把原因说清楚并允许重来，
绝不开出一局坏棋。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core import session
from core.errors import PlayerQuitError, WhisperFailedError
from core.errors import TimeoutError as GameTimeoutError

from .engine import constants as C  # noqa: N812
from .engine import resolve

#: 落座候选顺序：狼 → 神 → 民（与 `ROLE_LABELS` 顺序一致，读起来顺）
CAST_ORDER: tuple[str, ...] = (
    C.WEREWOLF,
    C.WOLF_KING,
    C.SEER,
    C.WITCH,
    C.HUNTER,
    C.GUARD,
    C.GRAVEDIGGER,
    C.FOOL,
    C.KNIGHT,
    C.VILLAGER,
)


@dataclass
class CustomBoard:
    """向导的产物。``to_config()`` 直接喂给 `create_and_start(config=...)`。"""

    roles: dict[str, int] = field(default_factory=dict)
    win_condition: str = C.WIN_EDGE
    items_enabled: bool = True

    @property
    def player_count(self) -> int:
        return sum(self.roles.values())

    def to_config(self) -> dict[str, object]:
        return {
            "mode": "custom",
            "roles": {role: count for role, count in self.roles.items() if count},
            "win_condition": self.win_condition,
            "items": self.items_enabled,
        }

    def describe(self) -> str:
        role_text = " · ".join(
            f"{C.ROLE_LABELS.get(role, role)}×{count}"
            for role, count in self.roles.items()
            if count
        )
        win = "屠边" if self.win_condition == C.WIN_EDGE else "屠城"
        items = "开" if self.items_enabled else "关"
        return f"{self.player_count} 人｜{role_text}｜{win}｜物品{items}"


# =====================================================================
# session 原语的安全包装：任何一种"拿不到输入"都归一成 None
# =====================================================================
async def _choose(
    qq_id: int, options: list[str], *, prompt: str, timeout: float | None
) -> int | None:
    """返回**下标**；拿不到输入返回 None。

    ⚠️ 必须接住 `ValueError`：`session.choose` 的 validator 重试次数用尽时抛的就是它，
    不接住等于"玩家连续答错就把整局崩掉"。
    """
    try:
        return await session.choose(
            qq_id, options, prompt=prompt, timeout=timeout
        )
    except (GameTimeoutError, PlayerQuitError, WhisperFailedError, ValueError):
        return None


async def _say(qq_id: int, text: str) -> None:
    """向导的反馈一律走私聊（群里保持安静）。"""
    try:
        await session.whisper(qq_id, text)
    except WhisperFailedError:
        pass


def _counts(cast: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for role in cast:
        counts[role] = counts.get(role, 0) + 1
    return counts


def _cast_line(cast: list[str], total: int) -> str:
    role_text = "、".join(
        f"{C.ROLE_LABELS.get(role, role)}×{count}"
        for role, count in _counts(cast).items()
    )
    return f"🛠 已落座 {len(cast)}/{total}：{role_text or '（空）'}"


# =====================================================================
# 向导
# =====================================================================
async def run_custom_wizard(
    qq_id: int, *, timeout: float | None = None
) -> CustomBoard | None:
    """跑一遍自定义向导。

    ``timeout``：真人传 None（本仓库大原则：AI 有超时、真人没有）。
    返回 ``None`` = 房主取消 / 退出 / 私聊不可达 / 反复答错。
    """
    sizes = [str(n) for n in range(C.MIN_PLAYERS, C.MAX_PLAYERS + 1)]
    picked = await _choose(
        qq_id,
        sizes,
        prompt=(
            f"🛠 自定义板子 · 第 1 步：几个人？\n回复数字（{C.MIN_PLAYERS}~{C.MAX_PLAYERS}）"
        ),
        timeout=timeout,
    )
    if picked is None:
        return None
    total = C.MIN_PLAYERS + picked

    while True:
        cast = await _pick_cast(qq_id, total, timeout=timeout)
        if cast is None:
            return None

        board = CustomBoard(roles=_counts(cast))
        # 先问胜负条件，再问物品（都影响校验文案）
        win = await _choose(
            qq_id,
            ["屠边（杀光神职 或 杀光平民）", "屠城（杀光所有好人）"],
            prompt="🛠 第 3 步：狼人怎么赢？",
            timeout=timeout,
        )
        if win is None:
            return None
        board.win_condition = C.WIN_EDGE if win == 0 else C.WIN_CITY

        items = await _choose(
            qq_id,
            ["开（随身物品 → 出局公开为遗物）", "关"],
            prompt="🛠 第 4 步：要不要随身物品？",
            timeout=timeout,
        )
        if items is None:
            return None
        board.items_enabled = items == 0

        ok, reason = resolve.validate_game_settings({**board.to_config(), "mode": "custom"})
        if not ok:
            # 不合法：说清原因，让他重新选人（人数/阵营比例改起来最频繁）
            await _say(qq_id, f"⚠️ 这个板子不合法：{reason}\n我们重新选一次角色。")
            continue

        action = await _choose(
            qq_id,
            ["就用这个", "重新选人", "取消"],
            prompt=f"🛠 板子总览：{board.describe()}\n确认的话我就把它设成本局板子。",
            timeout=timeout,
        )
        if action is None or action == 2:
            return None
        if action == 0:
            return board
        # action == 1 → 重来：人数也重新问（可能想换人数）


async def _pick_cast(qq_id: int, total: int, *, timeout: float | None) -> list[str] | None:
    """逐位落座。返回角色列表（长度 = total），或 None（取消）。

    逐位而不是"每个角色填数量"：源项目 UI 就是**每个座位一个下拉**，
    逐位落座能保证人数绝对精确，也不会出现"配到一半发现人数不对"。
    """
    cast: list[str] = []
    for seat in range(1, total + 1):
        counts = _counts(cast)
        options = [
            (
                f"{C.ROLE_LABELS.get(role, role)}（已 {counts[role]}）"
                if counts.get(role)
                else C.ROLE_LABELS.get(role, role)
            )
            for role in CAST_ORDER
        ]
        index = await _choose(
            qq_id,
            options,
            prompt=f"🛠 第 2 步 · {seat}/{total} 号位是什么角色？",
            timeout=timeout,
        )
        if index is None:
            return None
        cast.append(CAST_ORDER[index])
        await _say(qq_id, _cast_line(cast, total))
    return cast
