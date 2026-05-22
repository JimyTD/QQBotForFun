# OpenRA 参考仓库（不入库）

红警2斗蛐蛐以此处为**唯一权威数据源**（规则、武器、世界 Locomotor）。

```bash
# 仓库根目录执行
git clone --depth 1 https://github.com/OpenRA/ra2.git vendor/openra-ra2
git clone --depth 1 https://github.com/OpenRA/OpenRA.git vendor/openra
```

导出游戏数据：

```bash
uv run python scripts/crawler/openra_ra2_export.py
```

产出：`data/ra2/manifest.json`（及 actors/weapons/locomotors、icon_map 等）。

QQ 兵种 icon（需原版 `cameo.mix`）：

```bash
uv pip install ra2mix Pillow
uv run python scripts/crawler/ra2_icon_export.py --ra2-dir "你的RA2安装目录"
```

产出：`resources/ra2/icons/{actor_id}.png`。
