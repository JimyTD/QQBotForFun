# AoE3 damagecap 审计报告

## 1. 本次修改后溅射池变化的单位

- seeds 中带 AOE 的条目（ranged/melee 槽）约 **149** 条
- **溅射池与旧模拟器（一律 2×合并基础攻）不同**的槽位：**48** 条
- 有 AOE 但 JSON 无 `damage_cap_*`、仍走 2× fallback 的槽位：**9** 条

旧模拟器：`damage_cap = 合并基础攻 × 2`。
新模拟器：有 `damage_cap_*` 用 protoy；否则仍 2× fallback。

下表「满溅射每人伤害」按 `min(cap / round(aoe_radius), 合并基础攻)` 在满人数溅射时的上限估算。

| id | 中文名 | 槽 | 伤害×弹丸 | aoe | 旧cap | 新cap | Δcap | 旧溅射/人 | 新溅射/人 | Δ |
|----|--------|-----|-----------|-----|-------|-------|------|-----------|-----------|---|
| mediocrebombard | 中型火炮 | ranged | 5000.0×1 | 10 | 10000 | 100000 | +90000 | 1000.0 | 5000.0 | +4000.0 |
| demaltesefireship | 火战船 | melee | 500.0×1 | 2 | 1000 | 1500 | +500 | 500.0 | 500.0 | +0.0 |
| ypfireship | 火帆船 | melee | 500.0×1 | 2 | 1000 | 1500 | +500 | 500.0 | 500.0 | +0.0 |
| legacygatlingcamel | 加特林骆驼 | ranged | 50.0×6 | 10 | 600 | 1000 | +400 | 60.0 | 100.0 | +40.0 |
| organgun | 风琴炮 | ranged | 33.0×6 | 2 | 396 | 60 | -336 | 198.0 | 30.0 | -168.0 |
| ypsiegeelephantmansabdar | 曼萨卜达尔攻城大象 | ranged | 40.0×1 | 1 | 80 | 400 | +320 | 40.0 | 40.0 | +0.0 |
| destartingunitprivateer | 勇敢的私掠船 | ranged | 20.0×1 | 1 | 40 | 200 | +160 | 20.0 | 20.0 | +0.0 |
| demercgatlingcamel | 加特林骆驼 | ranged | 14.5×6 | 2 | 174 | 29 | -145 | 87.0 | 14.5 | -72.5 |
| ypsiegeelephant | 攻城大象 | ranged | 40.0×1 | 1 | 80 | 200 | +120 | 40.0 | 40.0 | +0.0 |
| dechincharaft | 钦查木筏 | ranged | 25.0×3 | 1 | 150 | 50 | -100 | 75.0 | 50.0 | -25.0 |
| deminer | 矿工 | ranged | 30.0×1 | 5 | 60 | 120 | +60 | 12.0 | 24.0 | +12.0 |
| galley | 箭船 | ranged | 100.0×1 | 1 | 200 | 140 | -60 | 100.0 | 100.0 | +0.0 |
| demercnapoleongun | 拿破仑炮 | ranged | 75.0×1 | 2 | 150 | 200 | +50 | 75.0 | 75.0 | +0.0 |
| detank | 莱昂纳多的战车 | ranged | 100.0×1 | 3 | 200 | 150 | -50 | 66.67 | 50.0 | -16.7 |
| russiancannon | 大型加农炮 | ranged | 650.0×1 | 6 | 1300 | 1350 | +50 | 216.67 | 225.0 | +8.3 |
| spcxpredoubtcannon | 防卫据点加农炮 | ranged | 650.0×1 | 6 | 1300 | 1350 | +50 | 216.67 | 225.0 | +8.3 |
| ypmercyojimbo | 保镖 | melee | 35.0×1 | 1 | 70 | 116 | +46 | 35.0 | 35.0 | +0.0 |
| yprepentantyojimbo | 归化的保镖 | melee | 35.0×1 | 2 | 70 | 116 | +46 | 35.0 | 35.0 | +0.0 |
| deordergalley | 军团箭船 | ranged | 65.0×1 | 1 | 130 | 170 | +40 | 65.0 | 65.0 | +0.0 |
| igcdeunclefrankhorse | 法兰克叔叔 | melee | 6.0×1 | 1 | 12 | 50 | +38 | 6.0 | 6.0 | +0.0 |
| igcxpcrazyhorse | 疯马 | melee | 6.0×1 | 1 | 12 | 50 | +38 | 6.0 | 6.0 | +0.0 |
| spcdeunclefrankhorse | 法兰克叔叔 | melee | 6.0×1 | 1 | 12 | 50 | +38 | 6.0 | 6.0 | +0.0 |
| spcxpchiefbravewolf | 狼勇士酋长 | melee | 6.0×1 | 1 | 12 | 50 | +38 | 6.0 | 6.0 | +0.0 |
| spcxpcrazyhorse | 疯马 | melee | 6.0×1 | 1 | 12 | 50 | +38 | 6.0 | 6.0 | +0.0 |
| xplakotawarchief | 战酋 | melee | 6.0×1 | 2 | 12 | 50 | +38 | 6.0 | 6.0 | +0.0 |
| ypmonkindian | 婆罗门 | melee | 4.0×1 | 2 | 8 | 40 | +32 | 4.0 | 4.0 | +0.0 |
| ypmonkindian2 | 婆罗门 | melee | 4.0×1 | 2 | 8 | 40 | +32 | 4.0 | 4.0 | +0.0 |
| ypspcbrahminhealer | 婆罗门治疗者 | melee | 4.0×1 | 2 | 8 | 40 | +32 | 4.0 | 4.0 | +0.0 |
| ypmorutaru | 日本迫击炮 | ranged | 19.0×1 | 4 | 38 | 69 | +31 | 9.5 | 17.25 | +7.8 |
| mortar | 迫击炮 | ranged | 30.0×1 | 4 | 60 | 90 | +30 | 15.0 | 22.5 | +7.5 |
| ypconsulatemortar | 迫击炮 | ranged | 30.0×1 | 4 | 60 | 90 | +30 | 15.0 | 22.5 | +7.5 |
| xpskullknight | 骷髅武士 | melee | 20.0×1 | 2 | 40 | 68 | +28 | 20.0 | 20.0 | +0.0 |
| demerccapturedmortar | 被夺取的迫击炮 | ranged | 25.0×1 | 4 | 50 | 75 | +25 | 12.5 | 18.75 | +6.2 |
| ypflamethrower | 猛火油柜 | ranged | 5.0×1 | 1 | 10 | 35 | +25 | 5.0 | 5.0 | +0.0 |
| desaloonoutlawarsonist | 马拉塔火兵 | ranged | 20.0×1 | 3 | 40 | 60 | +20 | 13.33 | 20.0 | +6.7 |
| xptlaloccanoe | 雨神独木舟 | ranged | 50.0×1 | 1 | 100 | 80 | -20 | 50.0 | 50.0 | +0.0 |
| xpwarcanoe | 战斗独木舟 | ranged | 40.0×1 | 1 | 80 | 60 | -20 | 40.0 | 40.0 | +0.0 |
| derevcalifornio | 加利福尼亚西裔兵 | ranged | 20.0×1 | 2 | 40 | 24 | -16 | 20.0 | 12.0 | -8.0 |
| definnishrider | 芬兰轻装骑兵 | ranged | 20.0×1 | 1 | 40 | 52 | +12 | 20.0 | 20.0 | +0.0 |
| desloop | 单桅战船 | ranged | 110.0×1 | 1 | 220 | 230 | +10 | 110.0 | 110.0 | +0.0 |
| xpcouprider | 塔斯云坎游荡者 | melee | 15.0×1 | 2 | 30 | 40 | +10 | 15.0 | 15.0 | +0.0 |
| ypflamingarrow | 火焰之箭 | ranged | 75.0×1 | 2 | 150 | 140 | -10 | 75.0 | 70.0 | -5.0 |
| ypmercflailiphant | 连枷象 | melee | 10.0×1 | 2 | 20 | 28 | +8 | 10.0 | 10.0 | +0.0 |
| ypmercflailiphantmansabdar | 曼萨卜达尔连枷象 | melee | 10.0×1 | 2 | 20 | 28 | +8 | 10.0 | 10.0 | +0.0 |
| ypkensei | 日本武士 | melee | 28.0×1 | 1 | 56 | 60 | +4 | 28.0 | 28.0 | +0.0 |
| ypurumi | 软剑兵 | melee | 17.0×1 | 1 | 34 | 38 | +4 | 17.0 | 17.0 | +0.0 |
| ypurumimansabdar | 曼萨卜达尔软剑兵 | melee | 17.0×1 | 1 | 34 | 38 | +4 | 17.0 | 17.0 | +0.0 |
| ypnatconquistador | 西班牙征服者 | ranged | 18.0×1 | 1 | 36 | 38 | +2 | 18.0 | 18.0 | +0.0 |

