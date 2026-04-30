# 13 · CLI ↔ QQ Bot 一致性铁律

> **Status**: ACTIVE · **Last Updated**: 2026-04-30 · **Owner**: @JimyTD

> 💡 **只是想启动 CLI 看看？** 直接看 [`12-local-testing.md §0.5`](./12-local-testing.md)。
> 本文讲的是**为什么 CLI 和 Bot 必须对齐**（铁律与治理），不是使用指南。

---

## 核心原则

**`scripts/play_cli.py` 是"单人 QQ 群模拟器"**。

用户视角下：
- **CLI 能验证的 = QQ 群能表现的**
- **CLI 跑通 = 群里就能跑通**
- **CLI 和群里两处玩起来的"剧本"必须完全一致**

这条规则是项目级铁律，**贯穿所有游戏、所有功能开发**，**优先级高于其他设计考量**。

---

## 必须一致的内容 ✅

| 维度 | 说明 |
|---|---|
| **玩家决策点** | 游戏流程里需要玩家做选择的每一个分支 |
| **指令集** | 游戏中可用的所有指令（包括中文别名、英文别名） |
| **选项数量与顺序** | 比如开局时的"1. 快速开始 / 2. LLM 生成" |
| **游戏状态机** | 状态转移、进入/退出条件 |
| **触发规则** | 例如"? 结尾算提问"、"汤底: 开头算宣告" |
| **超时机制** | 多少秒/分钟超时、超时后果 |
| **判定逻辑** | 同样的输入应得到同样的 LLM 场景 + prompt |
| **反馈文案结构** | 同一类反馈用相同的行数、相同的 emoji、相同的字段 |
| **结算规则** | 胜/负/中断条件、金币奖励 |

---

## 允许不一致的内容 ⚠️

| 维度 | 说明 |
|---|---|
| **debug 输出** | CLI 可打印 `[debug] LLM raw: {...}`，群里不打 |
| **emoji / 颜色** | CLI 用 ANSI 颜色；群里用 emoji 分隔符。视觉表现不同但传达的信息等价 |
| **字符兼容** | Windows 终端 GBK 问题可能让某些 emoji 在 CLI 退化为文字 |
| **底层传输** | CLI 直接用 `input()`；QQ bot 走 NoneBot event。**机制不同，结果要同** |
| **@提及** | CLI 不需要 "@昵称"，群聊需要 |
| **消息多段 vs 单段** | CLI 可能一次 print 多行；bot 可能分多条消息发送（但内容一致） |

---

## 开发工作流

### 新增游戏

同时提交以下 2 份实现，任一缺失视为未完成：

1. **游戏本体**（bot 路径）：
   - `src/plugins/games/<game_id>/game.py` — GameBase 子类
   - `src/plugins/games/<game_id>/commands.py` — QQ 指令入口
   - `src/plugins/games/<game_id>/prompts.py` — LLM prompt
2. **CLI adapter**（CLI 路径）：
   - `scripts/cli_adapters/<game_id>.py` — 继承 `GameCLIAdapter`
   - 在 `scripts/play_cli.py` 的 `ADAPTERS` 注册表里加一行

两者的**玩家视角行为必须对齐**，底层可以不共享代码（但鼓励共享 prompts、判定函数、puzzle_service 等纯业务层，避免写两遍）。

### 改动游戏交互

当你改了**玩家能感知到的任何行为**时：

- [ ] `game.py` 改了？→ 检查 `cli_adapters/<game_id>.py` 是否要同步改
- [ ] `commands.py` 改了？→ 检查 CLI 的输入分类函数是否要同步改
- [ ] `prompts.py` 改了？→ 无需同步（两边引用同一份）
- [ ] 加了新指令别名？→ CLI 的 `_classify` 要加同样的分支
- [ ] 加了新结束原因？→ CLI 的结算分支要加同样的处理

### Code Review 关注点

审阅 PR 时：
- 有 `game.py` 改动但没 `cli_adapters/*.py` 改动 → ⚠️ 必问："为什么 CLI 不需要改？"
- 有新 `/xxx` 指令但 CLI 里没等效实现 → ⚠️ 必改
- "以后再加到 CLI 里" → ❌ **拒绝**，必须同一 PR 完成

---

## 为什么这么严格

1. **CLI 是你的主要调试工具**。不一致的 CLI 调试出来的效果 ≠ 群里真实效果，测试失去意义
2. **避免"CLI 一切正常但群里表现不一样"的长尾 bug**。这类 bug 极难复现（需要 NapCat + QQ 号 + 群）
3. **保持心智模型统一**。开发者写代码时不用区分"CLI 路径"和"bot 路径"在做什么事
4. **方便迭代速度**。改动在 CLI 快速验证后，上群几乎必过

---

## 当前已知差异（允许）

截至 2026-04-29：

| 差异项 | CLI 表现 | Bot 表现 | 性质 |
|---|---|---|---|
| 输入触发方式 | 直接 `input()` 读文字 | 群内需 `@机器人 + 内容`（选择态） | 机制差异（不违反铁律） |
| 前缀 | 无需 `/` | 指令需 `/` 开头 | 机制差异 |
| Debug 输出 | CLI 可打印 `[debug]` | 群里不打 | 调试支持差异（允许） |

## 当前已对齐的流程

- **启动流程**：两端都是 "选游戏 → 选模式 → 开局" 两层交互
- **参数跳过**：CLI `python play_cli.py turtle_soup library` = Bot `/开始 turtle_soup library`
- **开局模式**：由 `GameBase.MODES` 类属性声明，CLI 和 bot 共享同一份权威清单
- **超时**：选择态 60 秒超时自动取消（CLI 走 `input()` 没超时，不需要）
- **全局结束**：CLI `quit` = Bot `/结束`，都能退出任何状态回到主菜单

对齐任务跟踪见 `docs/10-roadmap.md`。

---

## 检查清单（开发者自测）

提交任何游戏相关改动前，逐项打勾：

- [ ] CLI 里能玩一遍完整流程（胜/负/中断）
- [ ] CLI 里所有指令都按预期工作（帮助、状态、回顾、投降、退出）
- [ ] CLI 里的 emoji/文案和群里 broadcast 的内容一致（可对比 `render.*` 的调用）
- [ ] CLI 里每个分支对应 bot 里同样的分支（用同一套 prompt 场景）
- [ ] 超时、LLM 异常、重试等边界在 CLI 里都能复现

---

## 附：相关文档

- `docs/04-game-development.md` — 新增游戏指南（含 CLI adapter 章节）
- `docs/09-conventions.md` — 编码规范（包含 CLI-bot 一致性要求）
- `scripts/cli_adapters/base.py` — CLI adapter 协议定义
