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

## 🔫 多弹丸 / 连射兵种 DPS 严重低估（aoe3 数据 + simulator）

**现象**：加特林机枪、连弩兵这种**一次攻击循环打多发**的热门单位，斗蛐蛐里
DPS 被算成实际值的 1/3 ~ 1/10，对线表现完全脱离游戏直觉。

**问题对照**：

| 单位 | id | 当前数据 | 游戏实际 | 偏差 |
|------|----|--------|--------|------|
| 加特林机枪 | `xpgatlinggun` / `defortgatlinggunbatch` | `attack_ranged=20`, `rof_ranged=3.0`，单发 | 一次攻击循环连射 5~10 发，每发 ~10-20 | DPS ≈ 1/5 ~ 1/10 |
| 中国连弩兵 | `ypchukonu` | `attack_ranged=5`, `rof_ranged=3.0`，单发 | 一次攻击 3 连发 × 5 伤害 = 15 总伤害 | DPS ≈ 1/3 |
| 飞行乌鸦 | `Flying Crow`（火箭车） | 同上单发 | 一次齐射多发火箭 | 偏弱 |

（这两个都是热门单位，**不是冷门兵**——加特林机枪是中国进入工业的核心远程，
连弩兵是中国全程主力 skirm）

**根因**：

1. **数据侧**：`seeds/aoe3/units.json` 没有"弹丸数 / 连射数"字段。
   游戏 protoy.xml 里这些信息在 protoaction 节点的 `<NumberProjectiles>` /
   `<NumRangedAttacks>` 之类的字段，**爬虫 (`aoe3_gamedata_parser.py`)
   完全没读**。
2. **模拟器侧**：`simulator.py` 也没有 burst / multi-projectile 处理逻辑
   （grep `projectile|burst|shots` 0 命中），完全按"一次开火 = 一发命中"
   计算。即使数据有了字段，simulator 也得改才能用上。

**修复方案**（需要装了 AoE3 DE 的机器拆包验证）：

1. **拆包确认弹丸字段名**
   - `scripts/crawler/_extracted/protoy.xml` 搜
     `<unit name="xpGatlingGun">` / `<unit name="ypChuKoNu">` 的
     `<protoaction>` 节点
   - 看连射相关字段叫什么（`NumberProjectiles` / `NumRangedAttacks` /
     `RangedAttackBurst` / 类似），记下精确字段名
   - 看 RoF 是"整个 burst 的间隔"还是"单发间隔"——这决定了乘法该怎么算

2. **爬虫补字段**
   修改 `scripts/crawler/aoe3_gamedata_parser.py :: _parse_attacks`，把弹丸数
   读出来塞进每个攻击模式的 dict，最终落到 `units.json`：
   ```json
   "attack_ranged": 20,
   "rof_ranged": 3.0,
   "num_projectiles_ranged": 8,   // ← 新增
   ```
   注意：和迫击炮 multipliers 问题一样要遵守 MEMORY.md ID 54955007 的铁律
   ——弹丸数必须和当前选定的代表攻击属于**同一个攻击模式**，不能跨模式拼。

3. **simulator 支持连发**
   `simulator.py :: _resolve_ranged` 一带，开火时按 `num_projectiles` 处理。
   两种实现方案：
   - **简化版**：伤害 × 弹丸数（一次结算）。最简单，但 AOE / 暴毙判定
     不准（实际是多发独立命中，会重复触发 AOE）。
   - **精确版**：拆成 N 次独立命中，每次走完整的伤害结算流程。
     更准但要小心 CD：N 发都已"打出"后才进入 RoF 间隔。
   - 推荐先做简化版，跑通后再决定要不要升级。

4. **验收**
   - `seeds/aoe3/units.json` 里加特林机枪、连弩兵、飞行乌鸦都有
     `num_projectiles_ranged` 字段
   - `/帝国3 加特林机枪` 详情页显示弹丸数（renderer 也得加）
   - 斗蛐蛐里 10 加特林机枪 vs 10 步兵线，加特林应该明显占优；
     现在大概率打输（DPS 被低估 5x）

**相关文件**：
- 爬虫：`scripts/crawler/aoe3_gamedata_parser.py`（`_parse_attacks`）
- 数据：`seeds/aoe3/units.json`
- 模拟：`src/plugins/games/aoe3_battle/simulator.py`
- 详情渲染：`src/plugins/aoe3/render.py`（如果加了字段也要在详情里展示）

**优先级**：中-高 / 平衡向 —— 影响两个热门兵种在斗蛐蛐里的判定，群里玩家
对加特林机枪 / 连弩兵的体感会很违和。但工作量较大（拆包 + 爬虫 + simulator
三处都要动），不是小修。

---


