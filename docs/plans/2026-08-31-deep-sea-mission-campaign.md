# 深海任务 · 战役模式 Implementation Plan

> **Status**: Draft · **Date**: 2026-08-31 · **Owner**: @JimyTD
> 调研依据：`docs/games/deep-sea-mission-campaign.md`（32 关数据已三方核对定稿）

**Goal:** 在 `deep_sea_mission` 游戏里新增「战役模式」，按官方 Logbook 32 关 + Epilogue 推进：关卡查表注入难度、6 类特殊符号、任务分配特殊规则、5 个无难度关、求救信号传牌、关卡进度持久化。与现有「任务难度」模式并存，CLI 与 Bot 保持 1:1 对齐（项目铁律 13）。

**Architecture:** 数据层独立为 `campaign.py`（32 关 + Epilogue 规则，纯数据 + 查询）；`game.py` 通过 `ctx.config["mode"]` 分支（`mission` 走现有逻辑，`campaign` 注入关卡）；声呐系统改造以支持沟通符号；关卡进度存 `group_config`（不建新表）。入口新增 `@我 深海战役` 命令，与 `@我 深海任务 N` 并存。

**Tech Stack:** Python 3.12, asyncio, NoneBot2，复用现有 `cards.py` / `tasks.py` / `render` / `session` / `scheduler`。

---

## 关键设计决策（已与用户确认）

| 决策 | 结论 |
|---|---|
| 实现范围 | **完整一次做完**（32 关 + 6 类符号 + 5 个无难度关 + 传牌 + 进度，一个大 PR） |
| 进度模型 | 每群只存一个「当前待挑战关卡号」到 `group_config`；**每次开局 = 打一整关**，通关后 +1；**不存牌局中途状态**（中途退出/失败不推进、不回溯） |
| 入口命令 | 新增 `@我 深海战役`（alias：`deep_sea_campaign` / `战役`），与 `@我 深海任务 N` 并存、互不干扰 |
| Real-time 限时 | 采用规则书「不计时则走括号内替代规则」：面板提示限时 + 默认走替代规则，**不做真实倒计时**（QQ 群场景体验差，且规则书明确允许） |
| Epilogue | 通关 M32 后进入无限模式：难度 18 起步每关 +1、🐙 自由选任务。**⚓ 使用记录/最终计分简化为面板提示，不做计分系统** |
| 无难度关判定 | 机器人在出牌结束后**自动校验**约束（M8/M12/M21/M23/M27 的可判定部分），但最终胜负仍由玩家 `@我 胜利 / 失败` 确认（沿用现有手动结算机制） |

---

### Task 1: campaign.py — 战役数据层

**Files:**
- Create: `src/plugins/games/deep_sea_mission/campaign.py`

**说明：** 纯数据 + 查询，不 import 任何 NoneBot / session / game 逻辑，可被 game.py 与 CLI adapter 复用。32 关数据直接抄 `docs/games/deep-sea-mission-campaign.md` §四（已核对定稿）。

**数据结构：**

```python
from dataclasses import dataclass

# 沟通符号（modifiers）
MOD_CURRENTS = "currents"        # ❓ 通信中断
MOD_RAPTURE = "rapture"          # -2 声呐全队共享
MOD_UNFAMILIAR = "unfamiliar"    # 🔴 发牌前抽颜色卡
MOD_REALTIME = "realtime"        # 🕒 限时（面板提示 + 替代规则）
MOD_FREE_SELECTION = "free_selection"  # 🐙 自由选任务
MOD_DISTRESS = "distress"        # ⚓ 求救信号传牌

# 任务分配规则（assignment）
ASG_ALL_ONE_CREW = "all_one_crew"       # M6：所有任务给一名船员
ASG_CAPTAIN_ALL = "captain_all"         # M10/M13：队长拿全部任务
ASG_SELF_NOMINATE_1 = "self_nominate_1" # M14/15/16：一人自荐包揽
ASG_HARDEST_TO_CAPTAIN = "hardest_to_captain"  # M19：最难任务给队长
ASG_CAPTAIN_NO_TASK = "captain_no_task" # M25：队长不接任务
ASG_SELF_NOMINATE_2 = "self_nominate_2" # M26：两人自荐包揽

@dataclass(frozen=True)
class Mission:
    no: int
    difficulty: int | None = None   # None = 无难度数字（M8/12/21/23/27/32）
    modifiers: tuple[str, ...] = ()
    assignment: str | None = None   # None = 现有轮流选
    task_source: str = "draw"       # draw | fixed | none
    special: str | None = None      # task_source=="none" 时的胜利约束文本
    note: str = ""                  # 附加说明（如 M10/M13 的"分出去则首墩前完成交流"）

CAMPAIGN_MISSIONS: dict[int, Mission]  # {1..32}
EPILOGUE_START_DIFFICULTY = 18

def get_mission(no: int) -> Mission: ...
def fixed_tasks_m32(player_count: int) -> list[dict]: ...
```

