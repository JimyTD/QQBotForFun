# 《静夜标记》全量移植计划

> 日期：2026-09-16 · 状态：待批（未开工）· 目标游戏 id：`silent_mark`
> 源项目：`d:/Fun/SilentWereWolf`（v0.2.1，TypeScript 全栈，服务端核心 + AI 玩家系统）
> 前置评估：[`2026-09-16-silent-mark-port-assessment.md`](./2026-09-16-silent-mark-port-assessment.md)（本文件第 1 节修正了其中 2 处事实错误）
> 参考规范：[`04-game-development.md`](../04-game-development.md)、[`13-cli-bot-parity.md`](../13-cli-bot-parity.md)、[`03-core-api.md`](../03-core-api.md)

---

## 0. 结论

**可行。全量迁移，不做功能裁剪。**

- 移植性质是**等价改写**，不是"阉割版"：源项目服务端全部已实现行为（含 AI 玩家子系统）都有 QQ 侧对应实现路径。
- 只有 **3 处平台语义不可保真**（多房间并存、狼人并发实时同步、断线重连），必须改成等价形式；这 3 处不是砍功能，是换承载方式（详见 §5）。
- 另有 **4 项源项目「声明了但从未实现」** 的功能，不属于迁移目标（§2.3 明确列出，避免误算工作量或被当成漏做）。
- 体量约为现有 `deep_sea_mission`（3116 行 Python）的 **2 倍左右**：预估 5000~7000 行 Python（含 AI 全套）+ CLI 适配器 + 文档测试。

---

## 0.1 M0 已完成（2026-09-16）

**交付物**（纯新增，未改任何既有文件）：

| 路径 | 内容 |
|---|---|
| `src/plugins/games/silent_mark/__init__.py` | 包说明。**刻意不导入 `game.py`**，因此不会被 `bot.py` 加载，不影响现有功能 |
| `src/plugins/games/silent_mark/engine/constants.py` | 角色/阵营/阶段/死因/物品/理由/12 套预设板子（转写 `shared/constants.ts`） |
| `engine/types.py` | 状态形状（TypedDict）+ 构造函数。定义「玩家标识 = `pid: str`」这一关键约定 |
| `engine/roles.py` | 10 个角色处理器 + `new_role_state` + `has_voting_right`（转写 `roles/*`） |
| `engine/fallback.py` | 玩家未行动时的确定性兜底：夜晚行动 / 标记 / 投票（转写 `submitDisconnectedFallback`） |
| `engine/resolve.py` | 夜晚结算 / 投票结算 / 胜负 / 标记合法性与选项 / 板子校验 / 物品（转写 `rules.ts` + `validators.ts`） |
| `engine/private_info.py` | 信息防火墙（转写 `shared/privateInfo.ts`） |
| `tests/games/silent_mark/` | 单测（`test_settings` / `test_private_info` 是源项目两份 vitest 用例的逐条转写） |

**验收方式**：

```
uv run pytest tests/games/silent_mark -q     # 135 passed（M0 规则内核）
uv run ruff check src/plugins/games/silent_mark tests/games/silent_mark \
    --ignore RUF001,RUF002,RUF003            # All checks passed!
```

> 说明：`RUF001/002/003`（全角标点被判为 ambiguous unicode）在仓库基线里已有 **6144** 处，
> 属既有常态，因此新代码不刻意规避；除该规则外无新增 lint 问题。

### M0 锁死规则时发现的三个源项目问题

| # | 发现 | 处理 |
|---|---|---|
| 1 | **同守同救会记两条死亡记录**：源项目 `rules.ts` 里第一个 `if` 漏写 `else`，清标志后会紧接着再记一条 `attacked`，导致同一玩家重复公告、重复进入死亡触发链（猎人可能被问两次开枪） | 本侧按设计文档只记一条（`guardWitchClash`，Python 里本来就是 `elif`）；源项目已在 **502ef26 改成 `else if`** → **两端口径已对齐**。`test_guard_witch_clash_kills_the_victim_exactly_once` 继续锁死防回退 |
| 2 | **屠边 + 缺类别的板子是陷阱**：`validate_game_settings` 允许「1 狼 + 3 平民」，而屠边判定里「神职全灭」开局即成立 → 首夜结算后立刻判狼胜（甚至无人死亡） | **已修（判定层 + 配置校验层，与源项目 502ef26 同口径）**：判定层要求"该类别在板子里存在"才构成屠边，并把"好人全灭"提升为无条件判负（否则场上只剩狼会死局）；配置校验层新增屠边必须同时有神职与平民。测试改为锁**修正后**行为 |
| 3 | **可选身份被当局职业限制**：可选身份由「当局参与的职业」生成，所以板子里没有预言家时**任何人都不能声称预言家**，诈身份空间比设计文档描述的更窄 | 锁住现状（`test_claim_identity_must_exist_on_the_board`）。源项目未回复此项，仍待 M3 决策 |

另有一处 JS↔Python 语义差异已处理：源项目 `settings.items.pool \|\| [默认池]` 在 JS 里空数组是 truthy，
Python 的 `or` 却把 `[]` 当 falsy（会误解成「用默认池」）。现明确取「空池 = 不发物品」。

### 0.2 源项目 502ef26 结论对齐（2026-09-16 第二轮）

源项目本轮提交了 502ef26，回报了对我在交接说明里提的问题的处理结论。逐项核对我侧是否有同类问题：

| 源项目处理项 | 源项目结论 | QQBot 侧是否有同类问题 | 本侧动作 |
|---|---|---|---|
| 同守同救双死亡记录 | 改成 `else if`，只记一条 | ❌ 无（本侧本来就是单条） | 仅把 `resolve.py` 注释从「与源项目的**有意差异**」改为「**已对齐**」；测试保留 |
| 屠边 + 缺类别开局即判狼胜 | 判定层 + 配置校验层**都要防** | ✅ 有（M0 当时只锁了现状、把决策推给 M3） | **已修**：见 §0.1 第 2 行 |
| 认输/退出不公开遗物 | 已修（与其它出局路径对齐） | ⚠️ 本侧**尚无认输代码**（属 M2） | 记入 M2 硬要求：认输必须与其它出局路径一样 `revealed=True` + 写 `relics` |
| AI 提示词提供规则层会拒绝的"跳过"选项 | 已修 | ✅ **有同类**：`fallback.py` 在守卫/预言家无合法目标时返回**不带 target** 的动作，而规则层要求必须有 target → 会被拒 | **已修**：`fallback_night_action` 返回类型改为 `dict \| None`，无合法目标时返回 `None`，调用方**直接推进阶段**；新增契约测试 `test_fallback_action_is_always_accepted_by_the_rules_layer` |
| AI 夜晚最终提交失败只记日志 → 阶段永久卡住 | 已修（兜底也要保证阶段推进） | ⚠️ 本侧状态机在 M1 才落地 | 已把「返回 None ⇒ 必须推进，绝不原地等待」写进 `fallback.py` 契约（第 1 条）；M1 验收项加「任何兜底失败都不能阻塞阶段」 |
| 座位号解析正则 `/^\\d+$/` 多一个反斜杠 | 已修（应为 `/^\d+$/`） | ⚠️ 本侧无对应代码（AI 属 M4） | 记入 M4 注意事项：模型答对的座位号不能被判非法（接受数字与数字字符串两种写法） |
| `guardTriggerAction` 注释承诺未实现的校验 | 核实后认定**无法实现**：猎人/骑士没有查验能力，`collectSeerResults` 对其返回空，"已确认好人"在他们身上不存在 → 实现只会是永不触发的死代码。结论：只保留白狼王"不带走队友"，**改注释、不写死代码** | ✅ **有同类**：`types.py` 的 `PendingTriggerDict` 注释把 `fool_immunity` / `knight_duel` 也列为触发类型，但这两个**从未入队**（白痴免疫走 `on_exile`、骑士决斗走独立 `day_knight` 阶段） | **已修注释**：明确只会有 `hunter_shoot` / `wolf_king_drag`，并说明另两个为什么不可达；**不新增任何死代码**。M4 移植 `AIDecisionGuard` 时同样只保留白狼王分支 |

**源项目回报中未提及的两项**（我在交接说明里提过，但回报未覆盖，需确认是有意跳过还是遗漏）：

- 问题 7：`GameManager.ts` 16 处中文注释乱码（仅注释，不影响运行）
- 问题 8：`getRandomDelay` 的 `maxTimeout * 800` 单位笔误（当前 `maxTimeout` 恒为 `undefined`，属死代码）

### 0.3 源项目补充回报的对齐确认（2026-09-16 第三轮）

源项目补充回报，逐项记录：

