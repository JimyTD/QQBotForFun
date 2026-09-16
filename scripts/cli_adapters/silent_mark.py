"""静夜标记 CLI adapter（热座）。

**里面没有一条游戏规则**：它把真实游戏跑起来，只把会话 IO 接到终端上
（`session.broadcast` / `whisper` / `ask` / `delete_message`）。
所以 CLI 与 QQ 群用的是同一份状态机、同一份文案 —— 这是
`docs/13-cli-bot-parity.md` 要求的对齐方式，也意味着本体改了文案，
CLI 自动跟着变，不会漂。

与 bot 的差异（都是 `docs/13` 允许的**机制**差异）：

- 不需要 @机器人；提示直接打在终端上。
- 私聊用 ``[私聊 3号 小刚]`` 前缀标出。真人一个人扮演所有座位，
  所以必须一眼看出"这句话群里能看到、那句话只有某个座位能看到"。
- 撤回（撤看板 / 撤玩家指令）不打印：CLI 是滚动日志，撤回只会添乱。
- 不发奖（避免污染真实金币/积分数据）。

输入约定（与 bot 保持同一套语义）：

- 直接输入 = 回答当前提问；
- ``退出`` / ``quit`` = **只让自己出局**（认输，遗物公开，别人继续打）；
- ``结束`` / ``abort`` = **终止整局**（等价于群里的 ``@我 结束``，任何人可用）；
- Ctrl+C / 管道结束 = 终止整局（CLI 专属的中断路径）。
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, patch

from cli_adapters.base import C, GameMode, box
from core import game_base, session
from core.errors import PlayerQuitError
from core.game_base import GameBase
from core.types import GameContext, User, new_session_id
from src.plugins.games.silent_mark.custom_setup import run_custom_wizard
from src.plugins.games.silent_mark.engine import constants as C_ENGINE  # noqa: N812
from src.plugins.games.silent_mark.game import DEFAULT_PRESET, SilentMarkGame

#: CLI 里的假群号（不占真实群）
_CLI_GROUP_ID = 88888
#: 房主座位：自定义向导以他的身份跑（与群里的房主是同一个概念）
_CLI_HOST = 1001
_ABORT_TOKENS = {"结束", "abort", "/结束", "/abort"}
_QUIT_TOKENS = {"退出", "quit", "/quit", "/q"}


def _ask_ai_seats(count: int) -> int:
    """问一句要不要 AI 补位。回车 = 0（默认还是"全部自己演"的热座模式）。"""
    raw = input(
        f"{C.YEL}AI 补位几个座位？(0~{count}，回车 = 0（全部自己演）) > {C.R}"
    ).replace("\ufeff", "").strip()
    if not raw:
        return 0
    try:
        return max(0, min(count, int(raw)))
    except ValueError:
        return 0


def _safe_print(text: str) -> None:
    """打印要经得起"控制台编码装不下 emoji"。

    Windows 控制台默认 GBK，直接 print 会抛 `UnicodeEncodeError`——
    ⚠️ 而它是 **`ValueError` 的子类**，会被业务流程里"输入不合法"的 except 顺手吞掉，
    最后表现成"向导莫名被取消"，极难定位（这次就踩了）。
    """
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(
            text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        )


class SilentMarkCLIAdapter:
    """热座 CLI：一个终端扮演全部座位。"""

    game_name = "静夜标记"
    MODES: list[GameMode] = SilentMarkGame.MODES

    def __init__(self, *, debug: bool = False) -> None:
        self.debug = debug
        self._task: asyncio.Task[None] | None = None
        self._runner: game_base.GameRunner | None = None
        self._labels: dict[int, str] = {}
        self._patches: list[Any] = []
        self._next_id = 1000
        self._aborted = False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    async def start(self, mode_id: str) -> None:
        # 先把 IO 接上：自定义向导要在这里跑（**与群里共用同一份实现**）
        self._labels = {_CLI_HOST: "房主（你）"}
        self._install_io()
        try:
            if mode_id == "custom":
                board = await run_custom_wizard(_CLI_HOST, timeout=None)
                if board is None:
                    raise RuntimeError("自定义向导被取消了")
                config: dict[str, Any] = board.to_config()
                count = board.player_count
                board_label = "自定义板子"
            else:
                preset = mode_id if mode_id in C_ENGINE.PRESETS else DEFAULT_PRESET
                config = {"mode": preset}
                count = sum(C_ENGINE.PRESETS[preset].roles.values())
                board_label = C_ENGINE.PRESET_LABELS.get(preset, preset)
        except Exception:
            self._uninstall_io()
            raise

        # 单人调试入口：剩下的座位交给 AI（群里就是"房主不凑人也能开"的同一条路）。
        # 至少留一个座位给自己 —— 否则房主/热座的概念就没着落了。
        ai_seats = min(_ask_ai_seats(count), max(0, count - 1))
        config["ai_seats"] = ai_seats
        human_count = count - ai_seats

        players = [
            User(qq_id=1000 + index, nickname=f"玩家{index}", group_id=_CLI_GROUP_ID)
            for index in range(1, human_count + 1)
        ]
        self._labels = {p.qq_id: f"{index}号 {p.nickname}" for index, p in enumerate(players, 1)}

        ctx = GameContext(
            session_id=new_session_id(),
            game_id=SilentMarkGame.id,
            group_id=_CLI_GROUP_ID,
            host_id=players[0].qq_id,
            players=players,
            started_at=datetime.utcnow(),
            config=config,
            state={},
        )
        game = SilentMarkGame()
        self._runner = game_base.GameRunner(game, ctx)
        game_base._runners[ctx.session_id] = self._runner
        game_base._runner_by_group[ctx.group_id] = self._runner

        box(
            f"🌙 静夜标记 · {board_label}",
            f"热座模式：你扮演 {human_count} 个座位"
            + (f"，另外 {ai_seats} 个由 AI 补位" if ai_seats else "（全部座位）")
            + "，按提示逐座位作答。\n"
            f"输入约定：直接作答　|　{C.YEL}退出{C.R} 只让自己出局　|　"
            f"{C.YEL}结束{C.R} 终止整局",
        )
        # 游戏主循环在 start 里跑完，所以放后台任务，由 play() 等它
        self._task = asyncio.create_task(self._runner.start())
        await asyncio.sleep(0.05)

    async def play(self) -> None:
        assert self._task is not None
        try:
            await self._task
        except asyncio.CancelledError:
            if not self._aborted:
                raise
            print(f"\n{C.YEL}🏳 已终止本局。{C.R}")
        except Exception as e:  # noqa: BLE001
            print(f"\n{C.RED}游戏异常：{e!r}{C.R}")
        else:
            # 局末打印复盘：**与群里 `@我 复盘` 同一份渲染**（CLI 跑通 = 群里能跑）
            if self._runner is not None and self._runner.ctx.state.get("winner"):
                for page in self._runner.game.replay_pages(self._runner.ctx):
                    _safe_print(f"\n{page}")
        finally:
            self._uninstall_io()
            self._cleanup()

    # ------------------------------------------------------------------
    # 会话 IO ↔ 终端
    # ------------------------------------------------------------------
    def _install_io(self) -> None:
        async def fake_broadcast(_group_id: int, message: Any, *, at: Any = None) -> int:
            mention = ""
            if at is not None:
                ats = [at] if isinstance(at, int) else list(at)
                mention = "　" + C.MAG + "@" + "、".join(self._label(qq) for qq in ats) + C.R
            self._emit("群", str(message) + mention, color=C.CYAN)
            self._next_id += 1
            return self._next_id

        async def fake_whisper(qq_id: int, message: Any) -> int:
            self._emit(f"私聊 {self._label(qq_id)}", str(message), color=C.MAG)
            self._next_id += 1
            return self._next_id

        async def fake_delete_message(_message_id: int) -> bool:
            # CLI 是滚动日志：撤回不打日志（机制差异，见模块 docstring）
            return True

        async def fake_ask(
            qq_id: int,
            prompt: str | None = None,
            *,
            group_id: int | None = None,
            timeout: float | None = None,  # noqa: ARG001
            **_kwargs: Any,
        ) -> str:
            # 正常情况下提示由游戏侧自己发（看板 / 提问槽），这里只是兜底
            if prompt:
                if group_id is not None:
                    self._emit("群", str(prompt) + "　" + f"@{self._label(qq_id)}", color=C.CYAN)
                else:
                    self._emit(f"私聊 {self._label(qq_id)}", str(prompt), color=C.MAG)
            return self._read_answer(qq_id)

        async def fake_award(*_args: Any, **_kwargs: Any) -> None:
            return None

        for target, name, effect in (
            (session, "broadcast", fake_broadcast),
            (session, "whisper", fake_whisper),
            (session, "ask", fake_ask),
            (session, "delete_message", fake_delete_message),
            # CLI 不发奖：避免把测试数据写进真实金币/积分
            (GameBase, "award", fake_award),
        ):
            patcher = patch.object(target, name, AsyncMock(side_effect=effect))
            patcher.start()
            self._patches.append(patcher)

    def _uninstall_io(self) -> None:
        for patcher in self._patches:
            patcher.stop()
        self._patches.clear()

    def _cleanup(self) -> None:
        if self._runner is not None:
            game_base._runner_by_group.pop(self._runner.ctx.group_id, None)
            game_base._runners.pop(self._runner.ctx.session_id, None)
            self._runner = None

    # ------------------------------------------------------------------
    # 终端
    # ------------------------------------------------------------------
    @staticmethod
    def _emit(channel: str, text: str, *, color: str) -> None:
        lines = text.splitlines() or [""]
        pad = " " * (len(channel) + 1)
        _safe_print(f"\n{color}{C.B}[{channel}]{C.R} {lines[0]}")
        for line in lines[1:]:
            _safe_print(f"{pad} {line}")

    def _label(self, qq_id: int) -> str:
        return self._labels.get(qq_id, str(qq_id))

    def _read_answer(self, qq_id: int) -> str:
        """读一条输入。``退出`` = 认输；``结束``/Ctrl+C = 终止整局。"""
        while True:
            try:
                # 去掉 UTF-8 BOM：Windows 上把文本用管道喂进来时会带上，
                # 而它既不是空白、也不被 strip() 吃掉，会一路污染到 int() 解析。
                raw = input(f"{C.YEL}{self._label(qq_id)} > {C.R}").replace(
                    "\ufeff", ""
                ).strip()
            except (KeyboardInterrupt, EOFError):
                print()
                self._aborted = True
                raise asyncio.CancelledError from None
            if raw in _ABORT_TOKENS:
                self._aborted = True
                raise asyncio.CancelledError
            if raw.lower() in _QUIT_TOKENS:
                raise PlayerQuitError(f"player {qq_id} quit")
            return raw
