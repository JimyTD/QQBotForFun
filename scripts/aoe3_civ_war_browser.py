# ruff: noqa: RUF001
"""Local review browser for AoE3 civ-war lineup rules.

This is intentionally a development-only HTTP server.  It reuses the real
unit repository, ordinary battle-pool filtering, and civ-war role resolver;
it does not register or alter any QQ command.

Usage:
    uv run python scripts/aoe3_civ_war_browser.py
    uv run python scripts/aoe3_civ_war_browser.py --port 8765
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "tools" / "aoe3_civ_war_browser"
ICON_DIR = ROOT / "resources" / "aoe3" / "icons"
PREFERRED_TACTICS_PATH = ROOT / "seeds" / "aoe3" / "civ_war_preferred_tactics.json"

for import_path in (str(ROOT), str(ROOT / "src")):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover - legacy Windows console fallback
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.disable(logging.CRITICAL)

from plugins.aoe3.models import Unit  # noqa: E402
from plugins.aoe3.repository import UnitRepo, is_excluded_unit  # noqa: E402
from plugins.aoe3.upgrades import apply_upgrades  # noqa: E402
from plugins.games.aoe3_battle.civ_war_lineups import (  # noqa: E402
    CivWarCandidate,
    allocate_candidate,
)
from plugins.games.aoe3_battle.civ_war_roles import (  # noqa: E402
    DEDICATED_DEMOLITION_IDS,
    GENERIC_ARCHETYPES,
    NATIONAL_TACTICS,
    ROLE_ANTI_CAV_HEAVY,
    ROLE_ANTI_INFANTRY_ARTILLERY,
    ROLE_DRAGOON,
    ROLE_MUSK,
    ROLE_SHOCK,
    ROLE_SKIRM,
    AllocationRule,
    civ_regular_units,
    is_regular_civ_war_unit,
    load_curated_civ_units,
    resolve_archetypes,
    unit_roles,
)
from plugins.games.aoe3_battle.lineup import (  # noqa: E402
    BATTLE_BLACKLIST,
    BLACKLIST,
    PURE_HEALER_ATTACK_THRESHOLD,
    get_bet_pool,
    unit_game_age,
)

ROLE_META = {
    ROLE_MUSK: {"label": "火枪", "rule": "AbstractMusketeer"},
    ROLE_SKIRM: {
        "label": "散",
        "rule": "散兵/步弓标签，且反重步倍率或官方 tooltip 确认反步兵",
    },
    ROLE_SHOCK: {
        "label": "冲击",
        "rule": "AbstractHandCavalry，或 AbstractHandInfantry + AbstractLightInfantry",
    },
    ROLE_DRAGOON: {"label": "龙骑", "rule": "AbstractRangedCavalry 或 AbstractRangedShockInfantry"},
    ROLE_ANTI_CAV_HEAVY: {
        "label": "重步反骑",
        "rule": "AbstractHandInfantry + AbstractHeavyInfantry，且近战对 AbstractCavalry 有倍率",
    },
    ROLE_ANTI_INFANTRY_ARTILLERY: {
        "label": "反步兵炮",
        "rule": "AbstractArtillery 且远程对步兵有倍率，或英文 tooltip 明确反步兵；排除纯反炮/迫击炮",
    },
}
ROLE_ORDER = tuple(ROLE_META)

PENDING_NATIONAL_TACTICS = {
    "XPAztec": (
        "待验证：豹勇士 + 投石兵 + 美洲狮矛兵",
        "xpjaguarknight",
        "xpmacehualtin",
        "xppumaman",
    ),
    "XPSioux": (
        "待验证：斧头骑兵 + 火枪骑兵",
        "xpaxerider",
        "xpriflerider",
    ),
    "Indians": (
        "待验证：印度兵 + 廓尔喀 + 印度重装骑兵",
        "ypsepoy",
        "ypnatmercgurkha",
        "ypsowar",
    ),
}


def is_consulate_unit(unit: Unit) -> bool:
    """Recognize both ordinary and siege consulate units.

    Infantry/cavalry use ``AbstractConsulateUnit`` while consulate artillery is
    tagged ``AbstractConsulateSiege*`` in the seed.  Both are legal units, but
    both must sort after native-only candidates and respect the UI filters.
    """
    return any(tag.startswith("AbstractConsulate") for tag in unit.type)


def has_multiplier(unit: Unit, attack: str, targets: set[str]) -> list[str]:
    multipliers = unit.multipliers_melee if attack == "melee" else unit.multipliers_ranged
    return [
        f"{entry.vs} x{entry.value:g}"
        for entry in multipliers
        if entry.vs in targets and entry.value > 1
    ]


def role_explanations(unit: Unit, roles: frozenset[str]) -> dict[str, str]:
    tags = set(unit.type)
    explanations: dict[str, str] = {}
    if ROLE_MUSK in roles:
        explanations[ROLE_MUSK] = "含 AbstractMusketeer"
    if ROLE_SKIRM in roles:
        matched = sorted(tags & {"AbstractSkirmisher", "AbstractFootArcher"})
        explanations[ROLE_SKIRM] = f"含 {' / '.join(matched)}"
    if ROLE_SHOCK in roles:
        if "AbstractHandCavalry" in tags:
            explanations[ROLE_SHOCK] = "含 AbstractHandCavalry"
        else:
            explanations[ROLE_SHOCK] = "同时含 AbstractHandInfantry 与 AbstractLightInfantry"
    if ROLE_DRAGOON in roles:
        matched = sorted(tags & {"AbstractRangedCavalry", "AbstractRangedShockInfantry"})
        explanations[ROLE_DRAGOON] = f"含 {' / '.join(matched)}"
    if ROLE_ANTI_CAV_HEAVY in roles:
        multipliers = has_multiplier(unit, "melee", {"AbstractCavalry"})
        explanations[ROLE_ANTI_CAV_HEAVY] = "重步近战标签，且近战 " + " / ".join(multipliers)
    if ROLE_ANTI_INFANTRY_ARTILLERY in roles:
        infantry = has_multiplier(
            unit,
            "ranged",
            {"AbstractInfantry", "AbstractHeavyInfantry", "AbstractLightInfantry"},
        )
        if infantry:
            explanations[ROLE_ANTI_INFANTRY_ARTILLERY] = "火炮远程 " + " / ".join(infantry)
        else:
            explanations[ROLE_ANTI_INFANTRY_ARTILLERY] = (
                "火炮英文 tooltip 明确写明 against infantry"
            )
    return explanations


def unit_payload(
    unit: Unit,
    age: int,
    *,
    civ_id: str | None = None,
    slot_role: str | None = None,
) -> dict:
    upgraded = apply_upgrades(unit, age, civ_id=civ_id)
    roles = unit_roles(upgraded)
    ranged_counters = has_multiplier(
        upgraded,
        "ranged",
        {
            "AbstractInfantry",
            "AbstractHeavyInfantry",
            "AbstractLightInfantry",
            "AbstractCavalry",
            "AbstractArtillery",
        },
    )
    melee_counters = has_multiplier(upgraded, "melee", {"AbstractCavalry", "AbstractInfantry"})
    icon_exists = (ICON_DIR / f"{unit.id}.png").is_file()
    return {
        "id": unit.id,
        "name": upgraded.name,
        "base_name": unit.name,
        "name_en": unit.name_en,
        "age": unit_game_age(unit),
        "current_age": age,
        "roles": [role for role in ROLE_ORDER if role in roles],
        "role_explanations": role_explanations(upgraded, roles),
        "slot_role": slot_role,
        "is_consulate": is_consulate_unit(unit),
        "icon": f"/icons/{unit.id}.png" if icon_exists else None,
        "type": unit.type,
        "cost": upgraded.cost,
        "pop": upgraded.pop,
        "hp": upgraded.hp,
        "speed": upgraded.speed,
        "attack_ranged": upgraded.attack_ranged,
        "range": upgraded.range,
        "attack_melee": upgraded.attack_melee,
        "ranged_counters": ranged_counters,
        "melee_counters": melee_counters,
    }


def normal_pool_exclusion_reason(unit: Unit) -> str | None:
    """Mirror get_bet_pool's safety gates with a human-readable first reason."""
    tags = set(unit.type)
    if not unit.cost:
        return "普通池：无资源费用"
    if not unit.has_attack:
        return "普通池：没有对兵攻击"
    if "AbstractBannerArmy" in tags:
        return "代币：AbstractBannerArmy（召唤入口，不能直接上场）"
    if is_excluded_unit(unit):
        return "普通池：全局占位符 / 守护者 / 战役专属条目"
    if tags & {"Building", "AbstractBuilding", "AbstractWagon"}:
        return "普通池：建筑或建筑马车"
    if tags & {"Ship", "AbstractWarShip"}:
        return "普通池：船只"
    if "AbstractVillager" in tags:
        return "普通池：村民"
    if (
        "AbstractHealer" in tags
        and max(unit.attack_ranged, unit.attack_melee) <= PURE_HEALER_ATTACK_THRESHOLD
    ):
        return "普通池：纯治疗者"
    if unit.hp <= 0:
        return "普通池：生命值为 0"
    if unit.id in BLACKLIST:
        return "普通池：永久黑名单（数据异常）"
    if unit.id in BATTLE_BLACKLIST:
        return "普通池：彩蛋 / 剧情 / 怪物黑名单"
    return None


