# 游戏设计文档 · 趣味问答（Trivia）

- **Game ID**: `trivia`
- **Status**: Design v1
- **Last Updated**: 2026-04-30
- **Owner**: @owner
- **Version**: 1.0（LLM 实时生成线索题）

---

## 1. 玩法简介

**趣味问答** 是一个"听线索猜答案"的轻量抢答游戏：

- Bot 选定类型（猜国家 / 城市 / 美食 / 人物 / 动物 / 成语）
- 每题给出 **5 条递进线索**（从最隐晦到最直白）
- 玩家在群里自由发言作答，**谁先答对得分**
- 想要更多线索就发"线索"，卡住就发"跳过"
- **共 10 题**，每题结算后自动出下一题；10 题答完自动结算

设计目标：
- **节奏轻松**：没有倒计时，群友随时参与
- **门槛低**：常识题为主，涉及的都是家喻户晓的东西
- **可持续**：LLM 生成题目，题库无限，不会重复

## 2. 范围与不做什么

### v1.0 **做**
- ✅ 6 个固定类型（国家 / 城市 / 美食 / 人物 / 动物 / 成语）
- ✅ LLM 实时生成题目（含答案、2-5 个别名、5 条线索、讲解）
- ✅ 字符串宽松匹配判定答案（不调 LLM，即时响应）
- ✅ 玩家指令：`线索` / `跳过` / `/问答 状态` / `/问答 结束`
- ✅ 每题结算展示本局 TOP 3
- ✅ 答对按"第几条线索命中"分档得分（15 / 10 / 5）
- ✅ 10 题自动结束 + MVP +20 分
- ✅ 结算入 `economy.score`，支持 `/榜` 查全局榜
- ✅ 答错每次都回应

### v1.0 **不做**（未来 v2+）
- ❌ 预置题库（纯 LLM 生成，零维护）
- ❌ 烂题淘汰机制（题目不持久化，烂题就当乐子翻篇）
- ❌ 持久化题目记录（只记总得分到 economy.score）
- ❌ 每类自定义题数（所有类型都 10 题）
- ❌ 倒计时 / 抢答时限
- ❌ 私聊出题 / 多群联机
- ❌ 难度分级

## 3. 术语

| 术语 | 含义 |
|---|---|
| 类型（type） | 猜国家 / 城市 / 美食 / 人物 / 动物 / 成语 之一 |
| 题目（puzzle） | 一个答案 + 别名列表 + 5 条线索 + 讲解 |
| 线索（clue） | 描述答案特征的单句，难度递减（第 1 条最隐晦） |
| 归一化（normalize） | 判定答案前对用户文本的预处理：去空格、转小写、繁→简 |
| MVP | 本局得分最高的玩家（并列时均为 MVP） |

## 4. 游戏流程

### 4.1 整体状态机

```
[IDLE] ──/开始 trivia [type]──▶ [PREPARING] ──第 1 题生成完成──▶ [PLAYING]
                                     │                             │
                                     │                             ├──玩家答对──▶ [结算本题] ──▶ [PREPARING 下一题]
                                     │                             │
                                     │                             ├──玩家答错──▶ 回应"不对" ──▶ [PLAYING]
                                     │                             │
                                     │                             ├──「线索」──▶ 追加一条 ──▶ [PLAYING]
                                     │                             │
                                     │                             ├──「跳过」──▶ 公布答案 ──▶ [PREPARING 下一题]
                                     │                             │
                                     │                             ├──10 题答完──▶ [SETTLING]
                                     │                             │
                                     │                             ├──整局超时──▶ [TIMEOUT]
                                     │                             │
                                     │                             └──/问答 结束 / /结束──▶ [ABORTED]
                                     │
                                     └──生成失败重试 3 次──▶ 跳过本题 / [ERROR]

终态：COMPLETED / ABORTED / TIMEOUT / ERROR
```

### 4.2 详细步骤

