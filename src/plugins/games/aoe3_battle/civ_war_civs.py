"""Playable civilization catalog and public-name resolution for civ war."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
_CIVS_PATH = _ROOT / "seeds" / "aoe3" / "civs.json"

_EXTRA_ALIASES: dict[str, tuple[str, ...]] = {
    "British": ("英国",),
    "Chinese": ("中国",),
    "DEAmericans": ("美国",),
    "DEDanish": ("丹麦",),
    "DEEthiopians": ("埃塞俄比亚", "埃塞"),
    "DEHausa": ("豪萨",),
    "DEInca": ("印加",),
    "DEItalians": ("意大利",),
    "DEMaltese": ("马耳他",),
    "DEMexicans": ("墨西哥",),
    "DEPolish": ("波兰",),
    "DESwedish": ("瑞典",),
    "Dutch": ("荷兰",),
    "French": ("法国",),
    "Germans": ("德国",),
    "Indians": ("印度",),
    "Japanese": ("日本",),
    "Ottomans": ("奥斯曼", "土耳其"),
    "Portuguese": ("葡萄牙",),
    "Russians": ("俄罗斯", "俄国"),
    "Spanish": ("西班牙",),
    "XPAztec": ("阿兹特克",),
    "XPIroquois": ("豪德诺索尼", "易洛魁"),
    "XPSioux": ("拉科塔", "苏族"),
}


@dataclass(frozen=True)
class CivProfile:
    id: str
    name: str
    name_en: str
    aliases: tuple[str, ...]


def _load_profiles() -> tuple[CivProfile, ...]:
    data = json.loads(_CIVS_PATH.read_text(encoding="utf-8"))
    profiles: list[CivProfile] = []
    for civ_id in data["_meta"]["curated_civs"]:
        civ = data["civs"][civ_id]
        raw_name = civ["name"]
        common_name = raw_name.removesuffix("人")
        aliases = tuple(dict.fromkeys((
            raw_name,
            common_name,
            civ["name_en"],
            civ_id,
            civ.get("statsid", ""),
            *_EXTRA_ALIASES.get(civ_id, ()),
        )))
        profiles.append(CivProfile(
            id=civ_id,
            name=common_name,
            name_en=civ["name_en"],
            aliases=tuple(alias for alias in aliases if alias),
        ))
    return tuple(profiles)


CIV_PROFILES: tuple[CivProfile, ...] = _load_profiles()
_BY_ID: dict[str, CivProfile] = {profile.id: profile for profile in CIV_PROFILES}
_BY_ALIAS: dict[str, CivProfile] = {
    alias.strip().lower(): profile
    for profile in CIV_PROFILES
    for alias in profile.aliases
}


def get_civ_profile(civ_id: str) -> CivProfile:
    try:
        return _BY_ID[civ_id]
    except KeyError as exc:
        raise ValueError(f"not a curated playable civ: {civ_id}") from exc


def resolve_civ(token: str) -> CivProfile | None:
    return _BY_ALIAS.get(token.strip().lower())


def pick_random_civs(*, rng: random.Random | None = None) -> tuple[CivProfile, CivProfile]:
    if rng is None:
        rng = random.Random()
    red, blue = rng.sample(CIV_PROFILES, 2)
    return red, blue
