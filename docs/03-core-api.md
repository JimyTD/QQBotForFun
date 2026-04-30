# 03 · Core 层接口契约

- **Status**: Draft v1
- **Last Updated**: 2026-04-28
- **Owner**: @owner
- **Audience**: 游戏插件开发者

> 本文是 **Core 层对 Games 层的正式 API 契约**。
> 游戏开发者只应使用本文档列出的接口。
> 任何 API 的**签名修改**必须：(1) 更新本文档 (2) bump Core 版本 (3) 通知下游游戏。

---

## 0. 使用约定

```python
# Games 层中统一通过 core 命名空间导入
from core import session, user, economy, llm, scheduler, render, permission
from core.game_base import GameBase, GameContext
from core.errors import GameError, TimeoutError, PlayerQuitError
```

**禁止**：
- `from nonebot import ...`
- `from sqlalchemy import ...`
- 直接 import OneBot adapter

Core 层是唯一允许依赖 NoneBot 的地方。

---

## 1. `core.types` — 公共数据结构

```python
@dataclass(frozen=True)
class User:
    qq_id: int
    nickname: str          # 群昵称 > QQ 昵称 > QQ 号
    group_id: int | None   # 来源群（私聊场景为 None）

@dataclass(frozen=True)
class GroupInfo:
    group_id: int
    name: str
    member_count: int

class Scope(str, Enum):
    GROUP = "group"
    PRIVATE = "private"

@dataclass
class GameContext:
    """游戏运行期上下文，由 Core 构造并传入 Game 生命周期钩子"""
    session_id: str           # 本局游戏唯一 ID
    game_id: str              # 游戏类型 ID，如 "turtle_soup"
    group_id: int             # 游戏所在群
    host_id: int              # 开局者 QQ
    players: list[User]       # 参与玩家
    started_at: datetime
    config: dict              # 本局配置（由 launcher 传入）
    state: dict               # 游戏自定义状态（由 Game 管理）
```

---

## 2. `core.session` — 会话与 I/O（最常用）

这是游戏与玩家交互的唯一通道。

### 2.1 发送消息

```python
async def broadcast(
    group_id: int,
    message: str | Message,
    *,
    at: int | list[int] | None = None,   # @某人，None 表示不 @
) -> None
    """向群内发送消息"""

async def whisper(
    qq_id: int,
    message: str | Message,
) -> None
    """私聊发送（例如发手牌）。若用户未加机器人好友会抛 WhisperFailedError"""

async def reply(
    event_ref: EventRef,    # on_player_action 收到的消息引用
    message: str | Message,
) -> None
    """引用回复某条消息"""
```

### 2.2 接收消息

```python
async def ask(
    qq_id: int,
    prompt: str | None = None,
    *,
    group_id: int | None = None,      # None 表示私聊；指定群则只接收该群此人的消息
    timeout: float = 300,
    validator: Callable[[str], bool] | None = None,
    retry_prompt: str = "输入无效，请重试",
    max_retries: int = 3,
) -> str
    """等待用户的下一条文本消息
    超时 → TimeoutError
    用户发送 /quit → PlayerQuitError
    """

async def choose(
    qq_id: int,
    options: list[str],
    *,
    group_id: int | None = None,
    timeout: float = 60,
    prompt: str | None = None,
) -> int
    """让用户从编号列表中选择。返回索引（0-based）。"""

async def wait_any(
    group_id: int,
    *,
    from_players: list[int] | None = None,  # None = 所有玩家
    timeout: float = 300,
    predicate: Callable[[Message, int], bool] | None = None,
) -> tuple[int, str]
    """等待群内任一玩家发言，返回 (qq_id, message_text)
    海龟汤的核心原语：玩家随时可问问题
    """
```

### 2.3 会话控制

```python
async def register_game_session(ctx: GameContext) -> None
    """向 session 路由器注册活跃对局。之后该群的消息会被路由给该游戏。"""

async def unregister_game_session(session_id: str) -> None
    """结束时必须调用，否则群消息会持续路由"""

async def is_in_game(group_id: int) -> str | None
    """查询该群当前活跃的 game_id；无则返回 None"""
```

---

## 3. `core.user` — 用户信息

```python
async def get(qq_id: int, group_id: int | None = None) -> User
async def get_many(qq_ids: list[int], group_id: int | None = None) -> list[User]
async def get_group_members(group_id: int) -> list[User]
async def get_group_info(group_id: int) -> GroupInfo
```

实现细节：
- 昵称有 60s 内存缓存
- 群成员列表有 5 分钟缓存，`/refresh_members` 可强制刷新

---

## 4. `core.economy` — 经济系统

跨游戏通用，所有游戏**共享**同一套金币/道具体系。

### 4.1 货币

```python
async def balance(qq_id: int, currency: str = "coin") -> int
async def add(qq_id: int, amount: int, *, reason: str, currency: str = "coin") -> int
async def deduct(qq_id: int, amount: int, *, reason: str, currency: str = "coin") -> int
    """余额不足抛 InsufficientFundsError"""
async def transfer(from_id: int, to_id: int, amount: int, *, reason: str) -> None
```

