# 10 · 路线图与实施清单

- **Status**: Baseline v1（**不可偏移，任何新增/调整必须更新本文件**）
- **Last Updated**: 2026-04-28
- **Owner**: @owner

> 本文件是项目"完整框架"交付的**权威清单**。
> 所有项必须完成，不允许"分批交付"或"先留 TODO 后面再补"。
> 如遇阻塞或决定裁掉某项，必须在本文件显式标注原因。

## 0. 交付原则

1. **完整**：清单内所有项必须实现，不留 `pass` / `raise NotImplementedError`
2. **可运行**：按 README 指引，最终能在本地和云端跑通完整海龟汤对局
3. **可观测**：所有模块有日志，失败有明确错误信息
4. **文档同步**：代码变更对应更新文档，不留过期描述

## 1. 文档清单

| ID | 文件 | 状态 | 说明 |
|---|---|---|---|
| D1 | `README.md` | ✅ 首版 | 结尾会补充启动说明 |
| D2 | `docs/01-architecture.md` | ✅ | 分层架构 |
| D3 | `docs/02-tech-stack.md` | ✅ | 技术选型 |
| D4 | `docs/03-core-api.md` | ✅ | Core API 契约 |
| D5 | `docs/04-game-development.md` | ✅ | 游戏开发指南 |
| D6 | `docs/05-deployment.md` | ⬜ | 部署指南（dev + prod） |
| D7 | `docs/06-configuration.md` | ⬜ | 配置说明 |
| D8 | `docs/07-database-schema.md` | ⬜ | 数据库设计 |
| D9 | `docs/08-llm-integration.md` | ⬜ | LLM 网关详解 + scene 清单 |
| D10 | `docs/09-conventions.md` | ⬜ | 编码与文档规范 |
| D11 | `docs/10-roadmap.md` | ✅ 本文件 | |
| D12 | `docs/11-ui-style.md` | ⬜ | 全文本 UI 排版规范 |
| D13 | `docs/games/turtle-soup.md` | ✅ | 海龟汤设计 |
| D14 | `docs/adr/0001-protocol-choice.md` | ✅ | |
| D15 | `docs/adr/0002-framework-choice.md` | ✅ | |
| D16 | `docs/adr/0003-llm-gateway.md` | ✅ | |

## 2. 目录结构（最终态）

```
QQBotForFun/
├─ .env.example
├─ .gitignore
├─ pyproject.toml
├─ uv.lock                              (生成)
├─ README.md
├─ Dockerfile
├─ docker-compose.yml                   (prod)
├─ docker-compose.dev.yml               (本地 NapCat + Redis)
├─ alembic.ini
├─ migrations/                          (Alembic)
│  ├─ env.py
│  └─ versions/
├─ docs/                                (见第 1 节)
├─ scripts/
│  ├─ seed_turtle_soup.py
│  └─ generate_soup_with_llm.py
├─ seeds/
│  └─ turtle_soup.json                  (3-5 道内置题)
├─ src/
│  ├─ bot.py                            (入口)
│  ├─ settings.py                       (pydantic-settings)
│  ├─ core/
│  │  ├─ __init__.py
│  │  ├─ types.py
│  │  ├─ errors.py
│  │  ├─ storage.py
│  │  ├─ user.py
│  │  ├─ session.py
│  │  ├─ economy.py
│  │  ├─ permission.py
│  │  ├─ scheduler.py
│  │  ├─ llm.py
│  │  ├─ render.py
│  │  └─ game_base.py
│  ├─ plugins/
│  │  ├─ core_commands/
│  │  │  ├─ __init__.py
│  │  │  └─ handlers.py
│  │  ├─ game_launcher/
│  │  │  ├─ __init__.py
│  │  │  └─ handlers.py
│  │  ├─ admin/
│  │  │  ├─ __init__.py
│  │  │  └─ handlers.py
│  │  └─ games/
│  │     └─ turtle_soup/
│  │        ├─ __init__.py
│  │        ├─ game.py
│  │        ├─ prompts.py
│  │        ├─ models.py
│  │        ├─ config.py
│  │        ├─ puzzle_service.py
│  │        └─ README.md
│  └─ testing/
│     └─ harness.py                     (GameTestHarness)
├─ tests/
│  ├─ conftest.py
│  ├─ core/
│  │  ├─ test_economy.py
│  │  ├─ test_session.py
│  │  ├─ test_permission.py
│  │  ├─ test_llm.py
│  │  ├─ test_render.py
│  │  └─ test_game_base.py
│  └─ games/
│     └─ turtle_soup/
│        ├─ test_flow.py
│        └─ test_classify.py
└─ napcat/
   └─ config.example.json               (NapCat 配置样例)
```

## 3. 实施清单（按顺序）

### 阶段 A · 文档补齐（先于代码）

| ID | 任务 | 验收 |
|---|---|---|
| A1 | 写 `docs/10-roadmap.md`（本文件） | 文件存在 |
| A2 | 写 `docs/11-ui-style.md` | 全文本排版规范、emoji 清单、卡片/菜单/列表模板 |
| A3 | 写 `docs/09-conventions.md` | 命名、日志、错误处理、git/提交规范 |
| A4 | 写 `docs/06-configuration.md` | 所有 env 变量、scene 配置示例 |
| A5 | 写 `docs/07-database-schema.md` | 核心表 + 游戏表前缀约定、ER 关系说明 |
| A6 | 写 `docs/08-llm-integration.md` | scene 清单、prompt 版本管理、成本估算 |
| A7 | 写 `docs/05-deployment.md` | 本地 dev + 云端 prod 步骤、NapCat 登录 |

