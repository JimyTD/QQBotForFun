# AoE3 数据勘误清单

> 记录 `seeds/aoe3/units.json` 中已知的数据异常，供后续爬虫修复或手动补正参考。
> 已通过黑名单临时屏蔽的单位会标注 `[已黑名单]`。

---

## 一、HP 数据缺失（wiki 爬虫未抓到）

以下单位的 HP 在 wiki 页面上可能以非标准格式展示，导致爬虫解析为 1 或极小值。
`units_aoe_supplement.json`（aoe3explorer 数据源）不包含 HP 字段，无法自动补正。

| id | 中文名 | 当前 HP | 预估真实 HP | 状态 |
|---|---|---|---|---|
| `elmetto` | 钢盔骑兵 | 1 | ~320 | [已黑名单] |
| `mameluke_age_of_empires_iii` | 马穆鲁克 | 1 | ~230 | [已黑名单] |
| `sennar_horseman` | 森纳尔骑兵 | 1 | ~320 | [已黑名单] |

### 修复建议

- 方案 A：改进 wiki 爬虫 `aoe3_wiki_crawler.py` 的 HP 解析逻辑，覆盖这些特殊页面格式
- 方案 B：在 `units_aoe_supplement.json` 的爬虫中增加 HP 字段抓取（aoe3explorer 有 HP 数据）
- 方案 C：手动在 `seeds/aoe3/units.json` 中修正这 3 个单位的 HP 值

修复后可从 `BLACKLIST` 中移除对应 id。

---

## 二、射击军（strelet）cost 极低

| id | 中文名 | cost | HP | 问题 |
|---|---|---|---|---|
| `strelet` | 射击军 | 10 | 72 | 3000 预算 = 300 个 |

**结论**：cost=10 是游戏真实数据（俄罗斯特色便宜兵），**不是数据 bug**。
300 个射击军模拟性能可接受（< 1 秒），暂不处理。如后续发现体验问题可考虑加入黑名单。

---

## 三、船只数据质量整体较差

大量船只 HP 为 1~4（实际应为数百到数千），ROF 异常（火船 ROF=0，大型帆船 ROF=0.05），
射程极端（铁甲舰 range=70）。已通过 `_is_ship()` 类型过滤统一排除，不逐个列举。

---

*Last Updated: 2026-05-14*
