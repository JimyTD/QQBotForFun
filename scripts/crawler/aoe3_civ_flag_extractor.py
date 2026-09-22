"""AoE3 文明旗帜提取器 —— 从 UI/UIResources1.bar 提取文明旗帜到 resources/aoe3/civ_flags/。

背景
----
国战开屏（`src/plugins/games/aoe3_battle/opening_renderer.py`）按 `{civ_id}.png` 读取
`resources/aoe3/civ_flags/`；取不到就留空（不使用自绘近似旗或红蓝圆点冒充国旗）。
本脚本负责把**游戏原始旗帜**补齐。

权威源
------
  - data/aoe3/raw/civs.xml  每个 ``<civ>`` 块的 ``<homecityflagiconwpf>``，
                            例如 ``resources/images/icons/flags/Flag_Chinese.png``
  - UI/UIResources1.bar     上述资源的实体（RTS3 DDT 或 PNG）

产出
----
  resources/aoe3/civ_flags/{civ_id}.png
  ``civ_id`` 为 ``civs.xml`` 的 ``<name>``（与 ``seeds/aoe3/civs.json``、CivProfile.id 一致）。

用法::

    uv run python scripts/crawler/aoe3_civ_flag_extractor.py \
        --bar-path "F:\\...\\Game\\UI\\UIResources1.bar"

未设置 ``--bar-path`` 时读环境变量 ``AOE3_UI_BAR``。缺失的文明不生成文件（保持留空）。
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aoe3_bar_extractor import extract_file_data, read_bar_entries  # noqa: E402
from aoe3_icon_extractor import decode_ddt_to_png  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CIVS_XML = PROJECT_ROOT / "data" / "aoe3" / "raw" / "civs.xml"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "resources" / "aoe3" / "civ_flags"
DEFAULT_BAR = os.environ.get(
    "AOE3_UI_BAR",
    r"E:\SteamLibrary\steamapps\common\AoE3DE\Game\UI\UIResources1.bar",
)

# 渲染器最终只画 42×28，128 宽足够清晰且单张 <10 KB
FLAG_MAX_WIDTH = 128


def parse_civ_flag_paths(civs_xml: Path) -> dict[str, str]:
    """Parse ``civs.xml`` into ``{civ_id: resource_path}``."""
    text = civs_xml.read_text(encoding="utf-8")
    result: dict[str, str] = {}
    for block in re.findall(r"<civ>(.*?)</civ>", text, re.S):
        name = re.search(r"<name>([^<]+)</name>", block)
        flag = re.search(r"<homecityflagiconwpf>([^<]+)</homecityflagiconwpf>", block)
        if name and flag:
            result[name.group(1).strip()] = flag.group(1).strip()
    return result


def _decode(raw: bytes) -> Image.Image | None:
    """Decode a BAR payload that is either a real PNG or an RTS3 DDT texture."""
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return Image.open(io.BytesIO(raw))
    return decode_ddt_to_png(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract AoE3 civilization flags")
    parser.add_argument("--bar-path", default=DEFAULT_BAR, help="Path to UIResources1.bar")
    parser.add_argument("--civs-xml", default=str(DEFAULT_CIVS_XML))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    civ_flags = parse_civ_flag_paths(Path(args.civs_xml))
    print(f"civs.xml 带旗帜定义的文明: {len(civ_flags)}")
    if not civ_flags:
        raise SystemExit("ERROR: civs.xml 未解析到任何 homecityflagiconwpf")

    print(f"Reading BAR: {args.bar_path}")
    entries = read_bar_entries(args.bar_path)
    # BAR 内路径使用反斜杠，civs.xml 使用正斜杠 → 归一化后索引
    index = {e["name"].replace("\\", "/").lower(): e for e in entries}
    print(f"  {len(entries)} files in archive")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    missing: list[tuple[str, str]] = []
    for civ_id, res_path in sorted(civ_flags.items()):
        entry = index.get(res_path.replace("\\", "/").lower())
        if entry is None:
            missing.append((civ_id, res_path))
            continue
        try:
            img = _decode(extract_file_data(args.bar_path, entry))
        except Exception as ex:  # noqa: BLE001
            print(f"    WARNING: {civ_id} 解码失败: {ex}")
            img = None
        if img is None:
            missing.append((civ_id, res_path))
            continue

        img = img.convert("RGBA")
        if img.width > FLAG_MAX_WIDTH:
            ratio = FLAG_MAX_WIDTH / img.width
            img = img.resize(
                (FLAG_MAX_WIDTH, max(1, round(img.height * ratio))),
                Image.Resampling.LANCZOS,
            )
        img.save(out_dir / f"{civ_id}.png", format="PNG", optimize=True)
        written.append(civ_id)

    print(f"\n写入 {len(written)} 个旗帜 -> {out_dir}")
    if missing:
        print(f"缺失 {len(missing)} 个（保持留空，不生成近似旗）:")
        for civ_id, res_path in missing:
            print(f"    {civ_id:16s} {res_path}")


if __name__ == "__main__":
    main()
