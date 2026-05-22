"""从原版 RA2 cameo.mix 导出斗蛐蛐用 PNG icon。

依赖（导出机安装）:
    uv pip install ra2mix Pillow

需要原版游戏或 OpenRA 已安装的 mix（含 cameo.mix / cameo.pal）。

用法:
    uv run python scripts/crawler/ra2_icon_export.py
    uv run python scripts/crawler/ra2_icon_export.py --ra2-dir "D:/Games/Red Alert 2"
    uv run python scripts/crawler/ra2_icon_export.py --cameo-mix path/to/cameo.mix --palette path/to/cameo.pal

产出: resources/ra2/icons/{actor_id}.png
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src"
_SCRIPTS = _ROOT / "scripts"
for _p in (_SRC, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from plugins.games.ra2_battle.icon_map import build_icon_map  # noqa: E402
from plugins.games.ra2_battle.openra_yaml import load_rules_dir  # noqa: E402
from plugins.games.ra2_battle.shp_ts import (  # noqa: E402
    decode_shp_ts_first_frame,
    frame_to_rgba,
    load_jasc_pal,
)
from _vendor_path import openra_ra2_dir  # noqa: E402

OUT_DIR = _ROOT / "resources" / "ra2" / "icons"
ICON_MAP_PATH = _ROOT / "data" / "ra2" / "icon_map.json"
ACTORS_PATH = _ROOT / "data" / "ra2" / "actors.json"


def _find_cameo_assets(ra2_dir: Path) -> tuple[Path, Path]:
    """在 RA2 安装目录或 OpenRA Content 中定位 cameo.mix / cameo.pal。"""
    candidates_mix = [
        ra2_dir / "cameo.mix",
        ra2_dir / "Content" / "ra2" / "cameo.mix",
    ]
    candidates_pal = [
        ra2_dir / "cameo.pal",
        ra2_dir / "Content" / "ra2" / "cameo.pal",
    ]
    lang = ra2_dir / "language.mix"
    if lang.is_file():
        candidates_mix.insert(0, lang)

    mix_path = next((p for p in candidates_mix if p.is_file()), None)
    pal_path = next((p for p in candidates_pal if p.is_file()), None)
    if mix_path and mix_path.name.lower() == "language.mix" and pal_path is None:
        import ra2mix

        lang_files = ra2mix.read(str(mix_path))
        pal_blob = lang_files.get("cameo.pal") or lang_files.get("CAMEO.PAL")
        if pal_blob:
            tmp_pal = mix_path.parent / "_cameo_extracted.pal"
            tmp_pal.write_bytes(pal_blob)
            pal_path = tmp_pal
    if mix_path is None:
        raise FileNotFoundError(
            f"未找到 cameo.mix（已查 {ra2_dir}）。请用 --cameo-mix 指定。"
        )
    if pal_path is None:
        raise FileNotFoundError(
            f"未找到 cameo.pal（已查 {ra2_dir}）。请用 --palette 指定。"
        )
    return mix_path, pal_path


def _load_cameo_filemap(mix_path: Path) -> dict[str, bytes]:
    import ra2mix

    if mix_path.name.lower() == "language.mix":
        lang_files = ra2mix.read(str(mix_path))
        nested = lang_files.get("cameo.mix") or lang_files.get("CAMEO.MIX")
        if nested is None:
            raise FileNotFoundError("language.mix 内无 cameo.mix")
        tmp = mix_path.parent / "_cameo_nested.mix"
        tmp.write_bytes(nested)
        try:
            return ra2mix.read(str(tmp))
        finally:
            tmp.unlink(missing_ok=True)
    return ra2mix.read(str(mix_path))


def export_icons(
    *,
    icon_map: dict[str, str],
    cameo_files: dict[str, bytes],
    palette: bytes,
    resize: int = 128,
) -> tuple[int, int, list[str]]:
    try:
        from PIL import Image
    except ImportError as e:
        raise SystemExit("请安装 Pillow: uv pip install Pillow") from e

    pal = load_jasc_pal(palette)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ok = 0
    fail = 0
    missing: list[str] = []

    for aid, shp_name in icon_map.items():
        key = shp_name.lower()
        blob = cameo_files.get(key) or cameo_files.get(key.upper())
        if blob is None:
            missing.append(aid)
            fail += 1
            continue
        try:
            frame = decode_shp_ts_first_frame(blob)
            rgba = frame_to_rgba(frame, pal)
            img = Image.frombytes("RGBA", (frame.width, frame.height), rgba)
            img = img.resize((resize, resize), Image.Resampling.LANCZOS)
            out = OUT_DIR / f"{aid}.png"
            img.save(out, optimize=True)
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {aid} ({shp_name}): {e}")
            fail += 1

    return ok, fail, missing


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--vendor",
        type=Path,
        default=None,
        help="openra-ra2 目录；缺省按 QQBOT_VENDOR / ../vendor-openra/ / ./vendor/ 查找",
    )
    p.add_argument(
        "--ra2-dir",
        type=Path,
        default=None,
        help="RA2 安装目录或 OpenRA Content/ra2（含 cameo.mix）",
    )
    p.add_argument("--cameo-mix", type=Path, default=None)
    p.add_argument("--palette", type=Path, default=None)
    p.add_argument("--resize", type=int, default=128)
    args = p.parse_args()

    if not ACTORS_PATH.is_file():
        raise SystemExit("请先运行 openra_ra2_export.py 生成 data/ra2/actors.json")

    actor_ids = set(json.loads(ACTORS_PATH.read_text(encoding="utf-8")).keys())
    vendor = args.vendor.resolve() if args.vendor else openra_ra2_dir()

    raw_rules = load_rules_dir(vendor / "mods" / "ra2" / "rules")
    icon_map = build_icon_map(vendor, actor_ids, raw_rules)
    ICON_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    ICON_MAP_PATH.write_text(
        json.dumps(icon_map, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"icon_map: {len(icon_map)} 条 -> {ICON_MAP_PATH}")

    if args.cameo_mix and args.palette:
        mix_path, pal_path = args.cameo_mix.resolve(), args.palette.resolve()
    else:
        ra2_dir = args.ra2_dir
        if ra2_dir is None:
            for env in ("RA2_DIR", "RA2_PATH", "OPENRA_SUPPORT_DIR"):
                if os.environ.get(env):
                    ra2_dir = Path(os.environ[env])
                    break
        if ra2_dir is None:
            ra2_dir = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Red Alert 2")
        mix_path, pal_path = _find_cameo_assets(ra2_dir.resolve())

    print(f"cameo: {mix_path}")
    print(f"palette: {pal_path}")

    try:
        import ra2mix  # noqa: F401
    except ImportError as e:
        raise SystemExit("请安装 ra2mix: uv pip install ra2mix") from e

    cameo_files = _load_cameo_filemap(mix_path)
    palette = pal_path.read_bytes()
    ok, fail, missing = export_icons(
        icon_map=icon_map,
        cameo_files=cameo_files,
        palette=palette,
        resize=args.resize,
    )
    print(f"完成: 成功 {ok}, 失败 {fail}, 输出 {OUT_DIR}")
    if missing:
        print(f"  mix 中缺 shp ({len(missing)}): {', '.join(missing[:12])}...")


if __name__ == "__main__":
    main()
