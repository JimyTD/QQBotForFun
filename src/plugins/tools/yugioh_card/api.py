"""百鸽 (ygocdb.com) API 封装。

数据源：https://ygocdb.com/api
国内源、无 Cloudflare 防护、支持中文卡名搜索、提供卡图 CDN。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

_BASE_URL = "https://ygocdb.com/api/v0"
_IMG_CDN = "https://cdn.233.momobako.com/ygopro/pics"
_TIMEOUT = 10.0
_HEADERS = {
    "User-Agent": "QQBotForFun/1.0",
    "Accept": "application/json",
}


@dataclass
class YugiohCard:
    """游戏王卡片数据。"""

    id: int  # passcode / 密码
    name: str  # 卡名（中文）
    name_jp: str  # 日文卡名
    name_en: str  # 英文卡名
    types: str  # 类型行，如 "[怪兽|效果] 龙/光\n[★8] 3000/2500"
    description: str  # 效果/风味文本
    image_url: str  # 卡图 URL
    image_url_small: str  # 小尺寸卡图 URL


def _build_description(text: dict[str, Any]) -> str:
    """组合灵摆效果和怪兽效果为完整描述文本。

    搜索端点将灵摆效果放在 pdesc、怪兽效果放在 desc；
    详情端点则合并在 desc 里（已带【灵摆效果】/【怪兽效果】标题）。
    """
    pdesc = text.get("pdesc", "")
    desc = text.get("desc", "")
    if pdesc:
        return f"【灵摆效果】\n{pdesc}\n【怪兽效果】\n{desc}"
    return desc


def _parse_card(data: dict[str, Any]) -> YugiohCard:
    """从百鸽 API 搜索结果中解析单张卡片。"""
    card_id = data.get("id", 0)
    text = data.get("text", {})
    # 名称优先级：sc_name(官方简中) > cn_name(YGOPro译名) > md_name
    name = (
        data.get("sc_name")
        or data.get("cn_name")
        or data.get("md_name")
        or text.get("name", "未知卡片")
    )

    return YugiohCard(
        id=card_id,
        name=name,
        name_jp=data.get("jp_name", ""),
        name_en=data.get("en_name", ""),
        types=text.get("types", ""),
        description=_build_description(text),
        image_url=f"{_IMG_CDN}/{card_id}.jpg",
        image_url_small=f"{_IMG_CDN}/{card_id}.jpg!half",
    )


def _parse_card_detail(data: dict[str, Any]) -> YugiohCard:
    """从 /card/:id 端点解析单张卡片（格式略有不同）。"""
    card_id = data.get("id", 0)
    text = data.get("text", {})
    name = text.get("name", "未知卡片")

    return YugiohCard(
        id=card_id,
        name=name,
        name_jp="",
        name_en="",
        types=text.get("types", ""),
        description=_build_description(text),
        image_url=f"{_IMG_CDN}/{card_id}.jpg",
        image_url_small=f"{_IMG_CDN}/{card_id}.jpg!half",
    )


async def search_by_name(name: str) -> list[YugiohCard]:
    """按卡名模糊搜索。返回匹配的卡片列表（可能为空）。"""
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
        resp = await client.get(
            f"{_BASE_URL}/",
            params={"search": name},
        )

    if resp.status_code != 200:
        return []

    data = resp.json()
    results = data.get("result", [])
    return [_parse_card(c) for c in results]


async def search_by_id(passcode: int) -> YugiohCard | None:
    """按密码（passcode）精确查询。"""
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
        resp = await client.get(f"{_BASE_URL}/card/{passcode}")

    if resp.status_code != 200:
        return None

    data = resp.json()
    if not data or "id" not in data:
        return None
    return _parse_card_detail(data)


async def random_card() -> YugiohCard | None:
    """随机返回一张卡片。

    百鸽没有专门的 random 端点，用搜索空字符串取第一条来模拟。
    实际效果：返回最新/热门卡片之一。
    """
    import random as _random

    # 用一些常见关键词随机搜索来实现"随机"效果
    keywords = [
        "龙", "魔法师", "战士", "天使", "恶魔",
        "机械", "鸟兽", "水", "炎", "风",
        "光", "暗", "融合", "同调", "超量",
    ]
    keyword = _random.choice(keywords)

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
        resp = await client.get(
            f"{_BASE_URL}/",
            params={"search": keyword},
        )

    if resp.status_code != 200:
        return None

    data = resp.json()
    results = data.get("result", [])
    if not results:
        return None

    card_data = _random.choice(results)
    return _parse_card(card_data)