所有货币变动**必须传 reason**，写入流水表用于追溯与防刷。

### 4.2 道具/背包

```python
async def add_item(qq_id: int, item_id: str, count: int = 1) -> None
async def remove_item(qq_id: int, item_id: str, count: int = 1) -> None
async def has_item(qq_id: int, item_id: str, count: int = 1) -> bool
async def list_items(qq_id: int) -> dict[str, int]   # {item_id: count}
```

### 4.3 内置货币

- `coin`：通用金币
- `ticket`：入场券（将来用）
- `score`：跨游戏积分（趣味问答等"答对得分"类游戏共用）
- 游戏可申请自定义货币，通过 `core.economy.register_currency("<id>")` 注册

### 4.4 榜单（Leaderboard）

跨游戏通用排行榜查询。`/榜` 指令基于这组 helper 实现。

```python
@dataclass(frozen=True)
class LeaderboardEntry:
    rank: int       # 1-based
    qq_id: int
    balance: int

async def top_balances(
    currency: str = "score",
    *,
    limit: int = 10,
    min_balance: int = 1,   # balance < min_balance 的不入榜
) -> list[LeaderboardEntry]

async def rank_of(
    qq_id: int,
    currency: str = "score",
    *,
    min_balance: int = 1,
) -> tuple[int | None, int]
    """返回 (rank, balance)。rank=None 表示未上榜。
    并列使用"标准竞赛排名"：100,100,50 → 排名 1,1,3。
    """

async def count_in_leaderboard(
    currency: str = "score",
    *,
    min_balance: int = 1,
) -> int
    """榜单总人数。"""
```

排序规则：`balance DESC, qq_id ASC`（稳定）。

---

## 5. `core.llm` — LLM 统一网关

```python
@dataclass
class LLMMessage:
    role: Literal["system", "user", "assistant"]
    content: str

@dataclass
class LLMResponse:
    content: str
    model: str           # 实际使用的模型
    usage: dict          # tokens 统计
    latency_ms: int

async def chat(
    messages: list[LLMMessage],
    *,
    scene: str,                              # 必填，用于路由到场景配置
    temperature: float | None = None,        # None = 用 scene 默认
    max_tokens: int | None = None,
    json_mode: bool = False,                 # True 强制 JSON 输出
    response_schema: dict | None = None,     # JSON Schema，json_mode 时使用
    timeout: float = 60,
) -> LLMResponse

async def chat_stream(...) -> AsyncIterator[str]
    """流式返回，用于实时展示"""

async def embedding(text: str | list[str], *, scene: str = "default") -> list[list[float]]
```

**scene 是核心概念**：游戏不指定模型名，而是指定"场景"，由配置层决定用哪个模型。

示例配置（`config.yaml`）：
```yaml
llm:
  scenes:
    turtle_soup_host:       # 出题
      provider: anthropic
      model: claude-sonnet-4.5
      temperature: 0.9
    turtle_soup_judge:      # 判定
      provider: deepseek
      model: deepseek-chat
      temperature: 0.1
      json_mode_default: true
    default:
      provider: deepseek
      model: deepseek-chat
```

详见 [`adr/0003-llm-gateway.md`](./adr/0003-llm-gateway.md) 和 `08-llm-integration.md`。

---

## 6. `core.scheduler` — 调度

```python
async def schedule_once(
    delay: float,                   # 秒
    callback: Callable[..., Awaitable],
    *,
    tag: str | None = None,         # 便于取消
    **kwargs,
) -> str                            # 返回 job_id

async def schedule_cron(
    cron: str,                      # "0 9 * * *"
    callback: Callable[..., Awaitable],
    **kwargs,
) -> str

async def cancel(job_id_or_tag: str) -> int   # 返回取消数量

async def start_turn_timer(
    session_id: str,
    seconds: float,
    on_timeout: Callable[[], Awaitable],
) -> None
    """游戏回合计时器，session 结束时自动清理"""
```

---

## 7. `core.render` — 图片渲染

```python
async def render_html(
    template_name: str,            # 模板文件名（相对 templates/）
    data: dict,
    *,
    width: int = 800,
    height: int | None = None,     # None = 自动
) -> bytes                         # PNG bytes

async def render_text_card(
    title: str,
    body: str,
    *,
    theme: str = "default",
) -> bytes
    """快速文字卡片，无需写模板"""

# 消息构造辅助
def image(png_bytes: bytes) -> Message
    """将 PNG bytes 包装成可发送的 Message"""
```

---

## 8. `core.permission` — 权限与限流

