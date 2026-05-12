"""AoE3 数据仓库 —— 加载 seeds 数据，提供查询接口。

查询工具和猜兵种游戏共用此层。
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Sequence

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
        """中英文名 + 别名模糊搜索。优先精确匹配，然后前缀，最后包含。"""
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
        return results[:limit]

    # ------ 高级查询 ------

    def find_counters(
        self, target_type: str, *, min_mult: float = 1.5
    ) -> list[tuple[Unit, str, float]]:
        """找出克制某类型的兵种。
        
        返回 (unit, attack_type, multiplier_value) 列表，按倍率降序。
        target_type 支持模糊匹配（如 "骑兵" 匹配 "Cavalry"）。
        """
        # 类型名映射（中→英关键词）
        zh_to_en = {
            "骑兵": "cavalry", "步兵": "infantry", "炮兵": "artillery",
            "重步兵": "heavy infantry", "轻步兵": "light infantry",
            "重骑兵": "heavy cavalry", "轻骑兵": "light cavalry",
            "弓兵": "archer", "火枪": "musket", "船": "ship",
            "冲击步兵": "shock infantry", "攻城": "siege",
            "村民": "villager", "雇佣兵": "mercenary",
        }
        q = target_type.strip().lower()
        q_en = zh_to_en.get(q, q)

        results: list[tuple[Unit, str, float]] = []
        for u in self._units:
            for atk_type, mults in [
                ("ranged", u.multipliers_ranged),
                ("melee", u.multipliers_melee),
                ("siege", u.multipliers_siege),
            ]:
                for m in mults:
                    if q_en in m.vs.lower() or q in m.vs.lower():
                        if m.value >= min_mult:
                            results.append((u, atk_type, m.value))

        results.sort(key=lambda x: x[2], reverse=True)
        return results

    def list_by_civ(self, civ: str) -> list[Unit]:
        """按文明名查找（模糊匹配）。"""
        q = civ.strip().lower()
        # 中→英映射
        civ_map = {
            "英国": "british", "法国": "french", "德国": "germans",
            "俄罗斯": "russians", "西班牙": "spanish", "葡萄牙": "portuguese",
            "荷兰": "dutch", "奥斯曼": "ottomans", "瑞典": "swedes",
            "马耳他": "maltese", "意大利": "italians", "美国": "united states",
            "墨西哥": "mexicans", "日本": "japanese", "中国": "chinese",
            "印度": "indians", "阿兹特克": "aztecs",
            "易洛魁": "haudenosaunee", "豪德诺索尼": "haudenosaunee",
            "拉科塔": "lakota", "印加": "inca",
            "埃塞俄比亚": "ethiopians", "豪萨": "hausa",
        }
        q_en = civ_map.get(q, q)

        results = []
        for u in self._units:
            for c in u.civs:
                if q_en in c.lower() or q in c.lower():
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
