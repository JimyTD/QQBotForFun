"""AoE3 windup 调研 — 逐动作名解 anim；斗蛐蛐只选代表动作，不选 windup。

铁律：.cursor/rules/aoe3-attack-data-design.mdc §只选动作

用法（需本机 AoE3DE + 已解包 Data.bar tactics）:
  uv run python scripts/aoe3_windup_research.py
  uv run python scripts/aoe3_windup_research.py --units longbowman skirmisher musketeer ypChuKoNu

依赖: lz4（与 aoe3_bar_extractor 相同）
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "crawler"))
from aoe3_bar_extractor import decode_xmb_to_xml, extract_file_data, read_bar_entries  # noqa: E402
from aoe3_gamedata_parser import _parse_attacks  # noqa: E402

EXTRACTED_DIR = Path(os.environ.get("AOE3_EXTRACTED_DIR", str(PROJECT_ROOT / "data" / "aoe3" / "raw")))
ART_UNITS_BAR = os.environ.get(
    "AOE3_ART_UNITS_BAR",
    r"E:\SteamLibrary\steamapps\common\AoE3DE\Game\Art\ArtUnits.bar",
)
PROTOY_PATH = EXTRACTED_DIR / "protoy.xml"
TACTICS_DIR = EXTRACTED_DIR / "tactics"

# 另一动作名的社区参考（如 VolleyRangedAttack 0.46s），与 parser 代表动作名可能不同
OTHER_ACTION_HINT = {
    "skirmisher": ("VolleyRangedAttack", 0.46),
}

# protoy.xml 用 PascalCase；seeds/units.json 用小写 id
UNIT_ID_ALIASES = {
    "longbowman": "Longbowman",
    "skirmisher": "Skirmisher",
    "musketeer": "Musketeer",
    "chukonu": "ypChuKoNu",
    "ypchukonu": "ypChuKoNu",
}


@dataclass
class WindupTrace:
    unit_id: str
    tactics_file: str
    animfile: str
    proto_action: str
    tactics_anim: str
    attack_tag_sec: float | None
    rof_ranged: float | None
    error: str = ""


def _representative_ranged_action(el: ET.Element) -> tuple[str | None, float | None]:
    """与 aoe3_gamedata_parser 相同：ATTACK_PRIORITY 选 ranged 槽代表 protoaction。"""
    tactics = (el.findtext("tactics") or "").strip()
    attacks = _parse_attacks(el, tactics)
    ranged = attacks.get("ranged")
    if not ranged:
        return None, None
    return ranged["name"], ranged.get("rof")


def _load_tactics_anims(tactics_file: str) -> dict[str, str]:
    path = TACTICS_DIR / tactics_file
    if not path.exists():
        return {}
    root = ET.parse(path).getroot()
    result: dict[str, str] = {}
    for action in root.findall("action"):
        name = (action.findtext("name") or "").strip()
        anim = (action.findtext("anim") or "").strip()
        if name and anim:
            result[name] = anim
    return result


def _animfile_to_bar_path(animfile: str) -> str:
    # protoy: units\infantry_ranged\longbow\longbow.xml
    return animfile.replace("/", "\\") + ".XMB"


def _extract_attack_tag_from_anim_xml(xml_text: str, anim_name: str) -> float | None:
    """从 unit anim XML 读取指定 <anim> 块内第一个 tag type=Attack 的秒数。"""
    # anim 名大小写不敏感（Volley_standing_attack vs Volley_Walk）
    pattern = re.compile(
        rf"<anim>\s*{re.escape(anim_name)}\s*(.*?)</anim>",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(xml_text)
    if not m:
        return None
    block = m.group(1)
    tag_m = re.search(r'<tag\s+type="Attack">([^<]+)</tag>', block)
    if not tag_m:
        return None
    return round(float(tag_m.group(1).strip()), 4)


class AnimCache:
    def __init__(self, bar_path: str):
        self.bar_path = bar_path
        self._entries = {e["name"]: e for e in read_bar_entries(bar_path)}
        self._xml_cache: dict[str, str] = {}

    def get_xml(self, bar_rel_path: str) -> str | None:
        if bar_rel_path in self._xml_cache:
            return self._xml_cache[bar_rel_path]
        entry = self._entries.get(bar_rel_path)
        if not entry:
            return None
        raw = extract_file_data(self.bar_path, entry)
        xml_text = decode_xmb_to_xml(raw)
        self._xml_cache[bar_rel_path] = xml_text
        return xml_text


def _resolve_protoy_name(unit_name: str) -> str:
    key = unit_name.strip()
    return UNIT_ID_ALIASES.get(key.lower(), key)


def trace_unit(unit_name: str, protoy_root: ET.Element, anim_cache: AnimCache) -> WindupTrace:
    protoy_name = _resolve_protoy_name(unit_name)
    el = protoy_root.find(f".//unit[@name='{protoy_name}']")
    if el is None:
        return WindupTrace(unit_name, "", "", "", "", None, None, error=f"unit not in protoy ({protoy_name})")

    unit_id = el.get("name", "")
    tactics_file = (el.findtext("tactics") or "").strip()
    animfile = (el.findtext("animfile") or "").strip()
    if not tactics_file:
        return WindupTrace(unit_id, "", animfile, "", "", None, None, error="no tactics")

    tactics_anims = _load_tactics_anims(tactics_file)
    if not tactics_anims:
        return WindupTrace(unit_id, tactics_file, animfile, "", "", None, None, error="tactics missing")

    proto_action, rof = _representative_ranged_action(el)
    if not proto_action:
        return WindupTrace(unit_id, tactics_file, animfile, "", "", None, None, error="no ranged slot")

    tactics_anim = tactics_anims[proto_action]
    bar_path = _animfile_to_bar_path(animfile)
    xml_text = anim_cache.get_xml(bar_path)
    if not xml_text:
        return WindupTrace(
            unit_id, tactics_file, animfile, proto_action, tactics_anim, None, rof,
            error=f"anim not in ArtUnits.bar: {bar_path}",
        )

    attack_sec = _extract_attack_tag_from_anim_xml(xml_text, tactics_anim)
    if attack_sec is None:
        return WindupTrace(
            unit_id, tactics_file, animfile, proto_action, tactics_anim, None, rof,
            error=f"no Attack tag in anim {tactics_anim}",
        )

    return WindupTrace(
        unit_id, tactics_file, animfile, proto_action, tactics_anim, attack_sec, rof,
    )


def scan_art_units_bar() -> dict[str, int]:
    entries = read_bar_entries(ART_UNITS_BAR)
    xml_count = sum(1 for e in entries if e["name"].lower().endswith(".xml.xmb"))
    return {"total_entries": len(entries), "unit_anim_xml": xml_count}


def main() -> None:
    parser = argparse.ArgumentParser(description="AoE3 windup research")
    parser.add_argument(
        "--units",
        nargs="*",
        default=["longbowman", "skirmisher", "musketeer", "ypChuKoNu"],
    )
    args = parser.parse_args()

    print("=== ArtUnits.bar 规模 ===")
    stats = scan_art_units_bar()
    print(f"  总条目: {stats['total_entries']:,}")
    print(f"  unit *.xml.XMB: {stats['unit_anim_xml']:,}")
    print(f"  BAR: {ART_UNITS_BAR}")
    print()

    if not PROTOY_PATH.exists():
        print(f"ERROR: {PROTOY_PATH} 不存在，请先运行 aoe3_bar_extractor.py")
        sys.exit(1)
    if not Path(ART_UNITS_BAR).exists():
        print(f"ERROR: {ART_UNITS_BAR} 不存在")
        sys.exit(1)

    protoy_root = ET.parse(PROTOY_PATH).getroot()
    anim_cache = AnimCache(ART_UNITS_BAR)

    print("=== 抽样：代表动作名 -> tactics -> anim -> tag Attack ===")
    print(f"{'unit':<14} {'action_name':<22} {'anim':<28} {'windup':>7} {'rof':>5}  note")
    print("-" * 110)

    ok = 0
    for unit in args.units:
        t = trace_unit(unit, protoy_root, anim_cache)
        hint_key = t.unit_id.lower()
        other = OTHER_ACTION_HINT.get(hint_key)

        if t.error:
            print(f"{unit:<14} ERROR: {t.error}")
            continue

        note = ""
        if other:
            other_name, other_sec = other
            if t.attack_tag_sec is not None and abs(t.attack_tag_sec - other_sec) > 0.015:
                note = f"{other_name}={other_sec:.2f}s"
        print(
            f"{t.unit_id:<14} {t.proto_action:<22} {t.tactics_anim:<28} "
            f"{t.attack_tag_sec:>6.2f}s {t.rof_ranged or 0:>5.2f}  {note}"
        )
        ok += 1

    print()
    print(f"成功 {ok}/{len(args.units)}")
    print()
    print("=== 结论摘要 ===")
    print("  - windup 跟动作名（引擎行为），不跟 damagetype")
    print("  - 与 attack/rof/num_projectiles 同绑 ATTACK_PRIORITY 选定的代表动作名")
    print("  - 不同动作名可不同 windup（散兵 DefendRangedAttack 0.48 vs VolleyRangedAttack 0.46）")


if __name__ == "__main__":
    main()
