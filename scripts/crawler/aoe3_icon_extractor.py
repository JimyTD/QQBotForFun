"""AoE3 DE Icon Extractor — 从 ArtUnitsTextures*.bar 批量提取单位 icon 并转 PNG。

依赖: pip install Pillow lz4

用法: python scripts/crawler/aoe3_icon_extractor.py
"""
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from scripts.crawler.aoe3_bar_extractor import read_bar_entries, extract_file_data

try:
    from PIL import Image
except ImportError:
    print("ERROR: pip install Pillow")
    sys.exit(1)

import xml.etree.ElementTree as ET

# ============================================================
# Config
# ============================================================
GAME_ART_DIR = r"E:\SteamLibrary\steamapps\common\AoE3DE\Game\Art"
GAME_UI_DIR = r"E:\SteamLibrary\steamapps\common\AoE3DE\Game\UI"
EXTRACTED_DIR = Path(__file__).resolve().parent / "_extracted"
PROTOY_PATH = EXTRACTED_DIR / "protoy.xml"
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "resources" / "aoe3" / "icons"

# BAR files to scan for icons
ICON_BARS = [
    # Art bars (DDT format)
    (GAME_ART_DIR, "ArtUnitsTextures1.bar"),
    (GAME_ART_DIR, "ArtUnitsTextures2.bar"),
    (GAME_ART_DIR, "ArtUnitsTextures3.bar"),
    (GAME_ART_DIR, "ArtUnitsTextures4.bar"),
    (GAME_ART_DIR, "ArtUnitsTextures5.bar"),
    (GAME_ART_DIR, "ArtUI.bar"),
    (GAME_ART_DIR, "Art.bar"),
    (GAME_ART_DIR, "ArtObjects.bar"),
    (GAME_ART_DIR, "ArtNuggets.bar"),
    # UI bars (PNG format, DE DLC content)
    (GAME_UI_DIR, "UIResources1.bar"),
]


# ============================================================
# DDT decoder
# ============================================================
def decode_ddt_to_png(ddt_data: bytes) -> Image.Image | None:
    """Decode RTS3 DDT format to PIL Image.
    
    RTS3 DDT: 'RTS3'(4) + format(4) + width(4) + height(4) + mipmap_table...
    Mipmap table: pairs of (offset, size) for each level.
    """
    if len(ddt_data) < 16:
        return None
    if ddt_data[:4] != b'RTS3':
        return None

    width = struct.unpack_from('<I', ddt_data, 8)[0]
    height = struct.unpack_from('<I', ddt_data, 12)[0]
    if width == 0 or height == 0:
        return None

    # First mipmap (largest): offset at byte 16, size at byte 20
    mip0_offset = struct.unpack_from('<I', ddt_data, 16)[0]
    mip0_size = struct.unpack_from('<I', ddt_data, 20)[0]

    if mip0_offset + mip0_size > len(ddt_data):
        return None

    pixel_data = ddt_data[mip0_offset:mip0_offset + mip0_size]

    # Determine format from data size
    # DXT1 (BC1): 8 bytes per 4x4 block = w*h/2
    # DXT5 (BC3): 16 bytes per 4x4 block = w*h
    # BGRA8888: 4 bytes per pixel = w*h*4
    expected_dxt1 = (width * height) // 2
    expected_dxt5 = width * height
    expected_bgra = width * height * 4

    try:
        if mip0_size == expected_dxt1:
            return Image.frombytes('RGBA', (width, height), pixel_data, 'bcn', (1,))
        elif mip0_size == expected_dxt5:
            return Image.frombytes('RGBA', (width, height), pixel_data, 'bcn', (3,))
        elif mip0_size == expected_bgra:
            return Image.frombytes('RGBA', (width, height), pixel_data, 'raw', 'BGRA')
        else:
            # Try DXT1 first, then DXT5
            try:
                return Image.frombytes('RGBA', (width, height), pixel_data, 'bcn', (1,))
            except Exception:
                return Image.frombytes('RGBA', (width, height), pixel_data, 'bcn', (3,))
    except Exception:
        return None


