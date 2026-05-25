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

## ✅ 多弹丸 / 连射兵种 DPS 严重低估（aoe3 数据 + simulator）— 已修复

**修复日期**：2026-05-24

**根因（修正后）**：

AoE3 的多弹丸信息不在 protoy.xml 中（`numberprojectiles` 全文为 1），
而是在 **tactics 文件**的 `<displayednumberprojectiles>` 字段，按**攻击动作名**绑定。

引擎有两种"快射"机制：
- **机制 A（极短 ROF）**：如加特林机枪的 `RepeatingAttack` rof=0.5 → 爬虫已正确处理
- **机制 B（多弹丸齐射）**：如连弩 disp=3、管风琴炮 disp=6 → 之前完全缺失

**修复内容**：

1. `aoe3_bar_extractor.py`：新增 `extract_tactics()` 批量提取 432 个 tactics 文件
2. `aoe3_gamedata_parser.py`：
   - 新增 `_load_tactics()` 解析 tactics 文件的 displayednumberprojectiles
   - `_parse_attacks()` 按动作名匹配读取弹丸数，写入 `info["num_projectiles"]`
   - 输出 `num_projectiles_ranged` / `num_projectiles_melee` 字段（仅当 > 1）
3. `models.py`：`Unit` 新增 `num_projectiles_ranged: int = 1` / `num_projectiles_melee: int = 1`
4. `simulator.py`：`_calc_damage` 中 `damage = base_atk * num_proj * mult * (1 - armor)`
5. `lineup.py`：战力估算和展示层都乘弹丸数，展示格式 "5×3发"

**修复后受影响单位**（自动检测，非特判）：

| 单位 | 弹丸数 | 修正前 DPS | 修正后 DPS |
|------|--------|-----------|-----------|
| 连弩兵 ypChuKoNu | 3 | 1.7 | 5.0 |
| 管风琴炮 OrganGun | 6 | 8.2 | 49.5 |
| 加特林骆驼 deMercGatlingCamel | 6 | 4.8 | 29.0 |
| 皮衣牛仔 deREVVaquero | 4 | 1.3 | 5.3 |
| 战斗独木舟 deBattleCanoe | 5 | 8.7 | 43.3 |
| 钦查木筏 deChincharaft | 3 | 12.5 | 37.5 |
| 加特林骆驼(legacy) | 6 | 50 | 300 |

**未受影响**：加特林机枪（ROF=0.5 已正确编码）、鹰炮/长管炮（CaseShot 非主攻模式）

---