## 2. basedamagecap 调研（protoy.xml）

- 含 `damagearea` 的 protoaction：**592**
- 同时有 `damagecap`：**543**
- 有 `damagearea` 但无 `damagecap`：**49**（斗蛐蛐用 2× fallback）
- 含 `basedamagecap` 子节点：**11**
- `basedamagecap` 取值分布：`{'1': 11}`

### 含义（结合 techtreey `subtype="DamageCap"` + `relativity="BasePercent"`）

- `basedamagecap` **不是**「溅射池 = 1×攻击力」的意思。
- 多为 `1`，表示该动作的 DamageCap 会随科技/升级按**基础值百分比**缩放（与 `damage` 升级方式同类）。
- 斗蛐蛐当前**不模拟**科技升级，单局内 cap 用 protoy 静态 `damagecap` 即可。

### 是否把 fallback 从 2× 改成 1×？

**不建议。** 理由：

1. `basedamagecap=1` 是升级缩放标记，不是 fallback 倍数。
2. 有 `damagecap` 的 543 条 AOE 动作里，cap/damage **中位数 = 2.0**；约 310 条落在 ~2× 桶，仅 2 条 ~1×。
3. 改成 1× 会使「无 cap 字段」的少数单位溅射减半，与数据分布和旧斗蛐蛐一致。

