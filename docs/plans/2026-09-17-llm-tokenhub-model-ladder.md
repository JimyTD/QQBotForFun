# LLM 接入 TokenHub + 阶梯模型链 · 规划

- **Status**: Accepted（P0 实施中）
- **Date**: 2026-09-17
- **Owner**: @owner
- **关联**: [`08-llm-integration.md`](../08-llm-integration.md)、[`adr/0003-llm-gateway.md`](../adr/0003-llm-gateway.md)、[`06-configuration.md`](../06-configuration.md) §3.2、[`free-llm-vendors.md`](../free-llm-vendors.md)
- **参考实现**: `d:/Fun/BioTrace`（`apps/api/src/llm/text-chain.ts`、`apps/api/src/llm/tokenhub.ts`、`apps/api/src/identify/vl-chain.ts`）

---

## 1. 一句话目标

把 `core.llm` 从「一个 scene 绑死一个模型」升级为「一个 scene 绑一条**有序模型链**」，
接入 TokenHub（单 Key 多模型，**只消费免费额度、不充钱**），
让链上各档在**额度耗尽 / 限流 / 故障**时自动梯次降档，并由链尾兜底回现有免费池。

---

## 2. 调研结论 A：TokenHub 是什么

> 事实来源：腾讯云官方文档（`cloud.tencent.com/document/product/1823`），抓取日期 2026-09-17。

| 项 | 结论 |
|---|---|
| 定位 | 腾讯云「大模型服务平台」，聚合混元 / DeepSeek / GLM / Kimi / MiniMax / Qwen 等 |
| 协议 | **OpenAI Chat Completions 兼容**（另有 Anthropic Messages 协议） |
| Base URL（广州） | `https://tokenhub.tencentmaas.com/v1` |
| Base URL（新加坡） | `https://tokenhub-intl.tencentmaas.com/v1`（**与广州 Key 不互通**） |
| 认证 | `Authorization: Bearer <TOKENHUB_API_KEY>` |
| 接入方式 | 直接把 `openai` SDK 的 `base_url` 指过去即可 → **与本项目现有网关天然兼容，无需换 SDK** |
| 计费 | 按量调用；**新用户有免费额度包 → 本项目只消费这一部分，不充钱**（见 §5.5） |
| 前置条件 | 每个模型要在控制台**单独开通**，未开通直接报 `402` |
| 可用性查询 | `GET /v1/models`，`status=online` 即当前可用 |

### 2.1 实际开通的模型（来自控制台截图，共 33 条）

> ⚠️ **本节以用户控制台截图为唯一依据**，而不是官方文档的理论清单——两者差异很大：
> 官方文档里作为旗舰宣传的 `glm-5.2` / `kimi-k3` / `glm-5.1`，**在这份开通列表里并不存在**。

#### 适合本项目（对话 / 判定 / JSON / 创意）

| 模型 | model 参数 | 窗口 | 相对现役 `glm-4-flash-250414` | 建议归属 |
|---|---|---|---|---|
| GLM-5.3-Flash | `glm-5.3-flash` | 1M / 128k out | GLM 五代 Flash，结构化输出 + 多模态 | **通用主力** |
| DeepSeek-V4-Flash | `deepseek-v4-flash` | 1M / 384k out | V4 代 Flash | **高频低延迟档** |
| DeepSeek-V4.1-Flash（原厂直供） | `deepseek/deepseek-flash` | 1M / 384k out | V4.1 Flash 直供 | **极速档** |
| DeepSeek-V4-Pro | `deepseek-v4-pro` | 1M / 384k out | V4 旗舰档 | **判定 / 出题质量档** |
| Kimi K2.8 Preview | `kimi-k2.8-preview` | 1M | Kimi 新一代预览 | **创意出题候选** |
| Hy4 preview | `hy4-preview` | 1M / **64k out** | 混元 Hy4；官方建议用途即「结构化 JSON 产出」 | JSON 场景候选 |
| MiniMax-M3 | `minimax-m3` | 1M | 新一代旗舰 | 备用候选 |
| MiMo-V2.5-Pro | `mimo-v2.5-pro` | 1M | 小米 MiMo 旗舰 | 备用候选 |
| Kimi-K2.5 | `kimi-k2.5` | 256k | Kimi 上代 | 兜底 |
| Hy-Role / Hy-Role-Latest | `hy-role` / `hunyuan-role-latest` | 32k | **角色扮演专用** | **`silent_mark_ai` 的特色候选** |

> 第三方评测（腾讯云社区 / CSDN，2026-08~09）称：
> DeepSeek-V4-Flash 的 API 速度约为 GLM-5.3-Flash 的 3 倍，V4.1-Flash 可达 6–10 倍；
> 原因是 **GLM-5.3 系思考模式倾向强制开启**。→ **对 30s 超时的 judge 场景是关键差异**，但必须本地实测复验，不能直接采信。

#### ⏳ 有下线日期 / 版本快照 → **优先烧，别浪费**

额度独立、不刷新、下线即作废 → **剩余寿命短的必须排链头**（见 §5.5.0）。

| 模型 | 下线日期 | 剩余 | 处理 |
|---|---|---|---|
| `qwen3.5-flash` / `qwen3.5-plus` | 官方标 **2026-09-08**（**日期已过**） | 随时失效 | **最先烧**，失效即自动跳档 |
| `glm-5` / `glm-5-turbo` / `glm-5.1` | **2026-10-08** | 约 3 周 | 优先烧 |
| `glm-5v-turbo` | **2026-10-30** | 约 6 周 | ❌ **本次不参加**（视觉模型，用户指定） |

