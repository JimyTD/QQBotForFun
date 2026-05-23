"""AoE3 DE BAR Extractor — 从游戏 Data.bar 提取 XML 数据文件。

从帝国3决定版的 Data.bar 文件（BAR v6 格式）提取：
  - protoy.xml         (单位原型)
  - techtreey.xml      (科技树)
  - civs.xml           (文明数据)
  - stringtabley_en.xml (英文字符串表)
  - stringtabley_zh.xml (简体中文字符串表)

用法:
  python scripts/crawler/aoe3_bar_extractor.py [--bar-path PATH]

默认 BAR 路径: E:\\SteamLibrary\\steamapps\\common\\AoE3DE\\Game\\Data\\Data.bar
输出目录: E:\\aoe3_extracted (可通过环境变量 AOE3_EXTRACTED_DIR 覆盖)

依赖: pip install lz4
"""
from __future__ import annotations

import argparse
import os
import struct
import sys

sys.setrecursionlimit(100000)

DEFAULT_BAR = r"E:\SteamLibrary\steamapps\common\AoE3DE\Game\Data\Data.bar"
OUTPUT_DIR = os.environ.get("AOE3_EXTRACTED_DIR", r"E:\aoe3_extracted")


# ============================================================
# BAR v6 format reader
# ============================================================

def read_bar_entries(bar_path: str) -> list[dict]:
    """Read file directory from AoE3 DE BAR v6 archive.

    BAR v6 header (292 bytes):
      0x000: 'ESPN' (4) + version=6 (4) + 0x11223344 (4) + null padding (256)
      0x10C: padding (8) + unknown (4) + num_files (4) + padding (4) + dir_offset (4) + padding (4)

    Directory (at dir_offset):
      dir_name_len (4) + dir_name (unicode) + file_count (4)
      Per file: offset(4) + unk(4) + size_raw(4) + size_compressed(4) + size_decompressed(4) + name_len(4) + name(unicode) + flags(4)
    """
    entries = []
    with open(bar_path, "rb") as f:
        # Verify magic
        magic = f.read(4)
        if magic != b'ESPN':
            raise ValueError(f"Not a BAR file (expected ESPN, got {magic})")

        f.seek(280)
        num_files = struct.unpack('<I', f.read(4))[0]
        f.read(4)  # padding
        dir_offset = struct.unpack('<Q', f.read(8))[0]  # uint64 for large files

        f.seek(dir_offset)
        dir_name_len = struct.unpack('<I', f.read(4))[0]
        f.read(dir_name_len * 2)  # skip dir name
        file_count = struct.unpack('<I', f.read(4))[0]

        for _ in range(file_count):
            offset = struct.unpack('<I', f.read(4))[0]
            f.read(4)  # unknown
            size_raw = struct.unpack('<I', f.read(4))[0]
            size_compressed = struct.unpack('<I', f.read(4))[0]
            f.read(4)  # size_decompressed (same as compressed)
            name_len = struct.unpack('<I', f.read(4))[0]
            name = f.read(name_len * 2).decode('utf-16-le')
            flags = struct.unpack('<I', f.read(4))[0]
            entries.append({
                'name': name, 'offset': offset,
                'size_raw': size_raw, 'size_compressed': size_compressed,
                'flags': flags,
            })
    return entries


def extract_file_data(bar_path: str, entry: dict) -> bytes:
    """Extract and decompress a single file from BAR archive.

    Compression: alz4 format = 'alz4'(4) + decompressed_size(4) + compressed_size(4) + unknown(4) + LZ4 block data
    """
    import lz4.block

    with open(bar_path, "rb") as f:
        f.seek(entry['offset'])
        if entry['flags'] == 1 and entry['size_compressed'] < entry['size_raw']:
            compressed = f.read(entry['size_compressed'])
            assert compressed[:4] == b'alz4', f"Expected alz4, got {compressed[:4]}"
            decompressed_size = struct.unpack_from('<I', compressed, 4)[0]
            payload = compressed[16:]  # skip 16-byte alz4 header
            return lz4.block.decompress(payload, uncompressed_size=decompressed_size)
        else:
            return f.read(entry['size_raw'])


# ============================================================
# XMB decoder (AoE3 DE binary XML)
# ============================================================