### 2× fallback 能否从解包「证实」？

**不能从 XML 直接读到引擎默认值**（缺字段时游戏内部怎么填 cap 不在 protoy 里写死）。

**可确认的事实**（2026-05-27 重查 `E:\aoe3_extracted`）：

| 来源 | 结论 |
|------|------|
| `protoy.xml` | 592 条带 `damagearea`；543 条同时有 `damagecap`；**49 条无 cap**（多为战役 SPC/英雄特殊攻击，如 `SPCFrigate`、`SPCFixedGun`） |
| 入库可训练单位 | 20 条「某 protoaction 有 area 无 cap」，多数为**非代表攻击**或战役/英雄变体；parser 选中的代表攻击一般仍有 cap |
| `*.tactics` | 有 `basedamagecap`、`outerdamageareadistance/factor`（距离衰减），**无**「默认 cap = 2×」常量 |
| 社区（Fandom AoE wiki 等） | 写明多数单位 Damage Cap ≈ 2× 基础伤害（掷弹兵等例外以 protoy 为准） |
| 本项目旧模拟器 | 一直用 `2×合并基础攻` |

**结论**：2× fallback 是**与数据分布、社区描述、旧逻辑一致的经验默认**；缺 cap 的 49 条在常规斗蛐蛐池几乎碰不到。若以后要更严，只能编辑器实测或反编译，不能指望再多解几个 XML。

游戏目录（本机）：`E:\SteamLibrary\steamapps\common\AoE3DE\Game\Data\Data.bar` → 提取到 `E:\aoe3_extracted`（见 `scripts/crawler/aoe3_bar_extractor.py`）。

