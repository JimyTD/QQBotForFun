"""统一解析 OpenRA vendor 目录位置。

约定（按优先级）：
1. 命令行 `--vendor` 显式传入（调用方自行处理）
2. 环境变量 `QQBOT_VENDOR` 指向 vendor 根（含 openra-ra2/ openra/）
3. 项目同级目录 `../vendor-openra/`（推荐布局；不进部署上传，不污染 git）
4. 项目内 `./vendor/`（旧布局兜底，仍可用）

vendor 只在导出脚本 / 测试参考时读取，不参与运行时与部署。
"""

from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def vendor_root() -> Path:
    """返回 vendor 根目录（含 openra-ra2/ openra/ 子目录），不保证存在。"""
    env = os.environ.get("QQBOT_VENDOR")
    if env:
        return Path(env).expanduser().resolve()

    sibling = (_PROJECT_ROOT.parent / "vendor-openra").resolve()
    if sibling.is_dir():
        return sibling

    legacy = (_PROJECT_ROOT / "vendor").resolve()
    if (legacy / "openra-ra2").is_dir() or (legacy / "openra").is_dir():
        return legacy

    # 都没找到，按推荐位置返回（让上层自行报错）
    return sibling


def openra_ra2_dir() -> Path:
    return vendor_root() / "openra-ra2"


def openra_dir() -> Path:
    return vendor_root() / "openra"


def yuris_revenge_dir() -> Path:
    """cookgreen/Yuris-Revenge（YR 权威规则与 OpenRA.Mods.YR）。"""
    return vendor_root() / "yuris-revenge"