def decode_xmb_to_xml(xmb_data: bytes) -> str:
    """Decode AoE3 DE XMB binary format to XML text.

    XMB structure:
      Header: 'X1'(2) + total_len(4) + 'XR'(2) + version(4) + unknown(4)
      Element name table: count(4) + [len(4) + name(utf16le)]*
      Attribute name table: count(4) + [len(4) + name(utf16le)]*
      Tree: XN-wrapped nodes (recursive)

    XN node wrapper: 'XN'(2) + subtree_len(4)
    Node data: text_len(4) + text(utf16) + elem_idx(4) + unknown(4) + num_attrs(4)
               + [attr_idx(4) + val_len(4) + val(utf16)]* + num_children(4)
               + [XN child]* (recursive)
    """
    # Parse header
    pos = 16  # X1(2)+len(4)+XR(2)+ver(4)+unk(4)

    num_elem = struct.unpack_from('<I', xmb_data, pos)[0]; pos += 4
    element_names: list[str] = []
    for _ in range(num_elem):
        nl = struct.unpack_from('<I', xmb_data, pos)[0]; pos += 4
        element_names.append(xmb_data[pos:pos+nl*2].decode('utf-16-le'))
        pos += nl * 2

    num_attr = struct.unpack_from('<I', xmb_data, pos)[0]; pos += 4
    attr_names: list[str] = []
    for _ in range(num_attr):
        nl = struct.unpack_from('<I', xmb_data, pos)[0]; pos += 4
        attr_names.append(xmb_data[pos:pos+nl*2].decode('utf-16-le'))
        pos += nl * 2

    # Verify XN marker
    assert xmb_data[pos:pos+2] == b'XN', f"Expected XN at {pos}"

    lines: list[str] = ['<?xml version="1.0" encoding="utf-8"?>']

    def escape(s: str) -> str:
        return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

    def read_xn(pos: int, depth: int = 0) -> int:
        assert xmb_data[pos:pos+2] == b'XN'
        pos += 6  # XN(2) + len(4)

        text_len = struct.unpack_from('<I', xmb_data, pos)[0]; pos += 4
        text = ""
        if text_len > 0:
            text = xmb_data[pos:pos+text_len*2].decode('utf-16-le', errors='replace')
            pos += text_len * 2

        elem_idx = struct.unpack_from('<I', xmb_data, pos)[0]; pos += 4
        pos += 4  # skip unknown field
        num_attrs = struct.unpack_from('<I', xmb_data, pos)[0]; pos += 4

        indent = '  ' * depth
        tag = f'{indent}<{element_names[elem_idx]}'

        for _ in range(num_attrs):
            ai = struct.unpack_from('<I', xmb_data, pos)[0]; pos += 4
            vl = struct.unpack_from('<I', xmb_data, pos)[0]; pos += 4
            val = ""
            if vl > 0:
                val = xmb_data[pos:pos+vl*2].decode('utf-16-le', errors='replace')
                pos += vl * 2
            tag += f' {attr_names[ai]}="{escape(val)}"'

        num_children = struct.unpack_from('<I', xmb_data, pos)[0]; pos += 4
        ename = element_names[elem_idx]

        if num_children == 0 and not text:
            lines.append(f'{tag}/>')
        elif num_children == 0:
            lines.append(f'{tag}>{escape(text)}</{ename}>')
        else:
            lines.append(f'{tag}>{escape(text) if text else ""}')
            for _ in range(num_children):
                pos = read_xn(pos, depth + 1)
            lines.append(f'{indent}</{ename}>')

        return pos

    read_xn(pos, 0)
    return '\n'.join(lines)


# ============================================================
# Main
# ============================================================

TARGETS = {
    'protoy.xml.XMB': 'protoy.xml',
    'techtreey.xml.XMB': 'techtreey.xml',
    'civs.xml.XMB': 'civs.xml',
    r'strings\English\stringtabley.xml.XMB': 'stringtabley_en.xml',
    r'strings\SimplifiedChinese\stringtabley.xml.XMB': 'stringtabley_zh.xml',
}


def main():
    parser = argparse.ArgumentParser(description="Extract game data from AoE3 DE Data.bar")
    parser.add_argument("--bar-path", default=DEFAULT_BAR, help="Path to Data.bar")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="Output directory")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    print(f"Reading BAR: {args.bar_path}")
    entries = read_bar_entries(args.bar_path)
    print(f"  {len(entries)} files in archive")

    for bar_name, out_name in TARGETS.items():
        entry = next((e for e in entries if e['name'] == bar_name), None)
        if not entry:
            print(f"  WARNING: '{bar_name}' not found!")
            continue

        print(f"\n  Extracting: {bar_name} ({entry['size_raw']/1024/1024:.1f} MB)...")
        xmb_data = extract_file_data(args.bar_path, entry)
        xml_text = decode_xmb_to_xml(xmb_data)

        out_path = os.path.join(args.output_dir, out_name)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(xml_text)
        print(f"    -> {out_path} ({os.path.getsize(out_path)/1024/1024:.1f} MB)")

    print("\nDone!")


if __name__ == '__main__':
    main()
