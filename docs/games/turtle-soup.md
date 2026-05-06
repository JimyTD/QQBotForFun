# 游戏设计文档 · 海龟汤（Turtle Soup）

- **Game ID**: `turtle_soup`
- **Status**: Design v1.1
- **Last Updated**: 2026-05-06
- **Owner**: @owner
- **Version**: 1.1（新增购买提示功能）

---

## 1. 玩法简介

海龟汤（Lateral Thinking Puzzle）是一种推理游戏：

- **汤主**给出一段反常识的故事（**汤面**）
- **玩家**通过提问来还原故事真相（**汤底**），提问只能是"是/否"问题
- **汤主**只回答：**"是 / 不是 / 与此无关 / 问得好（关键信息）"**
- 玩家累计提问、逐步推理，直到说出汤底

本游戏中，**汤主由 LLM 扮演**，无需真人出题。

## 2. 范围与不做什么

### 本版本 (v1.0) **做**
- ✅ LLM 自动出题（从内置题库或即时生成）
- ✅ 多玩家自由提问（事件驱动，非轮次）
- ✅ LLM 判定每个问题
- ✅ 玩家主动宣告汤底，LLM 判定是否正确
- ✅ 超时、主动结束、投降（查看汤底）

### 本版本 **不做**（未来 v2+）
- ❌ 真人出题投稿
- ❌ 汤主人工 override
- ❌ 多群联机
- ❌ 积分榜 / 段位（可先记录数据，后续再展示）
- ❌ 汤的难度分级

## 3. 术语

| 术语 | 含义 |
|---|---|
| 汤面 | 反常识的故事片段，游戏开始时展示给玩家 |
| 汤底 | 故事的真相，玩家需要推理出来 |
| 提问 | 玩家向汤主发出的"是/否"问题 |
| 裁定 | 汤主对提问的回复：是 / 不是 / 与此无关 / 关键信息 |
| 宣告 | 玩家认为自己想出了真相，显式提交的完整故事版本 |
| 投降 | 玩家放弃推理，直接公布汤底 |

## 4. 游戏流程

### 4.1 整体状态机

```
[IDLE] ──/soup start──▶ [PREPARING] ──汤生成完成──▶ [PLAYING]
                             │                         │
                             │                         ├──玩家提问──▶ [判定] ──▶ [PLAYING]
                             │                         │
                             │                         ├──玩家宣告──▶ [宣告判定]
                             │                         │                │
                             │                         │           ┌────┴────┐
                             │                         │           ▼         ▼
                             │                         │       [WON]     [PLAYING]
                             │                         │
                             │                         ├──/soup giveup──▶ [LOST]
                             │                         │
                             │                         ├──超时/提问上限──▶ [TIMEOUT]
                             │                         │
                             │                         └──/soup quit──▶ [ABORTED]
                             │
                             └──生成失败重试 3 次──▶ [ERROR]

终态：WON / LOST / TIMEOUT / ABORTED / ERROR
```

### 4.2 详细步骤

**步骤 1：开局（PREPARING）**
1. 玩家在群里发 `/play turtle_soup`
2. Launcher 创建 `GameContext`，调用 `on_create`
3. `on_create`：
   - 调用 LLM（场景 `turtle_soup_host`）生成汤面 + 汤底
   - 也可以从内置题库随机抽取（见 §7）
   - 校验生成结果（JSON 格式、字段完整）
4. 调用 `on_start`：
   - 在群内发送汤面（图片 + 文字）
   - 提示玩家如何玩

**步骤 2：游戏中（PLAYING）**

玩家自由发言，`on_player_action` 处理。消息分类：

| 消息形式 | 识别规则 | 处理 |
|---|---|---|
| 问题 | 以 `?`/`？` 结尾 或 以 `问:`/`Q:` 开头 | 调用 LLM 判定 |
| 宣告 | 以 `汤底:`/`答案:`/`宣告:` 开头 | 调用 LLM 判定宣告是否正确 |
| 指令 | 以 `/soup` 开头 | 走指令处理 |
| 闲聊 | 其他 | 忽略（不消耗额度） |

