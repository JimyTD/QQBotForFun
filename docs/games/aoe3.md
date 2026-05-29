# AoE3 模块设计文档

- **Module ID**: `aoe3`
- **Status**: Design v0.1
- **Last Updated**: 2026-05-23

---

## 1. 概述

帝国时代3:决定版（AoE3:DE）数据查询 + 猜兵种小游戏。

包含两种形态：
- **查询工具**（v1，优先实现）：一问一答，查兵种属性 / 对比 / 克制 / 文明
- **猜兵种游戏**（v2，后续）：多轮交互，逐步给线索，玩家猜兵种名

两者共用同一份数据层和 icon 资源。

---

## 2. 数据来源

| 文件 | 内容 | 来源 |
|------|------|------|
| `seeds/aoe3/units.json` | 单位属性（含 type / 攻击 / 倍率 / AOE） | 游戏文件 `protoy.xml` 直接解析 |
| `seeds/aoe3/technologies.json` | 改良技术 | 游戏文件解析 |
| `seeds/aoe3/i18n_zh.json` | `AbstractXxx` → 中文显示名映射（仅展示层用） | 手工维护 |
| `resources/aoe3/icons/{id}.png` | 单位头像 (128×128) | 游戏 BAR 包提取 + Wiki 补充 |

**解析脚本**：`scripts/crawler/aoe3_gamedata_parser.py`

**本机游戏路径**（不入 git，见 `aoe3_bar_extractor.py`）：

| 项 | 默认路径 |
|----|----------|
| `Data.bar` | `E:\SteamLibrary\steamapps\common\AoE3DE\Game\Data\Data.bar` |
| 解包输出 | `E:\aoe3_extracted`（环境变量 `AOE3_EXTRACTED_DIR` 可覆盖） |

解包含 `protoy.xml`、`stringtabley_zh.xml`、`tactics/*.tactics` 等；AOE 半径/cap 在 **protoy 的 protoaction**；距离衰减等在 **tactics**（`outerdamageareadistance/factor`），斗蛐蛐未模拟。

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
| `@Bot aoe3 克制 <类型>` | 什么克制该类型 | `@Bot aoe3 克制 骑兵` |
| `@Bot aoe3 文明 <文明>` | 该文明可用兵种 | `@Bot aoe3 文明 日本` |

### 3.2 属性卡片格式

查询返回 icon 图片 + 文字属性卡：

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

### 3.4 克制查询

输入单位类型（如"骑兵"），列出所有 `multipliers` 中 `vs` 包含该类型且 `value > 1.5` 的兵种，按倍率降序。

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
    def find_counters(type: str, min: float) -> list[Unit]  # 克制查询
    def list_by_civ(civ: str) -> list[Unit]       # 文明查询
    def random_trainable() -> Unit                 # 猜兵种用
    def get_icon_path(unit: Unit) -> Path | None   # icon 本地路径
```

---

## 6. 资源文件

- icon 图片存 `resources/aoe3/icons/{unit.id}.png`
- 统一尺寸 128×128px，单个 ≤50KB（经 `compress_aoe3_icons.py` 压缩）
- 来源：主要从游戏 `ArtUnitsTextures*.bar` / `UIResources1.bar` 直接提取 RTS3 DDT 格式图标（`aoe3_icon_extractor.py`）；少量 DE DLC 单位因自研纹理格式无法解码，改从 AoE3 Wiki API 下载或用同类单位图标替代
- 个别 BAR 占位/错图：`data/aoe3/icon_overrides.json` 手动 `force_copy_from`，再跑 `aoe3_icon_extractor.py --backfill-only`（或直拷 PNG）同步 `resources/aoe3/icons/`

---

## 7. 待改进项（TODO）

### 7.1 同名兵种搜索：第二个永远看不到

**现象**：`units.json` 里存在多个同中文名的兵种条目（多文明变体、雇佣兵复制版等），
当玩家搜「长矛兵」「骠骑兵」这类名字时，`UnitRepo.search()` 按固定优先级返回，
**排在后面的同名兵种永远不会被玩家看到**。

**已做**：`is_excluded_unit()` 把以下"伪同名"条目从搜索池剔除：
- 召唤占位符（id 后缀 `*batch` / `*armyspawn`）
- PVE 宝藏守护者（type 含 `Guardian`）
- 八旗军 / 领事馆远征军 / 原住民代币（type 含 `AbstractBannerArmy`，共 84 token，
  hp 固定 200，是"召唤入口"标签，玩家不会直接控制单兵）

解决了"宝藏守护者长矛兵盖过普通长矛兵""明军/御林军等代币盖过真正名为类似汉字的兵种"
这类**伪同名**问题。具体规则及与斗蛐蛐两层黑名单的关系详见
`docs/games/aoe3-battle.md §2.2.2 + §十(2026-05-21 双层黑名单决议)`。

**仍未解决**：正经的多 civ 变体同名（如"骠骑兵"在多个文明里有微调版本）。
当前实现下玩家只能看到第一个。

**待定方案**（实现成本递增）：
- A. 同名时返回列表让玩家选（"找到 4 个同名兵种：1./2./...，回复数字查看"）
   —— 改动交互流，要加一个临时状态
- B. 支持带限定词查询：`/帝国3 长矛兵 印度`、`/帝国3 pikeman_inca`
   —— 改动小，但要让用户知道有这种用法
- C. 卡片末尾提示"同名兵种还有 N 个：A/B/C，发送 `/帝国3 <id>` 查看具体版本"
   —— 不改交互流，只加一行提示，最轻量

触发条件：等具体场景出现（玩家反馈"我搜的某兵种和卡片对不上"）再决定走哪条路。
