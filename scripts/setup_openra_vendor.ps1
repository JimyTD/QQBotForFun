# 克隆 OpenRA 参考仓库（vendor/ 已 gitignore）
$root = Split-Path -Parent $PSScriptRoot
$vendor = Join-Path $root "vendor"
New-Item -ItemType Directory -Force -Path $vendor | Out-Null

if (-not (Test-Path (Join-Path $vendor "openra-ra2\.git"))) {
    git clone --depth 1 https://github.com/OpenRA/ra2.git (Join-Path $vendor "openra-ra2")
}
if (-not (Test-Path (Join-Path $vendor "openra\.git"))) {
    git clone --depth 1 https://github.com/OpenRA/OpenRA.git (Join-Path $vendor "openra")
}

Write-Host "完成。请运行: uv run python scripts/crawler/openra_ra2_export.py"