**步骤 3：判定**
- 每次判定异步调用 LLM，期间允许其他玩家继续提问（并发）
- 判定结果统一用以下四档：
  - `是` / `不是` / `与此无关` / `关键线索（附加提示）`
- 累计提问数 +1

**步骤 4：结束**
- 宣告正确 → WON，播报完整汤底
- 投降 → LOST，公布汤底
- 提问数达上限（默认 50）→ TIMEOUT
- 整局超时（默认 60 分钟无活动）→ TIMEOUT
- `/soup quit` → ABORTED
- 内部错误（LLM 连续失败）→ ERROR，退款/不扣分

## 5. 指令集

| 指令 | 作用域 | 说明 |
|---|---|---|
| `/play turtle_soup` | 群 | 开局 |
| `@机器人 /提示` | 游戏中 | 花费金币购买一条方向性提示（每局限 3 次） |
| `@机器人 /状态` | 游戏中 | 查看已提问数 / 剩余时间 |
| `@机器人 /回顾` | 游戏中 | 回顾已问过的关键线索 |
| `@机器人 /烂题` | 局后 | 烂题淘汰（本局结束后短窗口内可用 |
| 投降/结束 | 游戏中 | 由 game_launcher 的 /结束 统一处理 |

## 6. LLM 设计

### 6.1 场景配置

```yaml
llm:
  scenes:
    turtle_soup_host:      # 出题
      model: <强模型>
      temperature: 0.9
      json_mode_default: true
    turtle_soup_judge:     # 判定提问
      model: <快且便宜>
      temperature: 0.1
      json_mode_default: true
    turtle_soup_claim:     # 判定宣告
      model: <中等>
      temperature: 0.2
      json_mode_default: true
```

### 6.2 Prompt 设计

所有 prompt 集中在 `prompts.py`，**版本化**（每次改动 bump 版本号）。

#### 6.2.1 出题 Prompt（`turtle_soup_host`）

> **v2.0 策略（2026-04 更新）**：category 和 difficulty 由代码层**随机指定**并注入 prompt，
> 不再由 LLM 自选，解决了旧版"几乎全是日常"的锚定问题。
> 同时移除了"禁止凶杀/自杀"之类的清单（内部群使用，LLM 自身已足够保守），
> 悬疑类**主动鼓励**凶案/失踪/复仇/出轨等成人向元素作为谜题内核，
> 奇幻类**强制要求**汤底用现实逻辑解释（禁止"真的是鬼"这种超自然答案）。

```
[System]
你是一位海龟汤（水平思考谜题）的出题者，擅长设计让人拍案叫绝的反转。

{category_guide}   # 4 张风格卡之一：日常 / 悬疑 / 温情 / 奇幻
{difficulty_guide} # 难度 1-5 对应的具体出题约束

【通用输出要求】
- 汤面（surface）：50-150 字，画面感强，必须有反常点
- 汤底（truth）：150-400 字，合理解释汤面所有异常；描写含蓄
- 关键线索（key_clues）：{clue_count} 条短语
- 人物与事件应为虚构，不涉及真实政治人物和宗教争议

只输出 JSON：
{
  "title": "...",
  "category": "{category}",
  "surface": "...",
  "truth": "...",
  "key_clues": [...],
  "difficulty": {difficulty}
}
```

**分类风格卡（定义在 `prompts.py::CATEGORY_STYLE_GUIDES`）**：

| 分类 | 核心 | 调性 | 可用素材 |
|---|---|---|---|
| 日常 | 生活反差 / 习惯 / 小秘密 | 轻松，会心一笑 | 家庭默契、职业秘密、邻里巧合 |
| 悬疑 | 诡异现象 + 意外合理的解释 | 紧张克制，含蓄留白 | 凶案、失踪、复仇、背叛、出轨、双面身份 |
| 温情 | 反常行为背后的情感 | 有后劲的暖意 / 酸楚 | 已故亲人、迟到的理解、长年默契 |
| 奇幻 | 看似超自然，实为现实解释 | 机智揭晓感 | 错觉、巧合、机械装置、心理作用、双胞胎 |

