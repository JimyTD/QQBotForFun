"""通用游戏 CLI 测试模拟器。

在终端里跟 LLM 玩一局游戏，不需要 NapCat / QQ。

用法：
    uv run --no-sync python scripts/play_cli.py              # 选游戏 → 选模式
    uv run --no-sync python scripts/play_cli.py turtle_soup  # 跳过游戏选择
    uv run --no-sync python scripts/play_cli.py turtle_soup 1        # 两步都跳过（按编号）
    uv run --no-sync python scripts/play_cli.py turtle_soup library  # 或按 mode id
    uv run --no-sync python scripts/play_cli.py turtle_soup 快速     # 或按别名

说明：
  本 CLI 和 QQ 群机器人的 /开始 指令交互逻辑保持 1:1 对齐，详见
  docs/13-cli-bot-parity.md（项目铁律）。

新增游戏：
  在 cli_adapters/ 下新建 adapter（实现 GameCLIAdapter 协议，声明 MODES），
  再到 ADAPTERS 字典注册。
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
from pathlib import Path

# Windows 控制台强制 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for p in (str(_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

_DEBUG = (
    os.environ.get("SOUP_DEBUG", "").strip() in ("1", "true", "yes")
    or os.environ.get("GAME_CLI_DEBUG", "").strip() in ("1", "true", "yes")
)

from core import llm  # noqa: E402
from core.storage import init_db  # noqa: E402

from cli_adapters.base import (  # noqa: E402
    C,
    GameCLIAdapter,
    GameMode,
    info,
    prompt,
    resolve_mode,
)
from cli_adapters.turtle_soup import TurtleSoupCLIAdapter  # noqa: E402
from cli_adapters.trivia import TriviaCLIAdapter  # noqa: E402
from cli_adapters.food import FoodCLIAdapter  # noqa: E402
from cli_adapters.web_search import WebSearchCLIAdapter  # noqa: E402


# ============ 已注册的 CLI 游戏 ============
# 顺序就是 "/菜单" 里的展示顺序
ADAPTERS: dict[str, type[GameCLIAdapter]] = {
    "turtle_soup": TurtleSoupCLIAdapter,
    "trivia": TriviaCLIAdapter,
    "food": FoodCLIAdapter,
    "ask_ai": WebSearchCLIAdapter,
    # "new_game": NewGameCLIAdapter,   # 未来新增
}


# ============ 选游戏（第一层）============
def pick_game(preselect: str | None = None) -> type[GameCLIAdapter] | None:
    """返回选中的 adapter 类；输入 q/quit 返回 None（退出）。

    preselect 非空时尝试直接解析，失败才进入交互。
    """
    names = list(ADAPTERS.keys())

    def _resolve_game(token: str) -> type[GameCLIAdapter] | None:
        t = token.strip().lower()
        if t in ADAPTERS:
            return ADAPTERS[t]
        try:
            idx = int(t)
            if 1 <= idx <= len(names):
                return ADAPTERS[names[idx - 1]]
        except ValueError:
            pass
        return None

    if preselect:
        cls = _resolve_game(preselect)
        if cls is not None:
            return cls
        print(f"{C.RED}未识别的游戏：{preselect}{C.R}")

    while True:
        print(f"\n{C.B}🎮 可用游戏{C.R}")
        for i, name in enumerate(names, 1):
            cls = ADAPTERS[name]
            print(f"  {C.CYAN}{i:>2}.{C.R} {cls.game_name}  {C.DIM}[{name}]{C.R}")
        print(f"  {C.CYAN}{'Q':>2}.{C.R} 退出")

        ch = prompt("\n选择游戏（编号 / ID / Q）> ").strip().lower()
        if ch in ("q", "quit", "exit"):
            return None
        cls = _resolve_game(ch)
        if cls is not None:
            return cls
        print(f"{C.RED}输入不对，重试。{C.R}")


# ============ 选模式（第二层）============
def pick_mode(
    adapter_cls: type[GameCLIAdapter], preselect: str | None = None
) -> GameMode | None:
    """返回选中的 GameMode；输入 q/quit 返回 None（退出当前游戏选择）。

    特例：如果 adapter 只定义了 1 个模式，直接返回它（无意义的"选择"略过）。
    """
    modes = adapter_cls.MODES
    if not modes:
        raise RuntimeError(f"{adapter_cls.__name__} has no MODES defined")

    # 单模式直接跳过菜单（工具型功能常见场景）
    if len(modes) == 1:
        return modes[0]

    if preselect:
        m = resolve_mode(modes, preselect)
        if m is not None:
            return m
        print(f"{C.RED}未识别的模式：{preselect}{C.R}")

    while True:
        print(f"\n{C.B}🎮 {adapter_cls.game_name}{C.R}")
        for i, mode in enumerate(modes, 1):
            sub = f"  {C.DIM}· {mode.description}{C.R}" if mode.description else ""
            print(f"  {C.CYAN}{i:>2}.{C.R} {mode.name}{sub}")
        print(f"  {C.CYAN}{'Q':>2}.{C.R} 返回上一级")

        ch = prompt("\n选择 > ").strip().lower()
        if ch in ("q", "quit", "exit"):
            return None
        m = resolve_mode(modes, ch)
        if m is not None:
            return m
        print(f"{C.RED}输入不对，重试。{C.R}")


# ============ 单局游戏流程 ============
async def run_one_game(
    adapter_cls: type[GameCLIAdapter], mode: GameMode
) -> None:
    adapter = adapter_cls(debug=_DEBUG)
    info(f"已选模式：{mode.name}。准备开局…")
    try:
        await adapter.start(mode.id)
    except Exception as e:  # noqa: BLE001
        print(f"{C.RED}准备失败：{e}{C.R}")
        return
    await adapter.play()
    # 局末可选 hook（如海龟汤的"烂题反馈"）
    post_hook = getattr(adapter, "post_game_prompt", None)
    if post_hook is not None:
        try:
            await post_hook()
        except Exception as e:  # noqa: BLE001
            print(f"{C.DIM}post_game_prompt error: {e}{C.R}")


# ============ 主流程 ============
async def main() -> None:
    print(f"{C.B}{C.CYAN}=== 🎮 游戏 CLI 测试器 ==={C.R}")
    if _DEBUG:
        print(f"{C.YEL}[DEBUG MODE ON]{C.R}")

    llm.init()
    await init_db()

    # 命令行参数：[game_id] [mode]
    args = sys.argv[1:]
    game_preselect = args[0] if len(args) >= 1 else None
    mode_preselect = args[1] if len(args) >= 2 else None

    first_iteration = True

    while True:
        adapter_cls = pick_game(game_preselect if first_iteration else None)
        if adapter_cls is None:
            break

        mode = pick_mode(
            adapter_cls, mode_preselect if first_iteration else None
        )
        first_iteration = False  # 之后不再沿用命令行参数
        if mode is None:
            continue  # 返回上一级（重新选游戏）

        await run_one_game(adapter_cls, mode)

        again = prompt("\n再来一局？(y/N) > ").strip().lower()
        if again not in ("y", "yes", "是", "好"):
            break

    print(f"\n{C.CYAN}拜拜 🎮{C.R}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{C.CYAN}中断退出 🎮{C.R}")