> ⚠️ `qwen3.5-*` 标称下线日已过，但用户确认控制台仍在 → **以 `GET /v1/models` 实测为准**（§5.5.2）。
> 若已失效，链的降档机制会自动跳过，不需要手工处理。

**带日期后缀的版本快照**（`deepseek-v4-pro-0813`、`-202606`、`deepseek-v4-flash-0731`、`-202605`）：
若「每个服务名各自一条额度」成立，则**它们与不带后缀的是不同的额度池**，
且版本快照通常会被优先清理 → **同样进链、同样优先烧**。
最终以控制台服务列表（33 条）逐条核对为准。

#### 不适用（专用向）

| 模型 | 原因 |
|---|---|
| `hy-mt2-pro` / `hy-mt2-plus` / `hy-mt2-lite` | 翻译专用 |
| `kimi-k2.7-code` / `kimi-k2.7-code-highspeed` | 代码专用 |
| `deepseek/deepseek-v4-flash-vision-exp` | 视觉理解，本项目暂无需 |

### 2.2 错误码（与降级决策直接相关）

业务错误码为 6 位，**前三位对应 HTTP 状态**：

| 码/现象 | 含义 | 正确的处理 |
|---|---|---|
| `401002` | API Key 无效（含站点不匹配） | 打长冷却，**别重试** |
| `401006` / `endpoint is inactive` | 瞬态 | ⚠️ **可重试**。码里带 "401"，通用分类器会误判成鉴权失败，必须特判 |
| `402` / `402xxx` | 模型未开通 或 额度不足 | 打长冷却并**降下一档**，不要当抖动重试 |
| `429` / `429xxx` | 限流 | 就地退避重试（可能带 `Retry-After`） |
| `400` / `400xxx` | 参数错误 | 通常是 quirks 没配对 → 修 quirks，**不是模型坏**，别白白降级 |

### 2.3 各模型请求差异（2026-09-18 实测）

用 [`scripts/probe_tokenhub_models.py`](../../scripts/probe_tokenhub_models.py) 对 A 类 13 档逐个实测。

**一句话结论：只有 `kimi-k2.5` 需要特殊照顾，其余 12 档走默认参数即可。**

| 模型 | 实测结论 | 需要的 quirk |
|---|---|---|
| `kimi-k2.5` | **只接受 `temperature=1.0`**（0.1 / 0.6 一律 400，业务码 `400001`）；另拒绝 `thinking` 字段 | `{"temperature": 1.0}` |
| `minimax-m2.7` | `thinking: disabled` **关不掉**（发完仍返回 `reasoning_content`） | 无需（默认就不发） |
| 其余 11 档 | 默认可用、接受 `thinking` 字段、默认带思考 | 无 |

**全局观察（影响链序设计）**：

- ✅ **13/13 全部支持 `response_format={"type":"json_object"}`** —— 判题/出题的硬需求满足。
- ✅ **13/13 响应都在 5s 内**（最快 `hunyuan-role-latest` 421ms，最慢 `glm-5-turbo` 2.9s）。
  → §5.5.0.1 里「别把强制思考的档放链头（怕 30s 超时）」这条**在 A 类清单上不成立**：
  没有哪个档慢到会超时，所以**不需要为延迟调整「寿命优先」的链序**。
- ⚠️ **12/13 默认开思考**（返回 `reasoning_content`），但**发 `disabled` 之后延迟并没有明显改善**
  （部分档反而更慢：`glm-5.1` 1.6s→2.1s、`glm-5-turbo` 3.0s→4.4s）。
  → 说明「返回 `reasoning_content`」与「思考拖慢响应」不是一回事，**不必为关思考而折腾**。
- ⚠️ **延迟是单次采样**，网络抖动大，只能作量级参考，不能当性能基线。

**⚠️ `kimi-k2.5` 与判定场景的天然冲突**：它强制 `temperature=1.0`，而 `turtle_soup_judge` /
`turtle_soup_claim` 需要低温度换取判定一致性（0.1 / 0.2）。
一旦降级到它，**判定会变随机**。它目前排在判定链的第 10 位左右，影响有限，但仍需知悉。

**额度状态**：13 档**全部未耗尽**（0 个 402），说明这批免费额度基本还没动过。

**思考内容的字段位置**：OpenAI 兼容路径下走 `reasoning_content`，**不在 `content` 里**。
本项目只读 `choices[0].message.content`，不受影响；但排障时要知道去哪看。

---

## 3. 调研结论 B：BioTrace 的做法

### 3.1 它解决的问题

识图 / 稀有度量表要打 TokenHub，但**免费额度会耗尽、模型会被限流、部分模型有 bug**。
于是不用「一个模型 + 失败重试」，而是 **「一条有序模型链 + 失败降档」**。

### 3.2 机制拆解（可直接照搬的部分）

| 机制 | 位置 | 要点 |
|---|---|---|
| 模型优先级链 | `llm/text-chain.ts` | `RARITY_TEXT_MODELS`（env 逗号分隔）= `glm-5.2, kimi-k3, glm-5.1, glm-5.3`。能关思考的在前，始终思考的垫底 |
| 单档健康态 | 同上，进程内 `Map<model, ModelHealth>` | `coolUntil` / `lastErrorKind` / `lastError` / `lastOkAt` |
| 错误分类 → 冷却时长 | `llm/tokenhub.ts` | `rate_limited`→按 `Retry-After`；`daily_exhausted`→6h；`auth`→30min；`transient`→20s；默认 10min |
| 重试 vs 降档的边界 | 同上 | **只有** `rate_limited` / `transient` 就地重试（最多 3 次）；`daily_exhausted` / `auth` 立即打冷却降档 |
| per-model quirks | `MODEL_QUIRKS` 表 | 按模型名精确匹配覆盖 temperature / 是否发 thinking，未登记走默认 |
| 生效模型名回传 | 返回值 `{ content, model }` | cache 里记下实际生效的模型名，事后查得出「这条是哪档判的」 |
| 诊断快照 | `textChainSnapshot()` | 后台接口看每档当前冷却状态与最后错误 |
| TokenHub 特判 | 同上 | `401006` → transient；`402` → daily_exhausted |
| 显式直连 | `tokenhubDirectAgent()` | 因为别处装了出境代理，TokenHub 是国内服务，不能跟着绕境外 |

