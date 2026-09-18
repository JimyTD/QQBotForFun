# 08 · LLM 网关详解

- **Status**: v2
- **Last Updated**: 2026-05-26
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

所有使用场景**必须**在此登记。每个 scene 配的不是单个模型，而是一条**阶梯链**
（机制见 §4.2；完整链见 [`config/llm.yaml`](../config/llm.yaml)）。

下表只列**链头**（首选档）与链长 —— 全链刻意不在文档里重复，避免与配置漂移。

| Scene | 用途 | 链头（首选档） | 链长 | JSON | 备注 |
|---|---|---|---|---|---|
| `turtle_soup_judge` | 海龟汤提问判定（高频 20–50 次/局） | `tokenhub:qwen3.5-plus` | 12 | ✓ | temp=0.1，**timeout=30s**，低延迟档靠前 |
| `turtle_soup_claim` | 海龟汤宣告判定（1–3 次/局） | `tokenhub:qwen3.5-plus` | 12 | ✓ | temp=0.2，判定质量优先 |
| `turtle_soup_host` | 海龟汤出题（1 次/局） | `tokenhub:qwen3.5-plus` | 12 | ✓ | temp=0.9，创意档靠前 |
| `trivia_host` | 趣味问答补题 | `tokenhub:qwen3.5-plus` | 12 | ✓ | temp=0.9，创意型 |
| `web_search` | 查资料 · 搜索总结 | `tokenhub:qwen3.5-plus` | 12 | ✗ | temp=0.3，长文吃上下文 |
| `ask_ai` | 查资料 · 纯 LLM 兜底 | `tokenhub:qwen3.5-plus` | 12 | ✗ | temp=0.7 |
| `finance_report` | 经济天气播报 | `tokenhub:qwen3.5-plus` | 12 | ✗ | temp=0.7 |
| `silent_mark_ai` | 静夜标记 AI 玩家决策（高频） | `tokenhub:qwen3.5-plus` | 14 | ✓ | temp=0.3，**timeout=30s**，含角色扮演档 |
| `silent_mark_ai_name` | 静夜标记 AI 取名 | `tokenhub:qwen3.5-flash` | 10 | ✗ | temp=0.9，输出仅 20 token |
| `default` | 通用兜底 | `tokenhub:qwen3.5-plus` | 12 | ✗ | temp=0.7 |

所有链的尾档统一是 `zhipu:glm-4-flash-250414` —— 智谱与 TokenHub 的额度是**两个独立的池**，
串起来总可用量更大，且保证「链路全挂时也不比改造前差」。

**为什么链头是 `qwen3.5-*`**：TokenHub 免费额度**按模型各自独立、不刷新、用完/下线即失效**，
所以**快过期的档必须先用**（标称 2026-09-08 下线，随时可能失效）。
完整取舍见 [`plans/2026-09-17-llm-tokenhub-model-ladder.md`](./plans/2026-09-17-llm-tokenhub-model-ladder.md)。

> ✅ **参数层面已实测**（2026-09-18，`scripts/probe_tokenhub_models.py`，A 类 13 档）：
> 全部可调用、全部支持 `response_format`、响应均在 5s 内。**只有 `kimi-k2.5` 需要 quirk**
> （只接受 `temperature=1.0`，已写进 `_MODEL_QUIRKS`）。详见规划 §2.3。
>
> ⚠️ **质量层面未验证，且已决定不再验证**（2026-09-18）：
> 链序是「剩余寿命升序 + 组内质量降序」的人工初判，没有 golden eval 数据支撑 ——
> 因为**验证成本 ≈ 被验证的资源本身**（详见规划 §5.5.0.2）。
> 若日后觉得判定变怪，翻日志的 `slot=` / `chain_index=` 定位到具体档，
> 再**只对那一档**跑几条 golden 定点验证（几千 token，而非全量十几万）。
>
> ⚠️ `kimi-k2.5` 强制 `temperature=1.0`，与判定场景需要低温度求一致性相冲突；
> 它排在判定链靠后位置，影响有限，但降级到它时判定会变随机。

厂商活动调研见 [`free-llm-vendors.md`](./free-llm-vendors.md)。

**新增场景流程**：
1. 在 `config/llm.yaml` 的 `scenes:` 下新增（写 `chain:`，或旧的 `provider`+`model`）
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
 查 scenes[turtle_soup_judge] → 得到 chain + 参数
  ↓
 取链上第一个「可用档」（跳过冷却中 / 已下线的）
  ↓
 得到 (provider, model)
  ↓
 查 providers[provider] → base_url + api_key
  ↓
 构造 OpenAI 兼容请求（含该 model 的 quirks 修正）
  ↓
 失败 → 打冷却 → 回到「取下一个可用档」
