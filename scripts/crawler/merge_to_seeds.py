"""把清洗后的候选题合并进 seeds/turtle_soup.json。

用法：
    uv run python scripts/crawler/merge_to_seeds.py \\
        scripts/crawler/raw/preselected.cleaned.json \\
        <keep_indices.json>

    其中 keep_indices.json 是一个 JSON 数组，指定要保留的题目索引（0-based）。
    也可以传 "all" 保留全部。

合并规则：
- seeds/turtle_soup.json 是 JSON 数组
- 按 title 去重（如果和已有 title 冲突，跳过并警告）
- 输出格式和现有 seeds 保持一致
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent


def main(
    cleaned_path: Path,
    keep_indices_arg: str,
    seeds_path: Path,
    dry_run: bool,
) -> None:
    cleaned = json.loads(cleaned_path.read_text(encoding="utf-8"))
    existing = json.loads(seeds_path.read_text(encoding="utf-8"))

    # 解析 keep_indices
    if keep_indices_arg == "all":
        keep_items = list(cleaned)
    else:
        indices = json.loads(keep_indices_arg) if keep_indices_arg.startswith("[") \
            else json.loads(Path(keep_indices_arg).read_text(encoding="utf-8"))
        keep_items = [cleaned[i] for i in indices if 0 <= i < len(cleaned)]

    existing_titles = {item["title"] for item in existing if "title" in item}
    to_add: list[dict] = []
    skipped_dup: list[str] = []
    for item in keep_items:
        if item["title"] in existing_titles:
            skipped_dup.append(item["title"])
            continue
        to_add.append(item)

    print(f"[merge] 候选保留 {len(keep_items)} 题")
    print(f"[merge] 其中 {len(skipped_dup)} 题标题重复跳过：{skipped_dup}")
    print(f"[merge] 实际将追加 {len(to_add)} 题")

    if dry_run:
        print("[merge] --dry-run，不实际写盘")
        return

    merged = list(existing) + to_add
    seeds_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[merge] DONE. wrote {seeds_path} (total {len(merged)} items)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("cleaned", type=Path, help="清洗后的 JSON 路径")
    p.add_argument(
        "keep",
        help=(
            "要保留的索引：'all' / JSON 内联数组（如 [0,1,2]） / JSON 文件路径"
        ),
    )
    p.add_argument(
        "--seeds",
        type=Path,
        default=_ROOT / "seeds" / "turtle_soup.json",
        help="seeds 目标文件（默认 seeds/turtle_soup.json）",
    )
    p.add_argument("--dry-run", action="store_true", help="只预览不写盘")
    args = p.parse_args()
    main(args.cleaned, args.keep, args.seeds, args.dry_run)