### 3.3 它**没有**的能力（本项目可以做得更好）

- ❌ **没有跨 provider 的链**：BioTrace 是「同一把 TokenHub Key，只换模型名」。本项目需要「TokenHub ↔ 智谱 ↔ LongCat」同链。
- ❌ **没有主动升级**：BioTrace 只有被动降级（坏了才往下掉），没有「低置信度时主动上更强档重试」。
- ❌ **没有成本控制**：BioTrace 没在链上区分贵贱，纯粹按可用性排。
- ⚠️ 它的链是**全局单一**（稀有度量表一条链、识图一条链），本项目要的是**每个 scene 一条链**。

---

## 4. 现状盘点：本项目 LLM 层

### 4.1 已有资产

| 项 | 位置 | 状态 |
|---|---|---|
| 统一网关 | `src/core/llm.py`（~390 行） | ✅ scene → provider + **单** model；指数退避重试 3 次；JSON 模式校验 |
| 场景配置 | `config/llm.yaml` | ✅ providers × 2（zhipu / longcat）、scenes × 9 |
| 异常族 | `src/core/errors.py` | ✅ `LLMError` / `LLMTimeoutError` / `LLMRateLimitError` / `LLMJSONParseError` / `LLMConfigError` |
| 纪律 | ADR 0003 | ✅ 所有 LLM 调用必须走 `core.llm`。已核验：`src/` 下仅 `core/llm.py` 直接 import openai，**无越权调用** |
| 备用设计 | `docs/06-configuration.md` §3.2 | 📝 已预留 `fallback:` 结构，标注「v1 暂不启用」 |

### 4.2 调用点（11 处 / 9 个 scene）

| Scene | 调用点 | 特征 | 当前模型 |
|---|---|---|---|
| `turtle_soup_judge` | `games/turtle_soup/game.py:385` | **高频**（20-50 次/局）、要 JSON、判定质量敏感 | glm-4-flash-250414 |
| `turtle_soup_claim` | `games/turtle_soup/game.py:538` | 低频、要 JSON、判定质量敏感 | 同上 |
| `turtle_soup_host` | `games/turtle_soup/puzzle_service.py:273` | 低频、创意、长输出、要 JSON | 同上 |
| `trivia_host` | `games/trivia/puzzle_generator.py:319/387` | 中频、创意、要 JSON | 同上 |
| `web_search` | `tools/ask_ai/service.py:74` | 中频、长文归纳、不要 JSON | 同上 |
| `ask_ai` | `tools/ask_ai/service.py:88` | 中频、开放问答 | 同上 |
| `finance_report` | `tools/finance/reporter.py:170` | 低频、短输出、要准 | 同上 |
| `silent_mark_ai` | `games/silent_mark/ai/controller.py:207` | 高频、要 JSON、超时窗口紧（30s） | 同上 |
| `silent_mark_ai_name` | `games/silent_mark/ai/names.py:74`、`commands.py:669` | 低频、极短输出 | 同上 |

### 4.3 现有能力缺口

| 缺口 | 后果 |
|---|---|
| 无模型链 / fallback | 单模型一坏，整个 scene 直接抛错。当前「优点稳定免费」是**单一供应商的单点稳定性** |
| 无健康态 / 冷却 | 每次调用都重新打一个已知挂掉的模型，浪费延迟和额度 |
| 无 model quirks | `kimi-k3` 这类模型一接就整档 400（temperature 不合法 / 思考默认开启到 80s 超时） |
| 无 TokenHub 错误特判 | `401006` 被当鉴权错误；`402`（未开通）被当抖动重试 |
| 无「生效模型」追溯 | `LLMResponse.model` 回的是配置里的模型名，链上降级后失去可追溯性 |
| `chat_stream` 无调用者 | 目前是死代码 → 本轮**不必**为它做降级（显式标注即可） |

### 4.4 顺带发现的文档漂移（实施时一并修）

- `docs/08-llm-integration.md` §2 的 scene 表写着 judge/claim = `LongCat-Flash-Chat`、web_search = `LongCat-Flash-Lite`，
  但 `config/llm.yaml` 实际**全部是 `zhipu / glm-4-flash-250414`**。
- `docs/06-configuration.md` §2.5 / §3 的示例还停留在 `longcat` 为 judge 主力的版本。
- `scripts/benchmark_llm.py` 的 `production_models()` 只列了一个模型（「全场景唯一」），与「阶梯」目标不符。

---

## 5. 设计

### 5.1 核心概念：Scene 的有序模型链

把 scene 从「单模型」改为「**有序链**」，链上每一档是 `(provider, model)`：

```yaml
scenes:
  turtle_soup_judge:
    # 链头 = 本场景的首选档；往后依次是降级档
    chain:
      - glm-5.3-flash              # 继承 scene.provider
      - tokenhub:kimi-k3           # 显式换 provider
      - zhipu:glm-4-flash-250414   # 免费兜底，保证不比现状差
    temperature: 0.1
    max_tokens: 256
    json_mode_default: true
    timeout_seconds: 30
```

**向后兼容**：`provider` + `model` 写法保留，内部等价于 `chain: [{provider: <provider>, model: <model>}]`。
→ **不做一次性大迁移，老 scene 不动也能跑**。

