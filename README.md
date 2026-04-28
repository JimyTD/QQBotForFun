# QQBotForFun

> 一个以 **小游戏平台** 为目标的 QQ 群机器人项目。
> 基于 NapCat + NoneBot2，插件化架构，多个小游戏共享一套底层能力。

## ✨ 项目定位

- **面向群友的娱乐机器人**：在工作/学习间隙，群内随时开局、异步等待、不打断节奏
- **多游戏平台**：每个小游戏是独立插件，彼此隔离，公用一套 Core 能力层
- **LLM 原生**：大模型作为汤主、NPC、判定者等

## 🎯 首个游戏

**海龟汤**（纯 LLM 汤主模式）：LLM 自动出题 + 玩家自由提问 + LLM 判定。

## 🏛️ 架构一图流

```
┌───────────────────────────────────────────────────────────┐
│  Games Layer   各小游戏，彼此隔离                          │
│  turtle_soup  /  guess_number  /  gomoku  /  ...          │
├───────────────────────────────────────────────────────────┤
│  Core Layer    共享能力                                    │
│  session · user · economy · render · llm ·                │
│  scheduler · storage · permission · game_base             │
├───────────────────────────────────────────────────────────┤
│  Framework     NoneBot2 + adapter-onebot (v11)            │
├───────────────────────────────────────────────────────────┤
│  Protocol      NapCatQQ ←WebSocket→ NoneBot               │
└───────────────────────────────────────────────────────────┘
```

详情见 [`docs/01-architecture.md`](./docs/01-architecture.md)。

## 🧰 技术栈

| 层 | 选型 |
|---|---|
| 语言 | Python 3.11 |
| 包管理 | uv |
| 机器人框架 | NoneBot2 + adapter-onebot v11 |
| 协议端 | NapCatQQ (Docker) |
| ORM | SQLAlchemy 2.0 (async) |
| 数据库 | SQLite (dev) / PostgreSQL (prod) |
| 缓存 | 内存 (dev) / Redis (prod) |
| UI | 全文本 + emoji（`core.render`） |
| LLM | OpenAI 兼容，多场景多模型 |

详见 [`docs/02-tech-stack.md`](./docs/02-tech-stack.md)。

---

## 🚀 快速开始（本地 Windows）

### 1. 准备
- Python 3.11
- Docker Desktop
- 一个专用 QQ 小号
- 智谱 AI API Key、硅基流动 API Key（已获得）

### 2. 安装
```powershell
# 克隆代码
cd i:\QQBotForFun

# 安装 uv
pip install uv

# 同步依赖
uv sync
```

### 3. 配置
```powershell
copy .env.example .env
# 编辑 .env：填入 ADMIN_QQ / ZHIPU_API_KEY / SILICONFLOW_API_KEY / ONEBOT_ACCESS_TOKEN
notepad .env
```

### 4. 启动 NapCat
```powershell
docker compose -f docker-compose.dev.yml up -d
```
- 浏览器打开 http://localhost:6099，扫码登录 QQ 小号
- NapCat WebUI 已预配置反向 WS 连接 `ws://host.docker.internal:8080/onebot/v11/ws`（见 `napcat/config.example.json`）
- 确保 token 与 `.env` 的 `ONEBOT_ACCESS_TOKEN` 一致

### 5. 初始化数据库 + 种子题库
```powershell
mkdir data
uv run python scripts/seed_turtle_soup.py
# 海龟汤 5 道内置题会写入 SQLite（./data/bot.db）
# 开发模式下 storage.init_db() 会 create_all，无需跑 alembic
```

（生产或想用 PostgreSQL 时）
```bash
uv run alembic upgrade head
uv run python scripts/seed_turtle_soup.py
```

### 6. 启动 Bot
```powershell
uv run python -m src.bot
```

看到 `Connected to OneBot: self_id=...` 即成功。

