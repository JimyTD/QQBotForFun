# 06 · 配置说明

- **Status**: Draft v1
- **Last Updated**: 2026-04-28
- **Owner**: @owner

## 1. 配置来源优先级

高 → 低：
1. 进程环境变量
2. `.env` 文件
3. `settings.py` 里的默认值

## 2. `.env` 完整清单

> 所有 `*_required_*` 字段**启动时缺失会报错**。

### 2.1 应用基础
```ini
# 运行环境: dev / staging / prod
APP_ENV=dev

# 日志级别: DEBUG / INFO / WARNING / ERROR
LOG_LEVEL=INFO

# 机器人监听地址（NoneBot fastapi）
HOST=0.0.0.0
PORT=8080

# 管理员 QQ 列表（逗号分隔）
ADMIN_QQ=10001,10002
```

### 2.2 OneBot（NapCat 连接）
```ini
# NapCat 暴露的 OneBot WS 地址
ONEBOT_WS_URL=ws://localhost:3001
ONEBOT_ACCESS_TOKEN=your_token_here    # 和 NapCat 设置的一致
```

### 2.3 数据库
```ini
# 开发：SQLite
DATABASE_URL=sqlite+aiosqlite:///./data/bot.db

# 生产：PostgreSQL
# DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/qqbot
```

### 2.4 缓存 / 锁
```ini
# 开发可留空（走内存）
REDIS_URL=

# 生产
# REDIS_URL=redis://redis:6379/0
```

### 2.5 LLM 配置
```ini
# LLM 场景配置文件路径（YAML）
LLM_CONFIG_PATH=./config/llm.yaml

# 各供应商的 API Key
ZHIPU_API_KEY=your_key
LONGCAT_API_KEY=your_key

# 腾讯云 TokenHub（广州站）：多模型阶梯链。只消费免费额度，不充钱。
# 控制台需按模型逐个「开通服务」，未开通会返回 402（会被判为额度耗尽而降档）。
# ⚠️ 广州站与新加坡站 Key 不互通；本项对应 https://tokenhub.tencentmaas.com/v1
TOKENHUB_API_KEY=your_key

# 可选
OPENAI_API_KEY=
OPENROUTER_API_KEY=
```

### 2.6 海龟汤配置
```ini
# 最大提问数
GAME_TURTLE_SOUP_MAX_QUESTIONS=50

# 整局超时（分钟）
GAME_TURTLE_SOUP_SESSION_TIMEOUT_MINUTES=60

# 闲置超时（分钟）
GAME_TURTLE_SOUP_IDLE_TIMEOUT_MINUTES=15

# 是否优先使用 LLM 生成新题（false = 优先题库）
GAME_TURTLE_SOUP_PREFER_LLM_GENERATION=false

# 判定 LLM 调用超时（秒）
GAME_TURTLE_SOUP_JUDGE_TIMEOUT_SECONDS=30

# 宣告 LLM 调用超时（秒）
GAME_TURTLE_SOUP_CLAIM_TIMEOUT_SECONDS=45

# 胜利奖励金币
GAME_TURTLE_SOUP_REWARD_ON_WIN=100
```

## 3. LLM 场景配置 `config/llm.yaml`

每个 scene 配的不是单个模型，而是一条**阶梯链**（有序候选）：
链头是首选档，某档额度耗尽/限流/故障时自动降下一档。
机制细节见 [`08-llm-integration.md`](./08-llm-integration.md) §4.2。