### 5.2 调度算法（单次 `chat()` 内）

```
for 档 in scene.chain:
    if 该档在冷却中: continue                    # 跳过已知坏档，不浪费一次调用
    for i in 1..attempts_per_model(=3):
        try: 调用
        except:
            kind = classify_tokenhub_error(msg)
            if kind in (rate_limited, transient) and i < attempts:
                sleep(退避) ; continue            # 就地重试
            mark_cooldown(档, kind)              # 打冷却
            break                                # 降下一档
    else: return 命中档的响应（含实际模型名）
全链失败 -> 抛 LLMError（保留 last_error 摘要）
```

关键取舍（照搬 BioTrace，已证明有效）：

- **重试与降档分离**：抖动就地重试，配额/鉴权/参数错立即降档。
- **冷却期内跳过**：不重复打已知坏档。冷却时长按 kind 映射（见 §2.2 / §3.2）。
- **链序 = 本场景优先级降序**：首选档在前，额度耗尽/故障时依次下移，链尾兜底到另一家免费池（见 §5.5）。

### 5.3 代码落点：`src/core/llm.py`

新增（约 +150 行，保持单文件，不引入新依赖）：

```python
# ---- 冷却与健康态（进程内）----
@dataclass
class _SlotHealth:
    key: str                    # "tokenhub:glm-5.3-flash"
    cool_until: float | None = None
    last_error: str | None = None
    last_error_kind: str | None = None
    last_ok_at: float | None = None

_HEALTH: dict[str, _SlotHealth] = {}

_COOL_SECONDS = {              # kind -> 冷却秒数
    "rate_limited": ...,       # 优先解析 Retry-After / "retry in Xs"，默认 35s
    "quota_exhausted": ...,    # 402/额度耗尽：见 §5.5.1，6h 起指数翻倍、24h 封顶
    "auth": 1800,
    "transient": 20,
    "fatal": 600,
}

def _classify_error(msg: str) -> str: ...
def _cool_seconds_for(kind: str, msg: str) -> float: ...
def _slot_available(key: str) -> bool: ...
def _mark_slot(key: str, kind: str | None, err: str | None) -> None: ...
def llm_health_snapshot() -> list[dict]: ...     # 诊断用
```

新增 **quirks 表**（键为 `model` 名，未登记走默认）：

```python
_MODEL_QUIRKS: dict[str, dict[str, Any]] = {
    # ⚠️ 下面除第一行外均为「按同族脾气推测的占位」，必须 P1 实测后改写（见 §2.3）
    "glm-5.3-flash":          {"thinking": "disabled"},   # 待验证：是否同 glm-5.3 强制思考
    "kimi-k2.8-preview":      {"temperature": 0.6},       # 待验证：是否沿袭 Kimi 系温度限制
    "deepseek-v4-flash":      {},                         # 待验证
    "deepseek/deepseek-flash": {},                        # 待验证
    # 未登记：temperature 用 scene 值，不发 thinking
}

# openai SDK 传非标准参数的通道：client.chat.completions.create(..., extra_body={"thinking": {...}})
```

改造 `chat()` 主循环（保持对外签名**完全不变**，11 个调用点零改动）：

```python
async def chat(messages, *, scene, temperature=None, max_tokens=None,
               json_mode=None, timeout=None) -> LLMResponse:
    ...
    for slot in chain:
        if not _slot_available(slot.key): continue
        ... # 见 §5.2
    raise last_err
```

`LLMResponse` 增补两个**可选**字段，便于追溯与统计：

```python
@dataclass
class LLMResponse:
    content: str
    model: str                      # 改为「实际生效模型名」
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0
    provider: str = ""              # 新增：实际生效 provider
    chain_index: int = 0            # 新增：命中的档位（0 = 链头，>0 说明发生过降级）
    degraded: bool = False          # 新增：chain_index > 0 的便捷标记
```

### 5.4 配置解析（`_load_config`）

```yaml
providers:
  tokenhub:
    base_url: https://tokenhub.tencentmaas.com/v1
    api_key: ${TOKENHUB_API_KEY}
    timeout_seconds: 60
```

- `Settings` 增 `tokenhub_api_key: str = ""`（`src/settings.py`，与 zhipu/longcat 并列）。
- `.env` 增 `TOKENHUB_API_KEY=`（**服务器侧按运维规则手工写入 `.env`，永不入 git**）。
- 链路元素解析：`"model"` → 继承 `scene.provider`；`"provider:model"` → 显式指定。
- 配置校验：链上任一 provider 未在 `providers` 声明 → 启动即 `LLMConfigError`（沿用现有严格校验风格）。
- 链上 provider 缺 api_key → **只 WARNING 不阻断**（让它能被跳过并降档），但要打印是哪一档被跳过。

### 5.5 阶梯的真实形态：**额度梯次池**（已定）

> **用户口径（2026-09-17，已确认）**
> - 只用 TokenHub 白嫖额度，**不充钱**
> - 额度**按模型各自独立一条**
> - **不刷新**——用完就没了
> - **模型下线 = 额度也没了**（过期作废）
> - 账号额度**跨项目共用** → 本项目只清理临期库存，**好资源不碰**
> - `glm-5v-turbo` 本次不参加
>
> → 原先「质量优先 vs 成本优先」的取舍**不存在了**。

#### 5.5.0 进链范围：**只串「旧 / 临期」的，好资源留给别的安排**

> **用户口径（2026-09-17 · 第二轮）**
> - `glm-5v-turbo` 本次**不参加**
> - **不是把 33 个服务名全串上** —— 部分好模型**另有用途，不能在这烧掉**
> - 本项目只吃「**相对旧的、或即将下线的，但比现役强**」的那批