| 项 | 结论 | 本侧动作 |
|---|---|---|
| 问题 7 注释乱码 | **已修；实际是 77 行，不是我报的 16 行**。逐行显式替换修好，未做整文件转码。`.editorconfig` 未加（不在允许修改清单内） | 无需改代码。**记一次我自己的方法教训**，见下 |
| 问题 8 `maxTimeout * 800` | **已修**，选最干净方案：删掉 `maxTimeout` 参数与整个分支，4 个调用点同步去掉实参；无独立单测，靠 tsc 验证 | 无需改代码 |
| 设计确认项「可选身份受当局职业限制」 | 判定为**有意设计**，保持现状、不放宽（与 `test_claim_identity_must_exist_on_the_board` 一致）。补充细节：固定项「神职」「好人」**始终可选**，所以板子里没有神职时仍可声称"神职"（模糊说法），只是不能声称"预言家"这种具体且不存在的职业。放宽必须同时改客户端选项 UI，本次禁止改 client | 本侧实现天然满足（`get_available_identities` 固定返回前两项）。**补一条防回退测试** `test_ambiguous_god_claim_is_always_available` |
| `checkWinCondition` 口径 | 源项目已按本侧写法对齐，并列出判定顺序（狼全灭 → 好人全灭 → 屠边类别），其第 2 步是本次新补 | 见下方三点核对 |

#### `checkWinCondition` 三点核对结果（回答源项目的 a / b / c）

- **a) 同轮双方全灭 → 好人优先（一致 ✅）**：本侧第 1 步就是"狼全灭 → 好人胜"，第 2 步才是"好人全灭 → 狼人胜"，与源项目最终形态相同。顺序若反过来，同轮全灭的结论会相反。**补一条锁定测试** `test_good_wins_when_both_sides_are_wiped_in_the_same_resolution`。
- **b) reason 字符串（一致 ✅）**：本侧实际使用的就是 `wolves_eliminated` / `good_eliminated` / `specials_eliminated` / `villagers_eliminated` 四个。**补一条锁定测试** `test_win_reason_strings_are_stable`（这四个是跨实现标识符，改名等于破坏对齐）。
- **c) 神职集合（一致 ✅）**：本侧 `SPECIAL_ROLES` = {预言家, 女巫, 猎人, 守卫, 守墓人, **白痴**, **骑士**}，含白痴与骑士，与源项目一致。**补一条锁定测试** `test_special_roles_are_exactly_the_seven_gods`。
- **唯一的字面差异（已改）**：本侧原先把"平民全灭"判在"神职全灭"之前。两者**可证等价**——能走到第 3 步说明 `alive_good > 0`，而每个好人角色要么是神职要么是平民，所以至多有一类全灭，顺序不影响结果。但仍已把顺序改为**神职在前、平民在后**，与源项目逐字一致，避免以后 diff 时产生无意义的争论。
- 另确认：第 3 步本侧也**不带** `alive_good > 0` 的前置条件（依赖第 2 步已拦截），与源项目一致；`winCondition` 非 `city`（含未设置）时走屠边分支，也一致。

#### 方法教训（记给自己，避免下次再漏报）

我报"16 处乱码"是**抽样匹配**的结果：当时用的是 `鐨|鏄|澶滄|娓告垙|鐜╁|閿欒|鍒濆鍖` 这类具体乱码片段去 grep，只能命中包含这些字节序列的行，其它原文产生的乱码字节对被漏掉了（真值 77 行）。
**正确做法**：把疑似行按 GBK 编码回去、再按 UTF-8 解码，能成功解码的才是乱码行——这是全量检测，不依赖猜测片段。

### 0.4 当前进度与下一步（2026-09-16）

| 里程碑 | 状态 | 说明 |
|---|---|---|
| **M0 规则内核** | ✅ **完成** | 135 条单测；与源项目 502ef26 完成三轮对齐（§0.1–0.3） |
| **M1a 输入层** | ✅ **完成** | `syntax.py` + 66 条单测；CLI/Bot 共用，纯函数零 IO |
| **M1b 单局内核** | ✅ **完成** | `game.py` / `views.py` / `config.py` + 6 条端到端测试；4 人局两种结局已跑通 |
| **M1c 报名房间与接线** | ✅ **完成** | `commands.py`（`加入`/`重复加入`/`离开`/`板子`/`踢人`/`开始`/`记录`）+ 热座 CLI adapter（**直接驱动真实本体，零规则复刻**）+ 四处注册（`bot.py`/帮助/菜单/`play_cli.ADAPTERS`）+ `docs/games/silent-mark.md`。**两处按实际约定偏离原计划**：① `认输` **不能**做命令——它是全局 `结束` 的别名，会误杀整局；单人出局改为在提问下回复「退出」；② `结束` 刻意不注册（全局命令，**任何人都能用、不需要房主**，并把等待中的报名房间一起收掉） |
| **M2 触发链连锁与边界** | ✅ **完成** | `test_trigger_chains.py` 11 条：三连链（白狼王带人→猎人开枪）、「只有被放逐才能带人」、技能致死后**立即**判胜负、骑士决斗两种结局+全局只问一次、被毒死的猎人不开枪且群内不提、**认输也走死亡链**、死人不再产生夜间行动/默认标记、守墓人无死者不打搅、白痴免疫一次、全席位挂机也能收场。途中修掉 3 个真 bug（见下） |
| **M3 全板子 + 物品** | ✅ **完成** | 12 套预设本来就能开（M0）；本轮补上：① **自定义板子**（`custom_setup.py` 分步向导，**群里与 CLI 共用同一份**）② **猎犬哨快照**（`record_death` 里记"出局那一刻还剩几只狼"，源项目只写了客户端标签、服务端从未赋值）③ 物品开关（`@我 物品 关` / 向导第 4 步）④ 自定义板子接入 `_build_settings`（原先 `mode="custom"` 会被**无声回落到 4 人标准**）|
| **M4 AI 玩家** | ✅ **完成** | `ai/*` 全套：`context`（信息过滤唯一出口，私有部分复用 `engine/private_info`）· `prompts`（6 套模板 + 角色策略，**中文文案逐字移植**）· `persona`（6 人格整局固定）· `guard`（硬约束，只保留白狼王分支）· `controller`（延迟/三层 JSON 容错/三级兜底）· `logger`（每局 JSONL）· `names`（LLM 取名 + 名字池）。接线：**默认 AI 补位**（`@我 AI 开/关/测试`）、AI 决策翻成"和真人一样的输入"再走同一解析器（同权校验是结构保证）、`logs/silent_mark_ai/`。途中发现并修掉 3 处真问题（见下） |

**M4 途中发现并修掉的三处真问题**（都不是"还没写完"，而是会静默出错的实现缺陷）：

1. **`LLMConfigError` 不是 `LLMError` 的子类**（它继承 `GameError`）→ 没配 api_key 时，
   AI 决策与取名都会把异常抛穿整局。现已按"任何 LLM 失败都只能导致兜底"接住
   —— 这类失败本该是最无害的一种。
2. **夜间/投票的等待把 AI 的超时传给了真人**（`timeout=cfg.ai_night_timeout` 直接用上）
   → 直接违反"真人永远不超时"。现改为真人 `timeout=None`，AI 的预算由 `_ai_budget()`
   按 `ai_kind` 单独给。
3. **AI 全程失败时兜底没落地**：两次都拿不到回复时会退回一个 `action="skip"`，
   对狼人/守卫来说是**非法动作**，阶段会卡住。现已保证"拿不到决策 ⇒ 必走 `fallback_*`"。
| **M5 体验与复盘** | ✅ **完成** | ① **`@我 复盘`**：一页一轮（概览 + 每轮的死讯/标记/投票），页数多时走 `send_forward` **合并转发**（自带降级）；② **`@我 面板`**：把常驻对局面板重贴一遍；③ **报名房间 30 分钟超时自动清理**（`schedule_once`，无调度器时安静跳过）；④ 发奖/`@我 记录` 在 M1 已完成。**唯一没做的是"出图"**：`core.render` 是纯文本，出图需自研 PIL —— 计划里本来就是"可选增强"，暂不做（见 §2.1-F 核对表） |
| M6 全量回归 | ⬜ 未开始 | |

> 当前累计 **310 条单测全绿**（M0 规则 135 + M1a 语法 67 + M1b/M1c/M2/M3 端到端 44 + M4 AI 56 + M5 复盘/房间 8）；
> 仓库全量 **740 条**同样全绿（`uv run pytest tests/ -q`）。

#### M2 途中修掉的 3 个真 bug（都是"死亡链要对所有出局方式一视同仁"这一个道理的三种漏法）

| # | 漏法 | 后果 | 修法 |
|---|---|---|---|
| 1 | 认输后**仍会写入夜间兜底行动** | 死人还能守护/查验（守卫死了还护着人） | `_apply_night_fallback` 对已出局者直接返回 + 夜/狼循环里跳过中途出局的人 |
| 2 | 认输后**仍会被"默认标记"** | 已出局的人出现在本轮标记记录里 | `_run_marking` 兜底前复查存活状态 |

