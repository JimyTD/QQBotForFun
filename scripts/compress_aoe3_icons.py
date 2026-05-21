"""把 resources/aoe3/icons/*.png 规整为 128x128 + 体积 ≤ ~50KB 的小图。

背景：``feat(aoe3): 彻底重建数据层`` 之后引入的 icon 来自游戏原始素材，
体积分布严重偏态——平均 108KB，最大 1MB+，部分文件甚至损坏。这些
大图被用作 aoe3 阵容广播的兵种 icon 时，3v3 一条消息累计可达 3MB+，
触发 NapCat ``rich media transfer failed`` (retcode=1200)。

策略：
  1. 扫描所有 png，>50KB 或非 128×128 的统一缩放到 128×128 + PNG optimize
  2. 损坏文件单独报告（不删除，需人工处理）
  3. 原地覆盖（git 可回滚），同时打印 before/after 体积对比

用法：
  uv run python scripts/compress_aoe3_icons.py            # 实际执行
  uv run python scripts/compress_aoe3_icons.py --dry-run  # 仅报告，不写入
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, UnidentifiedImageError

ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = ROOT / "resources" / "aoe3" / "icons"

TARGET_SIZE = (128, 128)
SIZE_THRESHOLD_KB = 50  # 已经 ≤ 这个值且尺寸正确就跳过


def process(path: Path, *, dry_run: bool) -> tuple[str, int, int]:
    """返回 (status, before_kb, after_kb)。

    status: ok | skip | broken | error
    """
    before = path.stat().st_size
    before_kb = before // 1024

    try:
        with Image.open(path) as img:
            img.load()  # 强制读出来才能发现损坏
            w, h = img.size
            mode = img.mode

            # 已经合规就跳过
            if (w, h) == TARGET_SIZE and before_kb <= SIZE_THRESHOLD_KB:
                return ("skip", before_kb, before_kb)

            if dry_run:
                return ("ok", before_kb, -1)

            # 统一处理：RGBA -> RGBA（保留透明），其他 -> RGBA
            if mode != "RGBA":
                img = img.convert("RGBA")
            img.thumbnail(TARGET_SIZE, Image.Resampling.LANCZOS)
            # 居中 padding 到 128×128（thumbnail 不会放大也不会强制 1:1）
            if img.size != TARGET_SIZE:
                canvas = Image.new("RGBA", TARGET_SIZE, (0, 0, 0, 0))
                canvas.paste(img, ((TARGET_SIZE[0] - img.width) // 2,
                                   (TARGET_SIZE[1] - img.height) // 2))
                img = canvas
            img.save(path, "PNG", optimize=True)
    except UnidentifiedImageError:
        return ("broken", before_kb, before_kb)
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR {path.name}: {e}", file=sys.stderr)
        return ("error", before_kb, before_kb)

    after_kb = path.stat().st_size // 1024
    return ("ok", before_kb, after_kb)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只报告不写入")
    args = ap.parse_args()

    if not ICONS_DIR.exists():
        print(f"no such dir: {ICONS_DIR}", file=sys.stderr)
        return 1

    pngs = sorted(ICONS_DIR.glob("*.png"))
    print(f"== scanning {len(pngs)} png under {ICONS_DIR.relative_to(ROOT)} ==")
    if args.dry_run:
        print("== DRY RUN: 不会修改任何文件 ==")

    counts = {"ok": 0, "skip": 0, "broken": 0, "error": 0}
    total_before = 0
    total_after = 0
    broken_files: list[str] = []
    big_savings: list[tuple[str, int, int]] = []

    for i, png in enumerate(pngs, 1):
        status, before_kb, after_kb = process(png, dry_run=args.dry_run)
        counts[status] += 1
        total_before += before_kb
        if after_kb >= 0:
            total_after += after_kb
        else:
            total_after += before_kb

        if status == "broken":
            broken_files.append(png.name)
        elif status == "ok" and not args.dry_run and before_kb - after_kb >= 100:
            big_savings.append((png.name, before_kb, after_kb))

        if i % 200 == 0:
            print(f"  ... processed {i}/{len(pngs)}")

    print()
    print(f"== done ==")
    print(f"  processed : {counts['ok']}")
    print(f"  skipped   : {counts['skip']}  (already ≤{SIZE_THRESHOLD_KB}KB & 128×128)")
    print(f"  broken    : {counts['broken']}")
    print(f"  error     : {counts['error']}")
    print(f"  size: {total_before/1024:.1f} MB -> {total_after/1024:.1f} MB "
          f"({(1 - total_after/total_before)*100:.1f}% saved)")

    if broken_files:
        print(f"\n*** broken files ({len(broken_files)}, 需人工处理）:", file=sys.stderr)
        for name in broken_files:
            print(f"  - {name}", file=sys.stderr)

    if big_savings:
        print(f"\n== top 10 biggest reductions ==")
        big_savings.sort(key=lambda x: x[1] - x[2], reverse=True)
        for name, b, a in big_savings[:10]:
            print(f"  {name:40s} {b:5d} KB -> {a:4d} KB")

    return 0 if counts["error"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
