# TODO

> 待办事项 —— 需在本机 / 装了游戏的机器上处理。做完即删；功能说明见 `docs/`。

---

## 🔴 AoE3 数据管线：权威源入库 + 重跑 parser

**背景**：仓库里只有 `seeds/aoe3/units.json`（~1.2MB 二手产物）；`protoy.xml` 不入 git，parser 错则无法对账修。旧 `ATTACK_PRIORITY` 误用 Defend 优先（非设计意图），远程步兵/弓弩应以 **Volley** 为准；已改 parser/文档，**未重跑**，JSON 仍是旧数据。

**待办**（有 `Data.bar` / `E:\aoe3_extracted` 的机器）：

1. **重跑**：`aoe3_bar_extractor.py` → `aoe3_gamedata_parser.py`，提交新 `units.json`（禁止手改 seeds）
2. **验收**：`demercirishbrigadier` 远程应为 Volley **2–12**（非 0/3）；抽查 `skirmisher` / `musketeer` 的 `range_min`、windup
3. **影响面**（旧 JSON 估算）：157 单位 Defend/Volley 双姿态；30 条 windup 已分叉；仅 1 条 `range=0` 硬伤
4. **权威层入库**（对齐 RA2 `data/ra2/`）：parser 另导出 `data/aoe3/protoactions.json`（或等价）——**全 protoaction 整包、不选代表**；`units.json` 降为模拟器/卡片用的派生视图
5. 模拟器/卡片显式绑定动作名（如 `VolleyRangedAttack`），弱化或移除 `ATTACK_PRIORITY` 猜默认值

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