> ⚠️ **一次我自己的误判（已改回）**：M2 一度把"认输"也接进死亡触发链（理由：死亡链应对所有
> 出局方式一视同仁），于是"认输的猎人能开枪"。核对源项目后确认**认输刻意不触发任何技能**
> ——`GameManager.handleResign` 注释原文：「玩家认输退出：视为死亡（不触发猎人/狼王等任何技能）、
> 豁免正在等待的行动、检查胜负」。已改回，并由 `test_resigning_hunter_does_not_shoot` 锁死。
> 教训：**"统一"要问的是源项目怎么规定，不是我觉得哪种更一致**。

#### M1 的三步拆分（每步都可独立验证）

| 子步 | 内容 | 交付物 | 验收 |
|---|---|---|---|
| **M1a 输入层** ✅ | 玩家输入语法（解析 ↔ 渲染），CLI 与 Bot **唯一共用** | `silent_mark/syntax.py` + `test_syntax.py` | 66 条纯函数单测 + **跨层契约测试**（语法层放行的产物必过语义校验） |
| **M1b 单局内核** ✅ | 好友预检 + 私聊发身份 + `_ask` 封装（超时/退出/私聊失败/`/结束` 打断）+ 夜晚 5 步 + 死讯 + 触发链 + 骑士决斗 + 标记 + 投票 + 放逐 + 胜负 + 结算发奖 | `game.py` / `views.py` / `config.py` + `test_game_flow.py` | 6 条端到端：狼胜 / 好人胜 / 人人都有身份牌 / 私聊失败劝退 / 超时走兜底 / 退出即认输且公开遗物 |
| **M1c 报名房间与接线** | `commands.py`（`静夜标记 [板子]` / `加入` / `重复加入` / `离开` / `踢人` / `开始` / `板子` / `认输` / `记录`）+ CLI adapter（热座）+ 注册点（`bot.py` / 帮助 / 菜单 / `play_cli.ADAPTERS`）+ `docs/games/silent-mark.md` | 注册全部到位 | CLI 与真机群各跑通一局 4 人局 |

**为什么先做 M1a**：它是 CLI↔Bot 一致性的唯一抓手（`docs/13` 铁律），且是纯函数、零 IO、可全量单测。
`_ask` 的难点是"异常分类 + 与兜底衔接"，只有在真实主循环里才验证得动，所以放到 M1b 与调用点一起做。

#### M1a 本轮定下的语法（假设，如有异议现在改成本最低）

- **标记（群内一行式）**：`标记 <身份> <理由> | <座位> <评价身份> <理由> | ...`
  - 分隔符半角/全角 `|`；段内空格/逗号/顿号均可分隔
  - **理由可省略**，默认「直觉判断」（降低输入门槛；规则层看到的 reason 永远有值，不违反"每个标记必须带理由"）
  - 身份/理由同时接受中文名与英文 key
  - 只发 `标记`（无参数）→ 走**引导式**选择（`session.choose` 逐项问，与一行式产出完全相同的状态）
- **夜间行动 / 投票（单选）**：`3` / `3号` / `@3`；动词前缀可带（`刀 3` / `守 3` / `查 3` / `投 3`）
- **跳过**：`跳过` / `过` / `pass` / `skip` / `不用`
- **女巫专用**：`救` / `解药` → 解药；`毒 3` → 毒药；`不用` → 不使用药物
- **分层原则**：`syntax.py` 只做**语法**（分词、别名归一、座位→pid、生成配对提示文案）；
  **语义**（身份是否可选、理由是否匹配申报身份、数量上限）仍由 `engine.resolve.validate_player_marks` 判定，
  避免出现两套真相。唯一的严格化差异：语法层要求「人类输入」至少给 1 个评价标记
  （产品要求"必须使用"），而 `validate_player_marks` 保持源项目口径（允许更少，因为 AI/兜底路径可能产生更少的评价）——这是**刻意的分层**，已在此记录。

#### M1b 过程中的两条经验（记下来省得重踩）

1. **`ruff --fix` 的 RUF100 陷阱**：单独 `--select RUF100 --fix` 时，其它规则的 `# noqa` 会被判定为"未使用"
   并被**批量删除**（一次干掉了我 16 处 `# noqa: N812`）。正确做法是把 RUF100 与目标规则放在同一次
   `--select` 里，或者干脆不用 RUF100 的自动修复。
2. **全量测试的瞬时失败**：`uv run pytest tests/` 期间出现过一次 checkin/food 报 ERROR、deep_sea CLI
   失败；用「先跑我的模块再跑它」的对照实验证明与本项目无关，重新单独跑全量即 `exitCode 0` 全绿。
   结论：那些是与本项目无关的瞬时失败（时间/资源相关），**排查前先做对照实验**，不要急着怀疑自己。

---

## 1. 本次核验方法，以及对上一版评估的修正

**核验方式**：逐文件读完源项目服务端全部非 AI 代码（`GameManager.ts` 1398 行、`roles/*` 334 行、`rules.ts`、`RoomManager.ts` 492 行、`socket/handlers.ts` 事件全集、`shared/*` 全部类型与常量与校验器）、AI 子系统全部（2242 行，含 `AIPlayerController` / `AIContextBuilder` / `AIPromptTemplates` / `AIDecisionGuard` / `AIPersona` / 日志）、客户端全部 18 个 tsx 的功能面、`docs/*` 全部设计文档；QQ 侧逐行核验了 `core/*`、`deep_sea_mission` 的多人/私聊/房间实现、CLI 适配器体系与 `play_cli.py` 注册机制。

### ⚠️ 修正 1：`core/render` 没有图片渲染能力

上一版评估（§3、§6）说"**`core.render` 出图**"——**错误**。`core/render.py` 是**纯文本排版库**，实际导出只有 `title/section/kv/truncate/text_card/menu/list_card/result/status_line/paginate/MenuItem`，**不存在 `render_html`、`render_text_card`、`image()`**（全仓 grep 0 命中）。`docs/03-core-api.md:321-343` 描述的那三个 API 是**设计稿，未实现**，该文档与代码已漂移。

**影响**：结算战报、玩家席位图等若想"出图"，必须自备 PIL 渲染（现成参考：`src/plugins/games/aoe3_battle/bracket_renderer.py` 用 PIL 画图 + `MessageSegment.image(f"base64://{b64}")` + `session.broadcast_rich` 发送）。计划里把"出图"降级为**可选增强**，默认走文本卡片（`render.text_card`）。

### ⚠️ 修正 2：`session.ask / choose / wait_any` 是"有实现、零使用"

三个原语在 `core/session.py:275-380` 存在且可用，但**当前 5 个游戏没有一个在用**（全部是 `event_driven=True` + `on_player_action`），也没有任何测试覆盖。本计划会成为它们的**首个生产使用者**，因此 §12 要求为它们补测试。

### ✅ 核验确认（影响设计的关键事实）

| 事实 | 证据 | 对计划的影响 |
|---|---|---|
| `scheduler.start_turn_timer` **无返回值**，只能按 session 整体清理 | `scheduler.py:131-159`、`game_base.py:297` | 阶段级超时必须用 `schedule_once(...)->job_id` + `cancel(job_id)` |
| 整局超时（`session_timeout_seconds`）**在生产路径从未被传入** | `game_launcher/handlers.py:48-54`、`rival_pick.py:328-334` | 不能依赖框架整局超时，必须逐动作自带 timeout |
| `/结束` → `unregister_game_session` 会 `cancel()` 所有 waiter | `session.py:95-98` | 用 `ask` 时**必须显式 catch `asyncio.CancelledError`**（仓库无先例） |
| `llm.chat` **没有 `response_schema`**，只有布尔 `json_mode` | `llm.py:227-235` | 沿用源项目 `extractJSON` 容错解析策略 |
| `GameBase.max_players` 默认 **10** | `game_base.py:87` | 12 人板子必须显式 `max_players = 12` |
| 群消息进 `on_player_action` **必须 @机器人** | `message_router.py:90-92` | 免 @ 输入需自建 `on_message` 旁路（priority=4） |
| `recover_active_sessions` 把重启后的进行中局面**一律标记 aborted** | `game_base.py:384-405` | 重启丢局是现状；§7.4 给出可选增强 |
| 报名房间是**进程内存字典**，非 `group_config` | `deep_sea_mission/commands.py:39` | 重启丢房间，可接受 |
| `ctx.state` key 经 JSON 往返会 int→str | 实证 `deep_sea_mission/game.py:1231-1238` 全用 `str(qq_id)` | §7.2 强制 str key 纪律 |

---

## 2. 全量迁移范围定义

### 2.1 源项目「已实现」清单 = 本次迁移目标基线

