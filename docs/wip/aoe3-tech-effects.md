# 帝国3科技与时代升级结算重做 WIP

- **Status**: WIP（方案已由 Owner 逐条确认，实施中）
- **Last Updated**: 2026-10-09
- **Owner**: @JimyTD
- **正式文档**: [../games/aoe3-battle.md](../games/aoe3-battle.md)（§3.9 运行时科技、§3.10 单位改良）

> 本文是会话交接的唯一依据。新会话先读本文，再看 `git status` 与“当前进度”。
> 不引用前任 agent 的结论，所有判断以 `data/aoe3/raw/` 原始数据为准。

## 铁律（Owner 定）

1. **数据权威**：`data/aoe3/raw/` 是帝国3真实解包数据。数据写什么就算什么，禁止“推断”。
   只有数据自相矛盾时才看说明文本，并带实际例子问 Owner；不能因为说明文本觉得数据错。
   例：华卡纳写“护甲 +0.05，作用步兵、轻步兵”，就是 +0.05。
2. **同一个科技只生效一次；效果合并只用统一算符，从来没有“取大”**。
3. **统一算符**（所有同类数据、所有使用处一致：生命、伤害、射程、溅射、攻速、移速、
   护甲、造价、对某类伤害倍率、蓄力冷却）：
   - `BasePercent`：按基础值，各项增量相加（1 + Σ(amount−1)）。
   - `Percent`：按当前值累乘。
   - `Absolute`：相加。
   - `Assign`/`Override`：设为该值，覆盖。
4. **每一项效果只打写明的兵**（`ProtoUnit` 目标：id 不分大小写相等或标签相等），
   **只打写明的攻击**（写攻击名只改同名攻击；`allactions` 或没写攻击名改全部）。
5. **护甲按伤害类型**：`Hand`→近战、`Ranged`→远程、`Siege`→攻城；`Armor` 没写类型三种都加。
6. **解锁要结算**：一个科技经 `TechStatus active` 激活的科技（影子或普通）、以及前置条件
   全部满足的影子科技，都一起结算。影子科技永远不出现在玩家可选列表里。
7. **已在本局时代升级里的科技跳过**（同一 id 不重复）。
8. 讨论用中文名，英文 id 放括号；必须问 Owner 的只有两类：源科技含义不清、之前完全没做过的效果。
   治疗类已定不做。

## 已查实的事实（原始数据）

- **燃烧弹**真实效果在配套影子科技 `IncendiaryGrenadesShadow`（前置：燃烧弹已研究）：
  齐射/散兵/防御远程攻击溅射 +1、迫击炮攻击 +0.5、手雷/喷火/火箭攻击 +1、迫击炮建筑/火箭建筑
  对建筑 ×1.15；墨西哥士兵、巨型掷弹兵三种远程攻击再 −0.5。前任“后缀匹配”方向错误，不做。
- **预热射击**同理（`HeatedShotShadow` 补火炮/连发/葡萄弹/弹幕/建筑攻击）。能选到的科技里
  29 条有单前置影子，37 条影子是多前置。
- 能选到的科技里 53 条经 `TechStatus active` 激活其他战斗科技，如华盛顿军团→燃烧弹、
  红衫军→护卫火枪兵、火龙经→两档猛火油柜。
- **时代升级“逐兵链与类别取大”是 `d4979db`（2026-05-29）引入的错误规则**。理由“土著逐兵传奇
  与类别传奇会 double”经数据核实不成立：没有任何科技同时给土著单兵和土著类别加血，也没有土著
  单兵有自己的 5 时代档。后果：134 个土著兵 5 时代与 4 时代完全相同，传奇土著 +50% 从未生效；
  马穆鲁克、保镖等佣兵同样少算。正确值例：阿坎安科比亚 5 时代 ×2.1（现 ×1.6）。
- 时代升级生成器其他取大：同档多条候选只选一条（通用线优先），`hp_dmg_increments` 对同一
  科技多项取 max，`_resolve_action_*` 点名与 allactions 取 max。都按铁律 2 改。
- 传奇土著、佣兵承包商不是游戏里自动生效的科技，是我们补充成时代科技的设计，保留。
- 普通斗蛐蛐没有文明：选线沿用“通用线优先，排除皇家卫队/主城卡/革命”，改为输出科技 id。
- 现有种子与生成器已有漂移（与本任务无关，重新生成时一并带上、单独说明）：
  7 条科技效果顺序不同；中国、印度、日本、豪萨通用池多出寺院攻速等几条。

## 实施方案

### 第 1 步：统一科技结算核心（`src/plugins/aoe3/tech_effects.py`）

- 输入：一个兵、本局已生效科技 id 集合（时代升级 + 选中科技）。
- 展开解锁闭包：`TechStatus active` 激活的科技；前置 `techstatus Active` 全部在集合内的影子
  科技；时代前置（`Colonialize`/`Fortressize`/`Industrialize`/`Imperialize`）按本局时代判定。
  `typecount`/`kbstat` 等本局无法判定的前置视为不满足。同一 id 只进一次。
- 结算：先收集所有打到这个兵的效果，按“字段 × 攻击名 × 对象”分组，按铁律 3 合并：
  `Assign` 覆盖（按科技顺序最后一个），然后 `BasePercent` 增量和，再 `Percent` 累乘，再 `Absolute` 加。
  删除现有 `_deduplicate_ops` / `_stat_winners` / `_apply_damage_ops` 里的取大。
