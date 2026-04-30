"""CLI 游戏 adapter 的通用协议 + 终端工具。

所有游戏的 CLI 测试器实现这个协议即可被 play_cli.py 加载。

与 bot 侧对齐：
- `GameMode` 从 core.game_base 导入，保证 CLI / bot 用同一份定义
- 游戏本体（GameBase.MODES）是权威清单；CLI adapter 只是映射到本地执行
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# 复用 core 里的定义，保持 CLI 与 bot 一致（铁律）
from core.game_base import GameMode, resolve_mode  # noqa: F401  对外 re-export


# ================ 颜色与输出工具 ================
class C:
    R = "\033[0m"
    B = "\033[1m"
    CYAN = "\033[36m"
    YEL = "\033[33m"
    GRN = "\033[32m"
    RED = "\033[31m"
    MAG = "\033[35m"
    DIM = "\033[2m"


def box(title: str, body: str, color: str = C.CYAN) -> None:
    bar = "━" * 40
    print(f"\n{color}{C.B}{bar}{C.R}")
    print(f"{color}{C.B}{title}{C.R}")
    print(f"{color}{bar}{C.R}")
    print(body)
    print(f"{color}{bar}{C.R}\n")


def info(msg: str) -> None:
    print(f"{C.DIM}» {msg}{C.R}")


def prompt(msg: str = "你> ") -> str:
    try:
        return input(f"{C.YEL}{msg}{C.R}").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return "quit"


# ================ Adapter 协议 ================
@runtime_checkable
class GameCLIAdapter(Protocol):
    """每个游戏实现这个协议。

    必须提供：
    - game_name：玩家看到的名字
    - MODES：该游戏的所有开局模式（来源于 GameBase.MODES）
    - start(mode_id)：按模式开局
    - play()：进入交互主循环
    """

    game_name: str
    MODES: list[GameMode]

    def __init__(self, *, debug: bool = False) -> None: ...

    async def start(self, mode_id: str) -> None:
        """按指定模式准备游戏。失败应 raise。"""
        ...

    async def play(self) -> None:
        """进入游戏交互主循环，玩完为止。"""
        ...

    async def post_game_prompt(self) -> None:  # 可选
        """局末收尾 hook（打完一局、回到 '再来一局?' 提示之前）。

        Protocol 不强制必须实现；play_cli.py 会 hasattr 判断后再调用。
        适合用于 CLI 的"烂题反馈"等不影响游戏本身流程的交互。
        """
        ...