账号额度是**跨项目共用**的，链的设计因此要带**预算意识**：本项目只做「清理临期库存」，
不碰仍在服役期的新资源。

**A. 建议进链**（旧代 / 临期 / 版本快照 —— 不用就是作废）

| 模型 | 性质 | 相对现役 `glm-4-flash-250414` |
|---|---|---|
| `qwen3.5-flash` / `qwen3.5-plus` | 标称 2026-09-08 下线（**已过**） | 新一代 Flash / Plus，更强 |
| `glm-5` / `glm-5-turbo` / `glm-5.1` | 2026-10-08 下线 | GLM5 代，更强 |
| `deepseek-v4-flash-202605` / `-0731` | V4-Flash **旧版本快照** | 更新代，更强 |
| `deepseek-v4-pro-202606` / `-0813` | V4-Pro **旧版本快照** | 更新代，更强 |
| `kimi-k2.5` | Kimi **上代** | 更新代 |
| `minimax-m2.7` | MiniMax **上代** | 更新代 |
| `hunyuan-role-latest` / `hy-role` | 角色扮演**专用**，用途窄 | 适配 `silent_mark_ai` |

**B. 建议保留**（好资源，本项目不消耗，留给其他安排）

`deepseek/deepseek-flash`（V4.1 原厂直供，最新最快）、`deepseek-v4-pro`、`deepseek-v4-flash`、
`glm-5.3-flash`、`kimi-k2.8-preview`、`minimax-m3`、`hy4-preview`、`mimo-v2.5-pro`

**C. 不进链**

| 模型 | 原因 |
|---|---|
| `glm-5v-turbo` | 视觉模型 + **用户指定本次不参加** |
| `hy-mt2-pro` / `plus` / `lite` | 翻译专用 |
| `kimi-k2.7-code` / `-code-highspeed` | 代码专用 |
| `deepseek/deepseek-v4-flash-vision-exp` | 视觉理解 |

##### ✅ 已确认：**不留常驻档，用完即弃**

链上**只有 A 类**。后果要写明白：**10-08 那批下线后，TokenHub 这条线整段归零**，
直接落到链尾 `zhipu:glm-4-flash-250414`。

**用户已确认接受**（2026-09-17）：「不留啊，等他们都废了我会再处理的」
→ 本次升级**有预期的时效性**；届时重新评估是否再开新的临期资源。
→ 因此 **B 类清单（好资源）全部保留不动**，本项目不消耗。

#### 5.5.0.1 排序原则：**先按过期时间分组，组内按质量降序**

```
第 1 组  qwen3.5-plus / qwen3.5-flash          ← 标称已过期，最先烧
  ↓
第 2 组  glm-5.1 / glm-5 / glm-5-turbo          ← 2026-10-08 下线
  ↓
第 3 组  deepseek-v4-pro-202606 / -0813         ← 版本快照，越旧越前
         deepseek-v4-flash-202605 / -0731
  ↓
第 4 组  kimi-k2.5 / minimax-m2.7 / hy-role     ← 上代通用 + 角色扮演
  ↓
         zhipu / longcat                         ← 另一家免费池，永续兜底
```

**组内为什么按质量降序**：同一批反正都要烧掉，**先用强的**——同样的额度换更好的体验。
例：`qwen3.5-plus` 排 `qwen3.5-flash` 前，`glm-5.1` 排 `glm-5` 前。

#### 5.5.0.2 质量门槛：讨论过，**因额度约束放弃**（2026-09-18）

> 用户问：「反正对比我们现在用的应该都是正提升？」

**代际上大概率是，但判题场景有真实反例风险，不能假设**：
海龟汤判定要求严格输出 `type: yes/no/irrelevant/key`，强模型「过度推理 / 不守格式」
反而可能比弱模型差 —— 这是这类任务的通病，不是猜测。

**原本的方案**：用 golden eval 筛出「质量 ≥ 现役 `glm-4-flash-250414`」的档才允许进链头。

**2026-09-18 放弃**，理由是 **验证成本 ≈ 被验证的资源本身**：
14 条 golden × 13 档，光 judge 那种长 prompt 就要烧掉**十几万 token**，
而这批额度本就有限、不刷新、用完即弃 —— 为了验证它而先烧掉它，不划算。

> 用户原话：「不需要质量测评了，就这么点 token，等你测完了我还用不用？」

**这不是疏忽，是知情取舍。** 接受「链序未经质量验证」，靠 §6-P1 的**事后追溯**兜底。

**参数层面**（能不能调通、吃不吃 JSON、多快）已在 §2.3 实测完毕，那部分没有未知项。

#### 5.5.0.3 ⚠️ 代价：链头放临期模型，会让「质量随时间漂移」

- `qwen3.5-*` 失效那天 → 链头自动下移到 `glm-5.1` → 玩家遇到**另一套判定风格**
- 10-08 那批下线后 → 再跳一次
- 表现为：**同一款游戏，前后几天的判定质量/倾向不一致**

**对策**：
1. 每次链序调整（含被动跳档）记 `docs/08` 变更日志，便于回溯「那几天判得怪」。
2. `LLMResponse` 回传实际生效模型名（§5.3）→ 判定结果若落库，带上模型名。

#### 5.5.0.4 各 scene 建议链（待 P1 实测定稿）

> 链头统一从 A 类「最先过期且通过质量门槛」的档开始，链尾是智谱兜底。
> **所有链的具体成员与顺序均由 P1 的 golden eval 决定，下表只是结构示意。**