- `DamageBonus` 的 `BasePercent` 按“基础倍率 ×(1+Σ增量)”算（燃烧弹对建筑 1.0→1.15），
  `Assign` 覆盖（美国海军陆战队建筑攻击对炮兵设为 1）。
- 射程、溅射的 `Assign` 按设为处理（榴霰弹等）。

### 第 2 步：时代升级改为科技 id 列表

- `scripts/crawler/aoe3_upgrades_parser.py`：输出 `{unit_id: {age: [tech_id, ...]}}` 与类别
  `{tag: {age: [tech_id, ...]}}`，不再输出合并倍率。选线规则不变（无文明）。
- `scripts/crawler/aoe3_civ_upgrades_parser.py`：输出文明专属的科技 id 列表（沿 `TechStatus`
  图，每个节点一次）。
- `src/plugins/aoe3/upgrades.py`：`apply_upgrades(unit, age, civ_id)` = 取该兵本时代科技 id
  列表，走第 1 步核心结算。`SetName` 改名照旧取最后一档。`age_upgrade_line` 改为返回 id 集合，
  供第 7 条跳过。`active_category_techs` 改为按真实是否生效展示。
- 运行时需要原始效果：从科技池/科技树生成一份“科技 id → 效果列表 + 前置 + 激活”的种子
  （`seeds/aoe3/tech_effects_index.json`，含所有有战斗/成本效果或参与解锁链的科技）。

### 第 3 步：接入与重新生成

- `civ_war_techs.runtime_tech()`、`lineup_draft._apply_combat`、`civ_war_lineups.allocate_candidate_with_techs`
  改为“时代科技 id + 选中科技 id”一次结算。
- 重新生成全部种子；对全部兵种 3/4/5 时代做改前改后全量对比，列出变化交 Owner 看。

### 第 4 步：文档

- 正式文档删除 §3.10 的 `max` 取大规则（第 1523、2066、2083 行附近）与由此算出的类别曲线描述，
  写明“同一 id 只生效一次 + 统一算符 + 解锁闭包”。

## 当前进度

- 未提交的工作区改动（第 0 步，已完成并测试通过）：效果只打写明的兵；写明攻击方式的伤害只打
  那种攻击；攻城护甲；`DamageForAllHandLogicActions` 按 `handlogic`；`UNAPPLIED_EFFECTS` 显式清单；
  摘要按兵种分写。文件：`tech_effects.py`、`civ_war_techs.py`、`tech_summary.py`、
  `tests/games/aoe3_battle/test_tech_effect_targets.py` 及几个测试适配。
- 第 0 步已提交：`6493a78`。
- 第 1 步进行中：`tech_effects.py` 已重写为统一核心（`Stack` 统一算符、`runtime_op` 统一换算、
  `settle_unit` 一次结算全部 op、`apply_techs` 合并后结算）；`civ_war_techs` 改用它。
  生成器新增 `build_tech_links()` → `seeds/aoe3/tech_links.json`（激活/前置图，尚未生成）。
  改前全部兵种 3/4/5 时代数值快照：`%TEMP%/aoe3_upgrades_before.json`（2883 条）。
  aoe3_battle 非慢测试已全部通过（测试按新规则改：点名+全部攻击相加、华卡纳三种护甲）。
- 解锁闭包已写：`src/plugins/aoe3/tech_links.py` `expand(ids, age)`；`seeds/aoe3/tech_links.json`
  已生成。判定：`activates` 递归；影子科技至少有一个非时代前置、全部前置满足才生效；只有时代
  前置的影子属于时代升级，不在这里触发。核对：燃烧弹→+影子；华盛顿军团→燃烧弹+影子；
  罗马战术 4 时代不触发影子、5 时代触发；红衫军→护卫火枪兵。
- 闭包已接入 `MatchedTech.unlocked`（摘要与 `runtime_tech()` 都含被解锁科技）。核对：燃烧弹下
  掷弹兵齐射溅射 3→4、迫击炮 3→3.5；墨西哥士兵齐射 0→0.5（+1−0.5）。
  已知缺口：红衫军→护卫火枪兵没被跳过，因为通用时代表不记科技 id。第 2 步解决。
- 第 2 步设计（定稿）：结算统一成“科技 id 列表 → `tech_links.expand` → 去重 → 科技池 op →
  `settle_unit` 一次结算”。`apply_upgrades(unit, age, civ_id=None, tech_ids=())`：时代升级 id 与
  国战选中科技 id 合并去重后一起结算，“已在时代升级里的跳过”自然成立。
  `unit_upgrades.json` 改为 `units[uid][age] = {techs: [累计 id], name}`、`category[tag][age] = [累计 id]`；
  `civ_unit_upgrades.json` 的 `techs` 改为累计 id 全列表。选线规则不变。`DIRTY_EFFECTS` 删除：
  原始数据里投石索兵现在是 +8 射程，不再有 +147。

## 暂缓（最后再看）

之前完全没做过的效果：改单位类型、开启阵型、击杀晋升、回血（治疗类，不做）、附加攻击单位、
攻击时减速对方、阵型护甲、攻击优先目标、命中暴击类、改阵型参数、改护甲类型、
所有远程攻击伤害（`DamageForAllRangedLogicActions`，数据现成，做法同近战版，可随第 1 步一起做）。
相关科技做或移出可选名单，由 Owner 决定。

## 验证

交给其他 agent 的只读验证清单见本会话记录；完成第 3 步后重新出一版。
