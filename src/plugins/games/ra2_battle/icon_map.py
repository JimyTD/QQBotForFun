"""从 OpenRA sequences 解析 actor_id → cameo shp 文件名。"""

from __future__ import annotations

from pathlib import Path

from .openra_yaml import load_rules_dir, merge_actor

_SEQUENCE_ALIASES: dict[str, str] = {
    "dog": "adog",
    "ghost": "seal",
}


def _sequence_lookup_id(actor_id: str, raw_rules: dict[str, dict]) -> str:
    if actor_id in _SEQUENCE_ALIASES:
        return _SEQUENCE_ALIASES[actor_id]
    try:
        rules_cache: dict[str, dict] = {}
        merged = merge_actor(actor_id, raw_rules, rules_cache)
        rs = merged.get("RenderSprites")
        if isinstance(rs, dict) and rs.get("Image"):
            return str(rs["Image"])
    except KeyError:
        pass
    return actor_id


def build_icon_map(
    vendor_ra2: Path,
    actor_ids: set[str],
    raw_rules: dict[str, dict] | None = None,
) -> dict[str, str]:
    mod = vendor_ra2 / "mods" / "ra2"
    seq_dir = mod / "sequences"
    if not seq_dir.is_dir():
        return {}
    if raw_rules is None:
        raw_rules = load_rules_dir(mod / "rules")
    raw_seq = load_rules_dir(seq_dir)
    cache: dict[str, dict] = {}
    out: dict[str, str] = {}
    for aid in sorted(actor_ids):
        seq_id = _sequence_lookup_id(aid, raw_rules)
        try:
            merged = merge_actor(seq_id, raw_seq, cache)
        except KeyError:
            continue
        icon = merged.get("icon")
        if isinstance(icon, dict) and icon.get("Filename"):
            out[aid] = str(icon["Filename"]).lower()
    return out
