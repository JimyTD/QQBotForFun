# 深海任务 · 战役模式调研报告

> 调研日期：2026-08-31
> 游戏 ID：`deep_sea_mission`
> 原型桌游：The Crew: Mission Deep Sea（KOSMOS / Thames & Kosmos，2021）

## ✅ 实现状态（2026-08-31）

本文档调研结论已落地为代码：

- **数据层**：`src/plugins/games/deep_sea_mission/campaign.py` —— 32 关 + Epilogue、6 类符号常量、5 类任务分配规则、`get_mission` / `fixed_tasks_m32` / `parse_campaign_progress`。
- **玩法引擎**：`game.py` 按 `ctx.config["mode"]` 分支（`mission` 走原有逻辑，`campaign` 查表注入）。声呐系统支持 `normal / currents / rapture / silence` 四态；`MOD_REALTIME` 按「不计时走括号内替代规则」处理（面板提示，不做真实倒计时）。
- **进度持久化**：`group_config` key `deep_sea_mission.campaign.level`，通关 +1、失败不推进、M32 后进 Epilogue（难度 18 起步 +1）。
- **传牌**：`MOD_DISTRESS` 无固定关卡，实现为选任务阶段可触发（`@我 求救` → 每人 `@我 传 X` 传给左邻，禁传潜艇）。
- **入口**：`@我 深海战役`（读进度）或 `@我 深海战役 N`（显式指定关卡，调试/回退）；CLI adapter 同步支持 `campaign` 模式。
- **无难度关**（M8/12/21/23/27）：无任务卡直接出牌，出牌结束自动提示约束校验结果，宣告胜利时硬校验。

## 一、现状（代码层面）

`src/plugins/games/deep_sea_mission/` 目前实现的是**「任务难度」模式**，不是战役模式：

- 开局命令 `@机器人 深海任务 <难度>`，随机抽任务卡凑到目标总难度（`tasks.py :: draw_tasks`）。
- 96 张任务卡 `T001–T096` 已完整录入（`tasks.py :: TASK_CARDS`），与官方 96 张任务卡一一对应。
- 出牌 / 吃墩 / 声呐 / 手动结算均已实现。
- **暂未实现**（`README.md` 自述）：任务自动判定、求救信号传牌、特殊关卡符号。

即：现有玩法是「自由选难度 + 随机任务」，缺少官方「按 32 个战役关卡推进」的结构。

## 二、战役模式是什么

官方战役是**一本独立 Logbook（航海日志）**，含 **32 个任务**（Mission 1–32），剧情从「船长 Meg Diver 率队潜入深海寻找姆大陆」逐关推进。每个任务有：

1. **固定难度值**（life preserver 符号里的数字 = 需凑齐的任务卡总难度，对应现有 `draw_tasks` 的 `target_difficulty`）。
2. **一组特殊规则符号**（见第三节）。
3. 通关后还有 **Epilogue 无限模式**（从难度 18 起每关 +1，自由选任务）。

注意：**32 是 Deep Sea 的关卡数**（初代《The Crew: Quest for Planet Nine》是 50 关），别混淆。

## 三、特殊规则符号系统（6 类，扩展必须支持）

| 符号 | 名称 | 规则 |
|---|---|---|
| ❓ | Currents（水流 / 通信中断） | 可用卡交流，但**不放声呐标记**，队友只能猜 |
| -2 | Rapture of the Deep（深海狂喜） | 声呐标记 = 人数 − 2，放桌中央**全队共享** |
| 🔴 1-9 | Unfamiliar Terrain（陌生地形） | 发牌前随机抽 1 张颜色卡：1–3 正常 / 4–6 走 Currents / 7–9 走 Rapture |
| 🕒 | Real-time（限时） | 限时完成；不计时则走括号内替代规则 |
| 🐙 | Free Selection（自由选任务） | 可自由讨论任务分配（仍不得透露手牌） |
| ⚓ | Distress Signal（求救信号） | 开局全队**传 1 张牌**给邻居（不能传潜艇），本关尝试数 +1 |

## 四、32 个战役任务清单

> 已三方交叉核对定稿：①官方 Logbook 图片 PDF 逐页 OCR（`The_Crew_Mission_Deep_Sea.Logbook.en.pdf`，24 页）；②官方英文 Logbook 文本（64ouncegames）；③粉丝任务速查表 v1d（David Fox, 2024）。
> 难度列「无」＝官方 logbook 里该关**没有难度数字**（符号位置直接显示特殊规则），非提取缺失。