**A. 房间与开局**（`RoomManager.ts`）
- 建房：预设模板 12 套（4/5/6/6神/7/8白狼王/8骑士/9/9守墓人/10守卫/12标准/12全角色）+ 完全自定义角色数量
- 配置校验：人数 4~12、至少 1 狼、好人 > 狼人、未知角色拒绝（`validators.ts:7-52`）
- 胜负条件二选一：屠边 `edge` / 屠城 `city`
- 大厅：玩家列表、房主标识、踢人、离开、房主自动转移、人数满才能开始
- **AI 玩家**：房主可加/移除 AI、可"测试 AI 连接"、AI 用 LLM 取名（失败回落名字池）
- 座位号随机分配（与加入顺序无关）
- 物品系统开关与物品池配置（服务端支持，UI 固定为月光石+天平徽章）

**B. 对局核心**（`GameManager.ts` + `roles/*` + `rules.ts`）
- 10 个角色：狼人、白狼王、预言家、女巫、猎人、守卫、守墓人、白痴、骑士、平民
- 夜晚固定顺序：守卫 → 狼人（含白狼王合议）→ 女巫 → 预言家 → 守墓人
- 狼人合议：各狼投票、平票随机、可自刀、不可刀队友（`Werewolf.ts:9-60`）
- 女巫：解药/毒药各 1、首夜可自救非首夜不可、**同夜不可双药**、同守同救同归于尽（`resolveNight`）
- 守卫：不可连守同一人（`Guard.ts:14`）
- 守墓人：只能验已死者；**无死者时自动跳过**；有死者则必须选（`Gravedigger.ts:11-16`）
- 猎人：被刀/被放逐/被决斗/被带走可开枪，**被毒死不可开枪**
- 白痴：仅放逐免疫一次，免疫后**失去投票权但保留标记权**
- 白狼王：仅被放逐可带人
- 骑士：全局一次决斗，狼死/好人则骑士自己死；结果公开但身份不公开
- 死亡触发链：队列处理，新触发插队首，**死亡链结束才统一判胜负**（`ai-improvement-plan.md:593-605`）
- 白天流程：公布死讯 → 猎人开枪 → 判胜负 → 骑士决斗 → 判胜负 → 标记发言 → 放逐投票 → 白痴免疫 → 白狼王带人 → 猎人开枪 → 判胜负
- 标记系统：1 身份声明 + 2~4 评价标记（按存活人数 2/3/4，`rules.ts:173-177`）、公开顺序发言、提交后立即公开
- 标记身份选项**动态**（当局有的职业才出现）+ 固定「神职/好人」+ 评价专属「狼人」
- 标记理由：4 通用 + 2 专属（【查验结论】限声称预言家/守墓人；【用药结果】限声称女巫）——**player 可诈身份**，校验只看申报身份不看真身份（`validators.ts:75-86`）
- 投票：同时投、不可弃票、不可投自己、平票无人出局、事后公开明细
- 胜负：好人杀光狼；狼人屠边（神职全灭或平民全灭）或屠城
- 认输：视为死亡、不触发任何技能、可能直接终局（`GameManager.ts:238-277`）

**C. 信息防火墙**（`shared/privateInfo.ts` + `toPublicDeathCause`）——**最容易被漏掉、但必须移植**
- `buildMyPrivateInfo(state, player)`：按角色裁剪的私有信息（查验历史/药水状态与用药史/守护史/狼刀史/技能可用性），**真人下发与 AI 上下文共用同一份推导**
- `toPublicDeathCause`：夜间出局（被刀/被毒/同守同救）对外**统一显示为「被袭击」**，防泄露女巫与守卫（`constants.ts:275-292`）
- 遗物只在 `revealed=true` 后进入公开信息

**D. 物品/遗物**
- 月光石（被夜间行动造访次数）、天平徽章（左右邻座是否同阵营，开局定死以原始座位计算）
- 猎犬哨（死亡时存活狼人数）——**代码中存在但从未被分配**（物品池被 UI 硬编码为前两种，`CreateRoomModal.tsx:64-67`）
- 死亡即公开遗物类型+内容

**E. AI 玩家子系统**（2242 行）
- 信息过滤：公开事实 / 私有事实 / 玩家公开声明三分区，AI 不能开天眼（`AIContextBuilder.ts`）
- 6 个提示模板：系统（规则+阵营策略+角色策略）、夜间行动、标记、投票、猎人/骑士/白狼王触发
- 6 种人格：标签细读型/投票追踪型/关注低调型/死亡线索型/独立思考型/直觉流，含 `paceFactor`（节奏）与 `intuitionBias`（理由偏好），**整局固定**
- 模拟思考延迟：双随机取小 + 人格系数 + 5% 秒交/4% 卡住（`AIPlayerController.ts:40-68`）
- JSON 容错解析：直解 → markdown 代码块 → 取最后一个平衡括号对象
- 语义硬约束层：狼人不自曝、不指控队友、查验结论必须自洽、特殊理由必须匹配申报身份、狼人不刀队友、预言家不重复查验、守墓人不重复验尸、白狼王不带队友（`AIDecisionGuard.ts` 全部）
- 角色专属兜底：LLM 失败/超时/格式错时的确定性 fallback（女巫默认不用药、白狼王/猎人/骑士允许 skip）
- 决策日志：prompt + 响应 + 解析结果 + 是否重试/兜底 + 真人动作 + 终局快照

**F. 玩家可见 UI 能力**（客户端 18 个 tsx → QQ 侧需等价表达）
玩家席位环与行动高亮、阶段头、信息面板 5 个页签（公告/标记/投票/查验/我的记录）、夜晚操作面板、标记面板、投票面板、触发面板（猎人/白狼王/骑士）、遗物公开、事件提示、"我的私有信息"卡片、认输按钮、终局结算（身份全公开+胜负）、**完整复盘日志（ReplayLog，按轮次回看全部标记/投票/死亡/遗物）**

**G. 房间级容错**
- 断线：保留位 60 秒可重连；游戏中"在线玩家不设超时"，仅断线玩家 60 秒后由服务端代打（`GameManager.ts:137-232`）
- 房间空闲超时清理（30 分钟全离线）

### 2.2 迁移到 QQ 后的承载方式总览

| 源承载 | QQ 承载 |
|---|---|
| Socket.IO 推送 | 群广播 + 私聊（`session.broadcast` / `whisper`） |
| 各角色私有面板 | 私聊消息 + 「我的记录」指令（按需重发） |
| React 席位环 / 信息面板 | 文本面板 + `@我 面板` / `@我 记录` 指令 + 合并转发（`session.send_forward`） |
| 终局结算页 / 复盘日志 | `render.text_card` 文本卡片 + 分页 + 合并转发；出图为可选增强（需自研 PIL） |
| `room:*` socket 事件 | `on_command` 指令（加入/离开/开始/踢人/加AI 等） |
| `client:*` socket 事件 | 私聊 `ask` 等待 + 群内 `ask` 等待 |
| 房间号 6 位、多房间并存 | 一群一局（`GameRunner` 按 group_id 唯一） |
| 昵称 | QQ 群昵称（`core.user.get`） |
| 断线重连 | 超时兜底 + `@我 离开`（无重连概念） |

### 2.3 明确**不在**迁移范围（源项目声明但从未实现）

| 项 | 证据 | 处理 |
|---|---|---|
| 警长系统 | `game-design.md:226-249` 整章被注释掉，标"待定不实现" | 不做 |
| 4 人局深度模式（两条命+双遗物） | `four-player-mode.md` 纯设计稿；`deepMode` 字段全仓只出现在类型定义与 `CreateRoomModal` 里被写死 `false` | 不做（除非用户要求补齐） |
| 遗言 | 同上，`lastWords` 字段从未被读取 | **建议补齐**（成本极低：房间开关 + 放逐者一条群消息），但需用户确认 |
| 猎犬哨启用 | `ITEMS.HOUND_WHISTLE` 只出现在显示映射与 AI 文案里，物品池从未包含它 | **建议补齐**（7 人以上局自动进池），成本极低 |
| HTML 图片渲染 | 不存在 | 见修正 1 |

---

## 3. 目标架构（文件清单）