**步骤 1：开局（PREPARING）**
1. 玩家发 `/开始 trivia` 或 `/开始 trivia 猜国家`
2. Launcher 创建 `GameContext`，调用 `on_create`
3. `on_create`：
   - 从 `ctx.config["mode"]` 读取类型；若无则走 launcher 的模式选择流程
   - 初始化 `ctx.state`：`type` / `total=10` / `current_index=0` / `scores={}` / `history=[]`
   - 调用 `_generate_next_puzzle` 生成第 1 题（失败 3 次重试，仍失败则 ERROR 结束）

**步骤 2：每题流程（PLAYING）**

玩家自由发言，`on_player_action` 分类处理：

| 消息形式 | 识别规则 | 处理 |
|---|---|---|
| 控制词 | 消息归一化后属于 `{线索, 再来一条, 更多线索}` | 追加下一条线索 |
| 控制词 | 消息归一化后属于 `{跳过, 不会, pass}` | 公布答案并进入下一题 |
| 作答 | 其他非空短文本（≤40 字） | 走答案匹配 |
| 闲聊 | 其他 | 忽略 |

**步骤 3：答案匹配**（不调 LLM）

```python
def match(user_text: str, answer: str, aliases: list[str]) -> bool:
    norm = normalize(user_text)
    for c in [answer, *aliases]:
        if normalize(c) in norm:
            return True
    return False

# normalize：全角→半角、去空格、大小写统一、繁→简、常见标点剔除
```

- 答对 → 按"当前已展示线索数"分档：1 条 +15 / 2-3 条 +10 / 4-5 条 +5
- 答错 → 回应 `❌ @某人 不对哦`

**步骤 4：每题结算**

- 答对：宣告胜者 + 加分 + 展示讲解（`explanation`） + 本局 TOP 3
- 跳过/无人答出：公布答案 + 讲解（该题 0 分） + 本局 TOP 3
- 进入下一题（调用 `_generate_next_puzzle`）

**步骤 5：整局结算（第 10 题结束后）**

- 计算 MVP（本局最高分，并列全给）
- MVP 额外 +20 分
- 每位有得分的玩家：`economy.add(qq_id, 本局总分, currency="score")`
- 展示最终榜单 + "发送 /榜 查看全服排名"提示
- 结束游戏

## 5. 指令集

| 指令 | 作用域 | 说明 |
|---|---|---|
| `/开始 trivia` | 群 | 开局，引导选类型 |
| `/开始 trivia <type>` | 群 | 指定类型直接开局（type = 类型 id 或编号或中文名） |
| `/问答 状态` | 游戏中 | 查看进度 / 本局榜 |
| `/问答 结束` | 游戏中 | 提前结束并结算已得分 |
| `/结束` | 游戏中 | 同"/问答 结束"（走 launcher 统一入口） |
| `线索` / `再来一条` / `更多线索` | 游戏中 | 追加一条线索（不占分档也不扣分，但会降低下次答对的分档） |
| `跳过` / `不会` / `pass` | 游戏中 | 跳过本题，公布答案 |

## 6. 类型清单

| ID | 名称 | 说明 | 线索角度 |
|---|---|---|---|
| `country` | 🌍 猜国家 | 世界各国 | 地理 / 国旗 / 标志物 / 语言 / 首都 |
| `city` | 🏙 猜城市 | 世界著名城市 | 地标 / 气候 / 历史 / 美食 / 所属国 |
| `food` | 🍜 猜美食 | 中外菜品 / 甜品 / 饮品 | 产地 / 主料 / 口味 / 典故 / 外观 |
| `person` | 👤 猜人物 | **真人 + 全民知名虚构**（神话/经典文学，禁现代动漫游戏 IP） | 成就 / 年代 / 作品 / 标志事迹 |
| `animal` | 🐾 猜动物 | 真实存在的动物 | 特征 / 习性 / 栖息地 / 食性 / 冷知识 |
| `idiom` | 📚 猜成语 | **有典故/有故事的成语**（禁纯描述性成语如"一丝不苟"） | 出处 / 主角 / 故事情节 / 字义 / 寓意 |

