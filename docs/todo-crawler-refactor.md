# TODO: AOE3 兵种数据爬虫重构

> 创建于 2026-05-14，来源：斗蛐蛐战斗日志分析中发现 AOE 数据污染问题，追溯到爬虫架构缺陷。

## 一、现状问题

### 当前数据收集流程（两轮爬虫）

1. **第一轮：wiki 爬虫**（`scripts/crawler/aoe3_wiki_crawler.py`）
   - 来源：ageofempires.fandom.com
   - 产物：`seeds/aoe3/units.json`（444 个兵种）
   - 内容：基础属性（HP/攻击/射程/护甲/倍率/中文名/icon_url）
   - **不含**：aoe_radius、damage_type、完整攻击模式

2. **第二轮：supplement 爬虫**（`scripts/crawler/aoe3_aoe_supplement.py`）
   - 来源：aoe3explorer.com
   - 产物：`seeds/aoe3/units_aoe_supplement.json`
   - 内容：完整 attacks 数组（所有姿态的 aoe_radius/damage_type/bonuses）
   - **关键缺陷**：不是独立爬 aoe3explorer 全量数据，而是拿第一轮的 444 个英文名转 slug 去 aoe3explorer 逐个匹配查询

3. **merge 脚本**（`scripts/crawler/aoe3_merge_supplement.py`）
   - 把 supplement 数据合并回 units.json
   - 只处理 supplement 里有的兵种，没有的保持原样

### 发现的问题

1. **slug 匹配率不稳定**：第二轮爬虫首次跑匹配了部分兵种（如 hakkapelit），后来重跑时因 aoe3explorer slug 变化或 `--force` 覆盖导致数据丢失。当前 supplement 只覆盖 329/444 = 74%。

2. **115 个兵种无 supplement 数据**：包括戟兵、枪骑兵、流镝马、切诺基弓手、战车等正经战斗单位。它们的攻击模式详情（AOE/damage_type）缺失。

3. **AOE 数据污染（已修复）**：旧 merge 脚本选攻击模式时没排除 Charge/Trample 等特殊技能，导致 153 个兵种被错误标记 AOE。已在 2026-05-14 修复为 95 个。

4. **数据来源不可追溯**：units.json 中的字段混合了 wiki 爬虫和 supplement merge 的结果，无法区分哪些是哪一轮产生的。

## 二、数据源对比

| | aoe3explorer.com | fandom wiki |
|---|---|---|
| 兵种数量 | **511** | 444 |
| HP/攻击/射程/护甲 | ✅ | ✅ |
| 完整 attacks 数组（所有姿态） | ✅ 含 AOE/damage_type/bonuses | ❌ 只有主攻击数值 |
| AOE 半径 | ✅ 每个攻击模式单独标 | ❌ |
| damage_type | ✅ | ❌ |
| 费用/人口/训练时间 | ✅ | ✅ |
| 兵种类型标签 | ✅ | ✅ |
| 中文名 | ❌ | ✅（部分） |
| icon 图片 URL | 待确认 | ✅ |
| 升级路线 | ✅（详细） | 部分 |

**结论**：aoe3explorer 数据更准、更全、兵种更多。fandom wiki 唯一优势是中文名和 icon 图片。

## 三、改进方案

### 核心思路：主数据源改为 aoe3explorer

1. **新主爬虫**：直接爬 aoe3explorer 全量 511 个兵种
   - 一次性获取：基础属性 + 完整 attacks 数组 + AOE + damage_type + bonuses
   - 不需要 slug 匹配，直接遍历 aoe3explorer 自己的兵种列表
   - 产物：新的 `seeds/aoe3/units_raw.json`（原始完整数据）

2. **fandom wiki 降级为补充源**：
   - 只用来匹配中文名和 icon 图片 URL
   - 通过英文名模糊匹配，不依赖 slug

3. **merge 脚本重构**：
   - 输入：`units_raw.json`（aoe3explorer）+ wiki 中文名/icon 映射
   - 输出：`units.json`（最终数据）
   - 选攻击模式的逻辑保持当前修正后的版本（排除 Charge/Trample，优先常规姿态）
   - 保留完整 attacks_all 数组供未来扩展

4. **数据溯源**：在 units.json 中标注每个字段的来源（explorer / wiki / manual）

### 预期收益

- 兵种从 444 → 511
- AOE/damage_type 覆盖率从 74% → 100%
- 不再有 slug 匹配丢数据的问题
- 数据来源清晰可追溯

## 四、注意事项

- aoe3explorer 是 SvelteKit 页面，数据嵌在 HTML 的 JS 中，需要正则提取
- 礼貌爬取（1.2s 间隔），511 个兵种约需 10 分钟
- icon 图片目前从 fandom wiki 获取并下载到 `resources/aoe3_icons/`，重构后需确认 aoe3explorer 是否也有 icon
- 现有的 `units.json` 格式不能大改，simulator/lineup/game 都依赖它