**关键点：**
- 常规关 `task_source="draw"`；M32 `task_source="fixed"`；M8/M12/M21/M23/M27 `task_source="none"`。
- M32 固定 4 张任务**复用现有 `TASK_CARDS`**：`T074`(不赢任何墩) / `T088`(恰好连赢三墩) / `T085`(连续赢两墩) / `T080`(赢首末墩)，`fixed_tasks_m32()` 从 `tasks.TASK_CARDS` 取这 4 张并套用与 `draw_tasks` 相同的 `{id,text,difficulty,assigned_to,completed}` 结构。
- 5 个无难度关 `special` 字段写清约束文本（M8「不得有玩家比别人多赢 2 张 9」、M12「不得用粉牌或潜艇开墩」、M21「🔴 + 不得多赢 2 张 1」、M23「🔴 + 赢首墩者始终领先 + 第二墩前禁止交流」、M27「🔴 + 黄5 作为最后一墩最后一张」）。
- M6 的 `ASG_ALL_ONE_CREW` 产生方式在实现时对照规则书最终确认（默认按「自荐一人包揽」复用 Task 3 的自荐机制，与 M14 同但无限时）。

---

### Task 2: game.py — 声呐系统改造（支持沟通符号）

**Files:**
- Modify: `src/plugins/games/deep_sea_mission/game.py`

**说明：** 现有声呐是「每人一次、公开 marker」。改造为三种 `sonar_mode`，**mission 模式默认 `normal`，行为完全不变**。

**State 字段：**

```python
ctx.state["sonar_mode"] = "normal"   # normal | currents | rapture
# normal：沿用 sonar_used（每 seat bool）
# rapture：sonar_quota = player_count - 2（共享次数）+ sonar_used_count
```

**改动点：**
1. `on_create` 初始化 `sonar_mode`（mission 模式写死 `normal`，campaign 模式由 Task 3 注入）。
2. `_handle_sonar` 按 `sonar_mode` 分支：
   - `normal`：现逻辑不动。
   - `currents`：校验通过后，`sonar_public` 记录 `{player, card}`（**不含 marker**），广播改为「这是 TA 的一张满足『最高/最低/唯一』之一的牌」（不透露具体是哪种）。
   - `rapture`：把「每人一次」改成「全队共享 quota」——`sonar_used_count += 1`，达到 `sonar_quota` 后拒绝；广播文案与 normal 一致（仍公开 marker）。
3. `in_game_hint` 补充声呐可用次数提示（rapture 显示「剩余共享声呐 X 次」）。

**验收：** mission 模式下声呐行为与改造前 100% 一致（CLI + Bot 双端）。

---

### Task 3: game.py — campaign 模式核心（最大改动）

**Files:**
- Modify: `src/plugins/games/deep_sea_mission/game.py`

**说明：** 这是主接入点，拆 5 个子步骤。

**3.1 声明模式**

```python
MODES = [
    GameMode(id="mission", name="任务难度", description="由开局命令指定任务总难度", aliases=("深海任务", "mission")),
    GameMode(id="campaign", name="战役模式", description="按官方 32 关推进", aliases=("深海战役", "战役", "campaign")),
]
```

**3.2 `on_create` 分支**