**难度指引（`prompts.py::DIFFICULTY_GUIDES`）**：难度 1-5 会被翻译为具体约束
（反常点数量、反转层数、预期问答轮数、线索条数），让 LLM 对难度有统一理解，而不是
自己模糊估一个 3。难度对应的 `clue_count` 为 `{1:3, 2:3, 3:4, 4:5, 5:6}`。

**生成入口**：`puzzle_service.py::_try_generate_via_llm` 会在每次调用前
`random.choice(CATEGORIES)` + `random.randint(1, 5)`，对 LLM 返回的 category/difficulty
做容错（若 LLM 改写成非法值，兜底回代码层指定值）。

#### 6.2.2 提问判定 Prompt（`turtle_soup_judge`）

```
[System]
你是海龟汤汤主，严格按以下规则回答玩家提问。

【汤面】{{surface}}
【汤底】{{truth}}
【关键线索】{{key_clues}}

玩家会提问是/否型问题，你必须回答四种之一：
- "yes": 问题陈述与汤底一致
- "no": 问题陈述与汤底矛盾
- "irrelevant": 问题与汤底无关（常见于玩家猜偏了）
- "key": 玩家问到了关键线索，除 yes/no 外附加提示

重要：
- 严禁透露汤底完整内容
- 若玩家问题包含猜测性的完整真相描述，应视为"宣告"而非提问，返回 "type": "claim_detected"
- 回答简洁，不添加解释（除非 key 类型附带 1 句提示）

玩家问题：{{question}}

输出 JSON：
{
  "type": "yes" | "no" | "irrelevant" | "key" | "claim_detected",
  "hint": "仅 key 类型时包含，1 句话提示"
}
```

#### 6.2.3 宣告判定 Prompt（`turtle_soup_claim`）

```
[System]
你是海龟汤汤主，判定玩家的宣告是否还原了汤底核心真相。

【汤底】{{truth}}
【关键线索】{{key_clues}}

玩家宣告：{{claim}}

判定标准：
- 核心真相（动机、主要因果、关键设定）准确 → correct
- 核心真相部分准确、关键要素缺失 → partial
- 完全偏离 → wrong

输出 JSON：
{
  "verdict": "correct" | "partial" | "wrong",
  "feedback": "1-2 句话反馈，correct 时简要点评，partial 时暗示缺失点，wrong 时鼓励继续"
}
```

### 6.3 成本控制

- **判定类调用**使用便宜模型（DeepSeek-chat 级别）
- **出题类**使用更强模型（一局一次，不心疼）
- 判定 prompt 中汤底只传一次，历史提问不累积到上下文（每次判定独立）
- 单局硬上限：50 次提问，超过强制结束

### 6.4 失败处理

| 失败场景 | 处理 |
|---|---|
| 出题 JSON 解析失败 | 重试最多 3 次，仍失败则用题库兜底 |
| 判定超时 | 向玩家回复"汤主思考中…"，重试 1 次 |
| 判定连续失败 3 次 | 结束游戏，标记 ERROR，不扣玩家分 |

## 7. 题库（兜底 + 冷启动）

**目的**：LLM 生成失败时的兜底；让首次体验更稳。

### 7.1 数据表

```python
class SoupPuzzle(Base):
    __tablename__ = "game_turtle_soup_puzzle"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    category: Mapped[str]
    surface: Mapped[str]
    truth: Mapped[str]
    key_clues: Mapped[list[str]] = mapped_column(JSON)
    source: Mapped[str]            # "builtin" | "llm_generated"
    difficulty: Mapped[int] = mapped_column(default=3)   # 1-5
    play_count: Mapped[int] = mapped_column(default=0)
    win_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime]
```

### 7.2 冷启动题库

项目首发附带 **20 道精选内置汤**（放 `seeds/turtle_soup.json`），首次启动 seed 到 DB。

### 7.3 出题策略

