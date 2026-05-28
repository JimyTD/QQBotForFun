# TODO

> 待办事项 —— 需在本机 / 装了游戏的机器上处理。做完即删；功能说明见 `docs/`。

---

## 🖼️ AoE3：审计 Wiki/复制补图

**待办**（人工验收）：

1. 对照 `data/aoe3/icon_manifest.json` → `audit.wiki_api`（1 条：`shrine`）与 `audit.variant_copy`（97 条），在游戏内或斗蛐蛐面板核对是否错图
2. 错图写入 `data/aoe3/icon_overrides.json`，再跑 `uv run python scripts/crawler/aoe3_icon_extractor.py --backfill-only`
3. 缺 BAR 解码器的伪 PNG（如 `beast_icon.png`）若需精确图，另找解包或手工 PNG，勿再批量爬 Wiki

```bash
uv run python scripts/crawler/aoe3_icon_extractor.py --backfill-only
```

**相关**：`resources/aoe3/icons/`、`docs/games/aoe3.md` §6

**优先级**：中

---

## 📐 AoE3 斗蛐蛐：阵线宽度 + 兵种碰撞体积（AOE 打不满）

炮兵及大范围 AOE 在一维共线模型里几乎每发溅射打满；需阵线宽度 + footprint，仅 AOE 结算用二维圆。

**待办**（先调研，暂不改模拟器）：

1. 解包调研 `protoy.xml` 体积/碰撞字段；抽样 `musketeer` / `hussar` / `cannon`
2. parser 写入 `units.json`（`footprint`，缺则按 type fallback）
3. 新 `formation.py`（`pos` + `y`）、`aoe.py`（圆内候选 + 体积）
4. `docs/games/aoe3-battle.md` §3.8 + `tests/games/aoe3_battle/test_aoe_footprint.py`

**验收**：重炮对横队溅射人数常态 **<** `round(aoe)`；骑兵切炮概率明显高于现模型。

**相关**：`docs/games/aoe3-battle.md` §3.1 / §3.8

**优先级**：中高