`mode == "campaign"` 时：
1. 从 `ctx.config["mission_no"]` 取关卡号，`get_mission(no)` 查表。
2. 若 `MOD_UNFAMILIAR in modifiers`：**在 build_deck/deal 之前**抽颜色卡（`random.Random().randint(1,9)`）→ 1-3 正常 / 4-6 `currents` / 7-9 `rapture`，据此写 `sonar_mode`；否则按 modifiers 直定（`MOD_CURRENTS`→currents、`MOD_RAPTURE`→rapture、无→normal）。
3. `build_deck` + `deal` + `_find_captain`（沿用）。
4. 任务来源三选一：
   - `draw`：`draw_tasks(mission.difficulty, player_count, rng)`。
   - `fixed`：`fixed_tasks_m32(player_count)`。
   - `none`：`tasks=[]`。
5. state 额外注入：`mode`、`mission_no`、`mission`（只存可 JSON 序列化字段：no/difficulty/modifiers/assignment/special/note）、`sonar_mode`、`assignment`、`special`、`distress_pending`（见 Task 6）。

**3.3 `on_start` 分支**

- 私聊手牌逻辑不变；私聊与群面板增加关卡信息头（`第 N 关 · 难度 X · 特殊符号说明`）。
- `task_source=="none"`（无任务关）时：**跳过 `task_selection`**，直接 `phase="playing"`，广播 `_playing_panel` 并附 `special` 约束文本。
- 否则进入 `task_selection`，面板显示 `special`/`note`/限时提示。

**3.4 任务选择阶段按 `assignment` 分支**

`_handle_task_selection` 顶部按 `ctx.state["assignment"]` 分流（`None` → 现有轮流选逻辑不动）：

| assignment | 行为 |
|---|---|
| `all_one_crew` | 跳过轮流选，进入「自荐」子流程：按队长起顺时针逐个问，先答 `@我 包揽` 者拿全部任务（复用 3.4 自荐机制，无限时） |
| `captain_all` | 直接全部任务 `assigned_to=队长`，跳过选择，进入出牌（`note` 提示「若分出去需首墩前完成交流」） |
| `self_nominate_1` | 自荐子流程：队长起顺时针逐个问 `@我 包揽`，第一个应答者拿全部任务；无应答则退回轮流选 |
| `self_nominate_2` | 自荐子流程：逐个问直到 **两名** 应答，两人各拿全部任务（即每张任务两人共享？按规则书核对：M26 是两人共同完成全部任务，实现为 tasks 的 `assigned_to` 支持两人，或复制一份给两人）；无应答退回轮流选 |
| `hardest_to_captain` | 先把「难度最高的一张任务」自动 `assigned_to=队长`，其余进轮流选 |
| `captain_no_task` | 轮流选，但 `_advance_selector` / `_handle_task_selection` 跳过队长（队长不参与选任务） |

- `MOD_FREE_SELECTION`：放宽 `_can_control_seat` 检查——任意玩家都可 `@我 选 N`，任务归该玩家；仍禁止透露手牌（软约束提示）。

**3.5 Real-time 处理**

`MOD_REALTIME` 关卡（M14/15/16/26）：面板显示「本关限时 X:XX（不计时则按替代规则：Currents / Rapture / 禁止交流 / 12 tasks）」，**默认走替代规则**（替代规则已在 `note` 字段描述并显示）。不接 `scheduler` 倒计时。

**验收：** mission 模式分支与改造前完全一致；campaign 下 6 类 assignment 均能走通到 `playing`。

---

### Task 4: commands.py — 「深海战役」入口

**Files:**
- Modify: `src/plugins/games/deep_sea_mission/commands.py`

**说明：**

1. `PendingRoom` 新增 `mode: str = "mission"`、`mission_no: int = 1` 字段。
2. 新增 `on_command("深海战役", aliases={"deep_sea_campaign", "战役"}, rule=to_me(), priority=3, block=True)`：
   - 先查 `group_config` 读当前进度（默认 1）；可选参数 `@我 深海战役 5` 指定起始关卡（跳关/回退，需房主权限；仅当目标关卡 ≤ 已通关+1 或房主显式覆盖）。
   - 显示房间面板：`第 N 关 · 难度 X · 特殊符号` + 当前进度。
   - 创建 `PendingRoom(mode="campaign", mission_no=no)`。
3. `_room_line` 按 mode 分支渲染（mission 显示难度；campaign 显示关卡 + 难度 + 符号）。
4. `_begin_room` 分支：`config={"mode":"campaign", "mission_no":..., "seat_owners":...}`；mission 分支不变。
5. `深海任务` 命令保持 `mode="mission"` 不变。