```

### 4.2 阶梯链与降级

```python
for 档 in chain:
    if 冷却中 / 已下线: 跳过          # 不浪费一次调用
    try: 调用
    except:
        限流(429) / 抖动(5xx、超时) → 档内退避重试（默认 3 次）
        额度耗尽(402) / 鉴权(401,403) / 参数错(400) / 下线(404) → 打冷却，降下一档
全链失败 → 抛 LLMError
```

**冷却时长**（额度按模型独立且**不刷新**，所以额度耗尽的冷却必须递增）：

| 错误类型 | 冷却 | 说明 |
|---|---|---|
| `quota_exhausted`（402） | **6h → 12h → 24h（封顶）** | 指数递增。封顶而非永久封禁，是为了留一条自愈路径 |
| `rate_limited`（429） | 35s | 可就地重试 |
| `transient`（5xx / 超时 / `401006`） | 20s | 可就地重试 |
| `auth`（401 / 403） | 30min | |
| `fatal`（400 参数错） | 10min | 通常是 quirks 没配对，**不是模型坏** |
| `unavailable`（404） | 24h | 模型已下线 |

**TokenHub 特判**：业务码 `401006`（endpoint is inactive）其实是**瞬态**，
但码里带 "401"，走通用字符串匹配会被误判成鉴权失败、白白降档 → 单独归类为可重试。

**可观测**（原则：**诊断默认零额度消耗**，探活就是烧额度）：

- 返回值的 `model` / `provider` 是**实际生效**的那一档（不是配置里的链头）；
- `chain_index > 0`（或 `degraded == True`）表示这次发生过降档；
- 每次调用都打 `[llm] scene=... slot=<provider:model> chain_index=N ...`；
- `llm.health_snapshot()` 只读内存给出每档的冷却/下线状态；
- `uv run python scripts/llm_status.py`：CLI 诊断，输出各 scene 链路与每档状态，**零额度消耗**；
- `@我 AI 测试`（`silent_mark/commands.py`）：真打一次并报出实际生效的档 ——
  **唯一会消耗额度的诊断入口**，用于确认「链到底通不通」。

**单档内的重试**：对 5xx / 429 / 网络错误指数退避（默认 3 次）；
对 4xx（除 429）不重试，直接降档。退避公式 `sleep = min(backoff_base * 2^attempt, backoff_max)`。

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
scene=turtle_soup_judge provider=zhipu model=glm-4-flash-250414
prompt_tokens=345 completion_tokens=28 total_tokens=373
latency_ms=620 status=ok
```

失败：
```
scene=... status=error error_type=LLMJSONParseError retries_exhausted=true ...
```

## 5. 成本预估（海龟汤参考值）

基于智谱 `glm-4-flash-250414` **免费档**：

| 操作 | 预估 tokens | 次数 | 说明 |
|---|---|---|---|
| 出题 | 2000 in + 800 out | 1/局 | 仅当 LLM 生成时，题库抽取为 0 |
| 提问判定 | 500 in + 50 out | 20-50/局 | 高频 |
| 宣告判定 | 400 in + 80 out | 1-3/局 | 低频 |

**单局总成本**（题库模式，典型）：约 15–25k tokens，均在智谱 Flash 免费额度内。

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

## 8. 未来能力

已落地：

- [x] **多模型阶梯链 + 自动降档**（§4.2，2026-09-17）
- [x] **跨 provider 兜底链**（`tokenhub:*` 与 `zhipu:*` 同链）

留钩子，尚未做：

- [ ] Function Calling / Tools
- [ ] 多模态（视觉输入）
- [ ] 回答缓存（基于 prompt hash）
- [ ] **主动升级**：判定置信度低 / JSON 反复失败时，主动跳到更强的档重判一次
      （与现有「被动降级」相反的方向）
- [ ] **额度消耗统计**：按 scene × 档位累计 token 用量，看哪个 scene 在吃额度、
      预计何时耗到链尾（免费额度语境下比「成本统计」有用）
- [ ] 跨进程冷却：目前是进程内 `dict`，重启清零、多实例不共享（生产单实例，够用）

## 9. 变更日志
| 版本 | 日期 | 变更 |
|---|---|---|
| v1 | 2026-04-28 | 初版 |
| v2 | 2026-05-26 | Scene 表格补充备注列；修正 provider 信息与 llm.yaml 对齐 |
| v3 | 2026-09-17 | scene 从单模型升级为**阶梯链**；接入 TokenHub；新增 §4.2 降级/冷却机制；scene 表改为只列链头与链长（避免与配置漂移） |
