"""从 aoe3explorer.com 补充 AOE 半径 + 伤害类型数据。

SvelteKit 页面通过 URL ?unit=xxx 加载选中兵种的 attacks 详情，
其中包含 area (AOE半径)、damageType (伤害类型) 等关键字段。

用法：
    uv run python scripts/crawler/aoe3_aoe_supplement.py
    uv run python scripts/crawler/aoe3_aoe_supplement.py --limit 5
    uv run python scripts/crawler/aoe3_aoe_supplement.py --force   # 覆盖已有补充数据
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

_SEEDS = Path(__file__).resolve().parent.parent.parent / "seeds" / "aoe3"
_UNITS_FILE = _SEEDS / "units.json"
_AOE_FILE = _SEEDS / "units_aoe_supplement.json"
_EXPLORER_BASE = "https://www.aoe3explorer.com/wiki/units"

_HEADERS = {
    "User-Agent": "QQBotForFun-AoE3Crawler/2.0 (hobby project; polite crawling)",
    "Accept": "text/html",
}
_DELAY = 1.2  # 礼貌间隔


def _unit_slug(name_en: str) -> str:
    """英文名 → URL slug。"""
    slug = re.sub(r"\s*\([^)]*\)", "", name_en).strip()
    slug = slug.lower().replace("'", "").replace("\u2019", "")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug


def _extract_attacks(html: str) -> list[dict] | None:
    """从 SvelteKit 页面中提取 attacks 数组。"""
    # 匹配 attacks:[{...},...,{...}] 结构
    match = re.search(r'attacks:\[(.*?)\](?:,\w)', html, re.DOTALL)
    if not match:
        return None

    raw = match.group(1)
    # 转换 JS 对象为 JSON：给 key 加引号，处理 null
    # JS 格式: {id:"xxx",damage:100,minRange:null,area:3}
    # 需要变成: {"id":"xxx","damage":100,"minRange":null,"area":3}
    json_str = "[" + raw + "]"
    # 给无引号的 key 加引号
    json_str = re.sub(r'(\{|,)\s*([a-zA-Z_]\w*)\s*:', r'\1"\2":', json_str)
    # 处理 .5 → 0.5 这类数值
    json_str = re.sub(r'(?<=[:,\[])\.(\d)', r'0.\1', json_str)

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        # 截断到最后一个完整的 } 重试
        last_brace = json_str.rfind("}")
        if last_brace > 0:
            try:
                return json.loads(json_str[:last_brace + 1] + "]")
            except json.JSONDecodeError:
                pass
        return None


def _pick_main_attack(attacks: list[dict]) -> dict:
    """从多种攻击模式中选择主攻击（伤害最高的非建筑攻击）。"""
    best = None
    best_dmg = 0
    for atk in attacks:
        name = atk.get("name", "").lower()
        # 跳过砍伐/建筑/特殊模式
        if any(kw in name for kw in ["chop", "build", "gather", "siege attack"]):
            # siege attack 是打建筑的，但如果只有这一个攻击就保留
            if "siege" in name and len(attacks) > 1:
                continue
        dmg = atk.get("damage", 0)
        if dmg > best_dmg:
            best_dmg = dmg
            best = atk
    return best or attacks[0]


async def fetch_unit_attacks(
    client: httpx.AsyncClient, slug: str
) -> list[dict] | None:
    """获取一个兵种的 attacks 数据。"""
    url = f"{_EXPLORER_BASE}?unit={slug}"
    try:
        await asyncio.sleep(_DELAY)
        resp = await client.get(url, follow_redirects=True)
        if resp.status_code != 200:
            return None
        return _extract_attacks(resp.text)
    except Exception:
        return None


def _get_explorer_slugs(html: str) -> dict[str, str]:
    """从页面中提取所有兵种的 slug → name 映射。"""
    slugs = {}
    for m in re.finditer(r'slug:"([^"]+)",name:"([^"]+)"', html):
        slugs[m.group(1)] = m.group(2)
    return slugs


async def main(limit: int | None = None, force: bool = False) -> None:
    print("=" * 60)
    print("AoE3 AOE 半径 + 伤害类型补充爬虫")
    print("=" * 60)

    units = json.loads(_UNITS_FILE.read_text(encoding="utf-8"))
    print(f"已加载 {len(units)} 个兵种")

    # 加载已有补充数据
    existing: dict[str, dict] = {}
    if _AOE_FILE.exists() and not force:
        try:
            existing = {d["unit_id"]: d for d in json.loads(_AOE_FILE.read_text(encoding="utf-8"))}
            print(f"已有补充数据: {len(existing)} 个")
        except Exception:
            pass

    async with httpx.AsyncClient(timeout=30, headers=_HEADERS, follow_redirects=True) as client:
        # 先获取页面拿到所有 explorer 上的兵种 slug
        print("\n[1] 获取兵种 slug 列表...")
        resp = await client.get(f"{_EXPLORER_BASE}?unit=falconet")
        all_slugs = _get_explorer_slugs(resp.text)
        print(f"    explorer 上共 {len(all_slugs)} 个兵种")

        # 为我们的每个兵种找到对应的 slug
        slug_map: list[tuple[str, str, str]] = []  # (unit_id, slug, name_en)
        for u in units:
            uid = u["id"]
            name_en = u["name_en"]
            slug = _unit_slug(name_en)
            # 验证 slug 存在
            if slug in all_slugs:
                slug_map.append((uid, slug, name_en))
            else:
                # 尝试不同的 slug 变体
                alt_slug = slug.replace("-age-of-empires-iii", "")
                if alt_slug in all_slugs:
                    slug_map.append((uid, alt_slug, name_en))

        print(f"    匹配到 {len(slug_map)} / {len(units)} 个兵种")
        unmatched = len(units) - len(slug_map)
        if unmatched:
            print(f"    未匹配: {unmatched} 个")

        # 过滤掉已有数据的
        if not force:
            slug_map = [(uid, slug, name) for uid, slug, name in slug_map
                        if uid not in existing]
            print(f"    需要爬取: {len(slug_map)} 个")

        if limit:
            slug_map = slug_map[:limit]
            print(f"    限制为前 {limit} 个")

        # 逐个爬取
        print(f"\n[2] 开始爬取攻击数据...")
        results: list[dict] = list(existing.values())
        new_count = 0
        fail_count = 0

        t0 = time.perf_counter()
        for i, (uid, slug, name_en) in enumerate(slug_map, 1):
            print(f"  [{i}/{len(slug_map)}] {name_en} ({slug}) ...", end=" ")
            attacks = await fetch_unit_attacks(client, slug)
            if not attacks:
                print("FAIL")
                fail_count += 1
                continue

            # 选主攻击
            main_atk = _pick_main_attack(attacks)

            entry = {
                "unit_id": uid,
                "slug": slug,
                "attacks": [{
                    "name": a.get("name", ""),
                    "damage": a.get("damage", 0),
                    "damage_type": a.get("damageType", ""),
                    "min_range": a.get("minRange"),
                    "max_range": a.get("maxRange", 0),
                    "rof": a.get("rateOfFire", 0),
                    "aoe_radius": a.get("area", 0),
                    "bonuses": a.get("bonuses", []),
                } for a in attacks],
                "main_attack_aoe": main_atk.get("area", 0),
                "main_attack_damage_type": main_atk.get("damageType", ""),
            }
            results.append(entry)
            new_count += 1

            aoe = main_atk.get("area", 0)
            dtype = main_atk.get("damageType", "?")
            print(f"OK | AOE={aoe} type={dtype} ({len(attacks)} attacks)")

            # 增量保存
            if new_count % 20 == 0:
                _save(results)
                print(f"    [保存] {len(results)} 条")

        elapsed = time.perf_counter() - t0

    _save(results)
    print(f"\n{'='*60}")
    print(f"完成! 新增 {new_count}, 失败 {fail_count}")
    print(f"总计 {len(results)} 条, 耗时 {elapsed:.0f}s")
    print(f"输出: {_AOE_FILE}")


def _save(results: list[dict]) -> None:
    _SEEDS.mkdir(parents=True, exist_ok=True)
    sorted_results = sorted(results, key=lambda r: r.get("unit_id", ""))
    _AOE_FILE.write_text(
        json.dumps(sorted_results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AoE3 AOE 半径补充爬虫")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.force))