```yaml
providers:
  zhipu:
    base_url: https://open.bigmodel.cn/api/paas/v4
    api_key: ${ZHIPU_API_KEY}
    timeout_seconds: 60

  tokenhub:                                  # 腾讯云 TokenHub（广州站）
    base_url: https://tokenhub.tencentmaas.com/v1
    api_key: ${TOKENHUB_API_KEY}
    timeout_seconds: 60

# 默认重试策略（用于单档内的就地重试）
defaults:
  retries: 3
  backoff_base_seconds: 1.0
  backoff_max_seconds: 10.0

scenes:
  default:
    chain:                                   # 有序候选，按序降级
      - tokenhub:glm-5.1                     # 显式指定 provider
      - qwen3.5-flash                        # 不带前缀 → 继承 scene 的 provider
      - zhipu:glm-4-flash-250414             # 跨家兜底
    temperature: 0.7
    max_tokens: 1024

  turtle_soup_judge:
    chain:
      - tokenhub:qwen3.5-plus
      - tokenhub:deepseek-v4-flash-202605
      - zhipu:glm-4-flash-250414
    temperature: 0.1
    max_tokens: 256
    json_mode_default: true
    timeout_seconds: 30
```

### 3.1 变量插值
配置文件中 `${VAR_NAME}` 会被替换为同名环境变量
（优先从 `Settings` 取，其次 `os.environ`）。

### 3.2 链元素写法

| 写法 | 含义 |
|---|---|
| `chain: [a, b]` + `provider: p` | `a`、`b` 都用 provider `p` |
| `chain: [p1:a, p2:b]` | 逐档显式指定 provider（可跨家兜底） |
| `provider: p` + `model: m` | **旧写法仍然有效**，等价于 `chain: [p:m]`（单档链） |

`provider:model` 按**第一个**冒号切分，所以模型名里的斜杠是安全的
（如 `tokenhub:deepseek/deepseek-flash`）。

链上任一 provider 未在 `providers` 声明 → 启动报 `LLMConfigError`；
链上 provider 缺 api_key → 只 WARNING（该档会被跳过并降级），不阻断启动。

### 3.3 启动时自动裁剪死档

`llm.init()` 会拉一次 TokenHub `GET /v1/models`，把**已停服**的档从链上剔除
—— 模型下线后**不必改配置**。该接口的 `status` 有三种取值：

| status | 含义 | 处理 |
|---|---|---|
| `online` | 正常在服 | 可用 |
| **`pre-offline`** | **已公告下线，但仍可调用** | ✅ **保留** —— 这正是最该优先烧的那批 |
| `discontinued` | 已停服 | 剔除 |

采用**黑名单**策略（只剔 `discontinued`）：字段没见过时宁可当成可用，
也不要把能调的档误剔掉。注意：

- 该接口返回的是**平台全量清单**（实测 121 个），**不代表当前 Key 已开通哪些**；
  能否调用仍以实际请求为准（未开通 / 额度耗尽都是 402）；
- 该接口**不反映额度是否耗尽**（额度只能靠 402 实际探测）；
- 接口失败**只告警、不阻断启动**（退化为「不裁剪，按配置原样跑」）。

## 4. NoneBot 内部配置

NoneBot 自身读取以 `DRIVER__`、`LOG_LEVEL` 等开头的环境变量。
本项目的 `.env.example` 会显式列出常用项：

```ini
DRIVER=~fastapi+~websockets
COMMAND_START=["/", ""]         # 允许有斜杠或无斜杠
COMMAND_SEP=[" "]
```

## 5. 运行时覆盖

生产环境推荐通过 docker compose 的 `environment:` 字段传入，而非把生产 `.env` 放到镜像里。

## 6. 配置校验

- `settings.py` 使用 `pydantic-settings.BaseSettings`，**启动时**对必填、类型做严格校验
- LLM YAML 由 `core.llm` 载入时校验（provider 存在、场景 provider 引用合法）
- 校验失败**阻止启动**并给出明确错误

## 7. 变更日志
| 版本 | 日期 | 变更 |
|---|---|---|
| v1 | 2026-04-28 | 初版 |
| v2 | 2026-09-17 | 新增 `TOKENHUB_API_KEY`；§3 改为**阶梯链**语法（`chain:` + `provider:model`），补充 §3.2 链元素写法与 §3.3 启动时自动裁剪死档 |
