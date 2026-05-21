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


# =====================================================================
# 全局排除规则
# =====================================================================
# 这套规则在两个地方共用：
#   1) /帝国3 单位搜索 —— 不让玩家搜到
#   2) 斗蛐蛐入池 —— 不让进对战池
#
# 排除原因：这些 id/标签对应的不是"玩家可控的真实兵种"，
# 而是召唤占位符 / PVE 守护者，玩家在游戏里看不到这些条目。
def is_excluded_unit(unit: "Unit") -> bool:
    """是否为玩家不应感知的单位（占位符 / PVE 守护者）。

    规则：
    1. id 以 ``batch`` 结尾 —— 颐和园 / 使馆联盟批量召唤的占位符
       （如 ``deforthussarbatch``, ``defortlegiondragoonbatch``）。
    2. id 以 ``armyspawn`` 结尾 —— 中国旗军军队的颐和园召唤占位符
       （如 ``ypstandardarmyspawn`` "正规军(颐和园)"，
       ``ypforbiddenarmyspawn`` "紫禁军" 等共 8 个）。
       这些条目在游戏里召唤后会立刻拆解为具体兵种，玩家不会直接控制。
    3. type 含 ``Guardian`` —— PVE 宝藏守护者
       （如 ``despcpikemanguardian`` "宝藏守护者长矛兵"）。
    """
    if unit.id.endswith("batch"):
        return True
    if unit.id.endswith("armyspawn"):
        return True
    if "Guardian" in unit.type:
        return True
    return False


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
        # 排除占位符 / 守护者，避免搜索结果被污染
        self._all_names: list[str] = []
        self._name_to_unit: dict[str, Unit] = {}
        for u in self._units:
            if is_excluded_unit(u):
                continue
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
        """中英文名 + 别名搜索。优先级：name精确 > alias精确 > 前缀 > 包含 > 模糊。

        会自动过滤召唤占位符 / PVE 守护者（``is_excluded_unit``）。
        """
        q = query.strip().lower()
        if not q:
            return []

        exact_name: list[Unit] = []   # name / name_en 精确
        exact_alias: list[Unit] = []  # alias 精确
        prefix: list[Unit] = []
        contains: list[Unit] = []

        for u in self._units:
            if is_excluded_unit(u):
                continue
            name_lower = u.name.lower()
            name_en_lower = u.name_en.lower()
            alias_lower = [a.lower() for a in u.aliases]

            # name / name_en 精确匹配（最高优先级）
            if name_lower == q or name_en_lower == q:
                exact_name.append(u)
            # alias 精确匹配
            elif q in alias_lower:
                exact_alias.append(u)
            # 前缀匹配
            elif (name_lower.startswith(q) or name_en_lower.startswith(q)
                  or any(a.startswith(q) for a in alias_lower)):
                prefix.append(u)
            # 包含匹配
            elif (q in name_lower or q in name_en_lower
                  or any(q in a for a in alias_lower)):
                contains.append(u)

        results = exact_name + exact_alias + prefix + contains
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
