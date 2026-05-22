# 红警2 / 尤里复仇 单位 icon（斗蛐蛐 QQ 展示）

本目录存放 `{actor_id}.png`（建议 128×128），开局阵容面板与帝国斗蛐蛐一样以图片形式发出。

`data/ra2/icon_map.json` 已由 `openra_ra2_export.py` 从 YR sequences 自动生成（约 74 条 actor → cameo shp 名），**无需游戏文件**。

## 结论：没有合适的「现成 PNG 包」

调研结果（2026-05）：

| 来源 | 情况 |
|------|------|
| **OpenRA / cookgreen YR mod** | 只有 yaml 里的 `icon: htnkicon` 引用，**不含** shp/png 资产（EA 版权，不能随 mod 分发） |
| **GitHub 开源 PNG 全集** | 未找到覆盖 RA2+YR 全部斗蛐蛐单位的合法 PNG 包 |
| **CnC Wiki (fandom)** | 各兵种页面有 cameo 截图，但尺寸/语言版本不一，且需逐页爬取，不适合批量 |
| **ModDB / DavoOnline 等** | 零散 mod 用 cameo，不是完整 vanilla+YR 集 |
| **原版游戏 mix** | ✅ **唯一完整、风格统一、与 OpenRA 对齐的来源** |

RA2+YR 斗蛐蛐池约 **58 个可上场单位**，cameo 全部在 Westwood 的 mix 里：

- `language.mix` → `cameo.mix`（RA2 本体图标）
- `langmd.mix` → `cameomd.mix`（尤里复仇新增/替换图标）

比帝国时代解包简单得多：**两个嵌套 mix + 一张调色板**，一次脚本跑完。

## 推荐做法（一次导出，永久使用）

### 前提

合法拥有的任一来源：

1. **Steam / Origin 原版 RA2 + YR**
2. **OpenRA「Manage Content」已导入** 的 `%APPDATA%\OpenRA\Content\ra2\` 与 `...\yr\`

### 命令

```powershell
cd I:\QQBotForFun
uv pip install ra2mix Pillow

# 自动搜索 Steam / OpenRA Content / RA2_DIR
uv run python scripts/crawler/ra2_icon_export.py

# 或手动指定（YR 单独目录时）
uv run python scripts/crawler/ra2_icon_export.py `
  --ra2-dir "D:\Games\Red Alert 2" `
  --yr-dir "D:\Games\Yuri's Revenge"
```

环境变量：`RA2_DIR`、`RA2_PATH` 也可指向安装根目录。

产出：`resources/ra2/icons/{actor_id}.png`（约 70+ 张）。

### OpenRA Content 路径（Windows）

```
%APPDATA%\OpenRA\Content\ra2\   ← language.mix, ra2.mix
%APPDATA%\OpenRA\Content\yr\    ← langmd.mix, ra2md.mix
```

若只装了 RA2 没装 YR content，YR 单位（飞碟、心控车、尤里等）icon 会缺失。

## 部署

服务器跑完导出后，将 `resources/ra2/icons/*.png` 一并部署；缺失的 id 仅发文字详情，不影响开战（与 aoe3 坏图兜底相同）。

## 不推荐

- 从 Wiki 批量爬图：版权与一致性风险，且 actor_id 映射需手工维护
- 用 voxel 渲染代替 cameo：风格与游戏内建造栏不一致
