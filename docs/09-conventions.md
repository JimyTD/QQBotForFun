# 09 · 编码与文档规范

- **Status**: Draft v1
- **Last Updated**: 2026-04-28
- **Owner**: @owner

## 1. Python 风格

### 1.1 基础
- **Python 版本**：3.11，必要时使用 3.11 新语法（`Self`, `LiteralString`）
- **Lint/Format**：`ruff` 一把梭，配置在 `pyproject.toml`
- **类型注解**：**所有公共函数必须标注参数和返回类型**。使用 `from __future__ import annotations` 启用 PEP 604（`X | Y`）
- **最大行长度**：100

### 1.2 命名
| 对象 | 规则 | 例 |
|---|---|---|
| 模块 | `snake_case` | `game_base.py` |
| 类 | `PascalCase` | `GameContext` |
| 函数/变量 | `snake_case` | `register_game` |
| 常量 | `UPPER_SNAKE` | `MAX_QUESTIONS` |
| 私有 | `_leading_underscore` | `_internal_state` |
| 类型变量 | `PascalCase` + T 后缀 | `GameT` |

### 1.3 异步
- **所有 I/O 必须 async**（数据库、HTTP、Redis、文件）
- 不在同步函数里调用 `asyncio.run()`（除入口与脚本）
- 取消点：长循环加 `await asyncio.sleep(0)`

### 1.4 异常
- **Core 抛出业务异常**，全部继承 `core.errors.GameError`
- **绝不裸 `except:`**，必须指定异常类型
- 捕获后**必须**：要么处理、要么记日志、要么重抛（不吞异常）

### 1.5 依赖注入
- 不用复杂 IoC 容器
- Core 模块之间通过**显式 import** 互相引用
- 游戏通过 `GameContext` 获取运行时依赖，不自己 new 数据库连接

## 2. 日志规范

### 2.1 日志库
使用 NoneBot 自带的 `loguru`。不直接用 `logging` 标准库。

```python
from nonebot import logger

logger.info("...", extra={"session_id": sid})
logger.error("LLM failed: {e}", e=e)
```

### 2.2 日志级别

| 级别 | 用法 |
|---|---|
| `DEBUG` | 开发调试，生产关闭 |
| `INFO` | 关键业务事件：开局、结束、结算、LLM 调用 |
| `WARNING` | 边界情况、降级、重试 |
| `ERROR` | 捕获到的异常、外部服务失败 |
| `CRITICAL` | 需要人工介入，如 DB 连不上 |

### 2.3 结构化字段
关键日志**必须**附带：
- `session_id`（游戏对局 ID）
- `group_id`、`qq_id`（如适用）
- `scene`（LLM 调用时）
- `latency_ms`（外部调用）

### 2.4 敏感信息
- **不得**打印 API Key、用户密码、完整 LLM prompt（可以打印前 200 字 + 长度）
- 用户消息可打印（群聊本身就是公开的）

## 3. 文档规范

### 3.1 每篇文档开头必写

```markdown
# XX · 标题

- **Status**: Draft v1 | Accepted | Deprecated
- **Last Updated**: YYYY-MM-DD
- **Owner**: @xxx
```

### 3.2 何时更新
| 触发 | 需更新 |
|---|---|
| 新增 core API 或变更签名 | `03-core-api.md` |
| 新增游戏 | `docs/games/<id>.md` + `04-game-development.md` 的游戏清单 |
| 新增数据表或字段 | `07-database-schema.md` |
| 新增 LLM scene | `08-llm-integration.md` |
| 新增环境变量 | `06-configuration.md` + `.env.example` |
| 新增依赖 | `02-tech-stack.md` |
| 架构决策（跨模块影响） | 新增 `adr/XXXX-*.md` |
| 偏离路线图 | `10-roadmap.md` 变更日志 |

### 3.3 ADR 规则
- 编号顺序：`0001`, `0002`, ...
- 文件名：`adr/NNNN-kebab-case.md`
- 状态：`Proposed` → `Accepted` → `Deprecated`（不删除，标记）
- 格式固定：背景 / 决策 / 理由 / 替代方案 / 影响

### 3.4 代码注释
- 公共 API（Core 层）必须有 **docstring**（参数、返回、异常、示例）
- 复杂逻辑说明 **"为什么"**，不是"做什么"
- `TODO` / `FIXME` 必须带**负责人和日期**：`# TODO(@alice, 2026-05-01): ...`

## 4. Git 与提交

### 4.1 分支
- `main`：可运行的主干
- `feat/xxx`、`fix/xxx`、`docs/xxx`：功能分支
- 不强制 PR 流程（单人项目），但 commit 信息必须规范

### 4.2 Commit 规范（Conventional Commits 简版）

```
<type>: <subject>

[optional body]
```

type：
- `feat` 新功能
- `fix` 修 bug
- `docs` 只改文档
- `refactor` 重构
- `test` 测试
- `chore` 依赖/脚本/配置

示例：
```
feat(core.llm): add json_mode with schema validation
fix(turtle_soup): avoid double-judge on concurrent questions
docs(roadmap): mark phase C completed
```

### 4.3 `.gitignore` 必须包含
- `.env`、`.env.local`
- `__pycache__/`、`*.pyc`
- `.venv/`、`.uv-cache/`
- `*.db`、`*.sqlite*`
- `logs/`、`*.log`
- `.mypy_cache/`、`.pytest_cache/`、`.ruff_cache/`
- `.DS_Store`、`Thumbs.db`

## 5. 测试规范

### 5.1 覆盖目标
- Core 关键模块：**行覆盖 ≥ 70%**
- 游戏：至少 1 个完整流程测试 + 边界用例（超时/退出/异常）

### 5.2 测试原则
- **不依赖外部服务**：数据库用 SQLite in-memory，LLM 用 mock，OneBot 用 harness
- **不 sleep**：用 `asyncio.wait_for` 或时间注入
- **每个测试独立**：不跨测试共享状态（用 fixture 重建）

### 5.3 命名
- 文件：`test_<module>.py`
- 函数：`test_<scenario>_<expected>`，例如 `test_ask_timeout_raises`

## 6. 配置规范

### 6.1 分层
1. `.env`（本地私有，不入库）
2. 环境变量（生产）
3. 默认值（`settings.py` 内）

**不使用** YAML / JSON 配置文件（LLM scene 除外，见 §6.2）

### 6.2 LLM 配置特例
LLM scene 是结构化嵌套配置，用 YAML 或 TOML 更清晰。
放在 `config/llm.yaml`，路径由 `LLM_CONFIG_PATH` 环境变量指向。

### 6.3 游戏专属配置
- 前缀强制：`GAME_<GAME_ID>_<KEY>`
- 在游戏的 `config.py` 用 `pydantic-settings` 定义

## 7. 错误处理原则

### 7.1 业务错误 vs 系统错误
| 类型 | 例子 | 处理 |
|---|---|---|
| 业务错误 | 余额不足、非法输入 | 给用户友好提示，记 INFO/WARNING |
| 系统错误 | DB 断连、LLM 500 | 重试→降级→告警，记 ERROR |
| Bug | 未预期异常 | 捕获并记 ERROR，用户侧给"内部错误" |

### 7.2 向玩家展示的原则
- **永远不暴露**：堆栈、内部路径、SQL 错误
- **统一入口**：NoneBot 全局异常处理器统一兜底 + 友好模板

## 8. 变更日志
| 版本 | 日期 | 变更 |
|---|---|---|
| v1 | 2026-04-28 | 初版 |
