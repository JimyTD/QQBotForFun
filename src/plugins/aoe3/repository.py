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
# 而是召唤占位符 / 代币 / PVE 守护者，玩家在游戏里看不到这些条目。
#
# ⚠️ 注意：彩蛋 / 作弊 / 剧情兵（如镭射熊、加特林骆驼）**不在这里排除**，
# 它们是真单位，玩家应能 ``/帝国3 xxx`` 查到，仅在普通斗蛐蛐池排除。
# 详见 ``src/plugins/games/aoe3_battle/lineup.py`` 中的 ``BATTLE_BLACKLIST``。

# 战役 / 剧情专属条目，全局排除（搜索 + 对战池都不出现）。
#
# 筛选标准（2026-05-21 复审）：
#   spc / despc / ypspc / xpspc / yphc 前缀 = 战役专属，普通对战玩家造不到。
#   yphc* = 主城/剧情战役用的村民换皮（如 yphcjapanesesamurai「日本武士」），
#   与可训练的 ypkensei 等同名，由 ``is_excluded_unit`` 前缀规则排除。
#   按"是否够格当怪物"分两类：
#   - **菜鸡战役兵**（普通兵换皮 / 数据偏弱）→ 全局排除（这里）
#   - **怪物战役兵**（hp ≥ 500 或攻击数据离谱、有名有姓的英雄/大名/酋长/特殊机械）
#     → 留在 ``BATTLE_BLACKLIST``，黑名单乱斗模式里给玩家当 boss 玩
#   NATIVE 客兵（``spcaztecchief`` 等 5 个）保留在常规池：原住民部落能合法获取。
_EXCLUDED_IDS: frozenset[str] = frozenset({
    # —— 战役专属 NAVY（陆战池不要海军；同名普通版在普通池里 / 或纯剧情用）——
    "despcprivateer",      # 战役·私掠船（普通版 privateer 仍在）
    "spcfireship",         # 战役·火战船
    "despccorsairship",    # 战役·海盗船
    "spcfrigate",          # 战役·帝国护卫舰
    "despcrowboat",        # 战役·划艇
    "spclizzieflagship",   # 战役·莉丝的旗舰
    # —— 剧情触发物（不该进对战池）——
    "ypspcriderlesselephant",  # 没人骑的大象（hp 2000 train_time=0）
    "spcfiercecougar",         # 凶猛的美洲狮（战役剧情守护动物）
    # —— 菜鸡战役兵（普通一人口兵换皮，hp ≤ 280，数据跟普通版基本一样） ——
    # 这些战役兵进黑名单乱斗"不够怪"，留在常规池又是玩家造不到的冗余条目，
    # 因此彻底屏蔽。普通版同名兵在常规池里照常存在。
    "despcdelugecossack",      # 哥萨克骑兵（普通版 cossack hp 225 一致）
    "despcgenitour",           # 标枪骑兵
    "despchornspearman",       # 长矛兵（hp 100，比普通 pikeman 还菜）
    "despcjanissarynopop",     # 奥斯曼火枪兵（普通版 janissary 在）
    "despcshotel",             # 弯刀勇士（hp 90）
    "despcusregular",          # 正规军
    "spcbuccaneer",            # 海盗
    "ypspcarrowknight",        # 弓箭武士
    "ypspcarsonist",           # 火兵
    "spchoopthrowers",         # 火环兵
    "despcoutlawmusketeer",    # 亡命火枪兵（普通版 musketeer hp 150 一致）
    "despccityguard",          # 城市护卫
    "despchornskirmisher",     # 索马里火绳枪兵
    "despcusvolunteer",        # 志愿军
    "spcxpvfsoldier",          # 殖民地民兵
    "xpspccolonialmilitia",    # 殖民地民兵(xp)
    # —— 之前发现的 spc 守护者残留（虽已被 Guardian type 规则覆盖，列此处更显式） ——
    # despcpikemanguardian / despcstreletguardian / despcoprichnikguardian
    # → 已由 type 含 "Guardian" 规则排除，无需重复。
    # —— 治疗者（atk 4 < 10，已由 _is_pure_healer 自动排除） ——
    # ypspcbrahminhealer：lineup.py 里的 _is_pure_healer 处理。
})


