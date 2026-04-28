# 08 · LLM 网关详解

- **Status**: Draft v1
- **Last Updated**: 2026-04-28
- **Owner**: @owner

> 配合 [`adr/0003-llm-gateway.md`](./adr/0003-llm-gateway.md) 和 [`06-configuration.md`](./06-configuration.md) 一起看。

## 1. 调用入口

```python
from core import llm

# 普通调用
resp = await llm.chat(
    messages=[
        llm.LLMMessage(role="system", content="你是..."),
        llm.LLMMessage(role="user", content="问题..."),
    ],
    scene="turtle_soup_judge",
)
text = resp.content

# JSON 模式
resp = await llm.chat(messages=..., scene="...", json_mode=True)
data = resp.json()   # 已自动解析为 dict，失败抛 LLMJSONParseError

# 流式
async for chunk in llm.chat_stream(messages=..., scene="..."):
    print(chunk, end="")

# Embedding（未来用，v1 占位）
vec = await llm.embedding("文本", scene="default")
```

## 2. 场景（Scene）清单

所有使用场景**必须**在此登记。

| Scene | 用途 | 推荐模型 | JSON | 特点 |
|---|---|---|---|---|
| `default` | 通用兜底 | `glm-4-flash` | ✗ | 免费、快 |
| `turtle_soup_host` | 海龟汤出题 | `Qwen2.5-72B-Instruct` | ✓ | 强创意 |
| `turtle_soup_judge` | 海龟汤提问判定 | `glm-4-flash` | ✓ | 高频低延迟 |
| `turtle_soup_claim` | 海龟汤宣告判定 | `glm-4-flash` | ✓ | 中等强度 |

**新增场景流程**：
1. 在 `config/llm.yaml` 的 `scenes:` 下新增
2. 在本表登记
3. 代码中使用 `scene="xxx"` 调用

## 3. Prompt 管理

### 3.1 存放位置
- **每个游戏的 prompts 集中在 `src/plugins/games/<id>/prompts.py`**
- 通用 prompts（如系统人设）可放 `src/core/llm_prompts.py`（v1 暂无）

### 3.2 版本管理
每个 prompt 顶部标注版本：

```python
# prompts.py
TURTLE_SOUP_JUDGE_PROMPT_VERSION = "1.0"

TURTLE_SOUP_JUDGE_SYSTEM = """
[v1.0 · 2026-04-28]
你是海龟汤汤主...
"""
```

修改 prompt 时：
1. `_VERSION` 递增
2. 在下方 git commit message 写明改动
3. 重要变更在 `docs/games/<id>.md` 变更日志记录

### 3.3 模板变量
使用 Python f-string 或 `str.format`，**不引入** Jinja2 等模板引擎（简单场景不需要）：

```python
prompt = TURTLE_SOUP_JUDGE_SYSTEM.format(
    surface=puzzle.surface,
    truth=puzzle.truth,
    key_clues="\n".join(f"- {c}" for c in puzzle.key_clues),
)
```

## 4. 网关实现要点

### 4.1 请求路由
```
llm.chat(scene="turtle_soup_judge")
  ↓
 查 scenes[turtle_soup_judge]
  ↓
 得到 provider=zhipu, model=glm-4-flash, ...
  ↓
 查 providers[zhipu]
  ↓
 得到 base_url + api_key
  ↓
 构造 OpenAI 兼容请求
```

### 4.2 重试
- 对 5xx / 429 / 网络错误：指数退避重试（默认 3 次）
- 对 4xx（除 429）：**不重试**
- 退避公式：`sleep = min(backoff_base * 2^attempt, backoff_max)`

### 4.3 超时
- 读超时默认 60s，可在 scene 覆盖
- 流式模式首 token 30s 超时

### 4.4 JSON 模式
网关做的事：
1. 请求时：如果 scene 或 call 指定 `json_mode=True`，优先用供应商原生 JSON 模式（OpenAI `response_format={"type": "json_object"}`）；不支持则在 system prompt 追加"必须输出 JSON"
2. 返回时：
   - 去除 markdown 代码块包裹（` ```json ... ``` `）
   - `json.loads()` 校验
   - 失败则**重试一次**（同一 prompt）
   - 仍失败抛 `LLMJSONParseError`

### 4.5 流式
- 底层调用 `openai` SDK 的 stream=True
- 异步生成器 yield 文本增量
- 异常在首次 yield 前抛出；已开始流式后的异常包装为 `LLMError` 在生成器末尾抛

### 4.6 日志
每次调用 INFO 日志包含：
```
scene=turtle_soup_judge provider=zhipu model=glm-4-flash
prompt_tokens=345 completion_tokens=28 total_tokens=373
latency_ms=620 status=ok
```

失败：
```
scene=... status=error error_type=LLMJSONParseError retries_exhausted=true ...
```

## 5. 成本预估（海龟汤参考值）

基于 glm-4-flash **免费**、硅基流动免费额度：

| 操作 | 预估 tokens | 次数 | 说明 |
|---|---|---|---|
| 出题 | 2000 in + 800 out | 1/局 | 仅当 LLM 生成时，题库抽取为 0 |
| 提问判定 | 500 in + 50 out | 20-50/局 | 高频 |
| 宣告判定 | 400 in + 80 out | 1-3/局 | 低频 |

**单局总成本**（LLM 生成模式，最坏情况）：约 30k tokens。
**GLM-4-Flash 永久免费**，硅基流动 2000 万 token ≈ 600+ 局出题，远超早期测试需求。

## 6. 错误分类

| 异常 | 触发 | 处理建议 |
|---|---|---|
| `LLMError` | 网络/服务器错误重试失败 | 降级或向用户道歉 |
| `LLMJSONParseError` | JSON 模式解析失败 | 对判定类任务：记 WARNING，用"与此无关"兜底；对出题：切换备用 scene 或用题库 |
| `LLMTimeoutError` | 读超时 | 同 LLMError |
| `LLMRateLimitError` | 429 重试耗尽 | 告警管理员 |
| `LLMConfigError` | 启动时 scene/provider 错 | 阻止启动 |

## 7. 调用频率控制

- 网关内部无全局限流（交给供应商）
- 业务层限流靠 `core.permission.rate_limit`（如海龟汤限玩家每分钟 20 个问题）

## 8. 未来能力（留钩子，v1 不做）

- [ ] Function Calling / Tools
- [ ] 多模态（视觉）
- [ ] 回答缓存（基于 prompt hash）
- [ ] 多模型 A/B
- [ ] 成本计费统计

## 9. 变更日志
| 版本 | 日期 | 变更 |
|---|---|---|
| v1 | 2026-04-28 | 初版 |
