"""红警2斗蛐蛐测试 —— 自动打 `ra2` 标记。

红警玩法仍在线，但已基本不再迭代；这批战斗模拟测试约 32s，占全套测试 ~70%，
所以默认跳过（`pyproject.toml` 的 `addopts = "-m 'not ra2'"`）。

- 日常 `uv run pytest` → 本目录整体跳过（除 `test_import_smoke.py`）
- 改动 `src/plugins/games/ra2_battle/` 时**必须**手动跑：
  `uv run pytest tests/games/ra2_battle -m ra2`

不在此目录逐个文件加 `pytestmark`，是为了新增测试文件时不会漏标。
"""

from __future__ import annotations

import pytest

# 这些文件不打标记 —— 极快的接口冒烟测试，用于兜住 core 接口漂移，必须每次都跑。
_ALWAYS_RUN = {"test_import_smoke.py"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    here = __file__.rsplit("conftest.py", 1)[0]
    for item in items:
        path = str(item.fspath)
        if not path.startswith(here):
            continue
        if path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] in _ALWAYS_RUN:
            continue
        item.add_marker(pytest.mark.ra2)
