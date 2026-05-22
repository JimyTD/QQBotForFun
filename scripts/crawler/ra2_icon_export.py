"""从原版 RA2 + YR cameo mix 导出斗蛐蛐用 PNG icon。

依赖（导出机安装）:
    uv pip install ra2mix Pillow

需要合法拥有的原版游戏 mix（见 resources/ra2/icons/README.md 来源说明）。

用法:
    uv run python scripts/crawler/ra2_icon_export.py
    uv run python scripts/crawler/ra2_icon_export.py --ra2-dir "D:/Games/Red Alert 2"
    uv run python scripts/crawler/ra2_icon_export.py --yr-dir "D:/Games/Yuri's Revenge"

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
from _vendor_path import yuris_revenge_dir  # noqa: E402

OUT_DIR = _ROOT / "resources" / "ra2" / "icons"
ICON_MAP_PATH = _ROOT / "data" / "ra2" / "icon_map.json"
ACTORS_PATH = _ROOT / "data" / "ra2" / "actors.json"


def _openra_content_root() -> Path | None:
    for base in (
        os.environ.get("OPENRA_SUPPORT_DIR"),
        os.environ.get("APPDATA"),
        os.environ.get("LOCALAPPDATA"),
    ):
        if not base:
            continue
        root = Path(base).expanduser()
        if root.name.lower() == "openra":
            content = root / "Content"
        else:
            content = root / "OpenRA" / "Content"
        if content.is_dir():
            return content
    docs = Path.home() / "Documents" / "OpenRA" / "Content"
    return docs if docs.is_dir() else None


def _discover_asset_dirs(
    *,
    ra2_dir: Path | None,
    yr_dir: Path | None,
) -> list[Path]:
    """收集可能含 language.mix / langmd.mix 的目录（去重保序）。"""
    seen: set[Path] = set()
    out: list[Path] = []

    def add(p: Path | None) -> None:
        if p is None:
            return
        p = p.expanduser().resolve()
        if p.is_dir() and p not in seen:
            seen.add(p)
            out.append(p)

    add(ra2_dir)
    add(yr_dir)

    for env in ("RA2_DIR", "RA2_PATH"):
        if os.environ.get(env):
            add(Path(os.environ[env]))

    content = _openra_content_root()
    if content:
        add(content / "ra2")
        add(content / "yr")

    for guess in (
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\Red Alert 2"),
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\Command and Conquer Red Alert II"),
        Path(r"C:\Program Files (x86)\Origin Games\Command and Conquer Red Alert II"),
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\Yuri's Revenge"),
    ):
        add(guess)
        if guess.is_dir():
            add(guess / "Yuri's Revenge")

    return out


def _read_mix_filemap(mix_path: Path) -> dict[str, bytes]:
    import ra2mix

    return ra2mix.read(str(mix_path))


def _read_nested_mix(outer: Path, inner_names: tuple[str, ...]) -> dict[str, bytes]:
    """从 language.mix / langmd.mix 等外层 mix 解包内层 cameo mix。"""
    import ra2mix

    outer_files = ra2mix.read(str(outer))
    lowered = {k.lower(): v for k, v in outer_files.items()}
    for name in inner_names:
        blob = lowered.get(name.lower())
        if blob:
            tmp = outer.parent / f"_nested_{name.replace('.', '_')}.mix"
            tmp.write_bytes(blob)
            try:
                return ra2mix.read(str(tmp))
            finally:
                tmp.unlink(missing_ok=True)
    return {}


def _pick_palette(search_dirs: list[Path]) -> bytes:
    import ra2mix

    for d in search_dirs:
        pal = d / "cameo.pal"
        if pal.is_file():
            return pal.read_bytes()
        lang = d / "language.mix"
        if lang.is_file():
            files = ra2mix.read(str(lang))
            blob = files.get("cameo.pal") or files.get("CAMEO.PAL")
            if blob:
                return blob
    raise FileNotFoundError(
        "未找到 cameo.pal（请确认 RA2 安装或 OpenRA Content/ra2 含 language.mix）"
    )


def _load_all_cameo_files(search_dirs: list[Path]) -> dict[str, bytes]:
    """合并 RA2 cameo.mix + YR cameomd.mix（后者覆盖同名）。"""
    merged: dict[str, bytes] = {}
    sources: list[str] = []

    for d in search_dirs:
        direct = d / "cameo.mix"
        if direct.is_file():
            merged.update(_read_mix_filemap(direct))
            sources.append(str(direct))

        lang = d / "language.mix"
        if lang.is_file():
            part = _read_nested_mix(lang, ("cameo.mix",))
            if part:
                merged.update(part)
                sources.append(f"{lang} → cameo.mix")

        langmd = d / "langmd.mix"
        if langmd.is_file():
            part = _read_nested_mix(langmd, ("cameomd.mix",))
            if part:
                merged.update(part)
                sources.append(f"{langmd} → cameomd.mix")

    if not merged:
        dirs = ", ".join(str(p) for p in search_dirs) or "(无)"
        raise FileNotFoundError(
            f"未找到 cameo.mix / cameomd.mix（已查: {dirs}）。"
            "请用 --ra2-dir / --yr-dir 指定原版安装目录，或先通过 OpenRA 导入游戏资源。"
        )

    print(f"cameo 来源 ({len(sources)}):")
    for s in sources:
        print(f"  - {s}")
    print(f"  合计 shp: {len(merged)}")
    return merged


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
        help="yuris-revenge 目录；缺省 ../vendor-openra/yuris-revenge",
    )
    p.add_argument(
        "--ra2-dir",
        type=Path,
        default=None,
        help="RA2 安装目录或 OpenRA Content/ra2（含 language.mix）",
    )
    p.add_argument(
        "--yr-dir",
        type=Path,
        default=None,
        help="YR 安装目录或 OpenRA Content/yr（含 langmd.mix）",
    )
    p.add_argument("--cameo-mix", type=Path, default=None, help="手动指定 cameo.mix")
    p.add_argument("--palette", type=Path, default=None, help="手动指定 cameo.pal")
    p.add_argument("--resize", type=int, default=128)
    args = p.parse_args()

    if not ACTORS_PATH.is_file():
        raise SystemExit("请先运行 openra_ra2_export.py 生成 data/ra2/actors.json")

    actor_ids = set(json.loads(ACTORS_PATH.read_text(encoding="utf-8")).keys())
    vendor = args.vendor.resolve() if args.vendor else yuris_revenge_dir()
    mod = vendor / "mods" / "yr"
    if not mod.is_dir():
        raise SystemExit(f"未找到 YR mod: {mod}")

    raw_rules = load_rules_dir(mod / "rules")
    icon_map = build_icon_map(vendor, actor_ids, raw_rules, mod_id="yr")
    ICON_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    ICON_MAP_PATH.write_text(
        json.dumps(icon_map, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"icon_map: {len(icon_map)} 条 -> {ICON_MAP_PATH}")

    try:
        import ra2mix  # noqa: F401
    except ImportError as e:
        raise SystemExit("请安装 ra2mix: uv pip install ra2mix") from e

    if args.cameo_mix and args.palette:
        cameo_files = _read_mix_filemap(args.cameo_mix.resolve())
        palette = args.palette.resolve().read_bytes()
        print(f"cameo: {args.cameo_mix}")
        print(f"palette: {args.palette}")
    else:
        search_dirs = _discover_asset_dirs(ra2_dir=args.ra2_dir, yr_dir=args.yr_dir)
        if not search_dirs:
            raise SystemExit("未找到任何游戏目录，请设置 --ra2-dir / RA2_DIR")
        print("搜索目录:")
        for d in search_dirs:
            print(f"  - {d}")
        cameo_files = _load_all_cameo_files(search_dirs)
        palette = _pick_palette(search_dirs)

    ok, fail, missing = export_icons(
        icon_map=icon_map,
        cameo_files=cameo_files,
        palette=palette,
        resize=args.resize,
    )
    print(f"完成: 成功 {ok}, 失败 {fail}, 输出 {OUT_DIR}")
    if missing:
        print(f"  mix 中缺 shp ({len(missing)}): {', '.join(missing[:16])}")


if __name__ == "__main__":
    main()
