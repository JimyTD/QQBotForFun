# 趣味问答（Trivia）

**Game ID**: `trivia`

听线索猜答案的轻量群游戏。6 种类型，LLM 实时生成题目，10 题一局自动结算。

## 玩法

```
/开始 trivia              → 引导选类型
/开始 trivia country       → 直接开 "猜国家" 局
/开始 trivia 猜城市        → 中文名也认
```

每题 bot 先给 1 条最隐晦的线索，玩家自由作答：

- **直接说答案** → 匹配成功就得分（+15/+10/+5 按线索数）
- **发 "线索"** → 追加下一条线索（1→5 条）
- **发 "跳过"** → 放弃这题看答案

10 题答完自动结算，本局第一额外 +20 分。所有得分入 `economy.score`，可用 `/榜` 查全局榜。

## 类型

| ID | 名称 | 说明 |
|---|---|---|
| `country` | 🌍 猜国家 | 世界主权国家 |
| `city` | 🏙 猜城市 | 世界知名城市 |
| `food` | 🍜 猜美食 | 中外菜品 / 甜品 |
| `person` | 👤 猜人物 | 真人 + 全民知名虚构角色 |
| `animal` | 🐾 猜动物 | 真实存在的动物 |
| `idiom` | 📚 猜成语 | 有典故的成语 |

## 指令

| 指令 | 作用 |
|---|---|
| `/开始 trivia [type]` | 开局（type 可留空走引导） |
| `线索` / `再来一条` | 追加一条线索 |
| `跳过` / `不会` | 跳过本题 |
| 直接发言 | 作答 |
| `/问答 状态` | 进度 + 本局榜 |
| `/问答 结束` | 提前结束 |

## 判定

**不走 LLM，纯代码字符串宽松匹配**：

- 归一化：NFKC、转小写、繁→简、去空格和标点
- answer 或任一 alias 是玩家消息的子串 → 命中
- 废话词兜底（"是不是 X 啊" → 剥掉废话再匹配一次）

## 配置

环境变量前缀 `GAME_TRIVIA_`，可调项见 `config.py`。

## 架构说明

```
trivia/
├─ __init__.py              插件入口
├─ config.py                配置
├─ prompts.py               6 类风格卡 + 出题 prompt
├─ answer_matcher.py        归一化 + 宽松匹配
├─ puzzle_generator.py      LLM 调用 + 业务自检
├─ game.py                  GameBase 主逻辑
└─ commands.py              /问答 子命令
```

没有 models.py —— 本游戏不持久化题目，只有结算时把 score 写入 `core.economy`。

## 与 CLI 对齐

`scripts/cli_adapters/trivia.py` 是本游戏的 CLI 版本，**与 bot 共享**：
- `GameBase.MODES`（类型清单）
- `prompts.py`（出题逻辑）
- `answer_matcher.py`（判定逻辑）
- `puzzle_generator.py`（生成+自检）

详见 `docs/13-cli-bot-parity.md`。
