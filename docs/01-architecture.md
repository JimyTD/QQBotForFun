# 01 · 架构设计

- **Status**: Draft v1
- **Last Updated**: 2026-04-28
- **Owner**: @owner

## 1. 设计目标

| # | 目标 | 设计含义 |
|---|---|---|
| G1 | **多游戏可插拔** | 新增游戏 = 新建目录 + 实现约定接口，对其他游戏零影响 |
| G2 | **游戏之间物理隔离** | 独立目录、独立数据表前缀、独立配置 key |
| G3 | **共享底层能力** | 所有游戏通过统一的 Core 层调用 LLM、会话、经济、渲染等 |
| G4 | **协议层可替换** | 今天用 NapCat（OneBot v11），未来可切官方 QQ API 而业务代码几乎不变 |
| G5 | **异步友好** | 游戏长时间等待是常态，框架不应假设玩家快速响应 |
| G6 | **可演进** | 从 SQLite 单机演进到 PostgreSQL + Redis 集群，业务代码不改 |

## 2. 分层架构

```
┌──────────────────────────────────────────────────────────────┐
│  L4  Games Layer                                             │
│      各小游戏插件，互不感知，只依赖 L3                         │
├──────────────────────────────────────────────────────────────┤
│  L3  Core Layer（本项目的核心抽象层）                         │
│      对上：为游戏提供稳定 API                                 │
│      对下：封装 NoneBot / OneBot / DB / LLM / Redis 等        │
├──────────────────────────────────────────────────────────────┤
│  L2  Framework Layer                                         │
│      NoneBot2 + adapter-onebot v11                           │
│      负责事件分发、插件加载、基础调度                         │
├──────────────────────────────────────────────────────────────┤
│  L1  Protocol Layer                                          │
│      NapCatQQ 进程                                            │
│      登录 QQ、暴露 OneBot v11 WebSocket                      │
└──────────────────────────────────────────────────────────────┘
```

**依赖方向**：只允许**上层依赖下层**，严禁反向或跨层跳跃。

- ✅ `Games → Core`
- ✅ `Core → Framework`
- ❌ `Games → Framework`（会破坏协议可替换性，禁止）
- ❌ `Core → Games`（Core 不能知道任何具体游戏存在）

## 3. 模块职责

### 3.1 Core Layer 模块划分

| 模块 | 文件 | 职责 |
|---|---|---|
| `core.session` | `session.py` | 多轮对话、等待输入、超时、主动发消息 |
| `core.user` | `user.py` | 用户档案、昵称、群成员列表 |
| `core.economy` | `economy.py` | 金币、道具、背包、跨游戏通用 |
| `core.render` | `render.py` | HTML→PNG、棋盘、卡牌、长图排行榜 |
| `core.llm` | `llm.py` | LLM 统一网关，多场景多模型 |
| `core.scheduler` | `scheduler.py` | 定时任务、延迟回调、回合计时器 |
| `core.storage` | `storage.py` | ORM 封装、模型注册、迁移 |
| `core.permission` | `permission.py` | 冷却、频率限制、角色权限 |
| `core.game_base` | `game_base.py` | 游戏基类、生命周期、状态持久化 |
| `core.types` | `types.py` | 公共数据结构（User、GameContext 等） |
| `core.errors` | `errors.py` | 公共异常类 |

所有 Core API 的**签名与契约**见 [`03-core-api.md`](./03-core-api.md)。

### 3.2 Games Layer 规范

每个游戏 = `src/plugins/games/<game_id>/` 目录，内含：

```
games/turtle_soup/
├─ __init__.py          # 注册插件、声明元信息
├─ game.py              # 继承 GameBase 的游戏主类
├─ prompts.py           # （LLM 类游戏）Prompt 模板
├─ models.py            # （可选）游戏专属数据表，表名强制前缀 game_<id>_
├─ commands.py          # 指令路由
├─ config.py            # 游戏专属配置
└─ README.md            # 游戏玩法说明 + 指向 docs/games/<id>.md
```

详见 [`04-game-development.md`](./04-game-development.md)。

### 3.3 非游戏插件

除 `games/` 外，还有"系统级插件"，也放在 `src/plugins/` 下，但不继承 `GameBase`：

| 插件 | 职责 |
|---|---|
| `plugins.core_commands` | `/help` `/menu` `/profile` 等全局指令 |
| `plugins.game_launcher` | 游戏大厅：列出游戏、开局、加入、退出 |
| `plugins.admin` | 管理员指令：封禁、调金币、查日志 |

## 4. 典型数据流

### 4.1 玩家输入 → 游戏响应

```
QQ 用户发群消息
   │
   ▼
NapCat  ── OneBot event ──▶  NoneBot2 adapter
                                │
                                ▼
                     NoneBot matcher 路由
                                │
             ┌──────────────────┴──────────────────┐
             ▼                                      ▼
       全局指令处理                           活跃游戏会话
       (plugins.core_commands)           (core.session 路由到游戏)
                                                   │
                                                   ▼
                                          Game.on_player_action()
                                                   │
                                                   ▼
                                         调用 core.llm / core.render ...
                                                   │
                                                   ▼
                                          core.session.broadcast()
                                                   │
                                                   ▼
                                       NoneBot → NapCat → QQ
```

**关键点**：游戏逻辑永远不直接调用 NoneBot 的 `bot.send()`，一律走 `core.session`。

### 4.2 定时驱动的游戏回合

```
APScheduler 触发
   │
   ▼
core.scheduler 回调
   │
   ▼
Game.on_timeout() / Game.on_turn()
   │
   ▼
core.session.broadcast() 通知玩家
```

## 5. 状态管理

### 5.1 运行时状态

- **内存**：活跃对局的运行时对象（如当前轮、当前提问者）
- **Redis**（生产）/ **内存字典**（开发）：跨进程共享的轻量状态，如会话锁、冷却

### 5.2 持久化状态

- **数据库**：用户档案、经济数据、游戏存档、历史战绩
- 每个游戏通过 `GameBase.dump_state() / load_state()` 支持崩溃恢复

### 5.3 隔离约定

- 公共表：`user`, `economy_balance`, `economy_item`, `game_session`
- 游戏专属表：强制前缀 `game_<id>_`，例如 `game_turtle_soup_puzzle`
- 游戏 A **禁止**读写游戏 B 的表

## 6. 配置与环境

- 使用 `pydantic-settings` + `.env`
- 三套环境：`dev` / `staging` / `prod`，通过 `APP_ENV` 切换
- 配置详情见 `06-configuration.md`（第二批文档）

## 7. 错误处理原则

| 层 | 原则 |
|---|---|
| Games | 只抛业务异常（继承自 `core.errors.GameError`），不处理网络/协议错误 |
| Core | 捕获所有底层异常，转换为业务语义异常或降级返回 |
| Framework | 由 NoneBot 兜底，未捕获异常写入日志，向群内发送友好提示 |

## 8. 可观测性

- **日志**：loguru，结构化 JSON，按日轮转
- **关键事件**：游戏开始/结束、LLM 调用耗时、异常、用户行为
- **追踪 ID**：每局游戏分配 `session_id`，贯穿所有日志

## 9. 未来演进预留

| 方向 | 预留设计 |
|---|---|
| 切换到官方 QQ API | Core 层已屏蔽协议差异，只需换 NoneBot adapter |
| 多机部署 | Redis 抽象已在 Core，session 状态可外置 |
| Web 管理后台 | ORM 已是 SQLAlchemy，可直接给 FastAPI 复用 |
| 跨群赛事/联赛 | `core.economy` 的跨游戏通用设计已经支撑 |