| Scene | 建议链 | 依据 |
|---|---|---|
| `turtle_soup_judge` | `qwen3.5-plus` → `glm-5.1` → `deepseek-v4-flash-202605` → `zhipu:...` | 高频 20–50 次/局 + 30s 超时 |
| `silent_mark_ai` | `qwen3.5-plus` → `hunyuan-role-latest` → `glm-5.1` → `zhipu:...` | 高频 JSON 决策；角色扮演模型对味 |
| `turtle_soup_claim` | `qwen3.5-plus` → `deepseek-v4-pro-202606` → `glm-5.1` → `zhipu:...` | 1–3 次/局、决定胜负 |
| `turtle_soup_host` | `qwen3.5-plus` → `deepseek-v4-pro-0813` → `kimi-k2.5` → `zhipu:...` | 1 次/局、创意第一印象 |
| `trivia_host` | `qwen3.5-plus` → `glm-5.1` → `minimax-m2.7` → `zhipu:...` | 中频创意 |
| `web_search` / `ask_ai` | `qwen3.5-plus` → `deepseek-v4-flash-0731` → `kimi-k2.5` → `zhipu:...` | 长文归纳吃 1M 窗口 |
| `finance_report` | `qwen3.5-plus` → `glm-5-turbo` → `minimax-m2.7` → `zhipu:...` | 短输出 |
| `silent_mark_ai_name` | `qwen3.5-flash` → `glm-5` → `deepseek-v4-flash-202605` → `zhipu:...` | 输出仅 20 token，可用较弱的档 |

#### 5.5.1 额度耗尽的冷却语义（与 BioTrace 的关键分歧）

**已确认**：额度**按模型独立**、**不刷新**、**用完/下线即永久失效**。

BioTrace 的 `daily_exhausted → 6h 冷却` 是为 **Gemini 每日重置**设计的，此处**不适用**：
照抄就会每 6 小时白白打一次**已经永久耗尽**的档。

**设计：耗尽即长冷却 + 指数递增 + 24h 封顶**

```python
# 同一档连续返回 402/额度耗尽时，冷却时间翻倍
# 6h → 12h → 24h（封顶）
cool = min(6 * 3600 * (2 ** (exhaust_count - 1)), 24 * 3600)
```

封顶 24h 而非永久封禁，是因为**必须留一条自愈路径**：
万一是误判（临时 402 抖动、额度被后台补发），每天至少能自动重试一次。代价仅是每天一次调用。

#### 5.5.2 动态链裁剪：`GET /v1/models`（已实现）

既然**模型下线 = 额度也没了**，配置里写死的链会越攒越多死档。
TokenHub 的 `GET /v1/models`（实测返回 **121 个**模型）给出每个模型的 `status`：

| status | 含义 | 处理 |
|---|---|---|
| `online` | 正常在服 | ✅ 可用 |
| **`pre-offline`** | **已公告下线，但仍在服务** | ✅ **必须保留** —— 这正是最该优先烧的那批 |
| `discontinued` | 已停服 | ❌ 剔除 |

**实测（2026-09-18）**：`qwen3.5-plus` / `qwen3.5-flash` / `glm-5.1` / `glm-5` /
`glm-5-turbo` / `glm-5v-turbo` / `kimi-k2.5` **全都是 `pre-offline`**，且实测**都能正常调用**。

> ⚠️ **实施时踩过的坑**：最初只认 `status == "online"`，这会把这 7 个临期档
> **全部误剔** —— 恰好剔掉链头的目标，等于把这次改造的意义整个抹掉。
> 已改为**黑名单**策略（只剔 `discontinued`），字段不认识时宁可保留。
> 回归用例：`test_refresh_online_models_keeps_pre_offline_but_drops_discontinued`。

**设计**
- **启动时**拉一次，剔除 `discontinued` 的档并 WARNING。
- 好处 1：模型下线**不用改配置**，链自动缩短。
- 好处 2：避免每次调用都白打一个已停服的档。
- 好处 3：`pre-offline` 的档在 `health_snapshot()` 里会标成 `imminent_offline`，
  一眼看出「哪些档要赶紧烧」。
- ⚠️ 该接口返回的是**平台全量清单**（121 个），**不代表当前 Key 已开通哪些**；
  能否调用仍以实际请求为准（未开通 / 额度耗尽都是 402）。
- ⚠️ 该接口**不反映额度是否耗尽**。
- ⚠️ 该接口失败**不阻断启动**，退化为「不裁剪，按配置原样跑」。

#### 5.5.3 链长：够用即可，不追求最长

额度按模型独立 → 每个服务名都是独立额度池，理论上串得越多总量越大。
但本项目**只串 A 类临期档**，理由是：

- **好资源要留给别的用途**（账号额度跨项目共用）
- 链越长，「逐档探测」开销越大——首次调用或重启后，若前面几档都死了，
  要连着打几次才落到活档。冷却生效后不再重复，但重启会清零。
- A 类档的总容量对本群规模已经绰绰有余（友人小群，非公开大群）

**A 类 11–12 档 + 智谱兜底 ≈ 13 档**，容错层数足够。不设常驻档（见 §5.5.0）。

### 5.6 可观测性（已实现）

**原则：诊断默认零额度消耗** —— 探活就是烧额度。

| 手段 | 位置 | 额度消耗 |
|---|---|---|
| **调用日志** | 每次 `chat()` 打 `scene=... slot=<provider:model> chain_index=N` | 无（随调用产生） |
| **`llm.health_snapshot()`** | 只读内存，逐档给 `status / cool_remaining_s / exhaust_count / imminent_offline` | **零** |
| **`scripts/llm_status.py`** | CLI：各 scene 链路 + 每档状态 + 汇总（`--json` 便于采集） | **零**（只拉一次 `/v1/models`，不耗推理额度） |
| **`@我 AI 测试`** | `silent_mark/commands.py`，真打一次，报出**实际生效的档**与是否降级 | ⚠️ **消耗一次调用** |

