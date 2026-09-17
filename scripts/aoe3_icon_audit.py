"""图标审计 —— 判断图标是否同一张 / 「更新」是真换图还是重新编码噪声。

两个子命令：

  compare A B
      比对两个图标（单位 id 或 PNG 路径）的像素差异。
      用途：复核 `data/aoe3/icon_overrides.json` 里的人工覆盖是否仍有必要
      （覆盖初衷往往是「BAR 解出的图不对」，若差异已很大说明图已修好，可解除覆盖）。

  diff --ref <git-rev>
      批量判定 `resources/aoe3/icons/` 里相对某 git 版本被修改过的 PNG，
      哪些是**真换图**、哪些只是重新编码的字节差异（像素一致）。
      用途：避免被「上百个图标都变了」误导 —— 实际可能只有个位数换了图。

用法::

    uv run python scripts/aoe3_icon_audit.py compare dedeli hussar
    uv run python scripts/aoe3_icon_audit.py compare dedeli resources/aoe3/icons/hussar.png
    uv run python scripts/aoe3_icon_audit.py diff --ref HEAD~1
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "resources" / "aoe3" / "icons"
SAMPLE = 32  # 采样分辨率：够判"是否同图"，且对压缩噪声不敏感


def _resolve(name: str) -> Path:
    p = Path(name)
    if p.exists():
        return p
    cand = ICONS / f"{name}.png"
    if cand.exists():
        return cand
    raise SystemExit(f"icon not found: {name}")


def _pixels(path: Path) -> list[int]:
    img = Image.open(path).convert("RGB").resize((SAMPLE, SAMPLE))
    return list(img.tobytes())


def _dist(a: list[int], b: list[int]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def cmd_compare(args: argparse.Namespace) -> None:
    pa, pb = _resolve(args.a), _resolve(args.b)
    sa, sb = _pixels(pa), _pixels(pb)
    d = _dist(sa, sb)
    print(f"{pa.name} vs {pb.name}: 平均像素差 {d:.2f}")
    if sa == sb:
        print("  => 像素完全一致（同一张图）")
    elif d < 2:
        print("  => 几乎一致（仅压缩/编码差异）")
    else:
        print("  => 不同图")


def cmd_diff(args: argparse.Namespace) -> None:
    out = subprocess.run(
        ["git", "--no-pager", "diff", "--name-status", args.ref, "--", "resources/aoe3/icons"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    ).stdout
    rows = [line.split("\t") for line in out.strip().splitlines() if line.strip()]
    modified = [r[1] for r in rows if r[0] == "M"]
    added = [r[1] for r in rows if r[0] == "A"]
    deleted = [r[1] for r in rows if r[0] == "D"]
    print(f"相对 {args.ref}：新增 {len(added)} / 更新 {len(modified)} / 删除 {len(deleted)}")

    real_change: list[tuple[str, float]] = []
    same = 0
    for rel in modified:
        try:
            blob = subprocess.run(
                ["git", "show", f"{args.ref}:{rel}"], cwd=ROOT, capture_output=True,
            ).stdout
            if not blob:
                continue
            a = Image.open(io.BytesIO(blob)).convert("RGB").resize((SAMPLE, SAMPLE))
            b = Image.open(ROOT / rel).convert("RGB").resize((SAMPLE, SAMPLE))
            if a.tobytes() == b.tobytes():
                same += 1
            else:
                real_change.append((Path(rel).stem, round(_dist(list(a.tobytes()), list(b.tobytes())), 2)))
        except Exception as ex:  # pragma: no cover
            print(f"  WARNING {rel}: {ex}")

    print(f"  像素一致（仅重编码）：{same}")
    print(f"  真换图：{len(real_change)}")
    for uid, d in sorted(real_change, key=lambda x: -x[1]):
        print(f"    {uid:34s} {d}")
    print()
    if added:
        print("新增 id（前 60）：", ", ".join(Path(p).stem for p in added[:60]))


def main() -> None:
    ap = argparse.ArgumentParser(description="AoE3 icon audit")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compare", help="比对两个图标")
    c.add_argument("a")
    c.add_argument("b")
    c.set_defaults(func=cmd_compare)

    d = sub.add_parser("diff", help="批量判定真换图 vs 重编码")
    d.add_argument("--ref", default="HEAD", help="基准 git 版本（默认 HEAD）")
    d.set_defaults(func=cmd_diff)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
