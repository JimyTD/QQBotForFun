# AoE3 模块设计文档

- **Module ID**: `aoe3`
- **Status**: Design v0.1
- **Last Updated**: 2026-05-23

---

## 1. 概述

帝国时代3:决定版（AoE3:DE）数据查询 + 猜兵种小游戏。

包含两种形态：
- **查询工具**（v1，优先实现）：一问一答，查兵种属性 / 对比 / 文明
- **猜兵种游戏**（v2，后续）：多轮交互，逐步给线索，玩家猜兵种名

两者共用同一份数据层和 icon 资源。

---

## 2. 数据来源

| 文件 | 内容 | 来源 |
|------|------|------|
| `data/aoe3/raw/` | 权威解包源（protoy、techtreey、civs、stringtable、tactics、anims） | 游戏 BAR，**入库 git**（≈41 MB） |
| `data/aoe3/raw/homecity/` | 主城卡片定义：39 个文件 / **6721 张卡**（`name`/次数/主城等级/前置卡/时代） | 游戏 `Data.bar`，随灌库一起解出；卡片的**效果**在同名 tech（见 `techtreey.xml`） |
| `data/aoe3/manifest.json` | 灌库/生成元数据 | parser 自动生成 |
| `seeds/aoe3/units.json` | 单位属性（斗蛐蛐/卡片用派生视图） | parser 从 raw 生成 |
| `seeds/aoe3/civs.json` | 文明归属：文明→兵种/科技、单位→文明反查（137 条目：**24 可玩主文明 + 30 革命 + 37 原住民/结盟部落**） | `aoe3_civs_parser.py`：主文明走 `civs.xml` 的 agetech；**革命走 `techtreey.xml` 的 `<revolutionciv>`**；部落走 `NativeXxx` |
| `seeds/aoe3/i18n_zh.json` | `AbstractXxx` → 中文显示名映射（仅展示层用） | parser 生成 + 手工维护 tags |
| `resources/aoe3/icons/{id}.png` | 单位头像 (128×128) | 游戏 BAR 包提取 + Wiki 补充 |

**当前快照版本**（2026-09-17 刷新，对应游戏 2026-09-11 更新）：

| 项 | 值 |
|---|---|
| protoy.xml | 8.47 MB |
| 战斗单位 | 815 |
| tactics / anims 文件 | 472 / 535 |
| icon 记录 / PNG | 2225 / 2218 |
| 对照上一版 | 756 → 815 单位（+65 新增 / -6 消失），押注池 495 → 547，黑名单乱斗池 21 → 28 |

> 刷新流程、人工干预清单复核结论与逐单位改动名单见 `docs/aoe3-data-refresh-20260917.md`；
> 对比工具 `scripts/aoe3_seed_diff.py`（`--prev <旧快照>` 生成前后差异报告）。

**离线开发（无需安装游戏）**：`data/aoe3/raw/`（原始解包数据）、`seeds/aoe3/`（派生数据）、
`resources/aoe3/icons/`（2218 张图标）**全部入库 git**，克隆后即可开发数据解析 / 玩法 / 卡片等功能。
只有「游戏更新后重新灌库」这一步需要本机游戏（见 `aoe3-data-refresh.md`）。
BAR 中其余未解包内容（界面定义、多语言 stringtable）与本项目无关，不纳入。

**灌库（仅初次或自愿刷新快照，需本机游戏）**：

```bash
uv run python scripts/crawler/aoe3_bar_extractor.py
uv run python scripts/crawler/aoe3_anim_extractor.py
uv run python scripts/crawler/aoe3_gamedata_parser.py
```

**日常 derive（任意机器，无需游戏）**：

```bash
uv run python scripts/crawler/aoe3_gamedata_parser.py
```

**游戏 BAR 路径**（不入 git，仅灌库时用）：

| 项 | 默认路径 |
|----|----------|
| `Data.bar` | `E:\SteamLibrary\steamapps\common\AoE3DE\Game\Data\Data.bar` |
| `ArtUnits.bar` | `E:\SteamLibrary\steamapps\common\AoE3DE\Game\Art\ArtUnits.bar` |