### 7. 验证
在测试群里（已拉机器人小号进群）发送：
- `/ping` → 回复 `pong 🏓`
- `/menu` → 显示游戏大厅
- `/play turtle_soup` → 开始一局海龟汤
- 以 `?` 结尾提问，以 `汤底:` 开头宣告

---

## 🐳 生产部署（Linux + Docker）

```bash
git clone <repo> /opt/qqbot && cd /opt/qqbot
cp .env.example .env
nano .env   # APP_ENV=prod, DATABASE_URL=postgresql+asyncpg://..., REDIS_URL=..., 以及 API KEY

docker compose up -d
docker compose logs -f bot
```

详见 [`docs/05-deployment.md`](./docs/05-deployment.md)。

---

## 🧪 运行测试

```powershell
uv run pytest
```

应看到 core 模块与海龟汤流程全部通过。

---

## 📚 文档导航

### 开发者文档
- [`01-architecture.md`](./docs/01-architecture.md) — 分层架构
- [`02-tech-stack.md`](./docs/02-tech-stack.md) — 技术选型
- [`03-core-api.md`](./docs/03-core-api.md) — **Core 层接口契约**（游戏开发者必读）
- [`04-game-development.md`](./docs/04-game-development.md) — 如何新增一个游戏
- [`05-deployment.md`](./docs/05-deployment.md) — 云端部署
- [`06-configuration.md`](./docs/06-configuration.md) — 配置
- [`07-database-schema.md`](./docs/07-database-schema.md) — 数据库
- [`08-llm-integration.md`](./docs/08-llm-integration.md) — LLM 网关
- [`09-conventions.md`](./docs/09-conventions.md) — 编码规范
- [`10-roadmap.md`](./docs/10-roadmap.md) — **实施清单（不可偏移基线）**
- [`11-ui-style.md`](./docs/11-ui-style.md) — 文本 UI 规范
- [`12-local-testing.md`](./docs/12-local-testing.md) — **本地端到端测试指南**

### 游戏设计
- [`games/turtle-soup.md`](./docs/games/turtle-soup.md)

### ADR
- [`adr/0001-protocol-choice.md`](./docs/adr/0001-protocol-choice.md) — NapCat
- [`adr/0002-framework-choice.md`](./docs/adr/0002-framework-choice.md) — NoneBot2
- [`adr/0003-llm-gateway.md`](./docs/adr/0003-llm-gateway.md) — LLM 网关

---

## ✅ 交付验收清单

照着本清单逐项自查。对应 `docs/10-roadmap.md` 的基线。

- [x] 文档：13 篇（总览 + 11 篇专题 + 海龟汤设计）
- [x] ADR：3 篇（协议 / 框架 / LLM）
- [x] 脚手架：`pyproject.toml`、`.env.example`、`.gitignore`、`config/llm.yaml`、`settings.py`
- [x] Core 层：`errors` / `types` / `storage` / `user` / `session` / `economy` / `permission` / `scheduler` / `llm` / `render` / `game_base`
- [x] 系统插件：`core_commands` / `game_launcher` / `admin` / `message_router`
- [x] 海龟汤游戏：`models` / `config` / `prompts` / `puzzle_service` / `game` / `commands`
- [x] 数据：`seeds/turtle_soup.json`（5 道）+ `scripts/seed_turtle_soup.py` + `scripts/generate_soup_with_llm.py`
- [x] Alembic：`alembic.ini` + `migrations/env.py` + `migrations/versions/0001_init.py`
- [x] 部署：`Dockerfile` + `docker-compose.yml` + `docker-compose.dev.yml` + `napcat/config.example.json`
- [x] 测试：`conftest.py` + `test_economy` + `test_render` + `test_permission` + `test_llm` + `test_game_base` + `test_classify` + `test_flow` + `harness.py`

---

## 🗺️ 未来

见 [`docs/10-roadmap.md` §4](./docs/10-roadmap.md)（明确不做的范围）与各游戏设计文档末尾的"未来扩展"。

## 📝 状态

- **Status**: MVP framework complete
- **Last Updated**: 2026-04-28
