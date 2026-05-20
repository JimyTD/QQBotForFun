# AoE3 数据重建 TODO

> 创建于 2026-05-21，目标：基于游戏原始文件彻底重建数据层，消灭所有历史遗留问题。

## 已完成

- [x] BAR v6 解包 + alz4 解压 + XMB 解码 (`scripts/crawler/aoe3_bar_extractor.py`)
- [x] 提取 protoy.xml / techtreey.xml / civs.xml / stringtabley_en.xml / stringtabley_zh.xml
- [x] 确认游戏类型系统真相：unittype 标签直接匹配 damagebonus type，无翻译层
- [x] 确认 AbstractXxx 标签体系和倍率匹配机制

## 待执行

### 一、数据生成脚本 `scripts/crawler/aoe3_gamedata_parser.py` — 重写

- [ ] `unit.type`：直接存原始 unittype 标签，过滤 `LogicalTypeXxx` 等行为标签，保留分类标签
- [ ] `multiplier.vs`：直接存原始 `damagebonus type` 值，不翻译
- [ ] 删除 `UNITTYPE_MAP` 和 `BONUS_TYPE_MAP`（不再需要翻译映射）
- [ ] ID 生成：改为 `internal_name.lower()`，不做 CamelCase 拆分
- [ ] 重新评估哪些 unittype 该保留（`Abstract*`/`Hero`/`Ship`/`Mercenary`/`Guardian` 等分类标签）

### 二、翻译表 `seeds/aoe3/i18n_zh.json` — 重写

**原则**：能从官方字符串表（`stringtabley_zh.xml`）获取的，直接用官方翻译；官方不覆盖的手动维护。

#### 官方字符串表已覆盖（解析脚本直接从 stringtable 获取，不写死在 i18n_zh.json）

| 类别 | 覆盖率 | 方式 |
|------|--------|------|
| 单位名 | 100% | `displaynameid` → stringtable |
| 文明名 | 100% | `civs.xml` 的 `displaynameid` → stringtable |
| 时代名 | 100% | stringtable 中精确匹配 |
| 训练建筑名 | 100% | stringtable 中精确匹配 |

注意官方翻译与旧 i18n 有出入：
- 探索时代（旧：发现时代）、商业时代（旧：殖民时代）、要塞时代（旧：堡垒时代）
- 重装步兵（旧：重步兵）、轻型步兵（旧：轻步兵）、重装骑兵（旧：重骑兵）
- 突击步兵（旧：冲击步兵）

#### i18n_zh.json 中需手动维护的（~20 条 Abstract 标签翻译）

从字符串表中的间接匹配确定官方用语：

```json
"type": {
  "AbstractInfantry": "步兵",
  "AbstractHeavyInfantry": "重装步兵",
  "AbstractLightInfantry": "轻型步兵",
  "AbstractRangedInfantry": "远程步兵",
  "AbstractHandInfantry": "近战步兵",
  "AbstractCavalry": "骑兵",
  "AbstractHeavyCavalry": "重装骑兵",
  "AbstractLightCavalry": "轻型骑兵",
  "AbstractRangedCavalry": "远程骑兵",
  "AbstractHandCavalry": "近战骑兵",
  "AbstractRangedHeavyCavalry": "远程重骑兵",
  "AbstractLancer": "枪骑兵",
  "AbstractCoyoteMan": "突击步兵",
  "AbstractRangedShockInfantry": "远程突击步兵",
  "AbstractMusketeer": "火枪兵",
  "AbstractSkirmisher": "散兵",
  "AbstractRifleman": "步枪兵",
  "AbstractPikeman": "长矛兵",
  "AbstractGunpowderTrooper": "火器步兵",
  "AbstractGrenadier": "掷弹兵",
  "AbstractArcher": "弓箭手",
  "AbstractArtillery": "炮兵",
  "AbstractSiegeTrooper": "攻城单位",
  "AbstractWarShip": "战舰",
  "AbstractNativeWarrior": "原住民战士",
  "AbstractOutlaw": "亡命徒",
  "AbstractVillager": "村民",
  "AbstractPet": "宠物",
  "Hero": "英雄",
  "Ship": "船",
  "Mercenary": "雇佣兵",
  "Guardian": "守卫者",
  "Building": "建筑"
}
```

