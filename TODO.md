# TODO

> 待办事项 —— 需在本机 / 装了游戏的机器上处理。做完即删；功能说明见 `docs/`。

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
