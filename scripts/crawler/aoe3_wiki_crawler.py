"""帝国时代3决定版 兵种数据爬虫。

从 Fandom Wiki (ageofempires.fandom.com) 抓取 AoE3:DE 的军事单位数据，
输出为 seeds/aoe3/units.json。

用法：
    uv run python scripts/crawler/aoe3_wiki_crawler.py
    uv run python scripts/crawler/aoe3_wiki_crawler.py --limit 10   # 只抓前10个（调试用）
    uv run python scripts/crawler/aoe3_wiki_crawler.py --force       # 覆盖已有数据

数据源：
    https://ageofempires.fandom.com/

依赖：httpx, beautifulsoup4（需要额外安装 bs4）
    pip install beautifulsoup4 lxml
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

sys.stdout.reconfigure(encoding="utf-8")

try:
    from bs4 import BeautifulSoup, Tag
except ImportError:
    print("[!] 需要安装 beautifulsoup4: pip install beautifulsoup4 lxml")
    sys.exit(1)

# ============================================================
# 配置
# ============================================================

_WIKI_BASE = "https://ageofempires.fandom.com"
_API_URL = f"{_WIKI_BASE}/api.php"
_OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "seeds" / "aoe3"
_OUTPUT_FILE = _OUTPUT_DIR / "units.json"

# 要爬取的分类（覆盖所有 AoE3 军事单位的正确分类名）
# 分为三类：兵种类型、文明特有、特殊分类
_CATEGORIES = [
    # --- 兵种类型分类（跨系列共用，需要后续用 categories 过滤 AoE3） ---
    "Category:Gunpowder infantry",
    "Category:Melee infantry",
    "Category:Ranged infantry",
    "Category:Melee cavalry",
    "Category:Ranged cavalry",
    "Category:Gunpowder cavalry",
    "Category:Siege units",
    "Category:Artillery",
    # --- 文明特有兵种分类 ---
    "Category:Aztec units (Age of Empires III)",
    "Category:Chinese units (Age of Empires III)",
    "Category:Japanese units (Age of Empires III)",
    "Category:Indian units",
    "Category:Haudenosaunee units",
    "Category:Lakota units",
    "Category:Inca units",
    "Category:Italian units (Age of Empires III)",
    "Category:Mexican units",
    "Category:Ottoman units (Age of Empires III)",
    "Category:Unique units (Age of Empires III)",
    # --- 特殊分类 ---
    "Category:Mercenaries (Age of Empires III)",
    "Category:Ships in Age of Empires III",
    "Category:Outlaws",
    "Category:Native American warriors",
    "Category:Native African warriors",
    "Category:Native Asian warriors",
    "Category:Native European warriors",
    "Category:Revolutionaries",
]

# 页面必须属于以下至少一个分类才被视为 AoE3 内容
_AOE3_CATEGORY_MARKERS = {
    "Age_of_Empires_III",
    "Age_of_Empires_III:_Definitive_Edition",
    "Commerce_Age",
    "Fortress_Age",
    "Industrial_Age",
    "Exploration_Age",
    "Knights_of_the_Mediterranean",
    "The_Asian_Dynasties",
    "The_WarChiefs",
    "The_African_Royals",
    "Mexican_DLC",
    "USA_DLC",
}

# 排除这些页面（概述页 / 非单位页 / 其他系列）
_TITLE_EXCLUDES = {
    "Infantry",
    "Cavalry",
    "Artillery",
    "Ship",
    "Mercenary",
    "Outlaw",
    "Native warrior",
    "Pet",
    "Heavy infantry",
    "Light infantry",
    "Light cavalry",
    "Heavy cavalry",
    "Ranged infantry",
    "Melee infantry",
    "Gunpowder infantry",
    "Siege units",
    "Hand infantry",
    "Shock infantry",
    "Infantry (Age of Empires III)",
    "Heavy infantry (Age of Empires III)",
    "Heavy cavalry (Age of Empires III)",
    "Artillery (Age of Empires III)",
    "Ship (Age of Empires III)",
    "Mercenary (Age of Empires III)",
    "Outlaw (Age of Empires III)",
    "Native warrior",
}

# 请求配置
_TIMEOUT = 30.0
_HEADERS = {
    "User-Agent": "QQBotForFun-AoE3Crawler/1.0 (hobby project; polite crawling)",
    "Accept": "text/html,application/json",
}
_DELAY_BETWEEN_REQUESTS = 1.0  # 礼貌爬取

# 中文名映射
_ZH_NAME_MAP: dict[str, str] = {
    # 通用兵种
    "Musketeer": "火枪手",
    "Pikeman": "长枪兵",
    "Crossbowman": "弩手",
    "Skirmisher": "散兵",
    "Hussar": "轻骑兵",
    "Dragoon": "龙骑兵",
    "Cuirassier": "胸甲骑兵",
    "Lancer": "枪骑兵",
    "Falconet": "鹰炮",
    "Culverin": "长管炮",
    "Mortar": "臼炮",
    "Grenadier": "掷弹兵",
    "Halberdier": "戟兵",
    "Cavalry Archer": "骑射手",
    "War Wagon": "战车",
    "Minuteman": "民兵",
    # 英国
    "Longbowman": "长弓手",
    "Rocket": "火箭炮",
    "Ranger": "游骑兵",
    # 俄罗斯
    "Oprichnik": "沙皇骑兵",
    "Strelet": "射击军",
    # 奥斯曼
    "Janissary": "土耳其近卫军",
    "Abus Gunner": "掷弹炮手",
    "Spahi": "西帕希骑兵",
    "Great Bombard": "巨型射石炮",
    "Nizam Fusilier": "新军火枪手",
    # 西班牙
    "Rodelero": "盾剑手",
    "Conquistador": "征服者",
    # 葡萄牙
    "Cassador": "猎兵",
    "Organ Gun": "管风琴炮",
    # 德国
    "Doppelsoldner": "双手剑士",
    "Uhlan": "乌兰骑兵",
    # 法国
    "Cuirassier": "胸甲骑兵",
    # 荷兰
    "Ruyter": "骑枪手",
    # 瑞典
    "Carolean": "卡尔近卫军",
    "Hakkapelit": "哈卡佩利骑兵",
    "Leather Cannon": "皮炮",
    # 马耳他
    "Hospitaller": "医院骑士",
    "Sentinel": "哨兵",
    "Fire Thrower": "火焰投掷者",
    "Grand Master": "大团长",
    # 美国
    "State Militia": "州民兵",
    "Regular": "正规军",
    "Sharpshooter": "神射手",
    "Carbine Cavalry": "卡宾骑兵",
    "Gatling Gun": "加特林机枪",
    # 印第安-易洛魁
    "Tomahawk": "战斧兵",
    "Aenna": "弓箭手",
    "Kanya Horseman": "坎亚骑兵",
    "Mantlet": "木盾",
    "Light Cannon": "轻型炮",
    "Forest Prowler": "森林潜行者",
    # 印第安-拉科塔
    "Cetan Bow": "鹰弓手",
    "Wakina Rifle": "步枪手",
    "Axe Rider": "斧骑兵",
    "Bow Rider": "弓骑兵",
    "Rifle Rider": "枪骑兵",
    "Tashunke Prowler": "塔尚克潜行者",
    "Tokala Soldier": "托卡拉战士",
    # 印第安-阿兹特克
    "Coyote Runner": "郊狼奔袭兵",
    "Puma Spearman": "美洲豹长枪兵",
    "Arrow Knight": "箭骑士",
    "Eagle Runner Knight": "鹰奔袭骑士",
    "Jaguar Prowl Knight": "美洲豹潜行骑士",
    "Skull Knight": "骷髅骑士",
    "Otontin Slinger": "投石兵",
    # 印第安-印加
    "Jungle Bowman": "丛林弓手",
    "Chimu Runner": "奇穆奔袭兵",
    "Bolas Warrior": "流星锤战士",
    "Huaraca": "投石索兵",
    "Chincha Raft": "钦查木筏",
    # 日本
    "Samurai": "武士",
    "Ashigaru Musketeer": "足轻火枪手",
    "Yumi Archer": "弓箭手",
    "Naginata Rider": "薙刀骑兵",
    "Yabusame": "流镝马",
    "Flaming Arrow": "火箭",
    "Morutaru": "日本臼炮",
    # 中国
    "Chu Ko Nu": "诸葛弩手",
    "Qiang Pikeman": "枪兵",
    "Changdao Swordsman": "长刀兵",
    "Steppe Rider": "草原骑兵",
    "Keshik": "怯薛",
    "Iron Flail": "铁连枷骑兵",
    "Meteor Hammer": "流星锤骑兵",
    "Hand Mortar": "手持臼炮",
    "Flying Crow": "神火飞鸦",
    "Flamethrower": "喷火兵",
    # 印度
    "Sepoy": "印度火枪兵",
    "Gurkha": "廓尔喀兵",
    "Rajput": "拉杰普特兵",
    "Sowar": "印度骑兵",
    "Zamburak": "骆驼骑兵",
    "Mahout Lancer": "象兵",
    "Howdah": "象轿兵",
    "Siege Elephant": "攻城象",
    "Flail Elephant": "连枷象",
    "Urumi Swordsman": "软剑兵",
    # 非洲-埃塞俄比亚
    "Gascenya": "加斯塞尼亚弓手",
    "Shotel Warrior": "肖特尔战士",
    "Neftenya": "火枪手",
    "Oromo Warrior": "奥罗莫战士",
    "Sebastopol Mortar": "塞瓦斯托波尔臼炮",
    # 非洲-豪萨
    "Javelin Rider": "标枪骑兵",
    "Lifidi Knight": "利菲迪骑士",
    "Raider": "突袭者",
    "Maigadi": "迈加迪",
    # 墨西哥
    "Soldado": "士兵",
    "Chinaco": "奇纳科骑兵",
    "Insurgente": "起义者",
    "Salteador": "劫匪",
    # 意大利
    "Bersagliere": "狙击兵",
    "Pavisier": "盾牌兵",
    "Papal Lancer": "教皇枪骑兵",
    "Schiavone": "斯基亚沃内剑士",
    "Elmetto": "钢盔骑兵",
    # 海军
    "Caravel": "轻帆船",
    "Galleon": "大帆船",
    "Frigate": "护卫舰",
    "Monitor": "铁甲舰",
    "Canoe": "独木舟",
    "War Canoe": "战争独木舟",
    "Battle Canoe": "战斗独木舟",
    "Tlaloc Canoe": "特拉洛克独木舟",
    "Fune": "关船",
    "Atakebune": "安宅船",
    "Tekkousen": "铁甲船",
    "War Junk": "战船",
    "Fuchuan": "福船",
    "Fire Junk": "火船",
    "Battleship": "战列舰",
    # 雇佣兵
    "Ronin": "浪人",
    "Black Rider": "黑骑士",
    "Mameluke": "马穆鲁克",
    "Elmeti": "重装骑兵",
    "Landsknecht": "德意志雇佣兵",
    "Swiss Pikeman": "瑞士长枪兵",
    "Highlander": "苏格兰高地兵",
    "Jaeger": "猎兵",
    "Fusilier": "燧发枪兵",
    "Manchu": "满洲骑射手",
    "Iron Troop": "铁人军",
    "Ninja": "忍者",
    "Kanuri Guard": "卡努里卫士",
    "Zenata Rider": "泽纳塔骑兵",
    "Yojimbo": "用心棒",
    "Li'l Bombard": "小型射石炮",
    "Giant Grenadier": "巨型掷弹兵",
    "Harquebusier": "火绳枪骑兵",
    "Mounted Rifleman": "骑马步枪兵",
    "Gatling Camel": "加特林骆驼",
    # 亡命徒
    "Comanchero": "科曼切罗",
    "Pistolero": "手枪手",
    "Renegado": "叛徒",
    "Cowboy": "牛仔",
    "Gunslinger": "神枪手",
    "Bandido": "土匪",
    "Desperado": "亡命之徒",
    "Highwayman": "拦路强盗",
    "Crabat": "克拉巴特",
}


# ============================================================
# 工具函数
# ============================================================


async def _get_json(client: httpx.AsyncClient, url: str, params: dict) -> dict:
    """带延迟的 GET 请求，返回 JSON。"""
    await asyncio.sleep(_DELAY_BETWEEN_REQUESTS)
    resp = await client.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


# ============================================================
# 第一步：获取所有单位页面列表
# ============================================================


async def get_category_members(client: httpx.AsyncClient, category: str) -> list[str]:
    """从分类页获取所有成员页面标题（带分页）。"""
    titles: list[str] = []
    params: dict[str, Any] = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": category,
        "cmlimit": "500",
        "cmtype": "page",
        "format": "json",
    }

    while True:
        data = await _get_json(client, _API_URL, params)
        members = data.get("query", {}).get("categorymembers", [])
        for m in members:
            title = m.get("title", "")
            if title and not title.startswith("Category:"):
                titles.append(title)

        cont = data.get("continue")
        if cont and "cmcontinue" in cont:
            params["cmcontinue"] = cont["cmcontinue"]
        else:
            break

    return titles


async def get_all_unit_titles(client: httpx.AsyncClient) -> list[str]:
    """获取所有分类下的单位页面标题（去重 + 过滤概述页）。"""
    all_titles: set[str] = set()

    for cat in _CATEGORIES:
        print(f"  [分类] {cat} ...")
        titles = await get_category_members(client, cat)
        before = len(all_titles)
        all_titles.update(titles)
        added = len(all_titles) - before
        print(f"    → 找到 {len(titles)} 个页面 (新增 {added})")

    # 过滤排除列表
    filtered = sorted(t for t in all_titles if t not in _TITLE_EXCLUDES)
    excluded = len(all_titles) - len(filtered)
    print(f"\n[汇总] 共 {len(filtered)} 个候选单位页面 (排除 {excluded} 个概述页)")
    return filtered


# ============================================================
# 第二步：获取并解析单位页面
# ============================================================


async def fetch_unit_page(
    client: httpx.AsyncClient, title: str
) -> tuple[str, list[str]] | None:
    """获取单位页面的 HTML + categories。返回 (html, categories) 或 None。"""
    params = {
        "action": "parse",
        "page": title,
        "format": "json",
        "prop": "text|categories",
    }
    try:
        data = await _get_json(client, _API_URL, params)
        if "error" in data:
            return None
        html = data.get("parse", {}).get("text", {}).get("*", "")
        cats = [c["*"] for c in data.get("parse", {}).get("categories", [])]
        return html, cats
    except Exception as e:  # noqa: BLE001
        print(f"    [x] 获取页面失败 {title}: {e}")
        return None


def _is_aoe3_page(categories: list[str]) -> bool:
    """通过分类标记判断页面是否属于 AoE3。"""
    cat_set = set(categories)
    return bool(cat_set & _AOE3_CATEGORY_MARKERS)


def _clean_text(text: str) -> str:
    """清理 Wiki 文本中的标记。"""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[\[([^|\]]*\|)?([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\{\{[^}]*\}\}", "", text)
    return text.strip()


def _parse_number(text: str) -> float | None:
    """从文本中提取第一个数字。"""
    text = _clean_text(text)
    if "%" in text:
        match = re.search(r"([\d.]+)%", text)
        if match:
            return float(match.group(1)) / 100
    match = re.search(r"([\d.]+)", text)
    if match:
        return float(match.group(1))
    return None


def _parse_cost(text: str) -> dict[str, int]:
    """解析费用字符串，如 '75Food25Coin1Population'。"""
    cost: dict[str, int] = {}
    text = _clean_text(text).lower()
    patterns = [
        (r"(\d+)\s*food", "food"),
        (r"(\d+)\s*wood", "wood"),
        (r"(\d+)\s*(?:gold|coin)", "gold"),
        (r"(\d+)\s*export", "export"),
        (r"(\d+)\s*influence", "influence"),
    ]
    for pattern, resource in patterns:
        match = re.search(pattern, text)
        if match:
            cost[resource] = int(match.group(1))
    return cost


def _parse_pop(text: str) -> int | None:
    """从 Cost 字段或 Population 字段解析人口。"""
    text = _clean_text(text).lower()
    match = re.search(r"(\d+)\s*population", text)
    if match:
        return int(match.group(1))
    return None


def _parse_multipliers(value_el: Tag) -> list[dict[str, Any]]:
    """从 bonus damage 字段解析克制倍率。
    HTML 中是 '3.0x vs.Cavalry2.25x vs.Shock infantry' 的连续文本。
    """
    text = value_el.get_text(separator=" ", strip=True)
    text = _clean_text(text)
    multipliers: list[dict[str, Any]] = []
    pattern = r"([\d.]+)\s*x\s*(?:vs\.?\s*)([^0-9]+?)(?=\d+\.?\d*\s*x\s*vs|$)"
    for match in re.finditer(pattern, text, re.IGNORECASE):
        value = float(match.group(1))
        target = match.group(2).strip().rstrip(",;")
        if value != 1.0 and target:
            multipliers.append({"vs": target, "value": value})
    return multipliers


def _parse_resistance(text: str) -> dict[str, float]:
    """解析抗性，如 '20%Hand' 或 '30%Ranged'。"""
    text = _clean_text(text)
    resist: dict[str, float] = {}
    for match in re.finditer(r"([\d.]+)%\s*(Hand|Ranged|Siege|Melee)", text, re.IGNORECASE):
        val = float(match.group(1)) / 100
        rtype = match.group(2).lower()
        if rtype in ("hand", "melee"):
            resist["melee"] = val
        elif rtype == "ranged":
            resist["ranged"] = val
        elif rtype == "siege":
            resist["siege"] = val
    return resist


def _parse_type_field(value_el: Tag) -> list[str]:
    """解析 Type 字段（类型标签之间没有分隔符，靠链接/换行分隔）。"""
    # 优先用链接文本
    links = value_el.find_all("a")
    if links:
        types = []
        for a in links:
            t = a.get_text(strip=True).rstrip("*")
            if t and t not in types:
                types.append(t)
        return types
    # 否则用原文
    text = _clean_text(value_el.get_text(separator=",", strip=True))
    return [t.strip().rstrip("*") for t in text.split(",") if t.strip()]


def _parse_civs(value_el: Tag) -> list[str]:
    """解析文明字段。"""
    text = value_el.get_text(separator=",", strip=True)
    text = _clean_text(text)
    if text.lower() in ("see description", "all", "varies"):
        return []  # 需要从正文中获取
    return [c.strip() for c in re.split(r"[,，、]", text) if c.strip()]


def _classify_attack_group(header_text: str) -> str | None:
    """根据 section group header 判断攻击类型。"""
    h = header_text.lower()
    if any(k in h for k in ("ranged attack", "ranged")):
        if "siege" in h:
            return "siege"
        return "ranged"
    if any(k in h for k in ("hand attack", "hand", "melee", "trample")):
        return "melee"
    if any(k in h for k in ("siege", "bombard", "barrage", "case shot", "mortar")):
        return "siege"
    if any(k in h for k in ("charged", "bugle", "special")):
        return "special"
    return None


def parse_unit_page(html: str, title: str) -> dict[str, Any] | None:
    """解析单位页面 HTML，支持两种 infobox data-source 格式：
    - 格式A（固定前缀）: RRDamage, HHDamage, SSDamage, RRange, RMulti...
    - 格式B（编号后缀）: RDamage1, HDamage2, SDamage1, Range1, Multi1...
      需要用 section group header 来判断攻击类型。
    """
    soup = BeautifulSoup(html, "lxml")

    infobox = soup.find("aside", class_="portable-infobox")
    if not infobox:
        infobox = soup.find("div", class_="portable-infobox")
    if not infobox:
        infobox = soup.find("table", class_="infobox")
    if not infobox:
        print(f"    [!] 未找到 infobox: {title}")
        return None

    unit: dict[str, Any] = {
        "id": re.sub(r"[^a-z0-9_]", "", title.lower().replace(" ", "_").replace("(", "").replace(")", "")),
        "name_en": title,
        "name": _ZH_NAME_MAP.get(title, ""),
        "wiki_url": f"{_WIKI_BASE}/wiki/{title.replace(' ', '_')}",
    }

    if not isinstance(infobox, Tag):
        return None

    # --- 先处理格式A：固定前缀（RRDamage, HHDamage等）---
    items = infobox.find_all("div", class_="pi-item")
    for item in items:
        ds = (item.get("data-source") or "").strip()
        value_el = item.find("div", class_="pi-data-value")
        if not value_el:
            continue
        value_text = value_el.get_text(strip=True)

        if ds == "HP":
            num = _parse_number(value_text)
            if num:
                unit["hp"] = int(num)
        elif ds == "Type":
            unit["type"] = _parse_type_field(value_el)
        elif ds == "Civilization":
            civs = _parse_civs(value_el)
            if civs:
                unit["civs"] = civs
        elif ds == "Age":
            unit["age"] = _clean_text(value_text).split("(")[0].strip()
        elif ds == "Cost":
            unit["cost"] = _parse_cost(value_text)
            pop = _parse_pop(value_text)
            if pop:
                unit["pop"] = pop
        elif ds == "Time":
            num = _parse_number(value_text)
            if num:
                unit["train_time"] = int(num)
        elif ds == "Resistance":
            resist = _parse_resistance(value_text)
            if "melee" in resist:
                unit["armor_melee"] = resist["melee"]
            if "ranged" in resist:
                unit["armor_ranged"] = resist["ranged"]
        elif ds == "Speed":
            num = _parse_number(value_text)
            if num:
                unit["speed"] = num
        elif ds == "LOS":
            num = _parse_number(value_text)
            if num:
                unit["los"] = num
        elif ds == "Internal Name":
            unit["internal_name"] = _clean_text(value_text)
        elif ds == "Building":
            unit["trained_at"] = _parse_type_field(value_el)

        # 格式A 攻击字段
        elif ds == "RRDamage":
            num = _parse_number(value_text)
            if num:
                unit["attack_ranged"] = num
        elif ds == "RRange":
            range_match = re.search(r"(\d+)-(\d+)", value_text)
            if range_match:
                unit["range_min"] = int(range_match.group(1))
                unit["range"] = int(range_match.group(2))
            else:
                num = _parse_number(value_text)
                if num:
                    unit["range"] = num
        elif ds == "RROF":
            num = _parse_number(value_text)
            if num:
                unit["rof_ranged"] = num
        elif ds == "RMulti":
            mults = _parse_multipliers(value_el)
            if mults:
                unit.setdefault("multipliers", {})["ranged"] = mults
        elif ds == "HHDamage":
            num = _parse_number(value_text)
            if num:
                unit["attack_melee"] = num
        elif ds == "HROF":
            num = _parse_number(value_text)
            if num:
                unit["rof_melee"] = num
        elif ds == "HMulti":
            mults = _parse_multipliers(value_el)
            if mults:
                unit.setdefault("multipliers", {})["melee"] = mults
        elif ds == "SSDamage":
            num = _parse_number(value_text)
            if num:
                unit["attack_siege"] = num
        elif ds == "SRange":
            num = _parse_number(value_text)
            if num:
                unit["range_siege"] = num
        elif ds == "SROF":
            num = _parse_number(value_text)
            if num:
                unit["rof_siege"] = num
        elif ds == "SMulti":
            mults = _parse_multipliers(value_el)
            if mults:
                unit.setdefault("multipliers", {})["siege"] = mults

    # --- 格式B：编号后缀（RDamage1, HDamage2, SDamage1, Range1, Multi1...）---
    # 通过 section group header 判断攻击类型
    has_format_a = "attack_ranged" in unit or "attack_melee" in unit or "attack_siege" in unit
    if not has_format_a:
        groups = infobox.find_all("section", class_="pi-group")
        for group in groups:
            header = group.find("h2")
            if not header:
                continue
            header_text = header.get_text(strip=True)
            atk_type = _classify_attack_group(header_text)
            if not atk_type or atk_type == "special":
                continue

            group_items = group.find_all("div", class_="pi-item")
            for gitem in group_items:
                gds = (gitem.get("data-source") or "").strip()
                gval_el = gitem.find("div", class_="pi-data-value")
                if not gval_el:
                    continue
                gval_text = gval_el.get_text(strip=True)

                # 匹配 RDamage1, SDamage2, HDamage3 等
                if re.match(r"[RSH]?Damage\d*", gds) or re.match(r"SDamage\d*", gds):
                    num = _parse_number(gval_text)
                    if num:
                        if atk_type == "ranged":
                            unit.setdefault("attack_ranged", num)
                        elif atk_type == "melee":
                            unit.setdefault("attack_melee", num)
                        elif atk_type == "siege":
                            unit.setdefault("attack_siege", num)

                elif re.match(r"Range\d*", gds):
                    if atk_type == "ranged":
                        range_match = re.search(r"(\d+)-(\d+)", gval_text)
                        if range_match:
                            unit.setdefault("range_min", int(range_match.group(1)))
                            unit.setdefault("range", int(range_match.group(2)))
                        else:
                            num = _parse_number(gval_text)
                            if num:
                                unit.setdefault("range", num)
                    elif atk_type == "siege":
                        num = _parse_number(gval_text)
                        if num:
                            unit.setdefault("range_siege", num)

                elif re.match(r"ROF\d*", gds):
                    num = _parse_number(gval_text)
                    if num:
                        if atk_type == "ranged":
                            unit.setdefault("rof_ranged", num)
                        elif atk_type == "melee":
                            unit.setdefault("rof_melee", num)
                        elif atk_type == "siege":
                            unit.setdefault("rof_siege", num)

                elif re.match(r"Multi\d*", gds):
                    mults = _parse_multipliers(gval_el)
                    if mults:
                        unit.setdefault("multipliers", {}).setdefault(atk_type, mults)

    # 如果没有中文名，尝试从页面正文提取
    if not unit.get("name"):
        first_p = soup.find("div", class_="mw-parser-output")
        if first_p:
            first_text = first_p.get_text()[:300]
            zh_match = re.search(r"[（(]([^\x00-\x7F]{2,})[）)]", first_text)
            if zh_match:
                unit["name"] = zh_match.group(1)

    if not unit.get("name"):
        unit["name"] = title

    return unit


# ============================================================
# 第三步：主流程
# ============================================================


async def main(limit: int | None = None, force: bool = False) -> None:
    """主函数。"""
    print("=" * 60)
    print("帝国时代3决定版 · 兵种数据爬虫 v2")
    print("=" * 60)
    print(f"数据源: {_WIKI_BASE}")
    print(f"输出: {_OUTPUT_FILE}")
    print()

    # 检查已有数据
    existing_units: dict[str, dict] = {}
    if _OUTPUT_FILE.exists() and not force:
        try:
            existing_data = json.loads(_OUTPUT_FILE.read_text(encoding="utf-8"))
            existing_units = {u["name_en"]: u for u in existing_data}
            print(f"[i] 断点续跑，已有 {len(existing_units)} 个单位")
        except Exception as e:  # noqa: BLE001
            print(f"[!] 读取已有数据失败: {e}")

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True) as client:
        # 第一步：获取所有单位标题
        print("\n[1/2] 获取单位列表...")
        all_titles = await get_all_unit_titles(client)

        if limit:
            all_titles = all_titles[:limit]
            print(f"[限制] 只抓取前 {limit} 个")

        # 第二步：逐个抓取单位详情
        print(f"\n[2/2] 抓取单位详情（共 {len(all_titles)} 个）...")
        results: list[dict[str, Any]] = list(existing_units.values()) if not force else []
        new_count = 0
        failed_count = 0
        skipped_non_aoe3 = 0

        t0 = time.perf_counter()
        for i, title in enumerate(all_titles, 1):
            if title in existing_units and not force:
                continue

            print(f"  [{i}/{len(all_titles)}] {title} ...")

            result = await fetch_unit_page(client, title)
            if not result:
                failed_count += 1
                continue

            html, categories = result

            # 对于通用分类（非 AoE3 专属），检查页面是否属于 AoE3
            if not _is_aoe3_page(categories):
                print(f"    [跳过] 非 AoE3 页面 (cats: {categories[:3]})")
                skipped_non_aoe3 += 1
                continue

            unit = parse_unit_page(html, title)
            if unit:
                results.append(unit)
                new_count += 1
                zh_name = unit.get("name", title)
                hp = unit.get("hp", "?")
                atk = unit.get("attack_ranged") or unit.get("attack_melee", "?")
                print(f"    ✓ {zh_name} | HP={hp} ATK={atk}")
            else:
                failed_count += 1

            # 增量保存
            if new_count > 0 and new_count % 10 == 0:
                _save_results(results)
                print(f"    [保存] 已保存 {len(results)} 个单位")

        elapsed = time.perf_counter() - t0

    # 最终保存
    _save_results(results)

    print(f"\n{'=' * 60}")
    print(f"[完成] 新增 {new_count}，失败 {failed_count}，跳过非AoE3 {skipped_non_aoe3}")
    print(f"[总计] {len(results)} 个单位")
    print(f"[耗时] {elapsed:.1f}s")
    print(f"[输出] {_OUTPUT_FILE}")


def _save_results(results: list[dict]) -> None:
    """保存结果到 JSON 文件。"""
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # 按 name_en 排序
    sorted_results = sorted(results, key=lambda u: u.get("name_en", ""))
    _OUTPUT_FILE.write_text(
        json.dumps(sorted_results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AoE3:DE 兵种数据爬虫 v2")
    parser.add_argument("--limit", type=int, default=None, help="限制抓取数量（调试用）")
    parser.add_argument("--force", action="store_true", help="覆盖已有数据")
    args = parser.parse_args()

    asyncio.run(main(limit=args.limit, force=args.force))