```
src/plugins/games/silent_mark/
├─ __init__.py          # import game → try import commands（照抄 deep_sea_mission/__init__.py:7-15）
├─ game.py              # GameBase 子类：主状态机（对应 GameManager.ts）
├─ engine/              # 纯逻辑，无 IO，可单测 —— 对应 rules.ts + roles/* + privateInfo.ts
│   ├─ constants.py     # 角色/阵营/阶段/死因/物品/理由/预设板子（对应 shared/constants.ts）
│   ├─ roles.py         # 10 个角色处理器（触发/可用目标/夜间行动/放逐钩子）
│   ├─ resolve.py       # 夜晚结算 / 投票结算 / 胜负判定 / 标记合法性 / 评价数量 / 动态身份选项
│   └─ private_info.py  # build_my_private_info / to_public_death_cause（信息防火墙）
├─ syntax.py            # 玩家输入语法解析（标记/投票/夜间）+ 反向渲染提示文本
├─ views.py             # 群内面板/公告/遗物/复盘/结算 的文本渲染（对应客户端 UI 能力）
├─ commands.py          # 报名房间 + 房主配置 + 游戏内指令（对应 room:* 事件）
├─ config.py            # pydantic 配置（时长、AI 开关、默认板子）
├─ ai/                  # 对应 server/game/ai/*
│   ├─ context.py       # build_ai_context + context_to_text
│   ├─ prompts.py       # 系统/夜间/标记/投票/触发 提示模板（对应 AIPromptTemplates.ts）
│   ├─ guard.py         # 语义硬约束（对应 AIDecisionGuard.ts）
│   ├─ persona.py       # 6 种人格 + 整局固定分配
│   ├─ controller.py    # 决策入口 + 思考延迟 + JSON 容错 + 兜底
│   └─ logger.py        # 决策日志（写 logs/，不写 DB）
├─ models.py            # 可选：game_silent_mark_record 对局记录表（复盘用）
└─ README.md

docs/games/silent-mark.md                     # 玩法 + 状态机 + 输入语法 + Prompt 设计 + 边界
scripts/cli_adapters/silent_mark.py           # CLI 适配器（热座）
tests/games/silent_mark/                      # 单测（见 §12）
```

**必须同时改动的注册点**（缺失任一项游戏就不可用）：

| 文件 | 改动 |
|---|---|
| `src/bot.py` | `nonebot.load_plugin("src.plugins.games.silent_mark")` |
| `src/plugins/core_commands/handlers.py` | `HELP_TEXT` 加一节；`_QUICK_CMD` 加 `"silent_mark": "@我 静夜标记"` |
| `src/plugins/message_router.py` | `_FALLBACK_HELP` 视情况补充 |
| `scripts/play_cli.py` | import + `ADAPTERS["silent_mark"] = SilentMarkCLIAdapter` |
| `src/core/storage.py` | 若建 `models.py`，追加到 `_import_all_models()` |
| `README.md` | 游戏列表 |

---

## 4. 交互通道设计（**这是全项目最关键的决策，先定死**）

静夜标记的核心卖点是"删掉自由发言"。因此它与 QQBot 现状的契合度极高：

> **`event_driven` 可以完全关闭**——不需要 `on_player_action`，因为游戏本身没有"玩家随时发言"这个环节。一切输入都是被询问的。[源项目也是同样的性质：所有玩家动作都由服务端 prompt 驱动。]

主循环采用 **范式 A（命令驱动 / `session.ask` 顺序推进）**，理由：

1. 源项目夜晚与标记阶段**本来就是严格顺序**的（`NIGHT_ACTION_ORDER` 逐个、`markingOrder` 逐个），顺序 `ask` 是最直接的同构。
2. CLI 热座模式天然是"轮到谁 → 谁输入"，与 `ask` 一一对应，CLI↔Bot 一致性最容易保证。
3. 避开了 `event_driven` + 定时器累加那套更复杂、更易出竞态的机制。
4. 源项目里"同时"的两个场景（狼人合议、全员投票）都能用**顺序收集 + 收齐后统一公布**等价实现，语义不丢（只丢"并发感"）。

### 4.1 每个动作的通道

| 玩家动作 | 通道 | 理由 | 超时 | 超时兜底 |
|---|---|---|---|---|
| 加入/离开/开始/踢人/加AI/配置 | 群内 `on_command` | 公开管理动作 | — | — |
| 收身份牌 | **私聊**（主动推） | 必须保密 | — | 私聊失败 → 点名劝退整局（同 deep_sea） |
| 守卫守护 / 预言家查验 / 守墓人验尸 | **私聊 `ask`** | 必须保密 | 60s | 按角色默认（守卫随机合法目标 / 预言家随机未查目标 / 验尸跳过） |
| 狼人合议刀人 | **私聊 `ask`**（逐狼顺序） | 保密；每个狼选完把"当前队友意向"告知后续狼，等效替代"实时看队友选择" | 60s | 从合法非队友目标随机 |
| 女巫用药 | **私聊 `ask`** | 保密（含"今夜被刀者"这一私有信息） | 60s | 不用药 |
| 猎人开枪 / 白狼王带人 / 骑士决斗 | **私聊 `ask`** | 源项目也是私密下发、结果公开 | 60s | 跳过 |
| 标记发言（1 声明 + 2~4 评价） | **群内 `ask`（@ 当前玩家）** | 标记结果本来就立即公开，"边说边交"不泄露任何信息；顺带大幅减少私聊量 | 120s | 用兜底标记（好人 + 直觉判断，照抄源项目 `submitDisconnectedFallback`） |
| 放逐投票 | **私聊 `ask`** | 需保密（结果收齐后统一公布） | 60s | 投当前被标记为"狼人"次数最多的非自己玩家，退化则随机合法目标 |
| 查面板 / 我的记录 / 复盘 | 群内 `@我` 指令 | 按需拉取，避免刷屏 | — | — |
| 认输 | 群内 `@我 认输` | 公开动作（源项目 `resignGame`） | — | — |
| 离开对局 | 群内 `@我 离开` | 源项目"游戏中断线"的 QQ 等价物 | — | — |

### 4.2 好友门槛（硬依赖）与处理

- **所有玩家必须先加机器人为好友**：夜间与投票必须私聊。
- 开局做**好友预检**：`on_start` 里逐个 `whisper` 身份牌，收集 `WhisperFailedError`；有失败者 → 点名 + `runner.end(EndReason.ERROR)`，**不开始游戏**（照抄 `deep_sea_mission/game.py:943-991`）。
- 对局中途某次私聊失败（被删好友等）：该动作按超时兜底处理并群内提示，不中断整局。
- 报名房间文案必须显式提示"请先添加机器人为好友"，与深海任务一致。

### 4.3 输入语法（`syntax.py`，CLI 与 Bot 共用同一份解析器）

必须极简，且**解析失败要能给出可读的纠正提示**。草案：

```
# 夜间（私聊，单选）
「3」或「@3号」            → 目标 = 座位 3
「不救」/「不毒」/「跳过」  → 女巫不用药、守卫不守、验尸跳过

# 投票（私聊，单选）
「3」

# 标记（群内，一行式）
标记 好人 直觉 | 3号 狼人 标记分析 | 5号 好人 直觉
  · 段 1（必填）= 身份声明：<身份> <理由>
  · 段 2..N     = 评价：<座位号> <评价身份> <理由>
  · 理由支持中文名或英文 key（intuition / vote_analysis / …）
  · 数量必须正好等于当局要求的评价标记数
```
- 同时提供**引导式备选**：`@我 标记` 不带参数时，机器人用 `session.choose` 逐项走（身份 → 理由 → 逐个目标 → 逐个评价），供不熟悉语法的玩家使用。**两条路径产出完全相同的状态**。
- 所有解析错误 → 群内/私聊回一条**结构化纠错**（错在第几段、合法值是什么），`ask` 的 `validator` 让它自动重问。

> ⚠️ 注意 `core/session.py:272` 的 `_QUIT_TOKENS = {"/quit", "/q", "退出", "quit"}`：玩家打「退出」会抛 `PlayerQuitError`。因此标记语法里**不能**把「退出」用作正常取值，且游戏要 catch 后按"认输/离开"处理而不是崩溃。

---

## 5. 逐项映射表（保真度）

