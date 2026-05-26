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

```yaml
providers:
  zhipu:
    base_url: https://open.bigmodel.cn/api/paas/v4
    api_key: ${ZHIPU_API_KEY}
    timeout_seconds: 60
  longcat:
    base_url: https://api.longcat.chat/openai
    api_key: ${LONGCAT_API_KEY}
    timeout_seconds: 30
  # 未来可加：
  # openrouter:
  #   base_url: https://openrouter.ai/api/v1
  #   api_key: ${OPENROUTER_API_KEY}

# 默认重试策略
defaults:
  retries: 3
  backoff_base_seconds: 1.0
  backoff_max_seconds: 10.0

# 场景 → 模型 映射（详见 config/llm.yaml 顶部注释）
scenes:
  default:
    provider: zhipu
    model: glm-4-flash-250414
    temperature: 0.7
    max_tokens: 1024

  turtle_soup_host:
    provider: zhipu
    model: glm-4-flash-250414
    temperature: 0.9
    max_tokens: 2048
    json_mode_default: true

  turtle_soup_judge:
    provider: longcat
    model: LongCat-Flash-Chat
    temperature: 0.1
    max_tokens: 256
    json_mode_default: true
    timeout_seconds: 30

  turtle_soup_claim:
    provider: longcat
    model: LongCat-Flash-Chat
    temperature: 0.2
    max_tokens: 512
    json_mode_default: true
    timeout_seconds: 45
```

### 3.1 变量插值
配置文件中 `${VAR_NAME}` 会被替换为同名环境变量。

### 3.2 场景 fallback
未来可扩展：
```yaml
scenes:
  turtle_soup_judge:
    provider: zhipu
    model: glm-4-flash
    fallback:
      - provider: longcat
        model: LongCat-Flash-Lite
```
当主模型失败达重试上限后，自动切换到 fallback。v1 暂不启用。

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
