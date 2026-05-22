"""红警2单位 icon（resources/ra2/icons/{actor_id}.png）。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
_ICONS_DIR = _ROOT / "resources" / "ra2" / "icons"
_ICON_MAP_PATH = _ROOT / "data" / "ra2" / "icon_map.json"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@lru_cache(maxsize=1)
def load_icon_map() -> dict[str, str]:
    if not _ICON_MAP_PATH.is_file():
        return {}
    raw = json.loads(_ICON_MAP_PATH.read_text(encoding="utf-8"))
    return {k: str(v).lower() for k, v in raw.items()}


def get_icon_path(actor_id: str) -> Path | None:
    """返回合法 PNG 路径；缺失或损坏则 None（与 aoe3_battle 一致）。"""
    p = _ICONS_DIR / f"{actor_id}.png"
    if not p.is_file():
        return None
    try:
        with p.open("rb") as f:
            if f.read(8) != _PNG_MAGIC:
                return None
    except OSError:
        return None
    return p