| # | 源机制 | QQ 实现 | 保真 |
|---|---|---|---|
| 1 | 6 位房间号 + 多房间并存 | **一群一局**（`GameRunner` 按 group_id 唯一），房间=本群 | ⚠️ 平台改写 |
| 2 | 昵称唯一 + 2~8 字符 | 直接用 QQ 群昵称，`@` 指向清晰 | ⚠️ 平台改写 |
| 3 | 玩家在线/重连（socket） | 无重连概念 → 逐动作超时兜底 + `@我 离开` | ⚠️ 平台改写 |
| 4 | 真人在线不设超时、断线 60s 代打 | **全员逐动作超时**（时长见 §4.1）+ 兜底（照抄源项目 `submitDisconnectedFallback` 的角色分支） | ⚠️ 必须反转 |
| 5 | 狼人同时行动 + 实时看队友选择 | 逐狼顺序私聊；每次把"当前队友意向"告知后续狼；收齐后按票数聚合、平票随机 | ⚠️ 语义等价、无并发感 |
| 6 | 全员同时投票 | 逐人私聊收集（每人提交后群内只播"已投"不播内容），收齐后统一公布明细 | ⚠️ 语义等价 |
| 7 | 标记按座位顺序、提交后立即公开 | 群内 `@` 当前玩家 `ask`，提交后 immediate broadcast | ✅ |
| 8 | 动态标记身份选项 | `rules.get_available_identities` 原样移植 | ✅ |
| 9 | 标记理由合法性（看申报身份） | `validators.is_mark_reason_allowed_for_identity` 原样移植 | ✅ |
| 10 | 夜晚 5 步固定顺序 | `NIGHT_ACTION_ORDER` 常量 + 顺序循环 | ✅ |
| 11 | 夜晚结算（同守同救/毒药/月光石） | `resolve_night` 原样移植 | ✅ |
| 12 | 死亡触发链（队列、插队首、链末判胜负） | 状态机内实现同构队列 | ✅ |
| 13 | 白痴免疫 + 失投票权保有标记权 | `has_voting_right` 原样移植 | ✅ |
| 14 | 裁决结果公开但身份不公开 | 广播措辞严格区分"谁出局"与"身份" | ✅ |
| 15 | 夜间死因对外统一为"被袭击" | `to_public_death_cause` 原样移植 | ✅ |
| 16 | 私有信息按角色裁剪 | `build_my_private_info` 原样移植，**唯一出口**，真人/AI 共用 | ✅ |
| 17 | 物品/遗物（3 种 + 开关 + 池） | `ctx.state` 记录 + 死亡广播；补上猎犬哨进池 | ✅（并补齐源项目未启用项） |
| 18 | 结算：身份全公开 + 胜负 | 文本卡片（分页）+ 发奖 | ✅ |
| 19 | 复盘日志（按轮次） | `@我 复盘` → 分页文本 / `send_forward` 合并转发 | ✅（形态改写） |
| 20 | 席位环 / 阶段头 / 事件提示 | 文本面板 + 必要时 `broadcast_rich` 出图 | ✅（形态改写） |
| 21 | AI 玩家全套 | §9 专项 | ✅ |
| 22 | AI 取名 + 测试连接 | `core.llm` 调用取名；`@我 测试AI` | ✅ |
| 23 | 房主踢人 / 加AI / 移除AI | 报名阶段指令 | ✅ |
| 24 | 房间空闲 30 分钟清理 | 报名房间加定时清理（`schedule_once`） | ✅ |
| 25 | 认输 | `@我 认输`，走 `handleResign` 同构逻辑 | ✅ |

---

## 6. 必须自研的组件（core 缺口与对策）

| 缺口 | 对策 |
|---|---|
| **无图片渲染** | 默认文本卡片；出图可选（自研 PIL，参考 `aoe3_battle/bracket_renderer.py`） |
| **无阶段级可取消计时器** | `scheduler.schedule_once(delay, cb, tag=f"sm:{sid}:{phase}")` → 存 `job_id`，阶段推进时 `cancel(job_id)` |
| **整局超时未武装** | 不依赖它；用 `schedule_once` 自建"整局上限"（如 60 分钟）+ 逐动作 timeout |
| **无并发聚合原语** | 顺序 `ask` 收集 + 计数到齐触发结算（范式 A 天然不需要聚合） |
| **`ask` 遇到 `/结束` 抛 `CancelledError`** | 统一包一层 `_ask_or_default()`，`except asyncio.CancelledError: raise`，其余异常走兜底 |
| **无中途存档恢复** | 现状：重启丢局。**可选增强**见 §7.4 |
| **无结构化输出 schema** | `json_mode=True` + 移植源项目 `extractJSON`（三层容错） |

---

## 7. 状态模型与持久化

### 7.1 `ctx.state` schema（草案）

```python
{
  "phase": "night|day_announcement|day_trigger|day_knight|day_marking|day_voting|game_over",
  "round": 1,
  "status": "playing|finished",
  "settings": {                      # 房主配置（对应 GameSettings）
      "mode": "preset|custom", "preset": "6standard", "roles": {"werewolf": 2, ...},
      "items": {"enabled": True, "pool": ["moonstone", "balance"]},
      "timers": {"night_action": 60, "marking": 120, "voting": 60},
      "last_words": False, "win_condition": "edge",
  },
  "players": [                        # 与源项目 GamePlayer 同构
      # pid 是玩家标识，语义等价源项目的 userId: string。
      # 人类玩家用 str(qq_id)，AI 座位与调试座位用自造 id（如 "ai:1" / "seat:uuid"）。
      # 规则内核（engine/）只认 pid，永不接触 QQ 号。
      {"pid": "10001", "nickname": "...", "seat": 3, "role": "werewolf",
       "faction": "evil", "alive": True,
       "items": [{"type": "moonstone", "value": 0, "revealed": False}],
       "role_state": {...}}
  ],
  "seat_owners": {"10001": 10001, "ai:1": None},   # pid → 控制者 qq_id（AI/托管为 null）
  "is_ai": ["ai:1"],                               # AI 座位（M4 用）
  "night_actions": {"guard": None, "wolves": None, "witch": None, "seer": None, "gravedigger": None},
  "night_current_role": "werewolf",
  "marking_order": ["10001", "10002"],   # 存 str
  "marking_current": 0,
  "pending_triggers": [{"type": "hunter_shoot", "qq_id": "10003"}],
  "collected_votes": {"10001": "10003"},
  "history": {"rounds": [], "marks": [], "votes": [], "deaths": []},
  "winner": None,
  "ai": {"10007": {"persona": "gut_player"}},      # AI 玩家登记 + 人格
  "panel_message_id": 123,                         # 常驻面板（用于撤回）
  "private_message_ids": {"10001": 456},           # 私聊消息 id（用于撤回/替换）
}
```

### 7.2 硬性纪律

1. **所有以玩家为 key 的 dict，key 一律用 `pid: str`**（`pid` 与 QQ 号的映射只放 `seat_owners`，规则内核不接触 QQ 号）。列表元素读回时统一按需转换（照抄 `deep_sea_mission` 的做法，`game.py:1231-1238`）。这样做的收益：AI 座位/调试座位天然可用（一个 QQ 控制多个座位），且与源项目 `userId: string` 语义一致，`engine/` 可以整体平移。
2. 状态必须 JSON 可序列化（不能塞 `User` 对象、不能塞 `datetime`）。
3. 每个玩家动作/阶段推进后调 `runner.persist()`（照抄 `deep_sea_mission/game.py:1379-1382`）。
4. `on_end` 必须撤回私聊与常驻面板（`session.delete_message`），并释放定时任务。

### 7.3 崩溃恢复：现状与选择

`recover_active_sessions` 会把重启后的进行中局面一律判 aborted（`game_base.py:384-405`）。一局 10~30 分钟的窗口内服务器重启概率低，**默认接受丢局**；在文档与开局提示里写明。

### 7.4 可选增强：真正的断点续跑

`ctx.state` 已经**每步落库**（`GameSessionRecord.state`），且主循环是"顺序脚本"，因此**具备续跑条件**：重启后读回 `state`，从 `phase` 的下一动作继续 `ask` 循环即可。需要：
- 游戏实现 `load_state` 并在启动钩子里注册"恢复回调"（现有 `recover_active_sessions(on_recovered=...)` 参数就是为这个留的，目前被忽略）；
- 恢复后重新注册 session、重新拉取玩家列表、给每个玩家重发一次"当前该谁"的私聊提醒。

列为 M6 之后的增强项，需要用户拍板（成本约 +300~400 行 + 1 组集成测试）。

---

## 8. 并发与超时总设计

### 8.1 主循环形态

```
on_start:
  1. 好友预检 + 私聊发身份牌（失败 → 劝退）
  2. 分配座位/身份/物品/人格；广播开局面板
  3. while status == playing:
       夜晚：按 NIGHT_ACTION_ORDER 顺序，对每个"有该角色且存活"的玩家私聊 ask
             → 狼人组内逐个 ask 并互相告知意向 → resolve_night
             → 广播死讯（夜间死因统一"被袭击"）+ 公开遗物
             → process_death_triggers（猎人/白狼王队列，链末判胜负）
             → 骑士决斗（如有且未用）→ 判胜负
       白天：标记阶段（按座位顺序，逐人群内 ask）
             → 投票（逐人私聊收集，收齐公布）→ 白痴免疫/白狼王/猎人 → 判胜负
             → 未结束：round++ 继续
  4. 结算：身份全公开 + 发奖 + 复盘入口
```

### 8.2 统一等待封装（**必须实现，且要有单测**）

