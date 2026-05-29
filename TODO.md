# TODO

> 待办事项 —— 需在本机 / 装了游戏的机器上处理。做完即删；功能说明见 `docs/`。

---

## 🔴 AoE3 数据管线：权威源入库 + 重跑 parser

**背景**：仓库里只有 `seeds/aoe3/units.json`（~1.2MB 二手产物）；`protoy.xml` 不入 git，parser 错则无法对账修。`ATTACK_PRIORITY` 层级已暂定为 **Volley/Stagger > 具名 > Defend**（远程步兵齐射、纯骑兵交错），**是否正确须全量 protoaction 验证**，当前不能靠推断定案。**未重跑**，JSON 仍是旧数据。

**核对参考**：[AOE 3 Home City](https://aoe3homecity.com/zh-CN/units?type=military&tags=Mercenary)

**待办**（有 `Data.bar` / `E:\aoe3_extracted` 的机器）：

1. **重跑**：`aoe3_bar_extractor.py` → `aoe3_gamedata_parser.py`，提交新 `units.json`（禁止手改 seeds）
2. **验收**：`demercirishbrigadier` Volley **2–12**；`mercmanchu` 仍为 `BowAttack`；远程骑兵（如 dragoon 类）远程槽来自 **Stagger**；抽查 `skirmisher` / `musketeer`
3. **影响面**（旧 JSON 估算）：157 单位 Defend/Volley 双姿态；30 条 windup 已分叉；仅 1 条 `range=0` 硬伤
4. **权威层入库**（对齐 RA2 `data/ra2/`）：parser 另导出 `data/aoe3/protoactions.json`（或等价）——**全 protoaction 整包、不选代表**；`units.json` 降为模拟器/卡片用的派生视图。**此项是下列所有核实的前置条件**
5. **验证代表攻击选取层级**（依赖第 4 项全量数据，禁止靠猜）：
   - 设计假设：`Volley/Stagger > 具名主攻击 > Defend`（远程/近战同理；Defend 为手动防御阵型）
   - 对**每个战斗单位**列出全部 protoaction，核对：是否存在「有 Volley 却应选具名/Defend」或「无 Volley/Stagger 却应选 Defend」等反例
   - 重点抽样：火枪/散兵（有齐射）、dragoon 类（交错）、满洲兵 `BowAttack`（无齐射）、爱尔兰准将（Defend 与 Volley 分叉）、英雄（技能 vs 常态射击）
   - 产出：确认或修订 `_ranged_attack_priority` / `_melee_hand_priority`；反例写入文档或单测 fixture
6. 模拟器/卡片显式绑定动作名（如 `VolleyRangedAttack`），弱化或移除 `ATTACK_PRIORITY` 猜默认值
7. **核实具名表**（`NAMED_RANGED_ATTACK_ORDER` / `NAMED_MELEE_ATTACK_ORDER`，依赖第 4 项）：逐条对照 protoy + [Home City](https://aoe3homecity.com) + 游戏内行为，区分：
   - **常态主攻击**（可进斗蛐蛐 DPS 循环）— 如 `BowAttack`（满洲兵主武器）、可能 `RifleAttack` / `BlunderbussAttack`
   - **一次性 / 冷却技能**（英雄技、狙击技等）— 如 `SharpshooterAttack`、`CrackshotAttack`、`LongRangeAttack`、`SwashbucklerAttack` 等**不应**压过 `VolleyRangedAttack`
   - **原则**：斗蛐蛐模拟持续对砍，用 **Volley/Stagger 常态循环**；具名层在 Volley/Stagger **之后**、Defend **之前**（多数具名单位本无齐射/交错后缀，如 `BowAttack`）
   - 产出：修订 `NAMED_RANGED_ATTACK_ORDER` / `NAMED_MELEE_ATTACK_ORDER` 白名单；确认后剔除一次性技能

**铁律**：数据第一 — 只改 parser/extractor，不手改 `seeds/aoe3/units.json`。

**相关**：`docs/games/aoe3-battle.md` §3.9、`.cursor/rules/aoe3-attack-data-design.mdc`

**优先级**：高

---

## 📐 AoE3 斗蛐蛐：阵线宽度 + 兵种碰撞体积（AOE 打不满）

炮兵及大范围 AOE 在一维共线模型里几乎每发溅射打满；需阵线宽度 + footprint，仅 AOE 结算用二维圆。

**待办**（先调研，暂不改模拟器）：

1. 解包调研 `protoy.xml` 体积/碰撞字段；抽样 `musketeer` / `hussar` / `cannon`
2. parser 写入 `units.json`（`footprint`，缺则按 type fallback）
3. 新 `formation.py`（`pos` + `y`）、`aoe.py`（圆内候选 + 体积）
4. `docs/games/aoe3-battle.md` §3.8 + `tests/games/aoe3_battle/test_aoe_footprint.py`

**验收**：重炮对横队溅射人数常态 **<** `round(aoe)`；骑兵切炮概率明显高于现模型。

**相关**：`docs/games/aoe3-battle.md` §3.1 / §3.8

**优先级**：中高