### 阶段 B · 脚手架

| ID | 任务 | 验收 |
|---|---|---|
| B1 | `pyproject.toml`（uv 管理，依赖列表齐全） | `uv sync` 可成功 |
| B2 | `.env.example`、`.gitignore` | env.example 字段与 settings.py 一致 |
| B3 | `src/settings.py`（pydantic-settings） | 启动时加载 `.env`，缺必填项报错 |
| B4 | 目录骨架（全部 `__init__.py`） | 目录结构与第 2 节一致 |
| B5 | `alembic.ini` + `migrations/env.py` | `alembic upgrade head` 可执行 |

### 阶段 C · Core 层（按依赖顺序）

| ID | 任务 | 验收 |
|---|---|---|
| C1 | `core.errors`、`core.types` | 所有异常类与数据结构定义完整 |
| C2 | `core.storage` | Base、register_model、async session、表名前缀校验 |
| C3 | `core.user` | `get/get_many/get_group_members/get_group_info` 全实现，60s 缓存 |
| C4 | `core.permission` | cooldown/rate_limit 装饰器 + 函数式 API，dev 走内存，prod 走 Redis |
| C5 | `core.economy` | balance/add/deduct/transfer/道具全实现，流水表 |
| C6 | `core.scheduler` | schedule_once / schedule_cron / cancel / start_turn_timer |
| C7 | `core.session` | broadcast/whisper/reply/ask/choose/wait_any/register_game_session 完整 |
| C8 | `core.llm` | OpenAI 兼容、scene 路由、重试退避、JSON 模式、流式、日志 |
| C9 | `core.render` | text_card/menu/list/result/header/divider 等排版原语 |
| C10 | `core.game_base` | GameBase/@register_game/GameContext/EndReason/状态持久化/崩溃恢复 |

### 阶段 D · 系统插件

| ID | 任务 | 验收 |
|---|---|---|
| D1 | `plugins.core_commands` | `/help` `/menu` `/profile` `/balance` 可用 |
| D2 | `plugins.game_launcher` | `/games` `/play <id>` `/quit` 覆盖开局到结束流程 |
| D3 | `plugins.admin` | `/admin grant` `/admin ban` `/admin reload` 等基础命令 |

### 阶段 E · 海龟汤游戏

| ID | 任务 | 验收 |
|---|---|---|
| E1 | `models.py`（SoupPuzzle / SoupSession / SoupQuestion） | 表名带 `game_turtle_soup_` 前缀 |
| E2 | `prompts.py`（出题/判定/宣告 3 个 prompt，带版本号） | 独立文件，无散落硬编码 |
| E3 | `puzzle_service.py`（题库抽取 + LLM 生成 + 兜底） | 配置开关决定策略，失败降级 |
| E4 | `game.py`（状态机、消息分类、判定、宣告、结束） | 覆盖设计文档 §4 的所有流程 |
| E5 | `config.py` + `README.md` | 环境变量 `GAME_TURTLE_SOUP_*` 生效 |

### 阶段 F · 数据与脚本

| ID | 任务 | 验收 |
|---|---|---|
| F1 | `seeds/turtle_soup.json`（3-5 道内置题） | JSON 合法、字段完整 |
| F2 | `scripts/seed_turtle_soup.py` | 读取 JSON 写入数据库，幂等 |
| F3 | `scripts/generate_soup_with_llm.py` | 调用 LLM 批量生成题目，写入数据库 |
| F4 | Alembic 首次迁移 | `alembic upgrade head` 从零建出所有表 |

### 阶段 G · 部署

| ID | 任务 | 验收 |
|---|---|---|
| G1 | `Dockerfile`（bot 服务） | `docker build` 成功 |
| G2 | `docker-compose.yml`（prod：bot + postgres + redis） | `docker compose up` 可拉起 |
| G3 | `docker-compose.dev.yml`（napcat + redis 本地跑） | Windows/Linux 本地均能用 |
| G4 | `napcat/config.example.json` | 含 WebSocket 连接 NoneBot 的配置 |

### 阶段 H · 测试

| ID | 任务 | 验收 |
|---|---|---|
| H1 | `src/testing/harness.py`（GameTestHarness） | 可在无真实 QQ/LLM 的情况下驱动一局游戏 |
| H2 | Core 关键模块单测（economy/session/permission/llm/render/game_base） | `pytest` 全绿 |
| H3 | 海龟汤集成测试（LLM mock）：赢局/投降/超时/退出/恢复 | `pytest` 全绿 |

### 阶段 I · 收尾

| ID | 任务 | 验收 |
|---|---|---|
| I1 | 更新 `README.md` 的"启动"与"验收"章节 | 从克隆到跑通的完整步骤 |
| I2 | 最终自查本文件所有清单项 | 每项 ✅ 或显式标注"裁掉+原因" |

## 4. 明确不做的范围

避免未来回看时混淆：

- 第二个游戏
- 排行榜 / 段位 / 积分榜 UI
- Web 管理后台
- 真人出题模式
- Sentry / Prometheus 监控
- CI/CD Workflow（可留示例文件但不默认启用）
- HTML→图片渲染（改为全文本 UI）
- Pillow 绘图
- 美术资源（Logo / 插画 / 字体文件）

## 5. 版本与变更

| 版本 | 日期 | 变更 |
|---|---|---|
| v1 | 2026-04-28 | 初版基线 |