权威 raw 默认读 `data/aoe3/raw/`（环境变量 `AOE3_EXTRACTED_DIR` 可覆盖）。

解包含 `protoy.xml`、`stringtabley_zh.xml`、`tactics/*.tactics`、`anims/**/*.xml` 等；AOE 半径/cap 在 **protoy 的 protoaction**；protoy 缺射程时从 **tactics** 回填；windup 从 **anims** 的 `tag Attack` 解析。

**人工核对参考**：[AOE 3 Home City](https://aoe3homecity.com/zh-CN/units?type=military)（单位面板数值较可靠；如 [雇佣兵](https://aoe3homecity.com/zh-CN/units?type=military&tags=Mercenary)）。权威仍以 `protoy.xml` 解析为准。

**核心设计原则**：
- `unit.type` 与 `multipliers.vs` 直接存游戏原始标签（`AbstractCavalry` 等），不翻译
- 倍率天然匹配：`damagebonus.type` 和 `unit.type` 来自同一份 XML 同一套字符串，不需要映射表
- 翻译只在展示层（`i18n_zh.json` + `formatter.py`），与数据/匹配逻辑解耦

### 2.1 单位数据结构 (Unit)

```json
{
  "id": "musketeer",
  "name": "火枪手",
  "name_en": "Musketeer",
  "type": ["AbstractInfantry", "AbstractHeavyInfantry", "AbstractGunpowderTrooper", "Unit"],
  "civs": ["British", "French", ...],
  "age": "Commerce Age",
  "cost": {"food": 75, "gold": 25},
  "pop": 1,
  "train_time": 30,
  "hp": 150,
  "speed": 4.0,
  "los": 16,
  "armor_melee": 0.2,
  "armor_ranged": null,
  "armor_siege": 0.0,
  "attack_ranged": 23,
  "range": 12,
  "range_min": 0,
  "rof_ranged": 3.0,
  "damage_type_ranged": "Ranged",
  "aoe_radius_ranged": 0,
  "attack_melee": 13,
  "range_melee": 0,
  "rof_melee": 1.5,
  "damage_type_melee": "Hand",
  "aoe_radius_melee": 0,
  "attack_siege": 20,
  "range_siege": 6,
  "rof_siege": 3.0,
  "multipliers": {
    "ranged": [],
    "melee": [
      {"vs": "AbstractCavalry", "value": 3.0},
      {"vs": "AbstractCoyoteMan", "value": 2.25}
    ],
    "siege": []
  },
  "trained_at": ["Barracks", "Fort"],
  "internal_name": "Musketeer"
}
```

> **type 与 multipliers.vs 的标签来自同一命名空间**——例如火枪手 melee 倍率 `vs: AbstractCavalry` 直接对得上骑兵单位的 `type` 中的 `AbstractCavalry`，无需映射。中文展示由 `i18n_zh.json` 在 formatter 层完成。
>
> **siege 槽位仅用于拆建筑展示**，斗蛐蛐战斗模拟器不使用（详见 `aoe3-battle.md` §3.9）。

---

## 3. 查询工具（v1）

### 3.1 指令

| 指令 | 说明 | 示例 |
|------|------|------|
| `@Bot aoe3 <名称>` | 查兵种属性卡 | `@Bot aoe3 火枪手` |
| `@Bot aoe3 对比 <A> <B>` | 两兵种对比 | `@Bot aoe3 对比 火枪手 散兵` |
| `@Bot aoe3 文明 <文明>` | 该文明可用兵种 | `@Bot aoe3 文明 日本` |

### 3.2 属性卡片格式

查询返回 icon 图片 + 文字属性卡：

查询和对比的 icon 在发送前合成黑色底图；斗蛐蛐普通对战的双方 icon 使用 AoE3:DE 的敌我配色：红方 `RGB(230, 40, 40)` / `#E62828`，蓝方 `RGB(75, 75, 230)` / `#4B4BE6`。输出为不透明 PNG，不受 QQ 气泡颜色影响，原始透明素材保持不变。

颜色来源：[帝国时代官方论坛中的 DE 社区教程](https://forums.ageofempires.com/t/friend-foe-colors-the-tutorial/232827)（2023-06-08）所列的 `playercolors.xml`，取 `friendorfoeenemy` / `friendorfoeself` 的 `color1`，不是小地图的纯红/纯蓝。尚未对照本机最新游戏包复核。

锦标赛使用独立的 **1–8 号玩家色**，不是上面的敌我识别色。抽签后按参赛编号固定分配，对阵图各轮、冠军大图标和最终排名图都按原编号取色；淘汰只变暗、加叉，不因晋级位置或名次换色。图表背景及金银铜排名样式不变。

| 参赛编号 | 玩家色 | RGB | HEX |
|---|---|---|---|
| 1 | 蓝 | 45, 45, 245 | `#2D2DF5` |
| 2 | 红 | 210, 40, 40 | `#D22828` |
| 3 | 黄 | 224, 224, 30 | `#E0E01E` |
| 4 | 紫 | 145, 15, 243 | `#910FF3` |
| 5 | 绿 | 42, 212, 58 | `#2AD43A` |
| 6 | 橙 | 234, 135, 0 | `#EA8700` |
| 7 | 青 | 28, 194, 219 | `#1CC2DB` |
| 8 | 粉 | 235, 97, 235 | `#EB61EB` |

2026-09-21 核验：对照两份公开的 DE `playercolors.xml` 副本，`player num="1"` 至 `num="8"` 的 `color1` / `color2` / `color3` / `minimap` 全部一致。主来源为 [AoE3DEDatabase 固定版本](https://github.com/rainsillwood/AoE3DEDatabase/blob/c392242f459b919ff7c34aadef3c29a6bdb08d3e/Data/playercolors.xml)，交叉来源为 [AOE3DE-Mods 中的数据副本](https://github.com/ismailyaseen6/AOE3DE-Mods/blob/061680b6e1881a3c60a99bafa76e3b1235e077ff/Population%20and%20Tree%20Wood%20Increase/Data%20-%20BAR/playercolors.xml)。前者该文件最后提交于 2024-01-16；这是公开数据副本间的核验，尚未对照 2026 年最新游戏包。

```
[icon图片]

🏰 火枪手 (Musketeer)
━━━━━━━━━━━━━━━━━━
时代：商业时代 | 人口：1
费用：75🍖 25🪙
训练于：兵营 / 堡垒

📊 基础属性
HP：150 | 速度：4.0 | 视野：16
抗性：20% 近战

⚔️ 远程攻击
  23伤害 | 射程12 | 射速3.0s

⚔️ 近战攻击
  13伤害 | 射速1.5s
  → 骑兵 x3.0 | 冲击步兵 x2.25

💣 攻城攻击
  20伤害 | 射程6 | 射速3.0s

📋 类型：重步兵 / 火枪步兵
文明：英法德俄西葡荷瑞…
```

**关键：克制倍率跟着所属攻击类型展示**，这是游戏的真实机制。

### 3.3 对比模式

并排展示两个单位，差异项用标记高亮。

---

## 4. 猜兵种游戏（v2，后续）

### 4.1 玩法

- 每局 5 题
- 每题随机抽一个**可训练兵种**（有 cost + 有攻击 + 非 Hero）
- 逐步给线索（类型 → 费用 → 某条克制 → 攻击数值 → icon）
- 玩家直接发消息猜兵种名（中英文均可）
- 答对得分，线索越少分越高
- 所有参与者都有参与分（符合项目"及时正反馈"哲学）

### 4.2 线索层级

| 线索 # | 内容 | 难度 |
|--------|------|------|
| 1 | 兵种类型 + 时代 | 最难 |
| 2 | 费用 + 人口 | 难 |
| 3 | 一条克制关系 | 中 |
| 4 | HP + 攻击数值 | 易 |
| 5 | 显示 icon | 最易 |

---

## 5. 代码结构

```
src/plugins/aoe3/
├── __init__.py              # 插件入口
├── models.py                # Unit / Technology 数据类
├── repository.py            # 数据加载 + 查询接口（查询+游戏共用）
├── formatter.py             # 属性卡片文本渲染
├── query/
│   └── handlers.py          # Bot 端查询指令处理
└── quiz/                    # v2: 猜兵种游戏
    ├── game.py
    └── ...

scripts/cli_adapters/
└── aoe3.py                  # CLI 适配器（查询 + 猜兵种）

resources/aoe3/icons/        # 单位 icon 图片
```

### 5.1 UnitRepo 接口

```python
class UnitRepo:
    def search(name: str) -> list[Unit]           # 中英文模糊搜索
    def get_by_id(id: str) -> Unit | None
    def list_by_civ(civ: str) -> list[Unit]       # 文明查询
    def random_trainable() -> Unit                 # 猜兵种用
    def get_icon_path(unit: Unit) -> Path | None   # icon 本地路径
```

---

## 6. 资源文件

- icon 图片存 `resources/aoe3/icons/{unit.id}.png`（当前 2218 个）
- 统一尺寸 128×128px，单个 ≤50KB（经 `compress_aoe3_icons.py` 压缩）
- 来源：从游戏 `ArtUnitsTextures*.bar` / `UIResources1.bar` 直接提取 RTS3 DDT 格式图标（`aoe3_icon_extractor.py`）
- **来源统计（2026-09-17 重提取，2225 条记录）**：
  - `bar` 2205 —— 直接从 BAR 解出
  - `variant_copy` 1 / `local_reuse` 9 —— 变体复制 / 历史遗留本地图（本次 BAR 未解出，来源不可回溯）
  - `missing` 10 —— 无图（多为建筑/装饰/彩蛋，不影响斗蛐蛐兵种卡）
- `source` 合法取值：`bar | bar_alt | bar_portrait | wiki_api | variant_copy | local_reuse | missing`
  （`bar_legacy` 不是合法值；历史快照中的 9 条是手工编辑产物，已由 `local_reuse` 取代）
- **人工覆盖** `data/aoe3/icon_overrides.json`：`force_copy_from` 强制从另一单位复制图标、`block_wiki` 禁止 Wiki 回退；extractor 优先读取。当前 2 条（`ypmandarinarmy` ← 铁军、`dedeli` ← 骠骑兵）。
- **所有战斗兵种图标均来自游戏 BAR**（2026-09-17 验证：2205/2225 BAR 命中）

---

## 7. 踩坑记录

### 7.1 同名兵种搜索
**已归档。**

### 7.2 BAR v6 64-bit offset 截断导致大量图标错误

**现象**：重型加农炮（`xppropheavycannon`）与加农炮（`cannon`）共用同一 bar entry，却产出不同图标；另有大量单位图标为游戏截图/绘画/错误单位头像。

**根因**：`aoe3_bar_extractor.py :: read_bar_entries()` 中 per-file entry 的 offset 字段被错误解析为 `uint32(4B) + skip(4B)`。BAR v6（AoE3 DE）格式中该字段实际为 `uint64(8B)`。Resource Manager 源码（`BarEntry.cs`）证实 `version>3` 时使用 `ReadInt64()`。

**修复**（commit 此后）：将 `struct.unpack('<I', f.read(4))[0]; f.read(4)` 改为 `struct.unpack('<Q', f.read(8))[0]`。

**影响范围**：

| 旧来源 | 数量 | 说明 |
|--------|------|------|
| bar（实际错误） | 192 | 提取成功但读到错误数据，外表看不出来 |
| bar_alt | 33 | 解码失败→降级用 portrait 替代 |
| variant_copy | 98 | BAR 未匹配→从相似单位拷贝 |
| wiki_api | 1 | 从 Fandom Wiki 下载 |
| missing→bar | 13 | 之前完全没解出 |

修复后重提取，**337 个图标得到改善，0 个丢失**。现在 2005 个 BAR 图标全覆盖，斗蛐蛐兵种头像 100% 真实。

### 7.3 以往归档

### 7.1 同名兵种搜索

**已解决**（方案 C 轻量提示）：

- `is_excluded_unit()` 排除伪同名（战役兵、占位符、守护者、八旗代币等）
- 搜索返回多结果时，卡片末尾提示"你可能还想查：X、Y、Z"（`commands.py`）
- 玩家可用 `/帝国3 <英文id>` 精确查看特定变体