```python
# 装饰器形式
@permission.cooldown(user=10, group=3)   # 用户级 10s, 群级 3s
@permission.rate_limit(per_minute=20, scope="user")
@permission.require_role("admin")        # admin / owner / member
async def some_command(...): ...

# 函数形式（在游戏内部用）
async def check_cooldown(qq_id: int, key: str, seconds: float) -> float
    """返回剩余秒数，0 表示无冷却"""
async def set_cooldown(qq_id: int, key: str, seconds: float) -> None
```

---

## 9. `core.storage` — 数据持久化

游戏通常**不直接**用本模块，而是通过 `GameBase` 的自动存档机制。
如需自定义数据表：

```python
from core.storage import Base, register_model

class TurtleSoupPuzzle(Base):
    __tablename__ = "game_turtle_soup_puzzle"   # 必须带 game_<id>_ 前缀
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    story: Mapped[str]
    truth: Mapped[str]
    ...

register_model(TurtleSoupPuzzle, migration_group="game_turtle_soup")
```

表名未带合法前缀会在启动时报错。

---

## 10. `core.game_base` — 游戏基类

```python
class GameBase(ABC):
    # === 元信息（子类必须覆盖）===
    id: ClassVar[str]                   # 如 "turtle_soup"
    name: ClassVar[str]                 # 如 "海龟汤"
    description: ClassVar[str]
    min_players: ClassVar[int] = 1
    max_players: ClassVar[int] = 10
    version: ClassVar[str] = "1.0"

    # === 生命周期钩子（子类按需实现）===
    async def on_create(self, ctx: GameContext) -> None:
        """开局前调用，用于出题、初始化"""

    async def on_start(self, ctx: GameContext) -> None:
        """所有玩家就位后调用"""

    async def on_player_action(
        self, ctx: GameContext, player_id: int, message: str,
    ) -> None:
        """玩家在游戏中发言时调用"""

    async def on_timeout(self, ctx: GameContext) -> None:
        """整局超时（由 launcher 配置）"""

    async def on_end(self, ctx: GameContext, reason: EndReason) -> None:
        """结束时调用，清理资源"""

    # === 状态持久化（默认实现基于 ctx.state 的 JSON）===
    def dump_state(self, ctx: GameContext) -> dict: ...
    def load_state(self, ctx: GameContext, data: dict) -> None: ...

class EndReason(str, Enum):
    COMPLETED = "completed"       # 正常结束
    TIMEOUT = "timeout"
    ABORTED = "aborted"           # 玩家 /quit
    ERROR = "error"               # 内部错误
```

**游戏必须通过 `@register_game` 装饰器注册**：

```python
from core.game_base import register_game

@register_game
class TurtleSoupGame(GameBase):
    id = "turtle_soup"
    name = "海龟汤"
    ...
```

---

## 11. `core.errors` — 异常

```python
class GameError(Exception):
    """游戏层所有异常的基类"""

class TimeoutError(GameError):
    """ask/choose 超时"""

class PlayerQuitError(GameError):
    """玩家主动退出（/quit）"""

class WhisperFailedError(GameError):
    """私聊发送失败（用户未加好友等）"""

class InsufficientFundsError(GameError):
    """经济余额不足"""

class LLMError(GameError):
    """LLM 调用失败（重试后仍失败）"""

class LLMJSONParseError(LLMError):
    """LLM json_mode 返回无法解析"""
```

---

## 12. 约定与最佳实践

### 12.1 消息控制
- 单条消息 ≤ 2000 字；超长必须拆分或转图片
- 连发消息间隔 ≥ 500ms，避免风控
- `broadcast` 内部已做节流，游戏无需自己 sleep

### 12.2 状态管理
- 运行时状态放在 `ctx.state`（一个 dict），Core 会自动持久化
- 不要在 Game 实例上保存状态（实例可能被回收重建）

### 12.3 并发
- `on_player_action` 可能并发（多玩家同时发言）
- 游戏内共享状态需自行加锁，推荐用 `asyncio.Lock`
- 或者在 game class 顶部声明 `serialize_actions = True`，由 Core 串行化

### 12.4 LLM 成本控制
- 必须指定 `scene`，不允许硬编码 model
- 长对话使用滑动窗口裁剪历史
- 判定类任务优先 `json_mode=True`，便于解析

### 12.5 错误处理
```python
try:
    answer = await session.ask(player_id, "你的问题？", timeout=60)
except TimeoutError:
    await session.broadcast(ctx.group_id, "超时，跳过")
except PlayerQuitError:
    return await end_game(ctx, EndReason.ABORTED)
```

---

## 13. 版本与兼容性

- 本 API 版本：**v0.1**（首版，尚不稳定）
- 破坏性变更会 bump 到 v0.2，并在本文件顶部记录变更日志
- 稳定前（v1.0 前），不保证向后兼容，但**所有变更都会在本文档记录**

## 14. 变更日志

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-04-28 | 初版 |
| v0.2 | 2026-04-30 | `economy` 新增 `top_balances` / `rank_of` / `count_in_leaderboard` 三个榜单 helper；`score` 加入默认已注册货币（供趣味问答等游戏跨局累计积分使用）。 |
