# 04 · 如何新增一个游戏

- **Status**: Draft v1
- **Last Updated**: 2026-04-28
- **Owner**: @owner

> 本文是新增游戏的 **step-by-step 指南**。配合 [`03-core-api.md`](./03-core-api.md) 一起看。
>
> ⚠️ **必读前置**：[`13-cli-bot-parity.md`](./13-cli-bot-parity.md) — CLI 与 Bot
> 交互必须保持 1:1 一致。新增游戏时必须同步实现 **游戏本体（bot 路径）+ CLI adapter**，
> 两者缺一不可。

---

## 1. 总览：六个步骤

```
1. 写游戏设计文档     →  docs/games/<id>.md
2. 创建游戏目录        →  src/plugins/games/<id>/
3. 实现 GameBase 子类   →  game.py
4. 注册到大厅           →  @register_game 装饰器自动完成
5. 写 CLI adapter      →  scripts/cli_adapters/<id>.py
                           在 scripts/play_cli.py 的 ADAPTERS 字典注册
6. 写玩法说明与测试     →  README.md + tests/
```

---

## 2. 游戏 ID 命名规范

- 全小写，下划线分隔：`turtle_soup`, `guess_number`, `werewolf`
- 一旦发布就不可更改（数据表、存档都会引用）
- 长度 ≤ 20 字符

---

## 3. 标准目录结构

```
src/plugins/games/<game_id>/
├─ __init__.py        # NoneBot 插件入口（一般只有 from .game import *）
├─ game.py            # 游戏主类（必需）
├─ config.py          # Pydantic 配置模型（可选）
├─ models.py          # 游戏专属数据表（可选）
├─ prompts.py         # LLM Prompt 模板（LLM 类游戏）
├─ commands.py        # 游戏内特殊指令（可选，复杂游戏才需要）
├─ templates/         # HTML 渲染模板（可选）
└─ README.md          # 玩法简介 + 指向 docs/games/<id>.md
```

---

## 4. 最小可用实现（骨架）

```python
# src/plugins/games/<game_id>/game.py
from core import session, llm
from core.game_base import GameBase, GameContext, GameMode, register_game, EndReason
from core.errors import TimeoutError, PlayerQuitError


@register_game
class YourGame(GameBase):
    id = "your_game"
    name = "你的游戏"
    description = "一句话介绍"
    min_players = 1
    max_players = 5
    version = "1.0"

    # 必须声明至少一个开局模式（CLI 和 bot 共享）
    MODES = [
        GameMode(id="normal", name="常规", description="默认规则"),
        GameMode(id="hard", name="困难", description="AI 更强"),
    ]

    async def on_create(self, ctx: GameContext) -> None:
        """开局前准备（例如出题）。
        mode = ctx.config.get('mode') 可拿到玩家选的模式 ID。
        """
        mode = ctx.config.get("mode", "normal")
        ctx.state["score"] = {p.qq_id: 0 for p in ctx.players}

    async def on_start(self, ctx: GameContext) -> None:
        """开局播报"""
        await session.broadcast(
            ctx.group_id,
            f"【{self.name}】开始！玩家：{', '.join(p.nickname for p in ctx.players)}"
        )

    async def on_player_action(
        self, ctx: GameContext, player_id: int, message: str
    ) -> None:
        """玩家发言处理"""
        pass

    async def on_end(self, ctx: GameContext, reason: EndReason) -> None:
        """清理"""
        await session.broadcast(ctx.group_id, f"【{self.name}】结束（{reason.value}）")
```

注册后，玩家在群里发 `/开始` 即可引导选择；`/开始 your_game` 跳过游戏选择；
`/开始 your_game normal` 直接开局。

### 配套：CLI Adapter（必须同时提交，见项目铁律）

```python
# scripts/cli_adapters/your_game.py
from src.plugins.games.your_game.game import YourGame
from .base import C, GameCLIAdapter, box, info, prompt


class YourGameCLIAdapter(GameCLIAdapter):
    game_name = YourGame.name
    MODES = YourGame.MODES   # 直接复用游戏本体的声明

    def __init__(self, *, debug=False):
        self.debug = debug

    async def start(self, mode_id: str) -> None:
        # 按模式准备（可以直接复用 bot 侧的 service 函数）
        ...

    async def play(self) -> None:
        # 主循环：input() → 判定 → 打印
        ...
```

别忘了在 `scripts/play_cli.py` 的 `ADAPTERS` 字典里注册一行。

---

## 5. 两种主流游戏范式

### 范式 A：**指令驱动**（回合制、有明确"该谁了"）
典型：五子棋、斗地主。

```python
async def on_start(self, ctx):
    current = ctx.players[0]
    while not self._is_game_over(ctx):
        try:
            move = await session.ask(
                current.qq_id,
                f"@{current.nickname} 你的回合",
                group_id=ctx.group_id,
                timeout=60,
            )
        except TimeoutError:
            await session.broadcast(ctx.group_id, f"{current.nickname} 超时")
            break
        # 处理 move
        current = self._next_player(ctx, current)
```