```python
async def _ask(self, ctx, *, qq_id, prompt, timeout, channel) -> str | None:
    """返回 None 表示"按兜底处理"。CancelledError 必须冒泡。"""
    try:
        return await session.ask(qq_id, prompt,
                                 group_id=ctx.group_id if channel == "group" else None,
                                 timeout=timeout)
    except GameTimeoutError:            # core.errors.TimeoutError
        await session.broadcast(ctx.group_id, f"⏰ @{nick} 超时，按默认处理。")
        return None
    except PlayerQuitError:
        await session.broadcast(ctx.group_id, f"🚪 @{nick} 退出（等同认输）。")
        return _QUIT
    except WhisperFailedError:
        await session.broadcast(ctx.group_id, f"⚠️ @{nick} 私聊不可达，按默认处理。")
        return None
    # asyncio.CancelledError 故意不捕获：/结束 时让它冒泡退出主循环
```

### 8.3 兜底矩阵（对应源项目 `submitDisconnectedFallback`，逐角色保留语义）

| 阶段 | 兜底 |
|---|---|
| 守卫 | 从合法目标随机（已排除上次守护对象） |
| 狼人 | 从合法非队友目标随机（源项目也是"合法目标[0]"，此处允许随机以贴近源项目兜底） |
| 女巫 | 永远 `none`（不使用药物） |
| 预言家 | 未查验过的合法目标随机 |
| 守墓人 | 无死者自动跳过；有死者随机 |
| 标记 | 身份=好人 + 理由=直觉 + 按嫌疑度排序取 N 个目标（源项目兜底逻辑） |
| 投票 | 排除自己后随机 |
| 猎人/白狼王/骑士 | `skip` |

---

## 9. AI 玩家迁移方案

这是本次移植的**最大增量价值**（web 版的 AI 子系统是完整实现的，而 QQBot 恰好有统一 LLM 网关）。

### 9.1 映射

| 源 | 目标 |
|---|---|
| `AIContextBuilder.buildAIContext` + `contextToText` | `ai/context.py`：**信息过滤唯一出口**，直接复用 `engine/private_info.py` 的 `build_my_private_info`，保证"AI 与真人看到同一份裁剪规则" |
| `AIPromptTemplates`（系统/夜间/标记/投票/触发 6 模板 + 角色策略） | `ai/prompts.py`：文本原样移植（中文策略文案是最有价值的资产，不要重写） |
| `AIDecisionGuard`（硬约束） | `ai/guard.py`：移植 `guardVote` / `guardNightAction` / `guardMarking`，以及 `guardTriggerAction` 的**白狼王分支**。⚠️ 触发校验里的"猎人/骑士不应选择已确认好人"**不可实现**（这两者没有查验能力，`collectSeerResults` 对其返回空，"已确认好人"这种私有信息在他们身上不存在），源项目 502ef26 已核实并改为注释说明 —— **不要移植成永不触发的死代码**。这是最容易写错、最该独立单测的部分 |
| `AIPersona`（6 人格 + 整局固定） | `ai/persona.py`：整局固定分配（按 `session_id` 而非座位，避免可预测） |
| `AIPlayerController`（延迟/容错解析/兜底） | `ai/controller.py`：`callLLM` → `core.llm.chat(scene="silent_mark_ai", json_mode=True)` |
| `AIApiClient` | 直接删除，改用 `core.llm` |
| `AILogger`（JSON 文件） | `ai/logger.py`：写 `logs/silent_mark_ai/`，与源项目同构；**不写 DB** |
| `generateAIName` | `core.llm.chat(scene="silent_mark_ai_name")` + 默认名字池回落 |

### 9.2 需要的 LLM 场景（追加到 `config/llm.yaml`）

```yaml
silent_mark_ai:            # AI 玩家决策：温度低、要 JSON、超时短
  provider: zhipu
  model: glm-4-flash-250414
  temperature: 0.3
  max_tokens: 1024
  json_mode_default: true
  timeout_seconds: 30
silent_mark_ai_name:       # AI 取名
  provider: zhipu
  model: glm-4-flash-250414
  temperature: 0.9
  max_tokens: 20
  json_mode_default: false
  timeout_seconds: 20
```

### 9.3 必须处理的新问题（源项目没有的约束）

1. **提示长度**：源项目 AI 上下文是"全量历史文本"，12 人局后期会很长。`glm-4-flash` 的 `max_tokens` 是**输出**上限，输入长度取决于模型上下文窗口。需要：只喂"最近 N 轮完整 + 更早轮次摘要"（源项目 `ai-improvement-plan.md` P1.4 已经提出这个方向，正好在移植时直接实现）。
2. **无 `response_schema`**：沿用 `json_mode=True` + 三层 `extractJSON` 容错。
3. **API 调用耗时 vs 交互节奏**：源项目给 AI 加了 3~15 秒"思考延迟"，在 QQ 群里这个延迟**反而有用**（掩盖 LLM 延迟、更像真人）。可直接移植 `getRandomDelay` 的分布设计。
4. **成本**：每轮约 存活人数 次调用（标记+投票）+ 夜间若干。9 人局 3 轮 ≈ 60~80 次调用。用 flash 级模型可控，但需要在 `config/llm.yaml` 里可切换（用户可选更强模型换更好的推理质量）。
5. **AI 与真人同权校验**：AI 的动作必须走**与真人完全相同**的合法性校验路径（源项目 `validateAction` 语义），禁止为 AI 开后门。
6. **AI 失败不能卡死**：`controller` 必须有"LLM 异常/超时/格式错 → 重试 1 次 → 角色专属兜底"的三级保证（源项目 P0 已实现，原样移植）。

---

## 10. CLI 适配器方案（铁律：CLI 跑通 = 群里能跑）

- **热座模式**：单终端顺序扮演所有座位（照抄 `deep_sea_mission` adapter 的做法）。
- **私密信息折叠**：CLI 里把"每个座位应看到的私聊"在**轮到该座位时**打印出来（比深海任务"全部公开打印"更保真，因为我们有明确的 turn 概念——轮到谁就显示谁能看到的东西）。
- **复用本体**：`engine/*`（全部纯逻辑）、`syntax.py`（**同一个解析器**，这是 CLI↔Bot 一致性的核心抓手）、`views.py`（同一份文本渲染）、`ai/*`（CLI 里可开 AI 座位，方便单人调试 4 人局）。
- **`MODES = SilentMarkGame.MODES`**（直接引用，禁止本地复制——`aoe3_battle` adapter 的 MODES 漂移是反面教材）。
- **必须实现 quit 分支**（`quit/exit/退出/结束`）。
- **超时不模拟**（CLI 无超时，属 `docs/13` 允许的机制差异），但要提供 `timeout` 调试开关。
- **不发真钱**：CLI 只打印 `+N coin / +N score`（照抄海龟汤）。
- 注册：`scripts/play_cli.py` import + `ADAPTERS["silent_mark"]`。

---

## 11. 施工顺序（M0–M6）

> **最终交付范围固定为 §2.1 全清单**；下列里程碑只是施工顺序与验收节点，不是取舍。每个里程碑都要求 CLI + Bot 双路径可跑通并有验收记录。

| 里程碑 | 内容 | 交付物 | 验收 |
|---|---|---|---|
| **M0 骨架** | 目录/注册/常量/角色表/预设板子/`engine/resolve.py`/`private_info.py` + 单测（从 `p0Rules.test.ts`、`privateInfo.test.ts` 逐条转 Python） | engine 全绿单测 | `pytest tests/games/silent_mark` |
| **M1 单局闭环** | 报名房间（加入/离开/开始/踢人）+ 好友预检 + 发身份 + 夜晚 5 步 + 死讯 + 标记 + 投票 + 胜负 + 结算 + CLI 骨架。**硬要求：任何兜底失败都必须推进阶段，绝不原地等待**（`fallback_*` 返回 None ⇒ 记录代打事件后继续） | 4 人局端到端 | CLI 与真机群各跑通一局 4 人局（狼胜/好人胜各一次） |
| **M2 触发链齐全** | 猎人/白狼王/骑士/白痴/守墓人全接入 + 死亡链统一判胜负 + 认输 + 兜底矩阵。**认输必须与其它出局路径一致：`revealed=True` + 写 `relics`**（源项目 502ef26 修过这条，早年实现遗漏会变成"用认输藏遗物"的漏洞） | 10 角色全通 | CLI 构造用例覆盖每种出局方式 × 每种技能 |
| **M3 全板子 + 物品** | 12 套预设 + 自定义配置分步向导 + 物品/遗物（含猎犬哨进池、玩家开关）+ 遗言（若拍板） | 12 板子全可开 | 12 板子逐个人数校验 + 自定义边界（3 狼 3 好人被拒等） |
| **M4 AI 玩家** | `ai/*` 全套（上下文/提示/人格/守卫/兜底/日志）+ 房主加 AI/移除/测试 + 场景配置。已知注意点：① 提示词**不得提供规则层会拒绝的选项**（守卫是必选、守墓人只在无死者时可跳过）；② 座位号解析必须同时接受数字与数字字符串；③ 触发校验**只保留白狼王"不带走队友"**——猎人与骑士没有查验能力，"不应选已确认好人"在他们身上不可实现，不要写成永不触发的死代码（源项目 502ef26 的结论） | AI 可参与完整对局 | AI 混编局（2 真人 + 2 AI）连胜 5 局无卡死；guard 纠正日志可读 |
| **M5 体验与复盘** | 信息面板（公告/标记/投票/查验/我的记录）、`@我 记录` 私聊重发、复盘（分页 + 合并转发）、结算出图（可选）、经济发奖、事件提示 | 玩家可见信息面 100% 覆盖客户端 UI 能力 | 逐条对照 §2.1-F 清单打勾 |
| **M6 全量回归** | 12 板子 × 角色组合 × AI 混编回归；CLI↔Bot 一致性核对表；`docs/games/silent-mark.md` 完稿；README/帮助/菜单登记 | 可发布版本 | `docs/13` 检查清单全绿 + 真机群连打 10 局 |

