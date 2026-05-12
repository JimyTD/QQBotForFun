# AoE3 模块设计文档

- **Module ID**: `aoe3`
- **Status**: Design v0.1
- **Last Updated**: 2026-05-12

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
| `seeds/aoe3/units.json` | 443 个单位属性 | Fandom Wiki API 爬取 |
| `seeds/aoe3/technologies.json` | 240 条改良技术 | Fandom Wiki API 爬取 |
| `resources/aoe3/icons/{id}.png` | 单位头像 (268px) | Fandom Wiki CDN 下载 |

### 2.1 单位数据结构 (Unit)

```json
{
  "id": "musketeer",
  "name": "火枪手",
  "name_en": "Musketeer",
  "wiki_url": "https://...",
  "type": ["Infantry", "Heavy infantry", "Gunpowder trooper"],
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
  "attack_ranged": 23,
  "range": 12,
  "rof_ranged": 3.0,
  "multipliers": {
    "ranged": [],
    "melee": [
      {"vs": "Cavalry", "value": 3.0},
      {"vs": "Shock infantry", "value": 2.25}
    ],
    "siege": []
  },
  "attack_melee": 13,
  "rof_melee": 1.5,
  "attack_siege": 20,
  "range_siege": 6,
  "rof_siege": 3.0,
  "trained_at": ["Barracks", "Fort"],
  "internal_name": "Musketeer"
}
```

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
- 缩略图尺寸 268x270px，单个约 15KB，总计约 6.5MB
- `units.json` 中记录 `icon_url`（Fandom CDN），本地不存在时可 fallback