此时通常**不实现** `on_player_action`，一切在 `on_start` 的大循环里跑。

### 范式 B：**事件驱动**（玩家随时可发言）
典型：海龟汤、狼人杀的讨论阶段。

```python
async def on_player_action(self, ctx, player_id, message):
    if message.startswith("？") or message.endswith("?"):
        # 判定问题
        verdict = await llm.chat(..., scene="turtle_soup_judge")
        await session.broadcast(ctx.group_id, f"答：{verdict}")
```

此时 `on_start` 通常只做播报，主循环由 Core 通过消息事件驱动。

**两种范式可以混合**：例如狼人杀夜间用范式 A（按顺序行动），白天用范式 B（自由讨论）。

---

## 6. 并发处理

`on_player_action` 可能被**并发调用**（多玩家同时发言）。

**推荐方式**：在类顶部声明串行化，Core 会自动加锁。

```python
@register_game
class YourGame(GameBase):
    serialize_actions = True   # 每局内的 on_player_action 串行执行
```

如需自定义粒度（例如只锁关键区），用 `asyncio.Lock`：

```python
async def on_create(self, ctx):
    ctx.state["_lock"] = asyncio.Lock()

async def on_player_action(self, ctx, player_id, message):
    async with ctx.state["_lock"]:
        ...
```

---

## 7. 数据持久化

### 7.1 运行时状态（自动存档）

放入 `ctx.state`，Core 会自动序列化保存。**要求**：可 JSON 序列化。

```python
ctx.state["round"] = 3
ctx.state["answers"] = {"114514": "xxx"}
```

### 7.2 长期数据（自定义表）

需要跨对局持久化的内容（题库、用户战绩等）才建表。

```python
# models.py
from core.storage import Base, register_model
from sqlalchemy.orm import Mapped, mapped_column

class SoupPuzzle(Base):
    __tablename__ = "game_turtle_soup_puzzle"   # 强制前缀
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    story: Mapped[str]
    truth: Mapped[str]

register_model(SoupPuzzle, migration_group="game_turtle_soup")
```

启动时 Alembic 会自动建表。

---

## 8. LLM 使用清单

若游戏用到 LLM：

1. **在 `prompts.py` 中集中管理所有 prompt**，不要散落在代码里
2. **声明场景**（`scene` 参数），不硬编码 model
3. **判定类任务用 `json_mode=True`**
4. **长对话裁剪历史**（工具函数 `llm.trim_history(msgs, max_tokens)`）
5. **失败降级**：`try/except LLMError`，给玩家友好提示

详见 `08-llm-integration.md`（第二批）。

---

## 9. 配置

若游戏有可调参数，使用 pydantic：

```python
# config.py
from pydantic_settings import BaseSettings

class YourGameConfig(BaseSettings):
    max_rounds: int = 20
    question_timeout: int = 120

    class Config:
        env_prefix = "GAME_YOUR_GAME_"   # 强制前缀
```

环境变量 `GAME_YOUR_GAME_MAX_ROUNDS=30` 即可覆盖。

---

## 10. 测试

每个游戏至少包含：

```
tests/games/<game_id>/
├─ test_basic_flow.py       # 跑通开局→结束
├─ test_edge_cases.py       # 超时、玩家退出、异常恢复
└─ test_llm_mock.py         # LLM 用 mock，不打真实 API
```

使用 `core.testing` 提供的测试工具（第二批建设）：

```python
from core.testing import GameTestHarness

async def test_basic():
    async with GameTestHarness(YourGame, players=[1001, 1002]) as h:
        await h.start()
        await h.send(1001, "hello")
        assert "..." in h.last_broadcast
```

---

## 11. 文档要求

新游戏**必须**配套：

1. `docs/games/<game_id>.md`：玩法规则、状态机、Prompt 设计、边界情况
2. `src/plugins/games/<game_id>/README.md`：简介 + 指令速查 + 指向上文
3. 更新 `README.md` 的游戏列表

**无文档不合并。**

---

## 12. Checklist：提交前自查

- [ ] 目录结构符合规范
- [ ] 继承 `GameBase` 并用 `@register_game` 注册
- [ ] 元信息（id/name/min/max_players）完整
- [ ] 全部通过 `core.*` 调用，未直接 import NoneBot
- [ ] 数据表前缀 `game_<id>_`
- [ ] 使用 `ctx.state` 保存运行时状态，不用实例变量
- [ ] LLM 调用指定 `scene`，prompt 在 `prompts.py`
- [ ] 有 `docs/games/<id>.md`
- [ ] 有至少 1 个基础测试
- [ ] `on_end` 中释放所有资源（取消计时器、清理临时数据）
