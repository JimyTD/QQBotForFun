"""科技解锁图：一个科技生效时，连带生效的科技。

数据：``seeds/aoe3/tech_links.json``（由 ``scripts/crawler/aoe3_civ_war_tech_pool.py``
从 ``techtreey.xml`` 生成）。规则见 docs/wip/aoe3-tech-effects.md：

- ``TechStatus active`` 激活的科技立即生效（影子或普通科技都算；主城卡的免费升级即此类）。
  ``obtainable``（开放研究、开放造兵）不生效。
- 影子科技在前置条件满足、且原始状态就是可获得（``OBTAINABLE``）时自动生效。原始不可获得、
  只能靠别的科技开放的不生效。本局判定不了的前置（单位数量、统计值等）视为不满足。
- 时代前置按本局时代判定。
- 同一个科技只进一次。
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger("aoe3.tech_links")

_LINKS_PATH = Path(__file__).resolve().parents[3] / "seeds" / "aoe3" / "tech_links.json"

# 时代科技名 → 游戏时代号（与单位 age、时代升级同口径）。
AGE_TECHS = {
    "Colonialize": 2,
    "Fortressize": 3,
    "Industrialize": 4,
    "Imperialize": 5,
}

_cache: dict | None = None
_shadow_by_prereq: dict[str, list[str]] | None = None


def _links() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_LINKS_PATH.read_text(encoding="utf-8"))["techs"]
        except (OSError, json.JSONDecodeError, KeyError) as e:
            logger.warning("加载 tech_links.json 失败：%s（不展开解锁链）", e)
            _cache = {}
    return _cache


def _shadows_waiting_on() -> dict[str, list[str]]:
    """非时代前置科技 → 以它为前置之一、且所有前置都能判定的影子科技。

    只有时代前置的影子科技（各种随时代自动生效的档、剧情/革命/独立档）不在这里：
    它们属于时代升级，由时代升级表按兵种选择，不因“到了这个时代”就全部生效。
    """
    global _shadow_by_prereq
    if _shadow_by_prereq is None:
        index: dict[str, list[str]] = {}
        for name, row in _links().items():
            if not row.get("shadow") or row.get("other_prereq") or not row.get("obtainable"):
                continue
            requires = row.get("requires") or ()
            if all(prereq in AGE_TECHS for prereq in requires):
                continue
            for prereq in requires:
                if prereq in AGE_TECHS:
                    continue
                index.setdefault(prereq, []).append(name)
        _shadow_by_prereq = index
    return _shadow_by_prereq


def age_techs(age: int) -> set[str]:
    """本局时代已生效的时代科技。"""
    return {name for name, value in AGE_TECHS.items() if value <= age}


def expand(tech_ids: Iterable[str], *, age: int) -> list[str]:
    """返回 ``tech_ids`` 加上它们连带生效的科技，保持首次出现顺序，不重复。

    时代科技本身参与前置判定，但不出现在返回值里（它的效果由时代升级负责）。
    """
    links = _links()
    waiting = _shadows_waiting_on()
    active: set[str] = set(age_techs(age))
    ordered: list[str] = []
    for tech in tech_ids:
        if tech:
            ordered.extend(_visit(tech, active, links, waiting))
    return ordered


def _ready_shadows(tech: str, active: set[str], waiting: dict, links: dict) -> list[str]:
    ready = []
    for shadow in waiting.get(tech, ()):
        if shadow in active:
            continue
        row = links[shadow]
        requires = row.get("requires") or ()
        met = (any if row.get("or_prereqs") else all)(prereq in active for prereq in requires)
        if met:
            ready.append(shadow)
    return ready


def _visit(tech: str, active: set[str], links: dict, waiting: dict) -> list[str]:
    ordered: list[str] = []
    queue = [tech]
    while queue:
        current = queue.pop(0)
        if current in active:
            continue
        active.add(current)
        ordered.append(current)
        queue.extend(
            child
            for child in (links.get(current) or {}).get("activates") or ()
            if child not in AGE_TECHS
        )
        # 新进来的科技可能补齐了某个影子的最后一个前置；这些影子都在 waiting 里。
        for prereq in list(active):
            queue.extend(_ready_shadows(prereq, active, waiting, links))
    return ordered
