"""AoE3 DE Anim Extractor — 从 ArtUnits.bar 提取战斗单位 anim XML（windup 用）。

从 protoy.xml 收集战斗单位的 animfile，在 ArtUnits.bar 中解包为 XML，
写入 data/aoe3/raw/anims/（保留相对路径，如 units/musketeer/musketeer.xml）。

用法:
  uv run python scripts/crawler/aoe3_anim_extractor.py
  uv run python scripts/crawler/aoe3_anim_extractor.py --protoy data/aoe3/raw/protoy.xml

依赖: lz4（与 aoe3_bar_extractor 相同）
"""
from __future__ import annotations

import argparse
import os
import xml.etree.ElementTree as ET
from pathlib import Path

from aoe3_bar_extractor import decode_xmb_to_xml, extract_file_data, read_bar_entries

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "aoe3" / "raw"
DEFAULT_ART_BAR = r"E:\SteamLibrary\steamapps\common\AoE3DE\Game\Art\ArtUnits.bar"


def _is_combat_unit(el: ET.Element, unit_types: set[str]) -> bool:
    hp = float(el.findtext("maxhitpoints", "0") or "0")
    if hp <= 0:
        return False
    has_attack = any(
        float(a.findtext("damage") or "0") > 0 for a in el.findall("protoaction")
    )
    if not has_attack or not el.findall("cost"):
        return False
    if "EmbellishmentClass" in unit_types or "Projectile" in unit_types:
        return False
    if unit_types & {"AbstractBuilding", "AbstractWall", "AbstractTownCenter",
                     "AbstractDock", "AbstractFort"}:
        return False
    return "Military" in unit_types or "Unit" in unit_types


def collect_combat_animfiles(protoy_path: Path) -> set[str]:
    """返回战斗单位引用的 animfile 路径集合（protoy 原样，反斜杠）。"""
    tree = ET.parse(protoy_path)
    animfiles: set[str] = set()
    for el in tree.getroot().findall("unit"):
        types = {ut.text.strip() for ut in el.findall("unittype") if ut.text}
        if not _is_combat_unit(el, types):
            continue
        animfile = (el.findtext("animfile") or "").strip()
        if animfile:
            animfiles.add(animfile)
    return animfiles


def animfile_to_bar_key(animfile: str) -> str:
    return animfile.replace("/", "\\") + ".XMB"


def animfile_to_output_path(output_dir: Path, animfile: str) -> Path:
    rel = animfile.replace("\\", "/")
    return output_dir / rel


def extract_anims(
    protoy_path: Path,
    art_bar: str,
    output_dir: Path,
) -> tuple[int, int, list[str]]:
    """解包战斗单位 anim。返回 (成功数, 跳过数, 缺失 BAR 条目列表)。"""
    animfiles = collect_combat_animfiles(protoy_path)
    entries = {e["name"]: e for e in read_bar_entries(art_bar)}
    ok = 0
    skipped = 0
    missing: list[str] = []

    for animfile in sorted(animfiles):
        out_path = animfile_to_output_path(output_dir, animfile)
        bar_key = animfile_to_bar_key(animfile)
        entry = entries.get(bar_key)
        if not entry:
            missing.append(animfile)
            continue
        if out_path.exists() and out_path.stat().st_size > 0:
            skipped += 1
            continue
        try:
            xml_text = decode_xmb_to_xml(extract_file_data(art_bar, entry))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(xml_text, encoding="utf-8")
            ok += 1
        except Exception as ex:
            print(f"    WARNING: {animfile}: {ex}")

    return ok, skipped, missing


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract combat unit anim XML from ArtUnits.bar")
    parser.add_argument(
        "--protoy",
        default=str(DEFAULT_RAW_DIR / "protoy.xml"),
        help="Path to protoy.xml",
    )
    parser.add_argument(
        "--art-bar",
        default=os.environ.get("AOE3_ART_UNITS_BAR", DEFAULT_ART_BAR),
        help="Path to ArtUnits.bar",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_RAW_DIR / "anims"),
        help="Output directory for decoded anim XML",
    )
    args = parser.parse_args()

    protoy_path = Path(args.protoy)
    output_dir = Path(args.output_dir)
    if not protoy_path.exists():
        raise SystemExit(f"protoy.xml not found: {protoy_path}")

    animfiles = collect_combat_animfiles(protoy_path)
    print(f"Combat units animfiles: {len(animfiles)}")
    print(f"ArtUnits.bar: {args.art_bar}")

    ok, skipped, missing = extract_anims(protoy_path, args.art_bar, output_dir)
    print(f"\nExtracted: {ok}, skipped (already present): {skipped}, missing in BAR: {len(missing)}")
    if missing:
        print("  Missing sample:", missing[:5])
    print(f"Output: {output_dir}")


if __name__ == "__main__":
    main()
