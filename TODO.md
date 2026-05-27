# TODO

> 待办事项列表 —— 需要在本机 / 装了游戏的机器上验证或处理的事项。
>
> **2026-05-28 进度**：AoE3 icon 提取器重写 + manifest/回补完成；windup 全量写入 `units.json`（parser ✅，模拟器待接）。

---

## 🖼️ AoE3：审计 Wiki/复制补图

**机制** ✅（2026-05-28）：`aoe3_icon_extractor.py` 重写完毕；`icon_manifest.json` / `icon_overrides.json` 产出（`data/aoe3/`，本机生成）。

**背景**（commit `83dcaa0`）：全量 icon 重建时，绝大多数来自游戏 BAR 解包；另有约 **28** 张走 AoE3 Wiki API（BAR 解不出）、约 **68** 张从基础兵种复制给变体。这批最容易「图和兵对不上」。

**现状**（2026-05-28，`aoe3_icon_extractor.py` 已重写）：

- 产出 `data/aoe3/icon_manifest.json`（`source`: bar | bar_alt | bar_portrait | wiki_api | variant_copy | missing；复制项记 `copy_from`）
- 手动覆盖：`data/aoe3/icon_overrides.json`（`force_copy_from` / `block_wiki`）
- 已跑 BAR 全量 + `--backfill-only` 回补：**2002** PNG；manifest 统计 **1870 bar + 33 bar_alt + 97 variant_copy + 1 wiki_api + 23 missing**
- 剩余 **23** 个 missing 多为 DE 彩蛋/编辑器占位（`deeggpenguin`、`testobject` 等）或 BAR 内伪 PNG（非标准 PNG/DDT，无法解码）；斗蛐蛐种子单位仅 `ypmandarinarmy` 已通过 override 临时复制

**待办**（人工验收）：

1. 对照 `icon_manifest.json` → `audit.wiki_api`（1 条：`shrine`）与 `audit.variant_copy`（97 条），在游戏内或斗蛐蛐面板核对是否错图
2. 错图写入 `data/aoe3/icon_overrides.json`，再跑 `uv run python scripts/crawler/aoe3_icon_extractor.py --backfill-only`
3. 缺 BAR 解码器的伪 PNG 格式（如 `beast_icon.png`）若需精确图，需另找解包方案或手工 PNG，勿再批量爬 Wiki

**命令**：

```bash
uv run python scripts/crawler/aoe3_icon_extractor.py          # 全量 BAR + wiki/复制
uv run python scripts/crawler/aoe3_icon_extractor.py --backfill-only  # 仅补 missing
```

**相关**：`resources/aoe3/icons/`、`docs/games/aoe3.md` §6

**优先级**：中 / 体验向 —— 主流程 BAR 图质量已够；重点审 variant_copy 清单。

---

## 🖼️ 红警2斗蛐蛐：导出兵种 icon（`ra2_battle`）

**现象**：红警斗蛐蛐开局只有中文文字面板，**没有**帝国斗蛐蛐那种兵种头像图。
代码已接通（`game.py` 用 `broadcast_rich` 发图 + 文字），但 `resources/ra2/icons/`
目前**只有 README，没有 PNG**。

**背景**（2026-05-22 确认）：

