# 红警2 单位 icon（斗蛐蛐 QQ 展示）

本目录存放 `{actor_id}.png`（建议 128×128），开局阵容面板与帝国斗蛐蛐一样以图片形式发出。

## 生成方式

需要**原版红警2**（或已安装 OpenRA 内容）中的 `cameo.mix` + `cameo.pal`：

```bash
uv pip install ra2mix Pillow
uv run python scripts/crawler/ra2_icon_export.py --ra2-dir "你的RA2目录"
# 或指定文件：
# uv run python scripts/crawler/ra2_icon_export.py --cameo-mix path/cameo.mix --palette path/cameo.pal
```

也可设置环境变量 `RA2_DIR` / `RA2_PATH`。

`data/ra2/icon_map.json` 由 `openra_ra2_export.py` 从 OpenRA sequences 的 `icon.Filename` 自动生成（无需游戏文件）。

## 部署

服务器上跑完导出后，将 `resources/ra2/icons/*.png` 一并部署；缺失的 id 仅发文字详情，不影响开战（与 aoe3 坏图兜底相同）。