**人物边界约定**：
- ✅ 可出：真实人物（爱因斯坦、乔布斯、李白、鲁迅…）
- ✅ 可出：全民知名的虚构（孙悟空、林黛玉、福尔摩斯、哈利·波特、雅典娜）
- ❌ 不可出：现代动漫/游戏/网文角色（路飞、皮卡丘、原神角色等）
- ❌ 不可出：在世的争议政治人物

**成语边界约定**：
- ✅ 有故事/典故：完璧归赵、刻舟求剑、画蛇添足、揠苗助长、守株待兔…
- ❌ 纯描述性：一丝不苟、根深蒂固、井井有条（没典故可说）

## 7. 题目结构

LLM 输出 JSON：

```json
{
  "answer": "加拿大",
  "aliases": ["Canada", "枫叶国"],
  "clues": [
    "它曾是英国和法国的殖民地，独立史与两大宗主国相关",
    "它的国歌名为《O Canada》",
    "被称为\"枫叶之国\"，国旗上有一片红色枫叶",
    "是世界上面积第二大的国家",
    "首都是渥太华，最大城市是多伦多"
  ],
  "explanation": "面积约 998 万平方公里，仅次于俄罗斯。官方语言英语和法语。"
}
```

**字段约束**：
- `answer`：3-15 字；必须是"明确、唯一"的答案
- `aliases`：2-5 个，常见别名/英文名/简称；**不得与 answer 完全相同**
- `clues`：**固定 5 条**，按"从难到易"排列（第 1 条最隐晦，第 5 条几乎是送分）
- `explanation`：一句话讲解（20-60 字），答对或跳过后展示

**生成期代码自检**（见 §11 自检清单）：
- `answer` 是否出现在任何 `clues` 里 → 是则重试
- `aliases` 是否为空 → 空则重试
- `clues` 长度是否为 5 → 不是则重试

## 8. Prompt 版本

| 场景 | 版本 | 说明 |
|---|---|---|
| `trivia_host` | 1.0 | 出题，接收 `type` 参数，由代码层从 `TYPE_STYLE_GUIDES` 取对应风格卡注入 |

每个 type 对应一张风格卡（见 `prompts.py::TYPE_STYLE_GUIDES`），职责：
- 限定答案范围（比如"成语必须有典故"）
- 约束线索风格（比如"猜国家从地理/文化入手，不要直接给国名首字母"）
- 提示 LLM 给合适的别名（比如"猜城市要给中英文名"）

## 9. 配置项

```python
class TriviaConfig(BaseSettings):
    total_questions_per_game: int = 10      # 每局题数
    max_clues_per_puzzle: int = 5           # 每题线索数（= prompt 里的固定值）
    session_timeout_minutes: int = 30       # 整局无活动超时
    llm_retry_times: int = 3                # 单题生成重试次数
    generator_timeout_seconds: int = 20     # 单次出题 LLM 调用超时

    # 计分（score 入全局榜，2026-04-30 v1.2 校准对齐海龟汤）
    score_tier_1_clue: int = 5
    score_tier_2_3_clue: int = 3
    score_tier_4_5_clue: int = 1
    mvp_score_bonus: int = 10

    # 金币奖励（coin 进钱包）
    coin_tier_1_clue: int = 3
    coin_tier_2_3_clue: int = 2
    coin_tier_4_5_clue: int = 1
    mvp_coin_bonus: int = 30

    # 作答长度上限（超过这个长度一律视为闲聊）
    max_answer_length: int = 40
```

环境变量前缀：`GAME_TRIVIA_`

## 10. 状态结构（ctx.state）

```python
{
    "type": "country",             # 类型 id
    "total": 10,                   # 本局题数
    "current_index": 3,            # 当前是第几题（0-based）
    "current_puzzle": {            # 当前题目
        "answer": "加拿大",
        "aliases": ["Canada", "枫叶国"],
        "clues": [...],            # 5 条
        "explanation": "..."
    },
    "clues_shown": 2,              # 当前题已展示线索数（初始 1）
    "scores": {                    # qq_id → 本局 score 累计（进排行榜）
        123456: 25,
        789012: 10
    },
    "coins": {                     # qq_id → 本局 coin 累计（进钱包）
        123456: 5,
        789012: 2
    },
    "history": [                   # 每题的记录，用于局末回顾
        {
            "answer": "日本",
            "winner": 123456,
            "clues_used": 2,
            "awarded": 10
        },
        {
            "answer": "伊斯坦布尔",
            "winner": None,         # 跳过
            "clues_used": 5,
            "awarded": 0
        }
    ],
    "last_activity_ts": "2026-04-30T12:00:00"
}
```