- GitHub [OpenRA/ra2](https://github.com/OpenRA/ra2) **能独立运行**（装 OpenRA + 导入原版资源后），
  但仓库里**不能**分发原版美术（版权）；头像在 `language.mix` → `cameo.mix` 里的
  `giicon.shp` 等，不在 git 里。
- `data/ra2/icon_map.json`（45 条 actor → shp 文件名）已由 `openra_ra2_export.py`
  从 sequences 自动生成，**无需**游戏文件。
- 中文名在 `data/ra2/locale_zh.json`；结算战报重复发送已修（2026-05-22）。

**待办**（需要本机已有原版 RA2 或 OpenRA 已导入内容）：

1. **安装导出依赖**
   ```bash
   uv pip install ra2mix Pillow
   ```

2. **从 cameo.mix 导出 PNG**（任选其一目录，需含 `cameo.mix` + `cameo.pal`）
   ```bash
   # Steam 原版
   uv run python scripts/crawler/ra2_icon_export.py --ra2-dir "你的红警2安装目录"

   # 或 OpenRA 已导入的内容目录（常见）
   uv run python scripts/crawler/ra2_icon_export.py --ra2-dir "%LocalAppData%\OpenRA\Content\ra2"
   ```
   也可：`--cameo-mix` / `--palette` 直接指定文件；或环境变量 `RA2_DIR`。

   产出：`resources/ra2/icons/{actor_id}.png`（脚本默认缩到 128×128）。

3. **验收**
   - 约 45 个 PNG，`file` 头为 `\x89PNG\r\n\x1a\n`
   - 单文件尽量 ≤ 50KB（过大可参考 `scripts/compress_aoe3_icons.py` 改目录跑一遍）
   - **部署到 bot 服务器**（与代码一起），群里开 `@我 红警斗蛐蛐` 应看到红/蓝方各槽位头像

**已落地**：

- 导出：`scripts/crawler/ra2_icon_export.py`（SHP 解码对齐 OpenRA `ShpTSLoader`）
- 读取：`src/plugins/games/ra2_battle/icons.py`（坏 PNG magic 校验，缺图只发文字）
- 说明：`resources/ra2/icons/README.md`、`docs/games/ra2-battle.md` §8.3

**相关文件**：

- `data/ra2/icon_map.json`
- `src/plugins/games/ra2_battle/icon_map.py`（`dog`→`adog` 等序列名别名）

**优先级**：高 / 体验向 —— 与帝国斗蛐蛐展示对齐，缺图不影响开战。

---

## ⏱️ AoE3 斗蛐蛐：调研 tactics / 动画能否解出「抬手时间」

**现象**：斗蛐蛐模拟**不算抬手（前摇）**——士兵进射程后**立即开火**（初始 CD=0），冷却只用 `protoy.xml` 的 `rof_*`（秒）。长抬手兵种偏强、短抬手兵种偏弱。

**背景**（2026-05-27，弹丸解包先例 + 网上 mod/数据社区核实）：

- **弹丸数已有先例**：`aoe3_gamedata_parser.py` 的 `_load_tactics()` 从解包 `tactics/*.tactics` 读 `displayednumberprojectiles`，与 `protoy.xml` 的 `protoaction` 按**动作名**对齐——诸葛弩（`chukonu`）等多弹丸单位因此比只看 proto 伤害更准。
- **引擎三层结构**（[AoE3 Heaven · datafiles 入门](https://aoe3.heavengames.com/modding/tutorials/beginner/datafiles/)）：
  - `protoy.xml`：数值（伤害、射程、`rof` 等）；
  - `tactics/*.tactics`：proto 与 anim 的**连接器**（每个 `<action>` 指定 `<anim>`、弹道、`rate` 等）；
  - `art/**/*.xml`（anim）：动画时长 + **`tag Attack` / `tag action 0.50 true`** 决定「动画播放到哪一帧真正结算伤害/出弹」。
- **`rof` 的含义已基本明确**（同上 Heaven 教程）：proto 里的 ROF = **`reload-time`（装填/射后冷却）**，**不是**「从下令攻击到第一发命中」的完整周期；前摇在 anim 时间轴里，**不进 proto 的 `rof` 字段**。
- **抬手 ≠ tactics 里一个简单标量**（比弹丸数难一档）：
  - [Steam · Proto & Anim Action Lists](https://steamcommunity.com/sharedfiles/filedetails/?id=821258879)：改抬手要点 anim 里的 `tag action <比例> true` 或 `length` 改动画时长；
  - [ESOCommunity · Attack delay 讨论](https://eso-community.net/viewtopic.php?t=22689)（dataminer **NewAoeIIIAi**）：各兵种 delay **差异很大**，且随升级、姿态、甚至同一单位的不同动画分支而变——**网上没有完整公开表**。
- **社区抽样数值**（Fandom + ESO 帖，单位不全，仅供校准方向）：
  | 类型 / 单位 | 约 pre-attack delay | 备注 |
  |---|---:|---|
  | 长弓手 Longbow | **~0.98s** | Fandom 写明 vs 多数远程 0.45–0.49s；ROF 仍 1.5s |
  | 多数火枪/散兵类 | ~0.45–0.49s | 基础火枪 ~0.48，帝国红衫 ~0.45；散兵 ~0.46 |
  | 弩手 Crossbow | ~0.48s | 与散兵差仅 ~0.02s，但长弓差 ~0.5s |
  | 弓骑 Cav Archer 等 | ~0.61s | 与 Dragoon 类 ~0.43s 分组，非逐单位唯一 |
  | 近战（Carolean 等） | 0.27–0.69s | 冲锋/不同挥刀动画多套 delay |
  | 弓骑特例 Yabusame/Yojimbo | ~0.25–0.28s | 弹丸甚至早于动画（desync） |
- **与斗蛐蛐偏差方向一致**：
  - 我们「进射程即打 + 只用 ROF」→ 长弓（0.98s 前摇 + 1.5s ROF）被**显著高估**；
  - 散兵/快射火枪（~0.46s 前摇）相对被**低估**；
  - Heaven 老帖也提到：长弓有拉弓动画才出箭、散兵弹丸即中，历史上影响 hit-and-run 手感（[Longbow vs Skirm](https://aoe3.heavengames.com/cgi-bin/forums/display.cgi?action=st&fn=15&tn=29856)）。
- **当前模拟器**（`simulator.py` + `docs/games/aoe3-battle.md` §3.3/§3.5）：CD = ROF；首次 CD=0；**无** windup 状态。

**调研结论（2026-05-28，本机 AoE3DE 跑通）** ✅ parser 数据已落地：

1. **只选动作，不选抬手** ✅ — 逐动作名写入 `windups`；`windup_ranged`/`windup_melee` 为代表动作整包
2. anim 在 **ArtUnits.bar** ✅
3. DE `<tag type="Attack">` 值已是秒数 ✅
4. `aoe3_gamedata_parser.py` 全量 windup ✅ — 661/756 单位有 `windups`，已重跑 `seeds/aoe3/units.json`

**待办**（模拟器 + 文档）：

1. `simulator.py`：首次 CD = 代表动作 windup（不展示在面板）
2. `docs/games/aoe3-battle.md` §3.3/§3.5 补 windup 说明

**参考链接**：

- [AoE3 Heaven · First steps / proto·tactics·anim](https://aoe3.heavengames.com/modding/tutorials/beginner/datafiles/)
- [AoE3 Heaven · gather 教程（tactics↔anim tag 机制）](https://aoe3.heavengames.com/modding/tutorials/beginner/gather/)
- [Steam · Proto & Anim Action & Logic Lists](https://steamcommunity.com/sharedfiles/filedetails/?id=821258879)
- [ESOCommunity · Attack delay/build up（无全表）](https://eso-community.net/viewtopic.php?t=22689)
- [Fandom · Longbowman（0.98s setup）](https://ageofempires.fandom.com/wiki/Longbowman_(Age_of_Empires_III))

**相关文件**：

- `scripts/aoe3_windup_research.py`（调研脚本；本机跑抽样/覆盖率）
- `scripts/crawler/aoe3_bar_extractor.py`（Data.bar + tactics；anim 在 **ArtUnits.bar**）
- `scripts/crawler/aoe3_gamedata_parser.py`（`_load_tactics` / `_parse_attacks`）
- `seeds/aoe3/units.json`
- `src/plugins/aoe3/models.py`
- `src/plugins/games/aoe3_battle/simulator.py`
- `docs/games/aoe3-battle.md`

**优先级**：中 / 平衡向 —— 影响几乎所有远程节奏；抬手在 anim 不在 proto，解包链比弹丸数长，但必须与弹丸数一样全自动从 BAR 来。

---

## 📐 AoE3 斗蛐蛐：阵线宽度 + 兵种碰撞体积（AOE 打不满）

**现象**：一维场上炮兵（及大范围 AOE）过强；实战里炮没那么「洗线」，骑兵常能切炮，但模拟器里 AOE 几乎**每发都打满**溅射人数与伤害池。

**根因（2026-05-27 讨论结论，纠正此前「纵深不溅射 / 只打前排」方向）**：

- 真 RTS：单位有**体积**，阵形有**横向宽度**；`damagearea` 是圆，圆里往往只能塞进 2～3 个目标，骑兵块头大更难被一发罩死 → 前排打不满 → 存活单位能继续顶、才能切后排炮。
- 当前模拟器：全员共线、同排同 `pos`；溅射用 `|Δpos| ≤ aoe_radius` 在轴线上数人 → 候选几乎总是 ≥ `round(aoe_radius)` → **`splash_count` 稳定顶满**；再叠 `damage_cap` 均分。在此几何下**改溅射区形状（同排/衰减/cap=2）意义不大**，只要线上人够多就仍满。
- **不宜**采用的修法：深排不溅射、只洗第一排、只许打前排、骑兵闪现绕后、炮专属 ×0.5——或**帮炮清前排威胁**，或**保护后排炮**，或纯砍炮表。
- **值得做**：**阵线宽度**（布阵 `y` 展开）+ **碰撞体积 / footprint**（步兵小、骑兵大）→ 仅 AOE 结算用二维距离 `sqrt(Δpos²+Δy²)`（或圆内占位上限），移动/射程/锁敌可仍用一维 `pos`。

**与现有 TODO 的关系**：

- `damagecap`（已完成）：对齐溅射**伤害池**上限（proto 值），不解决「圆里人数打满」。
- 本条：对齐「圆里**能命中几个**」——一维简化下缺体积与宽度，是炮兵失衡的主因之一。

**架构（建议拆包，避免 `simulator.py` 继续膨胀）**：

| 层 | 建议 |
|---|---|
| 数据 | `aoe3_gamedata_parser.py` + `models.py`：调研/解析单位占地（`protoy.xml` 里 `selectionradius`、`unitradius`、`obstruction` 等，需本机解包核对字段名）→ `footprint` 或 `collision_radius` |
| 布阵 | `aoe3_battle/formation.py`（新）：`pos` 纵深 + `y` 阵线宽度（按每排人数、`footprint` 展开） |
| AOE | `aoe3_battle/aoe.py`（新）：圆内候选、可选「大单位占 2 格名额」；读 `damage_cap_*`（已实现） |
| 模拟器 | `simulator.py`：只调 `formation` + `aoe`，主循环不变 |

**待办**（**先记 TODO，暂不改模拟器**）：

1. **解包调研**：`protoy.xml` / 相关 schema 里单位体积、碰撞、选中圈半径字段；抽样 `musketeer` / `hussar` / `cannon` 对比游戏内占地
2. **parser**：写入 `units.json`（如 `footprint`，缺则按 `type` 分档 fallback 并文档化）
3. **`formation.py`**：生成 `(pos, y)`；常量如 `FORMATION_WIDTH`、`LANE_SPACING` 与 `ROW_SPACING` 并列
4. **`aoe.py`**：`d ≤ aoe_radius` 筛候选；`splash_count = min(max_splash, 圆内有效人数)`，验证 8 火枪 vs 1 重炮不再稳定 4 溅射
5. **文档**：`docs/games/aoe3-battle.md` §3.8 改写——区分「一维移动」与「AOE 二维圆 + 体积」；注明禁止「深排不溅射」类规则
6. **测试**：`tests/games/aoe3_battle/test_aoe_footprint.py`（圆内人数、骑兵少命中、接战后 y 不变仅 pos 变）

**验收方向（定性）**：

- 重炮对展开横队：溅射人数 **<** `round(aoe)` 为常态，非每发顶满
- 骑兵对炮：同预算下切炮概率明显高于当前一维叠点模型
- 不改 2D 寻路、不加炮专属 debuff

**相关文件**：

- `scripts/crawler/aoe3_gamedata_parser.py`、`seeds/aoe3/units.json`
- `src/plugins/aoe3/models.py`
- `src/plugins/games/aoe3_battle/simulator.py`（`_compute_formation`、`_process_aoe` 待迁出）
- `docs/games/aoe3-battle.md` §3.1 / §3.8

**优先级**：中高 / 平衡向 —— 针对炮兵与 AOE 兵种结构性偏强；依赖解包体积字段，实现量大于只读 `damagecap`，但比全盘 2D 小。