```
if 配置 prefer_llm:
    1. 尝试 LLM 生成
    2. 失败 → 随机抽题库
else:
    1. 70% 概率抽题库（按 play_count 反向加权，给冷门题机会）
    2. 30% 概率 LLM 生成
```

## 8. 对局数据记录

```python
class SoupSession(Base):
    __tablename__ = "game_turtle_soup_session"

    session_id: Mapped[str] = mapped_column(primary_key=True)
    puzzle_id: Mapped[int]
    group_id: Mapped[int]
    host_id: Mapped[int]
    players: Mapped[list[int]] = mapped_column(JSON)
    question_count: Mapped[int]
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    end_reason: Mapped[str | None]    # won/lost/timeout/aborted/error
    winner_id: Mapped[int | None]

class SoupQuestion(Base):
    __tablename__ = "game_turtle_soup_question"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str]
    asker_id: Mapped[int]
    question: Mapped[str]
    verdict: Mapped[str]              # yes/no/irrelevant/key
    hint: Mapped[str | None]
    asked_at: Mapped[datetime]
```

用途：战绩展示、题目质量分析、（未来）排行榜。

## 9. 配置项

```python
class TurtleSoupConfig(BaseSettings):
    # 游戏参数
    max_questions: int = 50
    session_timeout_minutes: int = 60
    idle_timeout_minutes: int = 15          # 15 分钟无人提问则结束

    # 出题
    prefer_llm_generation: bool = False     # 首发阶段优先题库
    llm_retry_times: int = 3

    # LLM
    judge_timeout_seconds: int = 30
    claim_timeout_seconds: int = 45

    # 奖励（可选，接入 economy）
    reward_coin_on_win: int = 100
    reward_score_on_win: int = 20
    reward_score_on_key_hit: int = 2
    reward_score_on_partial_hit: int = 1
    penalty_on_lose: int = 0              # 永远保持 0（不做负反馈）

    # 购买提示
    hint_cost_coin: int = 30              # 每次购买消耗 coin
    max_hints_per_game: int = 3           # 每局最多购买次数

    class Config:
        env_prefix = "GAME_TURTLE_SOUP_"
```

## 10. 边界情况

| 场景 | 处理 |
|---|---|
| 机器人重启（游戏中） | 从 `ctx.state` 恢复汤面/汤底/已提问数；继续 PLAYING |
| 同群并发开新局 | 拒绝："本群已有海龟汤进行中" |
| 玩家退群 | 若是唯一参与者，自动终止；否则忽略 |
| 判定返回非 JSON | 重试 1 次；仍失败则向玩家回复"汤主走神了，请再问一次" |
| 恶意刷屏提问 | `permission.rate_limit(per_minute=20)` 限制 |
| 玩家问到敏感话题 | LLM 本身会拒答，汤主层额外返回 irrelevant |
| 汤底被提前泄露到群（通过 key 提示过多） | 由 prompt 约束，hint 设计为指向性但不完整 |

## 11. 测试清单

**单元测试**：
- [ ] 消息分类正确（问题/宣告/闲聊/指令）
- [ ] 判定 JSON 解析鲁棒（容错换行、多余文字）
- [ ] 状态机转移合法（不会从 IDLE 直接到 PLAYING 等）

**集成测试**（用 LLM mock）：
- [ ] 完整赢局流程
- [ ] 投降流程
- [ ] 超时流程
- [ ] 玩家退出流程
- [ ] 重启后状态恢复

**人工测试**：
- [ ] 真实 LLM 出题质量 sanity check（10 局）
- [ ] 真实 LLM 判定准确率（标记 50 个问题人工对比）

## 12. 未来扩展（v2+）

- 真人出题模式（`/soup submit` 投稿）
- 难度分级与段位
- 多群联机汤（同一道汤不同群并行，比速度）
- LLM 对话式汤主（不仅判定，还会暖场、调侃）

## 13. 变更日志

| 版本 | 日期 | 变更 |
|---|---|---|
| 1.1 | 2026-05-06 | 新增 `/提示` 指令：花金币购买方向性提示（每局限 3 次，5 coin/次） |
| 1.0 | 2026-04-28 | 初版设计 |