**不持久化题目到 DB**（v1 决策）。只有结算时把本局总分写入 `economy`。

## 11. LLM 生成期自检清单

代码层对 LLM 输出做三道闸：

1. **JSON 格式** → `LLMJSONParseError` 时按 `llm_retry_times` 重试
2. **字段齐全** → `answer` `aliases` `clues` `explanation` 任一缺失或类型错 → 重试
3. **业务校验**：
   - `len(clues) == 5` → 否则重试
   - `answer` 不出现在任何 `clues` 里（normalized） → 否则重试
   - `aliases` 非空且不含与 `answer` 完全相同的项
   - `len(answer) <= 20`
4. 连续失败达到上限 → 该题**跳过并记 0 分**（不中断整局），展示 `⚠️ 这题出题失败，跳过`

## 12. 计分与奖励

双轨制：`score`（进全局榜）+ `coin`（进钱包）。

**设计原则**：和海龟汤的产出基准对齐 —— 海龟汤一局赢 20 score，
趣味问答一局（10 题）理论最大 60 score ≈ 3x 海龟汤，体现知识面广的正向奖励
但不至于碾压榜单；平均水平（答对 6 题）约 28 score，与海龟汤接近。

coin 单价较低，避免问答成为"刷金币捷径"——单位时间产出约 170 coin/小时，
和海龟汤持平。

| 事件 | score | coin |
|---|---|---|
| 第 1 条线索内答对 | +5 | +3 |
| 第 2-3 条线索内答对 | +3 | +2 |
| 第 4-5 条线索内答对 | +1 | +1 |
| 跳过 / 无人答对 | 0 | 0 |
| 局末 MVP（本局 score 最高） | 额外 +10 | 额外 +30 |

并列 MVP 全给（所有并列者都拿 bonus）。

**结算入账**（使用 `core.game_base.GameBase.award` 统一接口）：

```python
# score 入排行榜
await self.award(qq, score_total,
                 reason=f"trivia_{type}:{session_id}",
                 currency="score")
# coin 入钱包
await self.award(qq, coin_total,
                 reason=f"trivia_{type}:{session_id}",
                 currency="coin")
```

`GameBase.award` 保证"及时正反馈"：`amount <= 0` 静默跳过、经济异常不阻塞游戏主线。

## 13. 与 CLI 的一致性（铁律）

- `scripts/cli_adapters/trivia.py` 与本游戏共享 `GameBase.MODES` 与 `prompts.py`
- CLI 单人玩：一局 10 题、同样的类型列表、同样的作答判定、同样的分档
- CLI 的差异仅在于 I/O 层：`print` 替代 `session.broadcast`、`input` 替代 `on_player_action`
- CLI 无积分榜入账（`economy.score` 在 CLI 下也可走，但 CLI `qq_id=0` 不参与群榜）

详见 `docs/13-cli-bot-parity.md`。

## 14. 变更日志

| 版本 | 日期 | 变更 |
|---|---|---|
| 1.0 | 2026-04-30 | 初版：6 类线索题、纯 LLM 生成、字符串宽松匹配、10 题自动结算、入 score 货币 |
| 1.1 | 2026-04-30 | 接入 `GameBase.award` 统一奖励接口；新增双轨金币奖励（coin 3/2/1 + MVP 30），与海龟汤单位时间产出对齐 |
| 1.2 | 2026-04-30 | **score 大幅下调对齐海龟汤**：5/3/1 + MVP 10（原 15/10/5 + MVP 20）。海龟汤赢一局 20 分是基准，问答 10 题全对理论上限 60 分 ≈ 3x 海龟汤，平均 6 题 ≈ 28 分与之接近，不碾压榜单。coin 不变。 |
