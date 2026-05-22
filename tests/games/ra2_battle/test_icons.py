"""icon 资源与 icon_map 覆盖。"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

from plugins.games.ra2_battle.icon_map import build_icon_map
from plugins.games.ra2_battle.icons import get_icon_path, load_icon_map
from plugins.games.ra2_battle.shp_ts import decode_shp_ts_first_frame

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from _vendor_path import openra_ra2_dir  # noqa: E402

_VENDOR = openra_ra2_dir()
_ICON_MAP = _ROOT / "data" / "ra2" / "icon_map.json"
_ACTORS = _ROOT / "data" / "ra2" / "actors.json"
_ICONS_DIR = _ROOT / "resources" / "ra2" / "icons"


def test_icon_map_covers_exported_actors():
    if not _ICON_MAP.is_file() or not _ACTORS.is_file():
        pytest.skip("缺少 data/ra2")
    actors = json.loads(_ACTORS.read_text(encoding="utf-8"))
    icon_map = json.loads(_ICON_MAP.read_text(encoding="utf-8"))
    missing = [aid for aid in actors if aid not in icon_map]
    assert not missing, f"icon_map 缺: {missing[:10]}"
    assert len(icon_map) >= 40


@pytest.mark.skipif(not _VENDOR.is_dir(), reason="无 vendor/openra-ra2")
def test_build_icon_map_from_vendor():
    actors = json.loads(_ACTORS.read_text(encoding="utf-8")) if _ACTORS.is_file() else {}
    m = build_icon_map(_VENDOR, set(actors.keys()))
    assert "e1" in m and m["e1"] == "giicon.shp"
    assert "ccomand" in m and m["ccomand"] == "ccomicon.shp"
    assert m.get("dog") == "adogicon.shp"


def test_get_icon_path_validates_png():
    _ICONS_DIR.mkdir(parents=True, exist_ok=True)
    p = _ICONS_DIR / "_test_icon.png"
    # minimal 1x1 PNG
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    p.write_bytes(png)
    try:
        assert get_icon_path("_test_icon") == p
        p.write_bytes(b"not a png!!!!!")
        assert get_icon_path("_test_icon") is None
    finally:
        p.unlink(missing_ok=True)


def test_shp_ts_header_roundtrip():
    # 最小合法头 + 空帧会被跳过；仅验证解析不崩
    header = struct.pack("<HHHH", 0, 60, 48, 0)
    with pytest.raises(ValueError):
        decode_shp_ts_first_frame(header)
