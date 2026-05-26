# TODO

> 待办事项列表 —— 需要在本机 / 装了游戏的机器上验证或处理的事项。

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

## 📜 AoE3 兵种查询：补单位 tooltip 描述

**现象**：`aoe3 <兵种名>` 卡片只有数值属性，**没有**游戏里鼠标悬停时的那段官方描述文案。

**背景**（2026-05-25 确认）：

- 官方中文**单位名**已在 `seeds/aoe3/units.json` 的 `name` 字段（来自 `stringtabley_zh.xml`），标题行有展示。
- **Tooltip 描述**游戏里有，但当前 pipeline **未提取、未入库、未展示**。
- 解包后（`aoe3_bar_extractor.py` → 默认 `E:\aoe3_extracted`，不入 git）：
  - `protoy.xml`：`RolloverTextID` / `ShortRolloverTextID` 指向 stringtable 条目
  - `stringtabley_en.xml` / `stringtabley_zh.xml`：含对应中英文描述文本
- 解析器 `aoe3_gamedata_parser.py` 目前只读 `displaynameid`（名字），没读 rollover 字段。

**待办**（需本机有 AoE3DE，能跑 extractor + parser）：

1. `aoe3_gamedata_parser.py`：解析 `rollovertextid`（及可选 `shortrollovertextid`），写入 `units.json` 新字段（如 `description` / `description_en`）
2. `models.py` + `Unit.from_dict`：接新字段
3. `formatter.py` `render_unit_card`：卡片末尾展示 tooltip（优先中文，过长可截断或换行）
4. 重跑 parser 更新 `seeds/aoe3/units.json` 并提交

**相关文件**：

- `scripts/crawler/aoe3_bar_extractor.py`
- `scripts/crawler/aoe3_gamedata_parser.py`
- `seeds/aoe3/units.json`
- `src/plugins/aoe3/models.py`、`formatter.py`

**优先级**：中 / 体验向 —— 纯展示增强，不影响查询与斗蛐蛐逻辑。

---

## 💥 AoE3 斗蛐蛐：从解包读取 `damagecap`（溅射伤害池）

**现象**：斗蛐蛐 AOE 溅射伤害可能偏强/不准；`damage_cap` 在文档里被标成「已解决」，但代码里**尚未**从游戏数据读取。

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

**待办**（需本机有 AoE3DE，能跑 extractor + parser；**先记录，暂不改代码**）：

1. `aoe3_gamedata_parser.py`：解析 `damagecap`，与对应攻击槽位一并写入 `units.json`（如 `damage_cap_ranged` / `damage_cap_melee`；无 cap 或 0 时可省略字段）
2. `models.py` + `Unit.from_dict`：接新字段
3. `simulator.py` `_apply_aoe_splash`：优先用 proto `damage_cap_*`；缺省再 fallback `2×基础攻`（与 Wiki「多数 2×」一致）
4. 重跑 parser 更新 `seeds/aoe3/units.json`；抽样验收 `grenadier` 远程 cap=36、Hand cap 与解包一致
5. 修正 `docs/games/aoe3-battle.md`：区分「已读 damagearea」与「待读 damagecap」；注明 `round(aoe_radius)` 为一维简化

**可选后续**（非必须）：距离衰减（DE 霰弹：0.25 半径内近满伤）、锥形 vs 圆形溅射形状——一维场地上优先级低于 cap。

**相关文件**：

- `scripts/crawler/aoe3_bar_extractor.py`
- `scripts/crawler/aoe3_gamedata_parser.py`
- `seeds/aoe3/units.json`
- `src/plugins/aoe3/models.py`
- `src/plugins/games/aoe3_battle/simulator.py`
- `docs/games/aoe3-battle.md`

**优先级**：中 / 平衡向 —— 主要影响带 AOE 兵种（掷弹兵、胸甲骑兵等）；一维简化可保留，cap 对齐后溅射强度会更贴 DE。