`"multiplier_vs"` 表 key 同样使用原始标签，翻译与 type 表一致（同一个标签既可以出现在 unit.type 中也可以出现在 multiplier.vs 中）。

- [ ] 重写 `"type"` 表：key 为原始 unittype 标签，value 为官方中文
- [ ] 重写 `"multiplier_vs"` 表：key 为原始 damagebonus type 值
- [ ] `"age"` 表：更新为官方翻译（探索/商业/要塞/工业/帝王）
- [ ] `"civs"` 表：从 civs.xml + stringtable 自动生成（不再手动维护）
- [ ] `"cost"` 表：保持不变（food/wood/gold/export/influence）
- [ ] `"trained_at"` 表：从 stringtable 自动生成

### 三、过滤/分类代码

#### `src/plugins/games/aoe3_battle/lineup.py`
- [ ] `_is_villager()`：改为 `"AbstractVillager" in unit.type`
- [ ] `_is_pet()`：改为 `"AbstractPet" in unit.type`
- [ ] `_unit_emoji()`：全部标签改为原始名（`AbstractCavalry`/`AbstractArtillery`/`AbstractArcher` 等）
- [ ] `_type_str_zh()` skip 集合：更新或删除（LogicalType 已在解析时过滤）
- [ ] `BLACKLIST`：用新 ID 重建（`internal_name.lower()` 格式），移除因数据 bug 加入的单位

#### `src/plugins/games/aoe3_battle/broadcaster.py`
- [ ] `_GUNPOWDER_TAGS` → `{"AbstractGunpowderTrooper", "AbstractRifleman", "AbstractMusketeer"}`
- [ ] `_ARCHER_TAGS` → `{"AbstractArcher"}`（验证是否还需要 AbstractFootArcher）
- [ ] `_ARTILLERY_TAGS` → `{"AbstractArtillery"}`

### 四、不需要改的（已确认）

| 文件 | 原因 |
|------|------|
| `simulator.py` `_calc_multiplier` | 动态匹配 `m.vs.lower() in target_types`，标签统一后天然正确 |
| `simulator.py` `_calc_damage` | 比较 damage_type（Ranged/Siege/Hand），与类型标签无关 |
| `models.py` `is_trainable` | `"Hero" in self.type` — Hero 标签确实存在于原始数据 |
| `lineup.py` `_is_hero`/`_is_ship` | `"Hero"`/`"Ship"` 标签确实存在于原始数据 |
| `formatter.py` | 走 i18n 翻译表，代码不含硬编码标签 |
| `repository.py` `find_counters` | 走 i18n 反查 + 动态匹配 |
| `i18n.py` | 通用函数，无硬编码 |
| CLI 适配器 | 不直接引用标签 |

### 五、清理

- [ ] 删除旧爬虫：`aoe3_wiki_crawler.py` / `aoe3_aoe_supplement.py` / `aoe3_merge_supplement.py` / `aoe3_icon_downloader.py`
- [ ] 删除旧数据：`seeds/aoe3/units_aoe_supplement.json` / `seeds/aoe3/technologies.json`（如不再使用）
- [ ] 删除旧文档中的过时内容（`docs/aoe3-data-errata.md` / `docs/todo-crawler-refactor.md`）
- [ ] 更新 `docs/games/aoe3.md` 描述数据来源为游戏原始文件

---

## 关键设计原则

1. **数据第一**：`units.json` 中的 type 和 multiplier.vs 直接存储游戏原始值，不翻译
2. **匹配在数据层完成**：`damagebonus type = "AbstractCavalry"` 精确匹配 `unit.type` 中的 `"AbstractCavalry"`
3. **翻译只在展示层**：`i18n_zh.json` 负责 `AbstractHeavyInfantry → "重步兵"` 这种转换，仅用于 UI 显示
4. **不打补丁**：遇到问题优先检查原始数据，而非在代码中硬编码修复
