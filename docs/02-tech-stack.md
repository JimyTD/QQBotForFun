# 02 · 技术栈与版本锁定

- **Status**: Draft v1
- **Last Updated**: 2026-04-28
- **Owner**: @owner

## 1. 选型原则

1. **较新但稳健**：选择当前稳定大版本，避免 beta / preview。
2. **生态活跃**：2026 年仍在持续维护、社区问答充足。
3. **可替换**：每个关键组件都有备选方案，避免锁死。
4. **最小依赖**：能用标准库就不引第三方。

## 2. 运行时与语言

| 项 | 选型 | 版本 | 理由 |
|---|---|---|---|
| 语言 | Python | **3.11.x** | NoneBot2 推荐；3.12/3.13 部分 C 扩展仍有兼容问题；3.11 性能提升明显 |
| 包管理 | **uv** | 最新 | Astral 出品，比 pip/poetry 快 10-100 倍；已成为 Python 社区新事实标准 |
| 虚拟环境 | uv venv | — | 与 uv 配套 |

## 3. 核心框架

| 项 | 选型 | 版本 | 备选 |
|---|---|---|---|
| 机器人框架 | **NoneBot2** | 2.4.x | Koishi (TS), LangBot (不适合复杂游戏) |
| 协议适配器 | `nonebot-adapter-onebot` | 2.x | `nonebot-adapter-qq`（官方 API，未来可切换） |
| 协议端 | **NapCatQQ** | 最新稳定版 | Lagrange.OneBot |

选型决策详见：
- [`adr/0001-protocol-choice.md`](./adr/0001-protocol-choice.md)
- [`adr/0002-framework-choice.md`](./adr/0002-framework-choice.md)

## 4. 数据层

| 项 | 开发环境 | 生产环境 | 库 |
|---|---|---|---|
| ORM | SQLAlchemy 2.0 async | 同左 | `sqlalchemy[asyncio]>=2.0` |
| 数据库 | SQLite | PostgreSQL 16 | `aiosqlite` / `asyncpg` |
| 迁移 | Alembic | 同左 | `alembic` |
| 缓存/锁 | 内存字典 | Redis 7 | `redis[asyncio]` |
| NoneBot 集成 | — | — | `nonebot-plugin-orm` |

**为什么 SQLAlchemy 2.0 而非 Tortoise**：
- SQLAlchemy 2.0 的 async API 已成熟，社区更活跃
- Alembic 迁移工具业界标杆
- Tortoise-ORM 维护放缓，2025 年更新频率下降

## 5. LLM 层

| 项 | 选型 | 说明 |
|---|---|---|
| 调用协议 | **OpenAI 兼容** | DeepSeek、通义、Kimi、硅基流动、OpenRouter 均兼容 |
| SDK | `openai` 官方 Python SDK | 通过 `base_url` 切换供应商 |
| 抽象层 | 自研 `core.llm` | 见 [`adr/0003-llm-gateway.md`](./adr/0003-llm-gateway.md) |
| 场景化配置 | 每个"场景"独立配模型 | 如 `soup_host`, `soup_judge`, `summary` |

**不使用 LangChain / LlamaIndex 的原因**：
- 本项目调用模式简单（单轮/多轮对话），不需要复杂编排
- LangChain 抽象过重，依赖复杂，升级不稳定
- 自写 ~200 行网关足够，且完全可控

## 6. 渲染层

| 项 | 选型 | 用途 |
|---|---|---|
| HTML → PNG | `nonebot-plugin-htmlrender` (Playwright) | 复杂排行榜、战报、卡牌 |
| 图像处理 | `Pillow` | 棋盘格、简单拼图 |
| 模板引擎 | Jinja2（随 htmlrender） | HTML 模板 |

## 7. 调度与异步

| 项 | 选型 |
|---|---|
| 定时任务 | `nonebot-plugin-apscheduler` |
| 异步运行时 | asyncio（Python 内置） |
| HTTP 客户端 | `httpx`（NoneBot 自带） |

## 8. 可观测性与工具

| 项 | 选型 |
|---|---|
| 日志 | `loguru`（NoneBot 自带） |
| 配置管理 | `pydantic-settings` |
| 错误追踪（可选） | Sentry（`sentry-sdk`），生产环境启用 |
| 类型检查 | `mypy` + `pyright`（IDE） |
| Lint/Format | `ruff`（合二为一，替代 black+isort+flake8） |
| 测试 | `pytest` + `pytest-asyncio` |

## 9. 部署

| 项 | 选型 |
|---|---|
| 容器化 | Docker + Docker Compose |
| 反代（可选） | Caddy（自动 HTTPS）或 Nginx |
| CI（可选） | GitHub Actions |

详细见 `05-deployment.md`（第二批文档）。

## 10. 版本锁定策略

- `pyproject.toml` 使用 **下限约束**（`>=`），便于安全更新
- `uv.lock` 提交到 git，**保证团队/生产环境完全一致**
- 每个季度 review 一次依赖升级

## 11. 明确不使用的技术（避免后悔）

| 排除项 | 原因 |
|---|---|
| go-cqhttp | 已停止维护，协议失效 |
| Mirai | Java 依赖重，社区收缩 |
| Tortoise ORM | 维护放缓 |
| LangChain | 过度抽象、依赖混乱 |
| Docker Swarm | 过时，需要集群用 k8s |
| MongoDB | 游戏数据强关系，关系型更合适 |

## 12. 依赖清单（规划）

```toml
# pyproject.toml 草案
[project]
name = "qqbotforfun"
version = "0.1.0"
requires-python = ">=3.11,<3.12"

dependencies = [
    "nonebot2[fastapi]>=2.4.0",
    "nonebot-adapter-onebot>=2.4.0",
    "nonebot-plugin-apscheduler>=0.5.0",
    "nonebot-plugin-orm[default]>=0.7.0",
    "nonebot-plugin-htmlrender>=0.6.0",
    "sqlalchemy[asyncio]>=2.0",
    "alembic>=1.13",
    "aiosqlite>=0.20",
    "asyncpg>=0.29",
    "redis[hiredis]>=5.0",
    "openai>=1.40",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "loguru>=0.7",
    "httpx>=0.27",
    "pillow>=10.3",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.4",
    "mypy>=1.10",
]
```

> 注：具体版本号以实施时最新稳定版为准，此表主要是**锁定量级**。