**注意：** `战役` 是新增 alias，需确认不与现有其他游戏的命令冲突（message_router 兜底帮助里也要加）。

---

### Task 5: 关卡进度持久化（group_config）

**Files:**
- Modify: `src/plugins/games/deep_sea_mission/game.py`（`on_end`）
- Modify: `src/plugins/games/deep_sea_mission/campaign.py`（进度辅助函数，或放 game.py）

**说明：** 复用 `core.group_config.get_group_config / set_group_config`，不建新表。

```python
# key 设计
LEVEL_KEY = "deep_sea_mission.campaign.level"       # 值："1".."32" 或 "epilogue:<难度>"
```

- `on_end` 中：`mode=="campaign"` 且 `reason==EndReason.COMPLETED` 且 `completed` 时推进：
  - 关卡号 < 32 → `set_group_config(group_id, LEVEL_KEY, str(no+1))`。
  - 关卡号 == 32 → 进入 Epilogue：`set_group_config(group_id, LEVEL_KEY, "epilogue:18")`。
  - 已是 `epilogue:<n>` → `set_group_config(..., "epilogue:" + str(n+1))`。
- 失败/中止/ERROR → 不推进（下一局重打当前关）。
- 结算文案显示「第 N 关通过 → 下一关第 N+1 关」或「进入 Epilogue（难度 18）」。
- `commands.py` 读进度时解析 `epilogue:<n>`。

**验收：** 通关后再次 `@我 深海战役` 自动显示下一关；失败后重开仍是同一关。

---

### Task 6: Distress Signal 传牌

**Files:**
- Modify: `src/plugins/games/deep_sea_mission/game.py`

**说明：** `MOD_DISTRESS` 关卡（M1 起所有带 ⚓ 的关，按 32 关数据实际标注）在发牌后、任务选择前插入「传牌阶段」。

- 新增 phase：`deal` → `distress`（仅 ⚓ 关）→ `task_selection` / `playing`。
- 规则：每位玩家私聊报 1 张要传的牌给**左邻**（`order` 中的下一家），禁传潜艇；机器人校验（在手牌、非潜艇）后统一结算。
- 实现：`on_start` 发完手牌后若含 `MOD_DISTRESS`，`phase="distress"`，私聊提示每人 `@我 传 蓝4`；`on_player_action` 新增 `distress` 分支收集齐 N 人后统一执行 `hands` 传递、重新 `sort_cards`、广播「传牌完成」；再进入任务选择。
- 传牌后重发私聊手牌（牌已变化）。
- 「本关尝试数 +1」：简化为面板提示（Epilogue 计分不做，见决策）。

**验收：** 3-5 人均可走完传牌；传潜艇被拒；传牌后手牌正确转移到邻座。

---

### Task 7: 无难度关胜利自动校验

**Files:**
- Modify: `src/plugins/games/deep_sea_mission/game.py`

**说明：** 5 个 `task_source=="none"` 的关无任务卡，出牌结束进入 `task_review` 后，机器人根据 `trick_history` / `won_tricks` 做**自动校验并提示**，最终仍由玩家 `@我 胜利 / 失败` 确认。

| 关卡 | 自动校验逻辑 |
|---|---|
| M8 | 统计每人赢得的 9 的数量，任两人差 ≥ 2 → 提示违反 |
| M12 | `trick_history` 每墩首张牌，出现粉牌或潜艇开墩 → 提示违反 |
| M21 | 同 M8，但数 1 |
| M23 | 校验「首墩赢家是否全程领先」；「第二墩前禁止交流」无法强制 → 仅提示（软约束） |
| M27 | 校验最后一墩最后一张是否为 `yellow:5` |

- `_result_review_lines` 在 campaign + 无难度关时追加「约束校验结果」。
- 校验结果只提示，**不自动结束对局**（保持手动结算铁律一致性）。

---

### Task 8: CLI adapter 同步（铁律 13）

**Files:**
- Modify: `scripts/cli_adapters/deep_sea_mission.py`

