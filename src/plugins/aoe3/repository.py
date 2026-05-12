"""AoE3 数据仓库 —— 加载 seeds 数据，提供查询接口。

查询工具和猜兵种游戏共用此层。
"""

from __future__ import annotations

import difflib
import json
import random
import re
from pathlib import Path
from typing import Sequence

from .i18n import reverse_lookup, t
from .models import Unit

_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # project root
_SEEDS_DIR = _ROOT / "seeds" / "aoe3"
_ICONS_DIR = _ROOT / "resources" / "aoe3" / "icons"


class UnitRepo:
    """单位数据仓库（单例，首次访问时懒加载）。"""

    _instance: UnitRepo | None = None
    _units: list[Unit]
    _by_id: dict[str, Unit]

    def __init__(self) -> None:
        data = json.loads((_SEEDS_DIR / "units.json").read_text(encoding="utf-8"))
        self._units = [Unit.from_dict(d) for d in data]
        self._by_id = {u.id: u for u in self._units}

        # 预构建搜索用的名称池（用于模糊匹配兜底）
        self._all_names: list[str] = []
        self._name_to_unit: dict[str, Unit] = {}
        for u in self._units:
            for name in [u.name.lower(), u.name_en.lower()] + [a.lower() for a in u.aliases]:
                if name and name not in self._name_to_unit:
                    self._all_names.append(name)
                    self._name_to_unit[name] = u

    @classmethod
    def get(cls) -> UnitRepo:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------ 基本查询 ------

    @property
    def all_units(self) -> list[Unit]:
        return self._units

    def get_by_id(self, uid: str) -> Unit | None:
        return self._by_id.get(uid)

    def search(self, query: str, *, limit: int = 5) -> list[Unit]:
        """中英文名 + 别名搜索。优先精确 → 前缀 → 包含 → 模糊兜底。"""
        q = query.strip().lower()
        if not q:
            return []

        exact: list[Unit] = []
        prefix: list[Unit] = []
        contains: list[Unit] = []

        for u in self._units:
            name_lower = u.name.lower()
            name_en_lower = u.name_en.lower()
            alias_lower = [a.lower() for a in u.aliases]

            # 精确匹配（name / name_en / 任意alias）
            if name_lower == q or name_en_lower == q or q in alias_lower:
                exact.append(u)
            # 前缀匹配
            elif (name_lower.startswith(q) or name_en_lower.startswith(q)
                  or any(a.startswith(q) for a in alias_lower)):
                prefix.append(u)
            # 包含匹配
            elif (q in name_lower or q in name_en_lower
                  or any(q in a for a in alias_lower)):
                contains.append(u)

        results = exact + prefix + contains
        if results:
            return results[:limit]

        # ── 模糊兜底：编辑距离匹配 ──
        # 用 difflib 找最接近的名称
        close_names = difflib.get_close_matches(
            q, self._all_names, n=limit, cutoff=0.5
        )
        if close_names:
            # 去重（不同名称可能指向同一 unit）
            seen_ids: set[str] = set()
            fuzzy_results: list[Unit] = []
            for name in close_names:
                u = self._name_to_unit[name]
                if u.id not in seen_ids:
                    seen_ids.add(u.id)
                    fuzzy_results.append(u)
            return fuzzy_results[:limit]

        return []

    def search_is_fuzzy(self, query: str) -> bool:
        """判断搜索结果是否来自模糊匹配（用于提示用户）。"""
        q = query.strip().lower()
        if not q:
            return False
        for u in self._units:
            name_lower = u.name.lower()
            name_en_lower = u.name_en.lower()
            alias_lower = [a.lower() for a in u.aliases]
            if (name_lower == q or name_en_lower == q or q in alias_lower
                    or name_lower.startswith(q) or name_en_lower.startswith(q)
                    or any(a.startswith(q) for a in alias_lower)
                    or q in name_lower or q in name_en_lower
                    or any(q in a for a in alias_lower)):
                return False
        return True

    # ------ 高级查询 ------

    def find_counters(
        self, target_type: str, *, min_mult: float = 1.5
    ) -> list[tuple[Unit, str, float]]:
        """找出克制某类型的兵种。

        返回 (unit, attack_type, multiplier_value) 列表，按倍率降序。
        target_type 支持中文（通过 i18n 反查）和英文。
        """
        q = target_type.strip().lower()

        # 利用 i18n 反向表：中文→英文
        q_en = reverse_lookup("multiplier_vs", q)
        if not q_en:
            q_en = reverse_lookup("type", q)
        if not q_en:
            q_en = q  # fallback 原文

        q_en_lower = q_en.lower()

        results: list[tuple[Unit, str, float]] = []
        for u in self._units:
            for atk_type, mults in [
                ("ranged", u.multipliers_ranged),
                ("melee", u.multipliers_melee),
                ("siege", u.multipliers_siege),
            ]:
                for m in mults:
                    vs_lower = m.vs.lower()
                    if q_en_lower in vs_lower or q in vs_lower:
                        if m.value >= min_mult:
                            results.append((u, atk_type, m.value))

        results.sort(key=lambda x: x[2], reverse=True)
        return results

    def list_by_civ(self, civ: str) -> list[Unit]:
        """按文明名查找（支持中文，通过 i18n 反查）。"""
        q = civ.strip().lower()

        # 利用 i18n 反向表
        q_en = reverse_lookup("civs", q)
        if not q_en:
            q_en = q
        q_en_lower = q_en.lower()

        results = []
        for u in self._units:
            for c in u.civs:
                if q_en_lower in c.lower() or q in c.lower():
                    results.append(u)
                    break
        return results

    # ------ 游戏用 ------

    def random_trainable(self) -> Unit:
        """随机一个可训练兵种（猜兵种游戏用）。"""
        trainable = [u for u in self._units if u.is_trainable]
        return random.choice(trainable)

    # ------ icon ------

    def get_icon_path(self, unit: Unit) -> Path | None:
        """返回本地 icon 路径，不存在则返回 None。"""
        p = _ICONS_DIR / f"{unit.id}.png"
        return p if p.exists() else None
