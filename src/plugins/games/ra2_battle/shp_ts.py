"""Westwood SHP (TS) 解码 —— 对齐 OpenRA ShpTSLoader（仅 icon 单帧）。"""

from __future__ import annotations

import struct
from dataclasses import dataclass


def _decode_rle_zeros(src: bytes) -> bytearray:
    out = bytearray()
    i = 0
    n = len(src)
    while i < n:
        cmd = src[i]
        i += 1
        if cmd == 0:
            if i >= n:
                break
            count = src[i]
            i += 1
            out.extend(b"\x00" * count)
        else:
            out.append(cmd)
    return out


@dataclass
class ShpFrame:
    width: int
    height: int
    pixels: bytearray  # indexed8, row-major


def decode_shp_ts_first_frame(data: bytes) -> ShpFrame:
    """解码 SHP-TS 第一帧有效图像（cameo icon 用）。"""
    if len(data) < 8:
        raise ValueError("SHP 数据过短")
    if struct.unpack_from("<H", data, 0)[0] != 0:
        raise ValueError("非 SHP-TS 格式")

    frame_w = struct.unpack_from("<H", data, 2)[0]
    frame_h = struct.unpack_from("<H", data, 4)[0]
    frame_count = struct.unpack_from("<H", data, 6)[0]
    if frame_count < 1:
        raise ValueError("SHP 无帧")

    pos = 8
    for _ in range(frame_count):
        if pos + 24 > len(data):
            break
        x, y, w, h = struct.unpack_from("<HHHH", data, pos)
        fmt = data[pos + 8]
        file_offset = struct.unpack_from("<I", data, pos + 20)[0]
        pos += 24

        if w == 0 or h == 0:
            continue
        if file_offset == 0:
            continue

        data_w = w + (w % 2)
        data_h = h + (h % 2)
        pixels = bytearray(data_w * data_h)

        start = file_offset
        if fmt == 3:
            for row in range(h):
                if start + 2 > len(data):
                    break
                row_len = struct.unpack_from("<H", data, start)[0] - 2
                start += 2
                chunk = data[start : start + row_len]
                start += row_len
                decoded = _decode_rle_zeros(chunk)
                row_start = data_w * row
                pixels[row_start : row_start + min(len(decoded), data_w)] = decoded[
                    :data_w
                ]
        else:
            row_len = struct.unpack_from("<H", data, start)[0] - 2 if fmt == 2 else w
            if fmt == 2:
                start += 2
            for row in range(h):
                chunk = data[start : start + (row_len if fmt == 2 else w)]
                start += len(chunk)
                row_start = data_w * row
                pixels[row_start : row_start + min(len(chunk), data_w)] = chunk[:data_w]

        return ShpFrame(width=data_w, height=data_h, pixels=pixels)

    raise ValueError("SHP 中无有效帧")


def load_jasc_pal(data: bytes) -> list[tuple[int, int, int]]:
    """768 字节 JASC RGB 调色板 → 256 色。"""
    if len(data) < 768:
        raise ValueError("调色板过短")
    colors: list[tuple[int, int, int]] = [(0, 0, 0)]
    for i in range(1, 256):
        o = (i - 1) * 3
        colors.append((data[o], data[o + 1], data[o + 2]))
    return colors


def frame_to_rgba(frame: ShpFrame, palette: list[tuple[int, int, int]]) -> bytes:
    """索引色 → RGBA（0 为透明）。"""
    out = bytearray(frame.width * frame.height * 4)
    for i, idx in enumerate(frame.pixels):
        o = i * 4
        if idx == 0:
            out[o : o + 4] = b"\x00\x00\x00\x00"
        else:
            r, g, b = palette[idx] if idx < len(palette) else (255, 0, 255)
            out[o : o + 4] = bytes((r, g, b, 255))
    return bytes(out)