> M0/M1 是**风险最大的部分**（`ask` 是仓库首用、`CancelledError` 无先例），建议先把 `_ask` 封装 + 超时兜底 + `/结束` 打断这三件事做成可复用的小模块并配单测，再往上堆业务。

---

## 12. 测试与验收

### 12.1 单元测试（`tests/games/silent_mark/`）

从源项目既有测试**逐条转写**（不要重写）：
- `p0Rules.test.ts` → `test_resolve.py`：夜晚结算（同守同救、毒药、守护、平安夜）、投票结算（平票）、胜负（屠边/屠城/好人胜）
- `privateInfo.test.ts` → `test_private_info.py`：每个角色的私有信息裁剪 + 平民为空 + 技能状态
- `aiContextBuilder.test.ts` → `test_ai_context.py`：AI 不能看到自己不该看的信息
- 新增：`test_syntax.py`（输入语法全部合法/非法组合）、`test_guard.py`（`AIDecisionGuard` 全部硬约束）、`test_roles.py`（10 角色的可用目标与技能限制）、`test_fallback.py`（每个阶段的超时兜底产物合法）

### 12.2 集成测试

- `asyncio.CancelledError` 路径：主循环阻塞在 `ask` 时执行 `/结束`，断言主循环干净退出、私聊被撤回、无残留 timer。
- 私聊失败路径：mock `session.whisper` 抛 `WhisperFailedError`，断言整局劝退且不进入夜晚。
- 12 人局状态体积：断言 `ctx.state` 序列化后体积可接受、往返后 key 类型不变。
- LLM mock：AI 决策全部用 mock，不打真实 API（`src/testing/harness.py` 已提供 whisper 打桩范式）。

### 12.3 真机验收（无法在本地替代）

- 4/6/9 人局各至少 1 局完整运行（含真人与 AI 混编）。
- 私聊可达性实测：确认群成员加好友后能稳定收私聊，观察 QQ 私聊风控（一局约 10~30 条私聊）。
- 消息节奏实测：确认 `broadcast` 节流下人机体验（源项目 UI 是即时推送，QQ 是逐条消息）。
- `/结束` 打断、认输、超时兜底在真机上各验证一次。

### 12.4 CLI↔Bot 一致性核对（`docs/13` 检查清单的具体化）

指令集、选项数量与顺序、状态机转移、超时值与后果、兜底行为、结算文案结构——逐项在 CLI 与群内对照。**`syntax.py` 与 `views.py` 是共用模块，一致性风险主要来自"通道差异"（群内 vs 私聊），因此要在文档中显式登记这条允许差异。**

---

## 13. 风险登记表

| # | 风险 | 级别 | 对策 |
|---|---|---|---|
| 1 | **玩家不加好友 → 游戏完全不可玩** | 高 | 开局好友预检 + 报名页强提示 + 劝退文案（同 deep_sea） |
| 2 | QQ 私聊风控（一局 10~30 条私聊） | 中高 | 减少私聊量：标记走群内；私聊仅夜间/投票/触发；实测观察 |
| 3 | `ask` 是仓库首用，`CancelledError` 无先例 | 高 | M0 先做 `_ask` 封装 + 单测 + 集成测试；统一异常策略 |
| 4 | 一局耗时可能显著长于 web 版（消息往返 ~35-45 次） | 中 | 超时收紧 + AI 补位 + 允许房主调时长 |
| 5 | 12 人局在 QQ 群实际凑人困难 | 中 | 板子全保留；AI 补位让任何人数都能开（这正是 M4 的价值） |
| 6 | LLM 成本与延迟（9 人局 3 轮 ≈ 60~80 次调用） | 中 | flash 级模型 + 可换场景配置 + AI 思考延迟掩盖延迟 + 日志可统计 |
| 7 | 服务器重启丢局 | 低 | 文档告知；可选做 §7.4 续跑 |
| 8 | 群消息刷屏 / 2000 字限制 | 中 | 常驻面板"撤回后重发"（`delete_message`）+ 复盘走分页/合并转发 |
| 9 | `ctx.state` int/str key 混用导致"找不到玩家" | 中 | 强制 str key 纪律 + 序列化往返单测 |
| 10 | 状态机细节写错（触发链 / 同守同救 / 白痴失投票权） | 高 | 先转写源项目测试再写状态机（M0 前置） |
| 11 | `docs/03-core-api.md` 与实际 API 漂移（如 render）误导开发 | 中 | 本次已发现；建议单独修正该文档（见 §15） |

---

## 14. 需要拍板的决策点

| # | 决策 | 建议 |
|---|---|---|
| 1 | 游戏 id / 中文名 / 触发词 | 建议 `silent_mark` / 「静夜标记」/ `@我 静夜标记`（别名 `标记`、`silent_mark`） |
| 2 | 标记提交通道 | 建议**群内提交**（内容本就公开，省一半私聊）；若要 100% 还原 web 的"私密提交"可改为私聊 |
| 3 | 是否默认允许 AI 补位 | 建议允许，房主可控；这是 12 板子能落地的前提 |
| 4 | AI 决策模型 | 建议 `glm-4-flash-250414`（成本/延迟优先），场景可配 |
| 5 | 是否补齐源项目未实现项：遗言 / 猎犬哨进池 / 房间物品开关 | 建议**遗言 + 猎犬哨 + 物品开关都补齐**（成本极低，且字段本来就在）；警长、深度模式不做 |
| 6 | 是否做 §7.4 断点续跑 | 建议列入 M6 后增强，先不做 |
| 7 | 是否要出图（席位图/战报图） | 建议先纯文本，M5 视体验再定 |

---

## 15. 附：本次核验发现的既有缺陷（**与本次移植无关，建议单独修**）

| # | 位置 | 问题 | 影响 |
|---|---|---|---|
| 1 | `scripts/cli_adapters/deep_sea_mission.py:86,95` | 调用 `draw_tasks` 但**从未 import** | `uv run python scripts/play_cli.py deep_sea_mission` 在 `start()` 阶段必抛 `NameError`，CLI 起不了深海局 |
| 2 | `scripts/cli_adapters/deep_sea_mission.py:226-281` | `play()` **无 quit/结束分支** | 与 `docs/13-cli-bot-parity.md:112`「CLI quit = Bot /结束」冲突，输 `quit` 被当出牌拒绝 |
| 3 | `scripts/cli_adapters/aoe3_battle.py:44-75` | 本地复制 `MODES` 且缺 `rival_tournament` | 违反「MODES 单一权威来源」，CLI 少一个模式 |
| 4 | `scripts/cli_adapters/aoe3.py:113` | 使用 `C.RESET`，但 `base.py:20` 只定义了 `C.R` | 该分支触发时 `AttributeError` |
| 5 | `docs/03-core-api.md:321-343` | 记载 `render_html` / `render_text_card` / `image()`，实际不存在 | 文档误导开发（本次核验已确认，建议修正为实际导出） |
| 6 | `docs/03-core-api.md:97-131` | 记载 `session.ask/choose/wait_any` 为通用原语，但实际零使用、零测试 | 不算错，但应标注"未验证" |

---

## 附：与上一版评估的差异摘要

| 项 | 上一版评估 | 本次核验结论 |
|---|---|---|
| 出图能力 | 说 `core.render` 可出图 | ❌ 纯文本；出图需自研 PIL，降级为可选 |
| 交互范式 | 未定 | ✅ 定为**顺序 `ask` 主循环**，因为本作天生无自由发言 → `event_driven=False` |
| 范围 | 建议 MVP（4/5/6 人局 + 6 角色） | ✅ 改为**全量**：10 角色 + 12 板子 + 物品 + AI 玩家 + 复盘 |
| 触发链/信息防火墙 | 未单列 | ✅ 确认为最高风险模块，M0 必须先转测试 |
| 既有缺陷 | 未发现 | ✅ 发现 4 个源无关缺陷（§15） |