# ============================================================
# Main
# ============================================================
def main():
    print("=== AoE3 DE Icon Extractor ===\n")

    # Load protoy to get icon paths per unit
    print("Loading protoy.xml...")
    tree = ET.parse(PROTOY_PATH)
    root = tree.getroot()

    # Build: unit_id -> list of candidate icon paths (normalized)
    unit_icons: dict[str, list[str]] = {}
    for u in root.findall('unit'):
        icon_path = u.findtext('icon', '').strip()
        if icon_path:
            unit_id = u.get('name', '').lower()
            raw = icon_path.replace('\\', '/').lower()
            candidates = []
            # Keep original path (for UIResources which stores full path)
            candidates.append(raw)
            # Also try with .ddt extension
            if raw.endswith('.png'):
                candidates.append(raw[:-4] + '.ddt')
            # Also try without "resources/art/" prefix (for Art bars)
            if raw.startswith('resources/art/'):
                stripped = raw[len('resources/art/'):]
                candidates.append(stripped)
                if stripped.endswith('.png'):
                    candidates.append(stripped[:-4] + '.ddt')
            unit_icons[unit_id] = candidates

    print(f"  {len(unit_icons)} units with icon paths")

    # Build index of all icon files across BAR archives
    print("\nScanning BAR files for icons...")
    bar_index: dict[str, tuple[str, dict]] = {}  # normalized_path -> (bar_path, entry)

    for bar_dir, bar_name in ICON_BARS:
        bar_path = os.path.join(bar_dir, bar_name)
        if not os.path.exists(bar_path):
            print(f"  WARNING: {bar_name} not found")
            continue
        entries = read_bar_entries(bar_path)
        for e in entries:
            name_norm = e['name'].replace('\\', '/').lower()
            if name_norm.endswith('.ddt') or name_norm.endswith('.png'):
                bar_index[name_norm] = (bar_path, e)

    print(f"  {len(bar_index)} DDT/PNG files indexed")

    # Match unit icons to BAR entries
    print("\nMatching unit icons to BAR entries...")

    # Build a secondary index by filename stem (without resolution suffix)
    import re
    stem_index: dict[str, tuple[str, dict]] = {}
    for name_norm, val in bar_index.items():
        filename = name_norm.rsplit('/', 1)[-1]
        stem = re.sub(r'_\d+x\d+', '', filename)
        stem = re.sub(r'_\d+\.(ddt|png)$', r'.\1', stem)
        stem = re.sub(r'\.(ddt|png)$', '', stem)
        if stem not in stem_index:
            stem_index[stem] = val

    matched = 0
    unmatched = []
    match_map: dict[str, tuple[str, dict]] = {}  # unit_id -> (bar_path, entry)

    for unit_id, candidates in unit_icons.items():
        found = False
        # Try exact path match first
        for cand in candidates:
            if cand in bar_index:
                match_map[unit_id] = bar_index[cand]
                matched += 1
                found = True
                break
        if found:
            continue

        # Try filename stem match
        for cand in candidates:
            filename = cand.rsplit('/', 1)[-1]
            stem = re.sub(r'_\d+x\d+', '', filename)
            stem = re.sub(r'_\d+\.(ddt|png)$', r'.\1', stem)
            stem = re.sub(r'\.(ddt|png)$', '', stem)
            if stem in stem_index:
                match_map[unit_id] = stem_index[stem]
                matched += 1
                found = True
                break

        if not found:
            unmatched.append((unit_id, candidates[0]))

    print(f"  Matched: {matched}/{len(unit_icons)}")
    print(f"  Unmatched: {len(unmatched)}")
    if unmatched:
        print(f"  Unmatched samples: {[(uid, p) for uid, p in unmatched[:5]]}")

    # Extract and convert
    print(f"\nExtracting icons to {OUTPUT_DIR}...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    success = 0
    failed = 0
    for unit_id, (bar_path, entry) in match_map.items():
        out_file = OUTPUT_DIR / f"{unit_id}.png"

        try:
            raw_data = extract_file_data(bar_path, entry)
            if entry['name'].lower().endswith('.png'):
                # Already PNG, save directly
                with open(out_file, 'wb') as f:
                    f.write(raw_data)
                success += 1
            else:
                # DDT format, decode
                img = decode_ddt_to_png(raw_data)
                if img:
                    img.save(out_file)
                    success += 1
                else:
                    failed += 1
        except Exception as e:
            failed += 1
            if failed <= 5:
                print(f"  ERROR: {unit_id}: {e}")

    print(f"\n  Success: {success}")
    print(f"  Failed: {failed}")
    print(f"  Total PNGs in output dir: {len(list(OUTPUT_DIR.glob('*.png')))}")


if __name__ == '__main__':
    main()
