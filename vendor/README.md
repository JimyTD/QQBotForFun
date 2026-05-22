# vendor/ 占位说明

红警2斗蛐蛐以 [OpenRA/ra2](https://github.com/OpenRA/ra2) 的 mod yaml 为唯一权威数据源，
但**参考源码不放在项目目录内**——它们体积大（~90MB）、与运行时无关，
且会拖慢 `deploy_project_preparation` 的整体上传。

## 推荐布局

把 OpenRA 源码放在**项目同级目录** `../vendor-openra/`：

```
i:/QQBotForFun/        ← 项目本体（这个仓库）
i:/vendor-openra/      ← OpenRA 参考源码（独立、不入库、不部署）
    ├── openra-ra2/    git clone https://github.com/OpenRA/ra2.git
    └── openra/        git clone https://github.com/OpenRA/OpenRA.git
```

## 一键 clone

```powershell
# Windows
.\scripts\setup_openra_vendor.ps1
```

```bash
# 手动（任意平台）
mkdir ../vendor-openra
git clone --depth 1 https://github.com/OpenRA/ra2.git ../vendor-openra/openra-ra2
git clone --depth 1 https://github.com/OpenRA/OpenRA.git ../vendor-openra/openra
```

## 自定义路径

通过环境变量覆盖（多项目共用一份时方便）：

```powershell
setx QQBOT_VENDOR "D:/dev/vendor-openra"
```

## 解析优先级

`scripts/_vendor_path.py` 按以下顺序查找 vendor：

1. 脚本 `--vendor` 命令行参数
2. 环境变量 `QQBOT_VENDOR`
3. 项目同级 `../vendor-openra/`（推荐）
4. 项目内 `./vendor/`（旧布局兜底）

## 用 vendor 做什么

只在**离线导出**时用：

```bash
# 导出兵种/武器/Locomotor JSON 到 data/ra2/
uv run python scripts/crawler/openra_ra2_export.py

# 从 RA2 cameo.mix 导出兵种 PNG 到 resources/ra2/icons/
uv run python scripts/crawler/ra2_icon_export.py --ra2-dir "你的RA2安装目录"
```

运行时插件只读 `data/ra2/*.json` 和 `resources/ra2/icons/*.png`，**不依赖 vendor**。
