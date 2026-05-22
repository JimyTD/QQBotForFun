# 克隆 OpenRA 参考仓库（vendor 不入库、不部署）
#
# 推荐布局：放在项目同级目录 ../vendor-openra/
#   i:/QQBotForFun/        ← 项目本体
#   i:/vendor-openra/      ← OpenRA 参考源码（独立于项目）
#
# 也可通过 $env:QQBOT_VENDOR 自定义路径（多项目共用一份时方便）。

$ErrorActionPreference = "Stop"

if ($env:QQBOT_VENDOR) {
    $vendor = $env:QQBOT_VENDOR
} else {
    $projectRoot = Split-Path -Parent $PSScriptRoot
    $vendor = Join-Path (Split-Path -Parent $projectRoot) "vendor-openra"
}

New-Item -ItemType Directory -Force -Path $vendor | Out-Null
Write-Host "vendor 目录: $vendor"

if (-not (Test-Path (Join-Path $vendor "openra-ra2\.git"))) {
    git clone --depth 1 https://github.com/OpenRA/ra2.git (Join-Path $vendor "openra-ra2")
}
if (-not (Test-Path (Join-Path $vendor "openra\.git"))) {
    git clone --depth 1 https://github.com/OpenRA/OpenRA.git (Join-Path $vendor "openra")
}

Write-Host ""
Write-Host "完成。可选：把路径写入用户环境变量以便测试/导出脚本自动找到："
Write-Host "  setx QQBOT_VENDOR `"$vendor`""
Write-Host ""
Write-Host "导出数据：uv run python scripts/crawler/openra_ra2_export.py"