| 关卡 | 难度(任务卡总分) | 特殊规则 |
|---|---|---|
| 1 | 1 | — |
| 2 | 2 | — |
| 3 | 3 | — |
| 4 | 4 | — |
| 5 | 5 | — |
| 6 | 5 | 所有任务给**一名**船员 |
| 7 | 6 | — |
| 8 | 无 | 不得有玩家比其他玩家多赢 2 张 9 |
| 9 | 7 | ❓ Currents |
| 10 | 4 | 队长拿全部任务；若分出去，则首墩前完成全部交流 |
| 11 | 8 | -2 Rapture of the Deep |
| 12 | 无 | 不得用粉牌或潜艇开墩 |
| 13 | 5 | 队长拿全部任务；若分出去，则首墩前完成全部交流 |
| 14 | 6 | 一人自荐包揽全部任务；🕒 3:30，否则 ❓ |
| 15 | 6 | 一人自荐包揽全部任务；🕒 3:00，否则 -2 |
| 16 | 6 | 一人自荐包揽全部任务；🕒 2:30，否则禁止交流 |
| 17 | 9 | 🐙 Free Selection |
| 18 | 9 | — |
| 19 | 9 | 最难任务给队长 |
| 20 | 10 | 🔴 Unfamiliar Terrain |
| 21 | 无 | 🔴 + 不得有玩家比其他玩家多赢 2 张 1 |
| 22 | 11 | 🔴 |
| 23 | 无 | 🔴 + 赢首墩者须始终领先赢墩数 + 第二墩前禁止交流 |
| 24 | 12 | 🔴 |
| 25 | 12 | 🔴 + 队长不接任务 |
| 26 | 10 或 12 | 两人自荐包揽；🕒 5:00（10 tasks），不计时则 12 tasks |
| 27 | 无 | 🔴 + 黄 5 须作为最后一墩的最后一张牌 |
| 28 | 14 | 🐙 Free Selection |
| 29 | 15 | 🐙 Free Selection |
| 30 | 16 | 🐙 Free Selection |
| 31 | 17 | 🐙 Free Selection |
| 32 | 固定任务 | 不抽卡，固定 4 张任务：赢 0 墩 / 恰好连赢 3 墩 / 连赢 2 墩 / 赢首末墩 |

**Epilogue**：通关后无限模式——难度 18 起步，每过一关 +1，🐙 自由选任务，记录是否用过 ⚓。

### 关于「难度＝无」的 5 关（M8 / M12 / M21 / M23 / M27）

官方 logbook 中这 5 关的难度符号位置**没有数字**，直接印特殊规则（M8「never two 9」、M12「no pink/sub opening」、M21/M23/M27「Unfamiliar Terrain 图例 + 附加约束」）。三方来源一致，BGG 亦有专门帖子询问「M8/M12 的目标是什么」，印证这两关无常规任务卡总数。

> 实现提示：这 5 关不能用现有 `draw_tasks(target_difficulty)` 直接套用，需在 `campaign.py` 中标记 `difficulty=None` + 独立特殊规则，任务分配与胜利判定走单独分支（详见第五节）。

## 五、与现有实现的差距（扩展需要改什么）

1. **难度来源**：现在难度是玩家手输的任意整数 → 战役模式下改为「关卡号查表取固定难度」。注意 M8/M12/M21/M23/M27 这 5 关**无难度数字**，需标记 `difficulty=None` 并走独立胜利判定，不能套 `draw_tasks`。
2. **特殊符号**：6 类符号目前全部未实现，需新增每关的 `modifiers` 字段并落到状态机。
3. **任务分配特殊规则**：M6/M10/M13（队长包揽）、M14/M15/M16（**一人自荐**包揽）、M25（队长不接）、M26（**两人自荐**包揽）、M32（固定任务卡）需覆盖现有 `_advance_selector` 的「轮流选」逻辑。
4. **求救信号传牌**：现有 README 已列为 TODO，战役模式必须补上（开局邻座传 1 张、禁传潜艇）。
5. **关卡通进度**：需要持久化「队伍打到第几关」（类似 `group_config` 或新表），支持断点续打。

## 六、建议的扩展方案（供后续设计）

- 新增 `GameMode(id="campaign")`，与现有 `mission` 模式并存。
- 数据层新增 `src/plugins/games/deep_sea_mission/campaign.py`，存 32 关的 `{no, difficulty, modifiers[]}` 表 + Epilogue 规则。
- 状态机 `game.py` 按 `ctx.config["mode"]` 分支：`mission` 走现有逻辑，`campaign` 注入关卡难度 + modifiers。
- CLI 侧 `scripts/cli_adapters/deep_sea_mission.py` 同步（CLI↔Bot 一致性铁律）。
- 关卡进度建议存 `group_config`（新增 key 如 `deep_sea_campaign_level`），避免新表迁移。

## 七、数据来源

- 官方规则书 PDF：`https://cdn.1j1ju.com/medias/e3/06/41-the-crew-mission-deep-sea-rulebook.pdf`
- 官方英文 Logbook 文本：`https://www.64ouncegames.com/pages/the-crew-mission-deep-sea`
- Logbook 图片 PDF（逐页 OCR 核对）：`https://c.tabletopia.com/games/mission-deep-sea/rules/logbook/en`
- 粉丝任务速查表 v1d（David Fox, 2024，本地 `Downloads/The_Crew_2_Mission_Sheet_v1d.pdf`）：补齐并纠正了 M3/M4/M14/M15/M16/M26 及 5 个「无难度」关卡的数值
- 中文规则速查：`https://ahchao.github.io/boardgame-rule-manual/the-crew-deep-sea-rules/`