「零消耗」为什么重要：TokenHub 额度**不刷新**，**每一次探活都是永久损失**。
所以诊断一律只读内存；唯一真打的那条命令保留，是因为「链到底通不通」只有打一次才知道。

~~评测脚本（golden 集对照表）~~ —— 因额度约束取消，见 §6-P1。

---

## 6. 分期落地计划

### P0 · 网关能力（不动业务，纯增量，可独立验证）

| # | 任务 | 文件 | 状态 |
|---|---|---|---|
| 1 | 加 `tokenhub` provider（配置 + Settings + `.env.example`） | `config/llm.yaml`、`src/settings.py`、`.env.example`、`docs/06` | ✅ |
| 2 | scene 支持 `chain`（含 `provider:model` 写法，向后兼容旧 `model`） | `src/core/llm.py` | ✅ |
| 3 | 冷却/健康态 + `llm.health_snapshot()` | `src/core/llm.py` | ✅ |
| 4 | `_classify_exception` / `_cool_seconds_for`（含 TokenHub `401006`、`402` 特判） | `src/core/llm.py` | ✅ |
| 5 | `_MODEL_QUIRKS` + `extra_body` 通道（thinking / temperature 修正） | `src/core/llm.py` | ✅（表待 P1 回填） |
| 6 | `LLMResponse` 补 `provider` / `chain_index` / `degraded` | `src/core/llm.py` | ✅ |
| 7 | 启动时 `GET /v1/models` 动态裁剪死档（失败不阻断） | `src/core/llm.py` | ✅ |
| 8 | 修 §4.4 的文档漂移 | `docs/08`、`docs/06` | ✅ |
| 9 | **缺陷修复（实施中发现）**：没配 api_key 的档会抛 `LLMConfigError`，而它**不是** `LLMError` 子类 → 会穿透降档循环打断整次调用 | `src/core/llm.py` | ✅ |

**P0 完成判据（已达成）**：链头返回 `402` 时自动降档并成功返回，`chain_index == 1`。
覆盖在 `tests/core/test_llm_ladder.py`（34 个用例，全部离线、不触网）。

**P0 遗留**：`_MODEL_QUIRKS` 仍是**空表**（不凭猜测填写）。
后果：默认不发 `thinking` 字段 —— 若某档默认开启思考，会表现为「响应慢但能出结果」，
不会报错。P1 探针跑完后回填即可。

### P1 · 参数实测与运维可见性

| # | 任务 | 状态 |
|---|---|---|
| 1 | **探针脚本** `scripts/probe_tokenhub_models.py`：逐档探 temperature / thinking / JSON / 延迟 | ✅ 2026-09-18 |
| 2 | **诊断脚本** `scripts/llm_status.py`：读 `health_snapshot()` 输出链路与冷却态（**零额度消耗**） | ⬜ |
| 3 | ~~`benchmark_llm.py` 重构~~ | ❌ 取消 |
| 4 | ~~`eval_judge_compare.py` 接入 TokenHub 候选~~ | ❌ 取消 |
| 5 | ~~按 golden eval 划门槛并定稿链序~~ | ❌ 取消 |

**3~5 取消的原因**：它们都要真实调用，而**验证成本 ≈ 被验证的资源本身**（见 §5.5.0.2）。

额度受限场景下，**前置全量评测**换成**事后定点排查**更划算：

```
出问题时  翻 logger 里的 slot= / chain_index= → 定位当时降到了哪一档
        → 只对那一档跑几条 golden（几千 token）
           而不是 13 档 × 14 条全量（十几万 token）
```

这也是为什么 `LLMResponse` 必须带 `provider` / `model` / `chain_index`：
**放弃前置评测后，事后可追溯就是唯一的质量兜底手段。**

### P2 · 可选增强（做完 P1 再评估）

- **主动升级**：JSON 反复解析失败 or 判定置信度低 → 主动跳到链上更强档重判一次（BioTrace 没有这个）。**需先确认业务是否真的受益**。
- **额度消耗统计**：按 scene × 档位累计 token 用量，看哪个 scene 在吃额度、预计何时耗到链尾。免费额度语境下这比「成本」有用得多。
- **跨进程冷却**：目前是进程内 `dict`，重启清零、多实例不共享。生产是单实例，够用；若将来多实例再迁 Redis。
- **`chat_stream` 降级**：当前无调用者。若将来要用，需明确「已 yield 后不可降档」的语义。

---

## 7. 风险与坑