def is_excluded_unit(unit: "Unit") -> bool:
    """是否为玩家不应感知的单位（占位符 / 代币 / PVE 守护者 / 战役海军）。

    规则：
    1. id 以 ``batch`` 结尾 —— 颐和园 / 使馆联盟批量召唤的占位符
       （如 ``deforthussarbatch``, ``defortlegiondragoonbatch``）。
    2. id 以 ``armyspawn`` 结尾 —— 中国旗军军队的颐和园召唤占位符
       （如 ``ypstandardarmyspawn`` "正规军(颐和园)"，
       ``ypforbiddenarmyspawn`` "紫禁军" 等共 8 个）。
       这些条目在游戏里召唤后会立刻拆解为具体兵种，玩家不会直接控制。
    3. id 以 ``igc`` 开头 —— in-game cinematic / 剧情过场专用单位
       （如 ``igcdeunclefrankhorse`` "法兰克叔叔"），玩家不可控。
    4. type 含 ``Guardian`` —— PVE 宝藏守护者
       （如 ``despcpikemanguardian`` "宝藏守护者长矛兵"）。
    5. type 含 ``AbstractBannerArmy`` —— 八旗军 / 领事馆远征军 / 原住民代币。
       这是"召唤入口"标签，hp 固定 200（占位 hp），点了之后会拆解为具体兵种，
       玩家不会直接控制单兵。覆盖 84 个 token：
       - 12 个中国八旗军（如 ``ypimperialarmy`` 御林军、``ypmingarmy`` 明军）
       - 39 个领事馆远征军（``ypconsulatearmy*``）
       - 4 个原住民代币（``*proxy``）
       - 29 个已被规则 1/2 覆盖的 batch/armyspawn（冗余防御）
    6. id 在 ``_EXCLUDED_IDS`` 中 —— 战役专属海军 + 剧情触发物
       + 菜鸡战役兵（普通一人口兵换皮，没资格进黑名单乱斗）。
       够格当怪物的战役兵（hp ≥ 500、英雄/大名/酋长 等）保留在
       ``BATTLE_BLACKLIST``，由黑名单乱斗模式专用。
    7. id 以 ``yphc`` 开头 —— 战役主城村民/剧情角色换皮（``AbstractVillager``），
       玩家正常造不到；避免与可训练军事单位中文名撞车。
    """
    if unit.id.endswith("batch"):
        return True
    if unit.id.endswith("armyspawn"):
        return True
    if unit.id.startswith("igc"):
        return True
    if unit.id.startswith("yphc"):
        return True
    if "Guardian" in unit.type:
        return True
    if "AbstractBannerArmy" in unit.type:
        return True
    if unit.id in _EXCLUDED_IDS:
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

    # PNG 文件头 magic bytes，用于过滤被错误命名为 .png 的 DDT/裸纹理文件
    _PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

    def get_icon_path(self, unit: Unit) -> Path | None:
        """返回本地 icon 路径，不存在或不是合法 PNG 则返回 None。

        校验文件前 8 字节 magic bytes，过滤掉 icons 目录里混入的非 PNG 文件
        （比如游戏 BAR 里解包出来的 DDT 裸纹理被错误命名为 .png）。
        这些坏文件如果发给 QQ，会导致整条消息（含其他正常图+文字详情）
        被服务端拒收（rich media transfer failed / retcode=1200）。
        """
        p = _ICONS_DIR / f"{unit.id}.png"
        if not p.exists():
            return None
        try:
            with p.open("rb") as f:
                if f.read(8) != self._PNG_MAGIC:
                    return None
        except OSError:
            return None
        return p