def civ_war_exclusion_reason(unit: Unit) -> str | None:
    tags = set(unit.type)
    if unit.id in {"xpspy", "despyottoman"} or {
        "MercType2",
        "AbstractCanSeeStealth",
    } <= tags:
        return "国战：间谍单位"
    if unit.id.endswith("mansabdar"):
        return "国战：Mansabdar 强化单位"
    if "Hero" in tags:
        return "国战：英雄"
    if "AbstractPet" in tags:
        return "国战：宠物"
    if unit.id in DEDICATED_DEMOLITION_IDS:
        return "国战：爆破 / 攻城特种单位"
    if "AbstractFindScout" in tags:
        return "国战：侦察单位"
    return None


class BrowserData:
    def __init__(self) -> None:
        self.repo = UnitRepo.get()
        self.civ_units = load_curated_civ_units()
        civs_path = ROOT / "seeds" / "aoe3" / "civs.json"
        self.civ_data = json.loads(civs_path.read_text(encoding="utf-8"))["civs"]
        self.preferred_tactics = json.loads(
            PREFERRED_TACTICS_PATH.read_text(encoding="utf-8")
        )
        self.preferred_extra_units = {
            civ_id: set(unit_ids)
            for civ_id, unit_ids in self.preferred_tactics["_meta"].get(
                "extra_unit_ids", {}
            ).items()
        }

    def _persist_preferred_tactics(self) -> None:
        temp_path = PREFERRED_TACTICS_PATH.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(self.preferred_tactics, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(PREFERRED_TACTICS_PATH)

    def _validate_preferred_tactic(self, civ_id: str, tactic: dict) -> dict:
        if civ_id not in self.civ_units:
            raise ValueError(f"Not a curated civ: {civ_id}")
        tactic_id = str(tactic.get("id", "")).strip()
        if not re.fullmatch(r"[a-z0-9_]{3,64}", tactic_id):
            raise ValueError("策略 id 只能使用 3~64 位小写字母、数字和下划线")
        if any(item.civ_id == civ_id and item.id == tactic_id for item in NATIONAL_TACTICS):
            raise ValueError("已实现的固定国家战术不能在草案页修改")
        title = str(tactic.get("title", "")).strip()
        reason = str(tactic.get("reason", "")).strip()
        if not title or len(title) > 30:
            raise ValueError("策略名称不能为空且最多 30 字")
        if not reason or len(reason) > 240:
            raise ValueError("入选说明不能为空且最多 240 字")
        min_age = int(tactic.get("min_age", 3))
        if min_age not in {3, 4, 5}:
            raise ValueError("最早时代必须为 3、4 或 5")

        unit_ids = [str(unit_id).strip() for unit_id in tactic.get("unit_ids", ())]
        if not 1 <= len(unit_ids) <= 3 or len(set(unit_ids)) != len(unit_ids):
            raise ValueError("策略必须包含 1~3 个不同兵种")
        allowed_ids = set(self.civ_units[civ_id]) | self.preferred_extra_units.get(
            civ_id, set()
        )
        for unit_id in unit_ids:
            unit = self.repo.get_by_id(unit_id)
            if unit is None or unit_id not in allowed_ids:
                raise ValueError(f"{unit_id} 不是该文明可用单位")
            if not is_regular_civ_war_unit(unit):
                raise ValueError(f"{unit.name} 不属于国战正规军")
            if is_consulate_unit(unit) and unit_id not in self.preferred_extra_units.get(
                civ_id, set()
            ):
                raise ValueError("优势策略草案只能使用本国单位，不能使用领事馆单位")
            min_age = max(min_age, unit_game_age(unit))

        allocation = tactic.get("allocation", {})
        if allocation.get("kind") != "resource_shares":
            raise ValueError("草案目前只支持资源占比")
        values = [float(value) for value in allocation.get("values", ())]
        if len(values) != len(unit_ids) or any(value <= 0 for value in values):
            raise ValueError("每个兵种必须有正数资源占比")
        if abs(sum(values) - 1.0) > 1e-6:
            raise ValueError("资源占比合计必须为 100%")
        basis = [
            str(item).strip()
            for item in tactic.get("basis", ())
            if str(item).strip()
        ][:6]
        return {
            "id": tactic_id,
            "status": (
                "approved" if tactic.get("status", "approved") == "approved" else "draft"
            ),
            "title": title,
            "min_age": min_age,
            "unit_ids": unit_ids,
            "allocation": {"kind": "resource_shares", "values": values},
            "basis": basis,
            "reason": reason,
        }

    def save_preferred_tactic(self, civ_id: str, tactic: dict) -> None:
        normalized = self._validate_preferred_tactic(civ_id, tactic)
        entries = self.preferred_tactics["civs"][civ_id]
        for index, current in enumerate(entries):
            if current["id"] == normalized["id"]:
                entries[index] = normalized
                break
        else:
            entries.append(normalized)
        self._persist_preferred_tactics()

    def delete_preferred_tactic(self, civ_id: str, tactic_id: str) -> None:
        if civ_id not in self.civ_units:
            raise ValueError(f"Not a curated civ: {civ_id}")
        entries = self.preferred_tactics["civs"][civ_id]
        remaining = [entry for entry in entries if entry["id"] != tactic_id]
        if len(remaining) == len(entries):
            raise ValueError("找不到可删除的审核草案")
        self.preferred_tactics["civs"][civ_id] = remaining
        self._persist_preferred_tactics()

    def bootstrap(self) -> dict:
        civs = []
        for civ_id in self.civ_units:
            data = self.civ_data[civ_id]
            civs.append({"id": civ_id, "name": data["name"], "name_en": data["name_en"]})
        return {
            "civs": civs,
            "roles": ROLE_META,
            "archetypes": [
                {"id": archetype.id, "title": archetype.title, "roles": list(archetype.roles)}
                for archetype in GENERIC_ARCHETYPES
            ],
            "quick_civs": [
                "DEEthiopians",
                "XPAztec",
                "XPSioux",
                "Indians",
                "Chinese",
                "Japanese",
                "Spanish",
            ],
            "preferred_counts": {
                civ_id: len(self.preferred_tactics["civs"].get(civ_id, ()))
                + sum(
                    tactic.civ_id == civ_id
                    and tactic.id not in {
                        entry["id"]
                        for entry in self.preferred_tactics["civs"].get(civ_id, ())
                    }
                    for tactic in NATIONAL_TACTICS
                )
                for civ_id in self.civ_units
            },
            "preferred_draft_note": self.preferred_tactics["_meta"]["note"],
        }

    def _preferred_tactics(self, civ_id: str, age: int) -> list[dict]:
        raw_entries = list(self.preferred_tactics["civs"].get(civ_id, ()))
        entries: list[dict] = []
        configured_ids = {entry["id"] for entry in raw_entries}

        for tactic in NATIONAL_TACTICS:
            if tactic.civ_id != civ_id or tactic.id in configured_ids:
                continue
            raw_entries.append({
                "id": tactic.id,
                "title": tactic.title,
                "min_age": tactic.min_age,
                "unit_ids": list(tactic.unit_ids),
                "allocation": {
                    "kind": tactic.allocation.kind,
                    "values": list(tactic.allocation.values),
                },
                "basis": ["已实现", "原游戏固定编制"],
                "reason": "中国旗军按原游戏固定单位数量比例扩编。",
                "status": "implemented",
            })

        for raw in raw_entries:
            min_age = int(raw.get("min_age", 3))
            units = tuple(
                unit
                for unit_id in raw["unit_ids"]
                if (unit := self.repo.get_by_id(unit_id)) is not None
            )
            if units:
                min_age = max(min_age, *(unit_game_age(unit) for unit in units))
            allocation_raw = raw["allocation"]
            allocation = AllocationRule(
                allocation_raw["kind"],
                tuple(float(value) for value in allocation_raw["values"]),
            )
            available = age >= min_age and len(units) == len(raw["unit_ids"])
            lineup = None
            if available:
                candidate = CivWarCandidate(
                    id=f"review:{raw['id']}",
                    title=raw["title"],
                    civ_id=civ_id,
                    units=units,
                    allocation=allocation,
                    source="national",
                    strategy_id=raw["id"],
                )
                lineup = allocate_candidate(
                    candidate,
                    budget=int(self.preferred_tactics["_meta"]["budget"]),
                    age=age,
                )
            counts_by_id = {
                slot.unit.id: slot.count for slot in lineup.slots
            } if lineup is not None else {}
            entries.append({
                "id": raw["id"],
                "title": raw["title"],
                "status": raw.get("status", "approved"),
                "min_age": min_age,
                "available": available,
                "basis": raw.get("basis", []),
                "reason": raw.get("reason", ""),
                "allocation_kind": allocation.kind,
                "allocation_values": list(allocation.values),
                "total_cost": lineup.total_cost if lineup is not None else None,
                "units": [
                    {
                        **unit_payload(unit, age, civ_id=civ_id),
                        "count": counts_by_id.get(unit.id),
                        "share": allocation.values[index],
                    }
                    for index, unit in enumerate(units)
                ],
            })
        return entries

    def _audit_exclusions(self, civ_id: str, age: int) -> list[dict]:
        excluded: list[dict] = []
        for unit_id in self.civ_units[civ_id]:
            unit = self.repo.get_by_id(unit_id)
            if unit is None:
                excluded.append(
                    {"id": unit_id, "name": unit_id, "reason": "seed 中的单位 id 无法解析"}
                )
                continue
            reason = normal_pool_exclusion_reason(unit) or civ_war_exclusion_reason(unit)
            if reason:
                excluded.append(
                    {"id": unit.id, "name": unit.name, "name_en": unit.name_en, "reason": reason}
                )
            elif unit_game_age(unit) > age:
                excluded.append(
                    {
                        "id": unit.id,
                        "name": unit.name,
                        "name_en": unit.name_en,
                        "reason": f"当前不可用：{unit_game_age(unit)} 时代登场",
                    }
                )
        return excluded

    def civ_snapshot(
        self,
        civ_id: str,
        age: int,
        *,
        local_only: bool,
        include_consulate: bool,
    ) -> dict:
        if civ_id not in self.civ_units:
            raise ValueError(f"Not a curated civ: {civ_id}")

        safe_pool = get_bet_pool(self.repo, age=age)
        regular_units = civ_regular_units(civ_id, safe_pool, civ_units=self.civ_units)
        displayed_units = [
            unit
            for unit in regular_units
            if (include_consulate or not is_consulate_unit(unit))
            and (not local_only or not is_consulate_unit(unit))
        ]
        preferred_editor_units = list(displayed_units)
        preferred_editor_ids = {unit.id for unit in preferred_editor_units}
        for unit_id in self.preferred_extra_units.get(civ_id, set()):
            unit = self.repo.get_by_id(unit_id)
            if unit is not None and unit.id not in preferred_editor_ids:
                preferred_editor_units.append(unit)
                preferred_editor_ids.add(unit.id)

        resolved = resolve_archetypes(displayed_units)
        grouped: dict[str, list[dict]] = defaultdict(list)
        for candidate in resolved:
            if all(is_consulate_unit(unit) for unit in candidate.units):
                continue
            slots = [
                unit_payload(unit, age, civ_id=civ_id, slot_role=role)
                for role, unit in zip(candidate.archetype.roles, candidate.units, strict=True)
            ]
            grouped[candidate.archetype.id].append(
                {
                    "id": "__".join(candidate.unit_ids),
                    "units": slots,
                    "uses_consulate": any(slot["is_consulate"] for slot in slots),
                    "default_shares": [
                        round(value * 100)
                        for value in candidate.archetype.allocation.values
                    ],
                }
            )
        for candidates in grouped.values():
            candidates.sort(key=lambda item: (item["uses_consulate"], item["id"]))

        role_coverage = Counter(role for unit in displayed_units for role in unit_roles(unit))
        current_civ = self.civ_data[civ_id]
        pending = PENDING_NATIONAL_TACTICS.get(civ_id)
        return {
            "civ": {"id": civ_id, "name": current_civ["name"], "name_en": current_civ["name_en"]},
            "age": age,
            "filters": {"local_only": local_only, "include_consulate": include_consulate},
            "units": [
                unit_payload(unit, age, civ_id=civ_id)
                for unit in sorted(
                    displayed_units,
                    key=lambda entry: (is_consulate_unit(entry), entry.name_en.lower()),
                )
            ],
            "preferred_unit_options": [
                unit_payload(unit, age, civ_id=civ_id)
                for unit in sorted(
                    preferred_editor_units,
                    key=lambda entry: entry.name_en.lower(),
                )
            ],
            "unit_counts": {
                "safe_regular": len(regular_units),
                "shown": len(displayed_units),
                "consulate": sum(is_consulate_unit(unit) for unit in displayed_units),
            },
            "candidates": dict(grouped),
            "candidate_counts": {
                archetype.id: len(grouped[archetype.id]) for archetype in GENERIC_ARCHETYPES
            },
            "role_coverage": {role: role_coverage[role] for role in ROLE_ORDER},
            "empty_roles": [role for role in ROLE_ORDER if not role_coverage[role]],
            "excluded": self._audit_exclusions(civ_id, age),
            "chinese_banners": self._chinese_banners(age),
            "pending_tactic": self._pending_tactic(pending, age, civ_id=civ_id),
            "preferred_tactics": self._preferred_tactics(civ_id, age),
        }

    def _chinese_banners(self, age: int) -> list[dict]:
        banners = []
        for tactic in NATIONAL_TACTICS:
            if tactic.civ_id != "Chinese":
                continue
            entries = []
            for unit_id, count in zip(
                tactic.unit_ids,
                tactic.allocation.values,
                strict=True,
            ):
                unit = self.repo.get_by_id(unit_id)
                if unit is not None:
                    item = unit_payload(unit, age, civ_id="Chinese")
                    item["count"] = int(count)
                    entries.append(item)
            banners.append(
                {
                    "title": tactic.title,
                    "min_age": tactic.min_age,
                    "available": age >= tactic.min_age,
                    "units": entries,
                }
            )
        return banners

    def _pending_tactic(
        self,
        pending: tuple[str, ...] | None,
        age: int,
        *,
        civ_id: str,
    ) -> dict | None:
        if pending is None:
            return None
        title, *unit_ids = pending
        units = []
        for unit_id in unit_ids:
            unit = self.repo.get_by_id(unit_id)
            if unit is not None:
                units.append(unit_payload(unit, age, civ_id=civ_id))
        return {"title": title, "units": units}


DATA = BrowserData()


class RequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/bootstrap":
            self._json(DATA.bootstrap())
            return
        if parsed.path == "/api/civ":
            query = parse_qs(parsed.query)
            try:
                civ_id = query.get("civ", ["DEEthiopians"])[0]
                age = int(query.get("age", ["3"])[0])
                if age not in {3, 4, 5}:
                    raise ValueError("age must be 3, 4, or 5")
                local_only = query.get("local_only", ["false"])[0].lower() == "true"
                include_consulate = query.get("include_consulate", ["true"])[0].lower() == "true"
                self._json(
                    DATA.civ_snapshot(
                        civ_id, age, local_only=local_only, include_consulate=include_consulate
                    )
                )
            except (TypeError, ValueError) as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path.startswith("/icons/"):
            unit_id = Path(parsed.path).name
            if not unit_id.endswith(".png") or unit_id != Path(unit_id).name:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            icon_path = ICON_DIR / unit_id
            if icon_path.is_file():
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(icon_path.read_bytes())
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/preferred-tactic":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 64_000:
                raise ValueError("请求正文大小无效")
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            action = payload.get("action")
            civ_id = str(payload.get("civ_id", ""))
            if action == "save":
                DATA.save_preferred_tactic(civ_id, payload.get("tactic", {}))
            elif action == "delete":
                DATA.delete_preferred_tactic(civ_id, str(payload.get("tactic_id", "")))
            else:
                raise ValueError("未知编辑操作")
            self._json({"ok": True})
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def _json(self, payload: dict, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local AoE3 civ-war review browser")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if not STATIC_DIR.is_dir():
        raise SystemExit(f"Missing browser assets: {STATIC_DIR}")

    server = ThreadingHTTPServer((args.host, args.port), RequestHandler)
    print(f"AoE3 Civ-War Browser: http://{args.host}:{args.port}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
