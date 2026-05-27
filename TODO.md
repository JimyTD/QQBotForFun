# TODO

> 待办事项列表 —— 需要在本机 / 装了游戏的机器上验证或处理的事项。

---

## 🖼️ AoE3：审计 Wiki/复制补图（28 + 68）

**背景**（commit `83dcaa0`）：全量 icon 重建时，绝大多数来自游戏 BAR 解包；另有约 **28** 张走 AoE3 Wiki API（BAR 解不出）、约 **68** 张从基础兵种复制给变体。这批最容易「图和兵对不上」。

**现状**：当时补图脚本/名单**未提交进 git**，仓库里无法还原精确的 28、68 个 `unit_id`。

**待办**（需本机 AoE3DE + 跑 extractor）：

1. 给 `scripts/crawler/aoe3_icon_extractor.py` 增加导出 `icon_manifest.json`（字段如 `source: bar | wiki_api | variant_copy`，复制项记 `copy_from`）
2. 重跑提取后，**只审** manifest 里标记为 `wiki_api` 与 `variant_copy` 的条目（对照游戏内头像 / 斗蛐蛐展示）
3. 错图优先改 BAR/portrait 或 `data/aoe3/icon_overrides.json`，避免再批量爬 Wiki

**相关**：`resources/aoe3/icons/`、`docs/games/aoe3.md` §6

**优先级**：中 / 体验向 —— 主流程 BAR 图质量已够，仅少数补图需人工验收。

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

## 📜 AoE3 兵种查询：补单位 tooltip 描述 ✅

**现象**：`aoe3 <兵种名>` 卡片只有数值属性，**没有**游戏里鼠标悬停时的那段官方描述文案。

**背景**（2026-05-25 确认）：

- 官方中文**单位名**已在 `seeds/aoe3/units.json` 的 `name` 字段（来自 `stringtabley_zh.xml`），标题行有展示。
- **Tooltip 描述**游戏里有，但当前 pipeline **未提取、未入库、未展示**。
- 解包后（`aoe3_bar_extractor.py` → 默认 `E:\aoe3_extracted`，不入 git）：
  - `protoy.xml`：`RolloverTextID` / `ShortRolloverTextID` 指向 stringtable 条目
  - `stringtabley_en.xml` / `stringtabley_zh.xml`：含对应中英文描述文本
- 解析器 `aoe3_gamedata_parser.py` 目前只读 `displaynameid`（名字），没读 rollover 字段。

**待办**（需本机有 AoE3DE，能跑 extractor + parser）：

1. ~~`aoe3_gamedata_parser.py`：解析 `rollovertextid` / `shortrollovertextid`~~ ✅
2. ~~`models.py` + `formatter.py` 展示~~ ✅
3. ~~重跑 parser 更新 `seeds/aoe3/units.json`~~ ✅（与 damagecap 同次 `aoe3_gamedata_parser.py`）

**相关文件**：

- `scripts/crawler/aoe3_bar_extractor.py`
- `scripts/crawler/aoe3_gamedata_parser.py`
- `seeds/aoe3/units.json`
- `src/plugins/aoe3/models.py`、`formatter.py`

**优先级**：中 / 体验向 —— 纯展示增强，不影响查询与斗蛐蛐逻辑。

---

## 💥 AoE3 斗蛐蛐：从解包读取 `damagecap`（溅射伤害池）✅

**现象**（已修复 2026-05-27）：模拟器按同槽 `damage_cap_*` 读 protoy；无字段仍 2× fallback。

**背景**（2026-05-26 确认，来源均为 AoE3 / DE，非 AoE2）：

- 解包 `protoy.xml`（`aoe3_bar_extractor.py` → 默认 `E:\aoe3_extracted`）中，带溅射的 `<protoaction>` 同时有：
  - `<damagearea>` — 溅射半径（**已在用**）
  - `<damagecap>` — 溅射**总伤害池**（不含主目标全额伤害；**尚未读取**）
- 社区 / proto 对照（如 AoE3 Heaven 专帖）：掷弹兵手榴弹 base=16、`damagearea=3`、**`damagecap=36`**（不是简单 `2×16=32`）；溅射常 11～14/人，非满 base。
- **斗蛐蛐有意简化**：一维线性、无体积，同排单位都能进溅射；`round(aoe_radius)` 当「最多溅射 N 人」是简化，**不是**引擎原义（原版还有距离衰减等）。此简化可保留，但 cap 应用 proto 值会更贴 DE。
- 当前链路断层：
  - `aoe3_gamedata_parser.py` 只 `findtext("damagearea")` → `aoe_radius_*`，无 `damagecap`
  - `seeds/aoe3/units.json` 有 `aoe_radius_ranged` / `aoe_radius_melee`（如 `grenadier`：3 / 1），**无** `damage_cap_*`
  - `simulator.py` 写死 `damage_cap = base_atk * 2.0`
  - `docs/games/aoe3-battle.md` §四 写「damage_cap 已通过解析器补全」——**与代码不符**，实现时需改文档

**待办**（需本机有 AoE3DE，能跑 extractor + parser）：

1. ~~`aoe3_gamedata_parser.py`：解析 `damagecap`~~ ✅
2. ~~`models.py` + `simulator.py`：读 `damage_cap_*`，fallback `2×`~~ ✅
3. ~~**重跑 parser** 更新 `seeds/aoe3/units.json`~~ ✅
4. ~~修正 `docs/games/aoe3-battle.md`~~ ✅
5. ~~审计清单~~ ✅ [`docs/aoe3-damagecap-audit.md`](docs/aoe3-damagecap-audit.md)（**48** 槽溅射池变化；`basedamagecap`：**勿**改 fallback 为 1×）

**可选后续**：距离衰减、Bolos 弹跳——引擎公式不在解包 XML。

**相关文件**：

- `scripts/crawler/aoe3_bar_extractor.py`
- `scripts/crawler/aoe3_gamedata_parser.py`
- `seeds/aoe3/units.json`
- `src/plugins/aoe3/models.py`
- `src/plugins/games/aoe3_battle/simulator.py`
- `docs/games/aoe3-battle.md`

**优先级**：中 / 平衡向 —— 主要影响带 AOE 兵种（掷弹兵、胸甲骑兵等）；一维简化可保留，cap 对齐后溅射强度会更贴 DE。

