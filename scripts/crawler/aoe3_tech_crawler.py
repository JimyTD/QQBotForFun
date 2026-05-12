"""帝国时代3决定版 改良技术数据爬虫。

从 Fandom Wiki 抓取 AoE3:DE 的改良技术数据，
输出为 seeds/aoe3/technologies.json。

用法：
    uv run python scripts/crawler/aoe3_tech_crawler.py
    uv run python scripts/crawler/aoe3_tech_crawler.py --limit 10
    uv run python scripts/crawler/aoe3_tech_crawler.py --force
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
    from bs4 import BeautifulSoup, Tag
except ImportError:
    print("[!] 需要安装 beautifulsoup4: pip install beautifulsoup4 lxml")
    sys.exit(1)

sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
# 配置
# ============================================================

_WIKI_BASE = "https://ageofempires.fandom.com"
_API_URL = f"{_WIKI_BASE}/api.php"
_OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "seeds" / "aoe3"
_OUTPUT_FILE = _OUTPUT_DIR / "technologies.json"

# 技术分类
_CATEGORIES = [
    "Category:Infantry technologies",
    "Category:Cavalry technologies",
    "Category:Military technologies",
    "Category:Economic technologies",
    "Category:Alliance technologies",
    "Category:Native technologies",
    "Category:Capitol",
    "Category:Big Button",
    "Category:Consulate technologies",
    "Category:Missile/siege technologies",  # 也可能存在
]

# AoE3 页面标记
_AOE3_MARKERS = {
    "Age_of_Empires_III", "Age_of_Empires_III:_Definitive_Edition",
    "Commerce_Age", "Fortress_Age", "Industrial_Age", "Exploration_Age",
    "Knights_of_the_Mediterranean", "The_Asian_Dynasties",
    "The_WarChiefs", "The_African_Royals",
}

# 排除的概述页
_TITLE_EXCLUDES = {
    "Big Button", "Home City Card", "Arsenal",
    "Arsenal (Age of Empires III)", "Capitol",
}

_TIMEOUT = 30.0
_HEADERS = {
    "User-Agent": "QQBotForFun-AoE3Crawler/1.0 (hobby project; polite crawling)",
    "Accept": "text/html,application/json",
}
_DELAY = 1.0


# ============================================================
# 工具
# ============================================================

async def _get_json(client: httpx.AsyncClient, url: str, params: dict) -> dict:
    await asyncio.sleep(_DELAY)
    resp = await client.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


def _clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[\[([^|\]]*\|)?([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\{\{[^}]*\}\}", "", text)
    return text.strip()


# ============================================================
# 分类获取
# ============================================================

async def get_category_members(client: httpx.AsyncClient, category: str) -> list[str]:
    titles: list[str] = []
    params: dict[str, Any] = {
        "action": "query", "list": "categorymembers",
        "cmtitle": category, "cmlimit": "500", "cmtype": "page", "format": "json",
    }
    while True:
        data = await _get_json(client, _API_URL, params)
        for m in data.get("query", {}).get("categorymembers", []):
            title = m.get("title", "")
            if title and not title.startswith("Category:"):
                titles.append(title)
        cont = data.get("continue")
        if cont and "cmcontinue" in cont:
            params["cmcontinue"] = cont["cmcontinue"]
        else:
            break
    return titles


async def get_all_tech_titles(client: httpx.AsyncClient) -> list[str]:
    all_titles: set[str] = set()
    for cat in _CATEGORIES:
        print(f"  [分类] {cat} ...")
        titles = await get_category_members(client, cat)
        before = len(all_titles)
        all_titles.update(titles)
        print(f"    -> {len(titles)} 页面 (新增 {len(all_titles) - before})")
    filtered = sorted(t for t in all_titles if t not in _TITLE_EXCLUDES)
    print(f"\n[汇总] {len(filtered)} 个候选技术页面")
    return filtered


# ============================================================
# 页面解析
# ============================================================

async def fetch_page(client: httpx.AsyncClient, title: str) -> tuple[str, list[str]] | None:
    params = {
        "action": "parse", "page": title,
        "format": "json", "prop": "text|categories",
    }
    try:
        data = await _get_json(client, _API_URL, params)
        if "error" in data:
            return None
        html = data.get("parse", {}).get("text", {}).get("*", "")
        cats = [c["*"] for c in data.get("parse", {}).get("categories", [])]
        return html, cats
    except Exception as e:  # noqa: BLE001
        print(f"    [x] {title}: {e}")
        return None


def parse_tech_page(html: str, title: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "lxml")
    infobox = soup.find("aside", class_="portable-infobox")
    if not infobox:
        infobox = soup.find("div", class_="portable-infobox")
    if not infobox:
        return None

    tech: dict[str, Any] = {
        "id": re.sub(r"[^a-z0-9_]", "", title.lower().replace(" ", "_")),
        "name_en": title,
        "wiki_url": f"{_WIKI_BASE}/wiki/{title.replace(' ', '_')}",
    }

    if not isinstance(infobox, Tag):
        return None

    cost: dict[str, int] = {}

    items = infobox.find_all("div", class_="pi-item")
    for item in items:
        ds = (item.get("data-source") or "").strip()
        val_el = item.find("div", class_="pi-data-value")
        if not val_el:
            continue
        val_text = val_el.get_text(strip=True)

        if ds == "Civilization":
            links = val_el.find_all("a")
            if links:
                tech["civs"] = list(dict.fromkeys(a.get_text(strip=True) for a in links if a.get_text(strip=True)))
            else:
                civs_text = _clean_text(val_text)
                tech["civs"] = [c.strip() for c in re.split(r"[,，、]", civs_text) if c.strip()]

        elif ds == "Age":
            tech["age"] = _clean_text(val_text).split("(")[0].strip()

        elif ds == "Building":
            links = val_el.find_all("a")
            if links:
                tech["building"] = list(dict.fromkeys(a.get_text(strip=True) for a in links if a.get_text(strip=True)))

        elif ds == "Time":
            match = re.search(r"(\d+)", val_text)
            if match:
                tech["train_time"] = int(match.group(1))

        elif ds == "Food":
            match = re.search(r"(\d+)", val_text)
            if match:
                cost["food"] = int(match.group(1))

        elif ds == "Wood":
            match = re.search(r"(\d+)", val_text)
            if match:
                cost["wood"] = int(match.group(1))

        elif ds in ("Coin", "Gold"):
            match = re.search(r"(\d+)", val_text)
            if match:
                cost["gold"] = int(match.group(1))

        elif ds == "Influence":
            match = re.search(r"(\d+)", val_text)
            if match:
                cost["influence"] = int(match.group(1))

        elif ds == "Export":
            match = re.search(r"(\d+)", val_text)
            if match:
                cost["export"] = int(match.group(1))

        elif ds == "Stats":
            # 保存效果描述的纯文本（用换行分隔多条效果）
            tech["effect"] = val_el.get_text(separator="\n", strip=True)

    if cost:
        tech["cost"] = cost

    return tech


# ============================================================
# 主流程
# ============================================================

async def main(limit: int | None = None, force: bool = False) -> None:
    print("=" * 60)
    print("帝国时代3决定版 · 改良技术爬虫")
    print("=" * 60)

    existing: dict[str, dict] = {}
    if _OUTPUT_FILE.exists() and not force:
        try:
            data = json.loads(_OUTPUT_FILE.read_text(encoding="utf-8"))
            existing = {t["name_en"]: t for t in data}
            print(f"[i] 已有 {len(existing)} 条技术")
        except Exception:
            pass

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True) as client:
        print("\n[1/2] 获取技术列表...")
        all_titles = await get_all_tech_titles(client)

        if limit:
            all_titles = all_titles[:limit]
            print(f"[限制] 前 {limit} 个")

        print(f"\n[2/2] 抓取详情 ({len(all_titles)} 个)...")
        results: list[dict] = list(existing.values()) if not force else []
        new_count = 0
        skipped = 0

        t0 = time.perf_counter()
        for i, title in enumerate(all_titles, 1):
            if title in existing and not force:
                continue

            print(f"  [{i}/{len(all_titles)}] {title} ...")
            result = await fetch_page(client, title)
            if not result:
                continue

            html, cats = result
            if not (set(cats) & _AOE3_MARKERS):
                print(f"    [跳过] 非 AoE3")
                skipped += 1
                continue

            tech = parse_tech_page(html, title)
            if tech:
                results.append(tech)
                new_count += 1
                effect = (tech.get("effect") or "")[:60]
                print(f"    OK | {effect}")
            else:
                print(f"    [-] 无 infobox")

            if new_count > 0 and new_count % 20 == 0:
                _save(results)

        _save(results)
        elapsed = time.perf_counter() - t0

    print(f"\n{'=' * 60}")
    print(f"[完成] 新增 {new_count}，跳过 {skipped}，总计 {len(results)}")
    print(f"[耗时] {elapsed:.1f}s")
    print(f"[输出] {_OUTPUT_FILE}")


def _save(results: list[dict]) -> None:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sorted_r = sorted(results, key=lambda t: t.get("name_en", ""))
    _OUTPUT_FILE.write_text(json.dumps(sorted_r, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AoE3:DE 改良技术爬虫")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(limit=args.limit, force=args.force))
