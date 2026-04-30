"""把 resources/foods/_raw/*.png 按 id 压缩 + 重命名为 resources/foods/<id>.jpg。

匹配逻辑（v2）：
  对每道菜，从 image_prompt 中提取一个"足够独特"的特征片段（30-60 字），
  在生成的文件 stem 里找这个片段。哪个菜的特征出现在 stem 里就认为是那张图。

压缩：512x512 + JPEG q=82。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "resources" / "foods" / "_raw"
OUT_DIR = ROOT / "resources" / "foods"
SEEDS = ROOT / "seeds" / "foods.json"


def normalize(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]+", "_", s)


def main() -> int:
    data = json.loads(SEEDS.read_text(encoding="utf-8"))
    raw_pngs = sorted(RAW_DIR.glob("*.png"))
    if not raw_pngs:
        print(f"no PNG under {RAW_DIR}", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 对每个 png 独立匹配：找"归一化后 prompt 最长前缀匹配 stem 开头"的菜
    # image_gen 保存的文件名是 prompt 的前 N 个字符 + 时间戳，N 大概是 25-35 字
    # 所以对每个 stem，尝试所有菜的 prompt，找"prefix 匹配最长"的一个

    prompts_normalized = [(item["id"], normalize(item["image_prompt"])) for item in data]

    ok = 0
    unmatched: list[str] = []
    total_kb = 0
    seen_ids: set[str] = set()

    for png in raw_pngs:
        stem_norm = normalize(png.stem)
        # 找 prompt 归一化后，作为 stem_norm 开头子串的最长那个
        best: tuple[int, str] = (0, "")  # (match_length, id)
        for fid, pnorm in prompts_normalized:
            # 这道菜的 prompt 是不是 stem 开头的前缀？
            # 比较从 stem 起点开始，两个字符串有多长公共前缀
            common = 0
            for a, b in zip(stem_norm, pnorm):
                if a != b:
                    break
                common += 1
            if common > best[0]:
                best = (common, fid)

        if best[0] < 10:  # 至少要公共前缀 10 字才算匹配
            unmatched.append(f"{png.name} (best prefix={best[0]}, candidate={best[1]})")
            continue

        matched_id = best[1]
        if matched_id in seen_ids:
            unmatched.append(f"{png.name} (id={matched_id} 已被占用，可能两张图撞车)")
            continue
        seen_ids.add(matched_id)

        out_path = OUT_DIR / f"{matched_id}.jpg"
        with Image.open(png) as img:
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.thumbnail((512, 512), Image.Resampling.LANCZOS)
            img.save(out_path, "JPEG", quality=82, optimize=True)
        size_kb = out_path.stat().st_size // 1024
        total_kb += size_kb
        print(f"  OK {matched_id}.jpg ({size_kb} KB, prefix={best[0]})")
        ok += 1

    print(f"\n== done: {ok}/{len(raw_pngs)} processed, total {total_kb} KB ==")
    print(f"== unique ids matched: {len(seen_ids)}/{len(data)} ==")
    if unmatched:
        print(f"\n*** unmatched ({len(unmatched)}):", file=sys.stderr)
        for line in unmatched:
            print(f"  - {line}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
