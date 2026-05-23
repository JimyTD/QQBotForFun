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
EXTRACTED_DIR = Path(os.environ.get("AOE3_EXTRACTED_DIR", r"E:\aoe3_extracted"))
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
            img = Image.frombytes('RGBA', (width, height), pixel_data, 'bcn', (1,))
        elif mip0_size == expected_dxt5:
            img = Image.frombytes('RGBA', (width, height), pixel_data, 'bcn', (3,))
        elif mip0_size == expected_bgra:
            img = Image.frombytes('RGBA', (width, height), pixel_data, 'raw', 'BGRA')
        else:
            # Try DXT1 first, then DXT5
            try:
                img = Image.frombytes('RGBA', (width, height), pixel_data, 'bcn', (1,))
            except Exception:
                img = Image.frombytes('RGBA', (width, height), pixel_data, 'bcn', (3,))
        return img
    except Exception:
        return None


# ============================================================
# Decode helpers
# ============================================================
def _try_decode(raw_data: bytes) -> "Image.Image | None":
    """尝试从原始字节解码出图片。

    支持格式：
    1. 真 PNG（magic: 89504e47）
    2. RTS3 DDT（magic: RTS3）
    3. DE 版裸 DXT5/BC3 纹理（无头，数据 >= 65536 bytes 即 256x256 mip0）
    """
    if raw_data[:8] == b'\x89PNG\r\n\x1a\n':
        from io import BytesIO
        return Image.open(BytesIO(raw_data))
    if raw_data[:4] == b'RTS3':
        return decode_ddt_to_png(raw_data)

    # 注意：不再盲目尝试裸 DXT5 解码——没有 RTS3 header 也不是 PNG 的文件
    # 很可能是匹配错误，强行解码只会产生噪声乱码。
    # 正确的 DDT 文件都有 RTS3 magic header。

    return None


def _find_higher_res(unit_id: str, current_entry: dict, current_img: "Image.Image",
                     bar_index: dict, min_size: int = 128) -> "Image.Image | None":
    """如果当前图片分辨率不足 min_size，搜索同单位的 portrait 等高分辨率替代。

    搜索策略：
    1. 将 _icon 替换为 _portrait 或 _icon_portrait 匹配
    2. 在同目录下搜索 portrait 文件
    """
    import re
    if current_img and min(current_img.size) >= min_size:
        return current_img  # 已经够大，不需要替代

    orig_name = current_entry['name'].replace('\\', '/').lower()

    # 构造 portrait 路径候选
    portrait_candidates = []
    # _icon.ddt -> _portrait.ddt
    if '_icon' in orig_name:
        portrait_candidates.append(re.sub(r'_icon(_\d+x\d+)?\.ddt$', '_portrait.ddt', orig_name))
        portrait_candidates.append(re.sub(r'_icon(_\d+x\d+)?\.ddt$', '_icon_portrait.ddt', orig_name))
    # 也试目录下的同名 portrait
    dir_part = orig_name.rsplit('/', 1)[0] if '/' in orig_name else ''
    stem_base = re.sub(r'(_icon|_portrait)(_\d+x\d+)?\.ddt$', '', orig_name.rsplit('/', 1)[-1])
    if dir_part:
        portrait_candidates.append(f"{dir_part}/{stem_base}_portrait.ddt")

    for cand in portrait_candidates:
        if cand in bar_index:
            alt_bar_path, alt_entry = bar_index[cand]
            try:
                alt_data = extract_file_data(alt_bar_path, alt_entry)
                img = _try_decode(alt_data)
                if img and min(img.size) >= min_size:
                    return img
            except Exception:
                continue

    return current_img  # 没找到更大的，返回原图


def _try_alternatives(unit_id: str, original_entry: dict,
                      bar_index: dict, unit_icons: dict) -> "Image.Image | None":
    """首选条目不可解码时，在 BAR index 中查找替代条目。

    策略（按优先级）：
    1. 同 stem 的 portrait（128x128，高分辨率）
    2. 同文件名 stem 的 _64x64.png（DE 预渲染的 UI icon）
    3. 同文件名 stem 的 .ddt（ArtUnitsTextures 中的 RTS3 DDT）
    4. 同 stem 的任何其他可解码条目
    """
    import re
    orig_name = original_entry['name'].replace('\\', '/').lower()
    orig_filename = orig_name.rsplit('/', 1)[-1]
    stem = re.sub(r'(_\d+x\d+)?\.(ddt|png)$', '', orig_filename)

    # 在全 bar_index 中查找包含这个 stem 的条目
    candidates = []
    for name_norm, val in bar_index.items():
        fn = name_norm.rsplit('/', 1)[-1]
        fn_stem = re.sub(r'(_\d+x\d+)?\.(ddt|png)$', '', fn)
        if fn_stem == stem:
            candidates.append((name_norm, val))

    # 也搜索 portrait 变体（stem_base + _portrait）
    stem_base = re.sub(r'_(icon|portrait)$', '', stem)
    if stem_base != stem:
        for name_norm, val in bar_index.items():
            fn = name_norm.rsplit('/', 1)[-1]
            fn_stem = re.sub(r'(_\d+x\d+)?\.(ddt|png)$', '', fn)
            if fn_stem == f"{stem_base}_portrait" and (name_norm, val) not in candidates:
                candidates.append((name_norm, val))

    # 排序：优先 portrait > _64x64.png > .ddt > 其他 .png
    def sort_key(item):
        name = item[0]
        if 'portrait' in name:
            return 0
        if '_64x64.png' in name:
            return 1
        if name.endswith('.ddt'):
            return 2
        return 3

    candidates.sort(key=sort_key)

    for name_norm, (alt_bar_path, alt_entry) in candidates:
        if alt_entry is original_entry:
            continue  # 跳过原始条目（已知不可解码）
        try:
            alt_data = extract_file_data(alt_bar_path, alt_entry)
            img = _try_decode(alt_data)
            if img:
                return img
        except Exception:
            continue
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
            img = _try_decode(raw_data)

            # 如果首选条目不可解码，尝试替代条目
            if img is None:
                img = _try_alternatives(unit_id, entry, bar_index, unit_icons)

            # 如果解码成功但分辨率太低，尝试找 portrait 高分辨率替代
            if img is not None and min(img.size) < 128:
                img = _find_higher_res(unit_id, entry, img, bar_index, min_size=128)

            if img:
                img.save(out_file)
                success += 1
            else:
                failed += 1
                if failed <= 10:
                    print(f"  FAILED: {unit_id} (no decodable entry found)")
        except Exception as e:
            failed += 1
            if failed <= 5:
                print(f"  ERROR: {unit_id}: {e}")

    print(f"\n  Success: {success}")
    print(f"  Failed: {failed}")
    print(f"  Total PNGs in output dir: {len(list(OUTPUT_DIR.glob('*.png')))}")


if __name__ == '__main__':
    main()
