# ADR 0003 · LLM 网关抽象设计

- **Status**: Accepted
- **Date**: 2026-04-28
- **Decider**: @owner

## 背景

项目多个游戏会深度使用 LLM，且不同使用场景对模型的要求差异大：

| 场景示例 | 需求 | 倾向模型 |
|---|---|---|
| 海龟汤出题 | 创意、长故事一致性 | 强模型（Claude/GPT-4 级） |
| 海龟汤判定 | 低延迟、高频次、简单推理 | 便宜快模型（DeepSeek-chat 级） |
| NPC 闲聊 | 角色感、低成本 | 中等模型 |
| 文本摘要 | 低成本、确定性 | 便宜模型 |

另外：
- 2026 年 LLM 供应商变化快，需要**易于切换**
- 绝大多数供应商（DeepSeek、通义、Kimi、Moonshot、龙猫、OpenRouter、Claude via 代理等）都兼容 **OpenAI Chat Completions 协议**
- 自托管（ollama、vllm）也支持 OpenAI 兼容接口

## 决策

1. **统一协议**：Core 内部只处理 OpenAI 兼容协议，通过 `base_url + api_key` 接入任何供应商
2. **场景化路由**：业务代码**不指定具体模型**，只指定**场景名**，由配置决定用什么模型
3. **自研轻量网关**：约 200-300 行代码实现，不引入 LangChain / LlamaIndex
4. **配置热更新**（可选，v2）：修改场景→模型映射无需重启

## 核心抽象

### 场景 (Scene)

**场景 = 一个业务用途的 LLM 配置**。游戏代码只知道场景名。

```python
# 游戏代码
await llm.chat(messages, scene="turtle_soup_judge")
```

### 配置

```yaml
llm:
  providers:
    deepseek:
      base_url: https://api.deepseek.com/v1
      api_key: ${DEEPSEEK_API_KEY}
    openrouter:
      base_url: https://openrouter.ai/api/v1
      api_key: ${OPENROUTER_API_KEY}
    local_ollama:
      base_url: http://localhost:11434/v1
      api_key: ollama

  scenes:
    default:
      provider: deepseek
      model: deepseek-chat
      temperature: 0.7
      max_tokens: 1024

    turtle_soup_host:
      provider: openrouter
      model: anthropic/claude-sonnet-4.5
      temperature: 0.9
      max_tokens: 2048
      json_mode_default: true

    turtle_soup_judge:
      provider: deepseek
      model: deepseek-chat
      temperature: 0.1
      max_tokens: 256
      json_mode_default: true
      timeout_seconds: 30
```

### 网关职责

```
game.py
   │ llm.chat(messages, scene="xxx")
   ▼
┌────────────────── core.llm ──────────────────┐
│  1. 查询 scene 配置 → 获得 provider + model   │
│  2. 应用默认参数（temperature 等）            │
│  3. 构造 OpenAI 兼容请求                     │
│  4. 超时、重试（带退避）                      │
│  5. JSON 模式校验（json_mode=True 时）        │
│  6. 记录调用日志（session_id / tokens / 耗时）│
│  7. 降级处理（fallback scene，可选）          │
└──────────────────────┬───────────────────────┘
                       ▼
            openai SDK (with base_url)
                       ▼
              供应商 API / 本地模型
```

### 关键能力

1. **重试**：网络错误/429 指数退避，最多 3 次；4xx 不重试
2. **JSON 模式**：传 `json_mode=True` 时，在系统 prompt 附加 JSON 约束，返回前 `json.loads()` 校验，失败抛 `LLMJSONParseError`
3. **流式**：`chat_stream()` 返回 `AsyncIterator[str]`，用于实时输出场景
4. **日志**：每次调用记录 session_id、scene、model、prompt_tokens、completion_tokens、latency_ms
5. **成本统计**（可选，v2）：按 token 单价累计

## 为什么不用 LangChain

| 问题 | 影响 |
|---|---|
| 抽象过重 | Chain/Agent/Runnable 等概念对简单场景是负担 |
| 依赖复杂 | 安装几十个子包，升级经常破坏兼容 |
| 文档/API 变动频繁 | 每个大版本都有 breaking change |
| 调试困难 | 调用栈深，出问题不好定位 |
| 本项目需求简单 | 主要就是单轮/多轮 chat + embedding，200 行足矣 |

## 未来扩展预留

| 能力 | 策略 |
|---|---|
| Function Calling / Tools | 场景配置里声明 tools 列表，网关透传 |
| 多模态（图片输入） | OpenAI 兼容的 vision 消息格式已有，网关透传即可 |
| 本地模型（ollama / vllm） | 已支持（OpenAI 兼容） |
| 缓存（相同 prompt 命中缓存） | 按 hash(prompt) + 场景做 Redis 缓存 |
| 多模型 A/B 测试 | 场景支持 weighted providers 列表 |
| Agent 框架 | 若真需要，再独立加一层 `core.agent`，不污染 `core.llm` |

## 影响

- 所有 LLM 调用**必须**走 `core.llm`，禁止游戏直接 `from openai import ...`
- 新增 LLM 使用场景时：
  1. 在配置里声明 scene
  2. 代码用 `scene="<name>"` 调用
  3. 在 `docs/08-llm-integration.md`（第二批）的 scene 清单中登记

## 验证标准

- [ ] 能在 0 代码改动下切换任意 OpenAI 兼容供应商（仅改 yaml）
- [ ] 判定类调用 p95 < 5s，失败率 < 1%
- [ ] 完整调用日志可追溯
