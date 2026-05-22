"""从 OpenRA sequences 解析 actor_id → cameo shp 文件名。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .miniyaml import load_miniyaml_file
from .openra_yaml import load_rules_dir, merge_actor

_SEQUENCE_ALIASES: dict[str, str] = {
    "dog": "adog",
    "ghost": "seal",
}

# voxels 序列覆盖后 merge 会丢 icon；斗蛐蛐仍用 cameo 占位
_ICON_FALLBACKS: dict[str, str] = {
    "apoc": "mtnkicon.shp",
}


def _icon_shp_name(icon: Any) -> str | None:
    if isinstance(icon, str) and icon.strip():
        name = icon.strip().lower()
        return name if name.endswith(".shp") else f"{name}.shp"
    if isinstance(icon, dict):
        if icon.get("Filename"):
            return str(icon["Filename"]).lower()
        val = icon.get("@value")
        if val:
            name = str(val).strip().lower()
            return name if name.endswith(".shp") else f"{name}.shp"
    return None


def _scan_sequence_icon(seq_dir: Path, seq_id: str) -> str | None:
    """逐文件扫描 icon，避免 voxels 合并覆盖掉 vehicles 里的 cameo。"""
    for path in sorted(seq_dir.glob("*.yaml")):
        chunk = load_miniyaml_file(path)
        node = chunk.get(seq_id)
        if not isinstance(node, dict):
            continue
        fn = _icon_shp_name(node.get("icon"))
        if fn:
            return fn
    return None


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
    vendor_root: Path,
    actor_ids: set[str],
    raw_rules: dict[str, dict] | None = None,
    *,
    mod_id: str = "yr",
) -> dict[str, str]:
    mod = vendor_root / "mods" / mod_id
    seq_dir = mod / "sequences"
    if not seq_dir.is_dir():
        return {}
    if raw_rules is None:
        raw_rules = load_rules_dir(mod / "rules")
    raw_seq = load_rules_dir(seq_dir)
    cache: dict[str, dict] = {}
    out: dict[str, str] = {}
    for aid in sorted(actor_ids):
        if aid in _ICON_FALLBACKS:
            out[aid] = _ICON_FALLBACKS[aid]
            continue
        seq_id = _sequence_lookup_id(aid, raw_rules)
        fn = _scan_sequence_icon(seq_dir, seq_id)
        if fn is None:
            try:
                merged = merge_actor(seq_id, raw_seq, cache)
            except KeyError:
                continue
            fn = _icon_shp_name(merged.get("icon"))
        if fn:
            out[aid] = fn
    return out