**说明：** 复用 `DeepSeaMissionGame.MODES`（已含 campaign），`start(mode_id)` 分支：
- `mode_id=="campaign"`：CLI 内维护一个内存 `current_level`（默认 1，可在 CLI 里用 `setlevel` 跳关调试）；`get_mission` 查表 → 抽卡/固定任务/无任务 → 注入 `sonar_mode` / `assignment`。
- `play()` 对应分支：campaign 下支持 3.4 的任务分配流程（自荐/队长包揽/跳过队长/自由选）、Task 6 传牌、Task 7 校验提示。
- 指令集与 Bot 完全对齐（`包揽` / `传` / `选` / `过` / `出` / `胜利` / `失败` 等）。
- CLI 进度不持久化（关掉即失），只在单次运行内推进；这是允许的机制差异（同 `docs/13` §允许不一致）。

**验收：** CLI 无参数启动 → 选「战役模式」→ 能完整打完 M1→M2 连续推进；所有指令与 Bot 侧一致。

---

### Task 9: 帮助文本 + 菜单 + 测试 + 文档

**Files:**
- Modify: `src/plugins/message_router.py` — 兜底帮助加 `🌊 @我 深海战役`
- Modify: `src/plugins/core_commands/handlers.py` — `HELP_TEXT` 加战役说明 + `_QUICK_CMD` 加 `deep_sea_campaign` 或沿用 `deep_sea_mission`
- Modify: `src/plugins/game_launcher/__init__.py` — usage 加战役入口
- Modify: `src/plugins/games/deep_sea_mission/README.md` — 战役玩法 + 指令速查
- Modify: `docs/games/deep-sea-mission-campaign.md` — 补「已实现」状态 + 实现说明（把调研报告升级为实现文档）
- Modify: `README.md` — 游戏列表说明
- Create: `tests/games/deep_sea_mission/test_campaign.py`

**测试覆盖：**
- `campaign.py`：`get_mission` 全 32 关可查、5 个无难度关 `task_source=="none"`、M32 `task_source=="fixed"`、`fixed_tasks_m32` 返回 4 张且 id 正确。
- `draw_tasks` 复用不受影响（回归）。
- 声呐三模式：normal 回归 + currents 不泄露 marker + rapture 共享 quota 耗尽。
- assignment 分支：`captain_all` / `hardest_to_captain` / `captain_no_task` 的分配结果正确。
- 无难度关校验函数（M8/M12/M21/M27）对构造的 `trick_history` 判对/判错。
- 进度推进：COMPLETED 后 `group_config` 值 +1 / 进 Epilogue。

**无需改动：** `src/bot.py`（同一 game_id 已注册）、`scripts/play_cli.py` 的 `ADAPTERS`（adapter 已在列表）、`migrations/`（用 group_config 不建新表）。

---

## 执行顺序

1. **Task 1** `campaign.py`（独立，先行）
2. **Task 2** 声呐三模式（依赖 Task 1 的 modifier 常量）
3. **Task 3** `game.py` campaign 核心（依赖 Task 1 + 2）
4. **Task 4** `commands.py` 入口（依赖 Task 3 + 5）
5. **Task 5** 进度持久化（依赖 Task 3）
6. **Task 6** 传牌（依赖 Task 3）
7. **Task 7** 无难度关校验（依赖 Task 3）
8. **Task 8** CLI adapter（依赖 Task 3，可并行于 5/6/7）
9. **Task 9** 帮助/菜单/测试/文档（最后收口）

Task 4 与 5 有耦合（入口读进度、on_end 写进度），建议 5 先于 4 完成写入函数，4 再接入读取。

---

## 验收 Checklist（上线前）

- [ ] CLI 无参数启动能选「战役模式」，连续打完 M1→M2 进度推进
- [ ] `@我 深海任务 8` 行为与改造前完全一致（回归无破坏）
- [ ] `@我 深海战役` 创建房间 → 显示当前关卡；`加入/重复加入/离开/开始` 正常
- [ ] 6 类特殊符号各能在对应关表现（Currents 不泄 marker、Rapture 共享声呐、Unfamiliar 抽卡、Free Selection 自由选、Distress 传牌、Real-time 面板提示）
- [ ] 5 个无难度关进入即出牌、结束有约束校验提示
- [ ] M32 固定 4 任务、M6/M10/M13/M14/M15/M16/M19/M25/M26 分配规则正确
- [ ] 通关 +1 / 失败不推进 / M32 后进 Epilogue
- [ ] 帮助文本（message_router / core_commands / game_launcher）三处一致
- [ ] `pytest tests/games/deep_sea_mission/` 全绿
