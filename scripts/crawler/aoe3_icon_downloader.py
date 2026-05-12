"""帝国时代3决定版 单位 icon 下载器。

从 Fandom Wiki 下载每个单位的 icon 图片到 resources/aoe3/icons/。
支持断点续跑（已下载的跳过）。

用法：
    uv run python scripts/crawler/aoe3_icon_downloader.py
    uv run python scripts/crawler/aoe3_icon_downloader.py --force   # 覆盖已有
    uv run python scripts/crawler/aoe3_icon_downloader.py --limit 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("[!] 需要安装 beautifulsoup4: pip install beautifulsoup4 lxml")
    sys.exit(1)

sys.stdout.reconfigure(encoding="utf-8")

_WIKI_BASE = "https://ageofempires.fandom.com"
_API_URL = f"{_WIKI_BASE}/api.php"
_ROOT = Path(__file__).resolve().parent.parent.parent
_UNITS_FILE = _ROOT / "seeds" / "aoe3" / "units.json"
_ICONS_DIR = _ROOT / "resources" / "aoe3" / "icons"
_TIMEOUT = 30.0
_DELAY = 1.0
_HEADERS = {
    "User-Agent": "QQBotForFun-AoE3Crawler/1.0 (hobby project; polite crawling)",
    "Accept": "image/png,image/*,*/*",
}


async def fetch_icon_url(client: httpx.AsyncClient, title: str) -> str | None:
    """从单位页面的 infobox 中提取 icon 图片 URL。"""
    await asyncio.sleep(_DELAY)
    params = {
        "action": "parse", "page": title,
        "format": "json", "prop": "text",
    }
    try:
        resp = await client.get(_API_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            return None
        html = data.get("parse", {}).get("text", {}).get("*", "")
    except Exception:
        return None

    soup = BeautifulSoup(html, "lxml")
    infobox = soup.find("aside", class_="portable-infobox")
    if not infobox:
        infobox = soup.find("div", class_="portable-infobox")
    if not infobox:
        return None

    # 找 pi-image-thumbnail（DE 版优先）
    img = infobox.find("img", class_="pi-image-thumbnail")
    if not img:
        img = infobox.find("img")
    if not img:
        return None

    src = img.get("src", "")
    if not src:
        return None

    # 优先用 data-image-key 中带 "aoe3de" 的版本
    # 从 tabber 里找 DE 版
    tabs = infobox.find_all("div", class_="wds-tab__content")
    if tabs:
        # 第一个 tab 通常是 DE 版
        first_tab = tabs[0]
        de_img = first_tab.find("img")
        if de_img and de_img.get("src"):
            src = de_img["src"]

    # 转为原图 URL（去掉 scale-to-width-down）
    # 但保留缩略图大小就行，268px 够用
    return src


async def download_icon(client: httpx.AsyncClient, url: str, dest: Path) -> bool:
    """下载图片到本地。"""
    try:
        await asyncio.sleep(0.5)  # 比页面请求短一些
        resp = await client.get(url)
        resp.raise_for_status()
        if len(resp.content) < 100:  # 太小，可能是错误页面
            return False
        dest.write_bytes(resp.content)
        return True
    except Exception:
        return False


async def main(limit: int | None = None, force: bool = False) -> None:
    print("=" * 60)
    print("帝国时代3决定版 · 单位 icon 下载器")
    print("=" * 60)

    units = json.loads(_UNITS_FILE.read_text(encoding="utf-8"))
    print(f"[i] 单位总数: {len(units)}")

    _ICONS_DIR.mkdir(parents=True, exist_ok=True)

    # 过滤需要下载的
    to_download = []
    for u in units:
        uid = u["id"]
        dest = _ICONS_DIR / f"{uid}.png"
        if dest.exists() and not force:
            continue
        to_download.append(u)

    if limit:
        to_download = to_download[:limit]

    already = len(units) - len(to_download)
    print(f"[i] 已有: {already}, 需下载: {len(to_download)}")

    if not to_download:
        print("[完成] 所有 icon 已存在")
        return

    downloaded = 0
    no_icon = 0
    failed = 0
    icon_urls_update: dict[str, str] = {}  # id -> url，用于回写 units.json

    t0 = time.perf_counter()

    async with httpx.AsyncClient(
        timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
    ) as client:
        for i, u in enumerate(to_download, 1):
            uid = u["id"]
            title = u["name_en"]
            dest = _ICONS_DIR / f"{uid}.png"

            print(f"  [{i}/{len(to_download)}] {title} ...")

            url = await fetch_icon_url(client, title)
            if not url:
                print(f"    [-] 无 icon")
                no_icon += 1
                continue

            icon_urls_update[uid] = url

            ok = await download_icon(client, url, dest)
            if ok:
                size_kb = dest.stat().st_size / 1024
                print(f"    OK {size_kb:.1f} KB")
                downloaded += 1
            else:
                print(f"    [x] 下载失败")
                failed += 1

    elapsed = time.perf_counter() - t0

    # 回写 icon_url 到 units.json
    if icon_urls_update:
        uid_map = {u["id"]: u for u in units}
        for uid, url in icon_urls_update.items():
            if uid in uid_map:
                uid_map[uid]["icon_url"] = url
        _UNITS_FILE.write_text(
            json.dumps(sorted(units, key=lambda u: u.get("name_en", "")),
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[i] 已回写 {len(icon_urls_update)} 条 icon_url 到 units.json")

    print(f"\n{'=' * 60}")
    print(f"[完成] 下载 {downloaded}, 无icon {no_icon}, 失败 {failed}")
    print(f"[耗时] {elapsed:.1f}s")
    print(f"[目录] {_ICONS_DIR}")

    # 统计总大小
    total_size = sum(f.stat().st_size for f in _ICONS_DIR.glob("*.png"))
    print(f"[总大小] {total_size / 1024 / 1024:.1f} MB ({len(list(_ICONS_DIR.glob('*.png')))} 个文件)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AoE3:DE 单位 icon 下载器")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(limit=args.limit, force=args.force))