| 风险 | 说明 | 对策 |
|---|---|---|
| **免费额度用尽** | 全链 TokenHub 档都会耗尽 → 必须能干净落到链尾 | 链尾串 zhipu/longcat（**独立额度池**）；`402` 打递增冷却（§5.5.1） |
| **链头质量不达标** | 寿命优先会把快过期档排链头，但它们未必判得更准 | **先过 golden eval 质量门槛**再进链（§5.5.0.1）——额度不值钱，体验值钱 |
| **质量随时间漂移** | `qwen3.5-*` / `glm-5.1` 陆续失效 → 链头自动下移，判定风格跟着变 | 链序变更记 `docs/08` 变更日志；判定结果带上实际生效模型名（§5.5.0.2） |
| **模型下线** | `glm-5`/`glm-5-turbo`/`glm-5.1` 2026-10-08；`glm-5v-turbo` 10-30；`qwen3.5-*` 标称 09-08 已过期 | **优先烧**（§2.1）+ 启动时用 `GET /v1/models` 自动裁剪（§5.5.2） |
| **模型未开通 → 402** | TokenHub 每个模型要单独开通 | 部署前用 `GET /v1/models` 核对；`402` 必须降档不能重试 |
| **quirks 未复验** | §2.3 的差异来自 BioTrace，且其主力模型我们多数没开通 | P1 对本项目候选**逐个实测**，不能照抄 |
| **思考默认开启导致超时** | 第三方评测称 GLM-5.3 系倾向强制思考，而 judge 只有 30s 超时 | 高频场景优先 DeepSeek Flash 系；quirks 尝试关思考；各档 timeout ≥ 该档真实 P95 |
| **JSON 模式兼容性未知** | 各 TokenHub 模型对 `response_format` 支持度需实测 | 保留现有「不支持则退化」逻辑，并做成 per-model quirk |
| **Key 泄露** | 项目历史上出过密钥进 public 仓库的事故（commit `66e2df6`） | `TOKENHUB_API_KEY` 只进服务器 `.env`，**永不入 git**；`.env.example` 只留空占位 |
| **诊断误伤** | 为看健康态而主动打真实模型会消耗免费额度 | 诊断快照只读内存状态，**不做探活调用** |

---

## 8. 待你拍板的决策点

> ✅ **已拍板（无待定项）**
>
> | 日期 | 结论 |
> |---|---|
> | 09-17 | 只用 TokenHub 免费额度，不充钱 |
> | 09-17 | 额度**按模型独立、不刷新、用完 / 下线即失效** |
> | 09-17 | 链按**剩余寿命升序 + 组内质量降序**排（§5.5.0.1） |
> | 09-17 | **只串 A 类临期档**，好资源留给别的安排（§5.5.0） |
> | 09-17 | `glm-5v-turbo` 不参加 |
> | 09-17 | A 类照单全收；**不留常驻档**，用完即弃，届时再处理 |
> | 09-17 | 原「质量优先 / 成本优先」取舍作废 |
> | 09-18 | **不做质量评测** —— 验证成本 ≈ 被验证的资源本身，改为事后定点排查（§5.5.0.2） |
> | 09-18 | scene **全量**改为阶梯链（不做分批试点） |
>
> 剩下的都是实施细节，见 §6。

---

## 9. 验收标准

沿用 ADR 0003 的既有指标，并补充链路专项：

- [ ] 改 `config/llm.yaml` 即可切换/调整链序，**零代码改动**（延续 ADR 0003 的验证标准）
- [ ] 链头故意配错仍能自动降档成功，`chain_index > 0` 且日志可追溯
- [ ] 已知坏档在冷却期内被跳过（不产生真实调用）
- [ ] 判定类调用 p95 < 5s、失败率 < 1%（未被降级链拖慢主路径）
- [ ] 全链不可用时抛出的异常仍是 `LLMError` 子类，**11 个调用点的现有错误处理不需要改**
- [ ] `docs/08` scene 表与 `config/llm.yaml` 完全一致（修掉 §4.4 的漂移）

---

## 10. 变更日志

| 日期 | 变更 |
|---|---|
| 2026-09-17 | 初版：TokenHub 调研 + BioTrace 机制拆解 + 现状盘点 + 分阶段方案 |
| 2026-09-17 | 按控制台实际开通清单（33 条）重写 §2.1：删掉文档里有但没开通的 `glm-5.2`/`kimi-k3`；标注下线模型。§5.5 从「成本取舍」改为「免费额度梯次池」，新增额度耗尽的递增冷却设计（§5.5.1）。§2.3 quirks 改为本项目待实测项 |
| 2026-09-17 | 确认额度**按模型独立、不刷新、用完/下线即失效**。据此 §5.5.0 定「剩余寿命优先」排序（用户提出），并叠加 §5.5.0.1「质量门槛」；§2.1 的「不应进链」改为「优先烧」；新增 §5.5.2 启动时 `GET /v1/models` 动态裁剪死档 |
| 2026-09-17 | 第二轮：`glm-5v-turbo` 移出（用户指定，且为视觉模型）；**不再串全部 33 个**，改为只串 A 类「旧/临期」档，好资源留给其他用途（§5.5.0 三分类清单）；排序细化为「先按过期分组、组内质量降序」（§5.5.0.1）；新增「全用 A 类会导致 10-08 后归零」的警告 |
| 2026-09-17 | **定稿**：A 类照单全收（11–12 档）；**不留常驻档**、用完即弃（§5.5.0）；Status → Accepted，开始 P0 |
| 2026-09-17 | **P0 完成**：`core.llm` 阶梯链 + 冷却 + 错误分类 + `extra_body` quirks 通道 + `GET /v1/models` 裁剪；10 个 scene 全部改写为链；`docs/06`/`docs/08` 同步。顺手修掉「缺 api_key 的档抛 `LLMConfigError` 打断整条链」的缺陷。新增 34 个离线用例 |
| 2026-09-18 | **P1-1 完成**：新增 `scripts/probe_tokenhub_models.py` 并实测 A 类 13 档。结论回填 §2.3 与 `_MODEL_QUIRKS`（仅 `kimi-k2.5` 需 `temperature=1.0`）。**发现 `pre-offline` 状态**（7 个链头档全是它，仍可调用）→ 修正 §5.5.2 的裁剪逻辑为黑名单，否则会把整条链头误剔 |
| 2026-09-18 | **P1 收缩（用户决策）**：取消全部质量评测 —— 「验证成本 ≈ 被验证的资源本身」，改为事后定点排查（§5.5.0.2 / §6-P1）。新增零消耗诊断 `scripts/llm_status.py` 与只读查询 `scene_chains()` / `providers_snapshot()`；`@我 AI 测试` 改为报出**实际生效的档**与降级信息 |
