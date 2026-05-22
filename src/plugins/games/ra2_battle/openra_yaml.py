"""解析 OpenRA MiniYaml 规则：继承合并、WDist、Trait 抽取。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .miniyaml import load_miniyaml_file

# OpenRA 距离：如 5c768 = 5 格 + 768 子单位（1 格 = 1024）
_WDIST_RE = re.compile(r"^(\d+)c(\d+)?$", re.IGNORECASE)


def parse_wdist(value: Any) -> int | None:
    """将 yaml 中的 Range/Speed 等转为 WDist 整数。"""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip().lower()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    m = _WDIST_RE.match(s)
    if m:
        cells = int(m.group(1))
        sub = int(m.group(2) or 0)
        return cells * 1024 + sub
    # 纯格：8c0
    if s.endswith("c0"):
        try:
            return int(s[:-2]) * 1024
        except ValueError:
            return None
    return None


def _load_yaml_file(path: Path) -> dict[str, Any]:
    return load_miniyaml_file(path)


def load_rules_dir(rules_dir: Path) -> dict[str, dict[str, Any]]:
    """合并目录下所有规则文件为 actor_id -> raw node。"""
    actors: dict[str, dict[str, Any]] = {}
    for path in sorted(rules_dir.glob("*.yaml")):
        chunk = _load_yaml_file(path)
        for key, node in chunk.items():
            if not isinstance(node, dict):
                continue
            if key in actors:
                actors[key] = _deep_merge(actors[key], node)
            else:
                actors[key] = node
    return actors


def load_weapons_dir(weapons_dir: Path) -> dict[str, dict[str, Any]]:
    weapons: dict[str, dict[str, Any]] = {}
    for path in sorted(weapons_dir.glob("*.yaml")):
        chunk = _load_yaml_file(path)
        for key, node in chunk.items():
            if not isinstance(node, dict):
                continue
            if key in weapons:
                weapons[key] = _deep_merge(weapons[key], node)
            else:
                weapons[key] = node
    return weapons


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if k.startswith("-"):
            continue
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _collect_inherits(node: dict[str, Any]) -> list[str]:
    parents: list[str] = []
    for key, val in node.items():
        if key == "Inherits" or key.startswith("Inherits@"):
            if isinstance(val, str):
                parents.append(val)
            elif isinstance(val, list):
                parents.extend(str(x) for x in val)
    return parents


def _apply_removals(merged: dict[str, Any], node: dict[str, Any]) -> None:
    """处理 -TraitName 移除。"""
    for key in node:
        if key.startswith("-"):
            trait = key[1:].split("@")[0]
            to_del = [k for k in merged if k == trait or k.startswith(trait + "@")]
            for k in to_del:
                merged.pop(k, None)


def merge_actor(
    actor_id: str,
    raw: dict[str, dict[str, Any]],
    cache: dict[str, dict[str, Any]],
    stack: set[str] | None = None,
) -> dict[str, Any]:
    if actor_id in cache:
        return cache[actor_id]
    if stack is None:
        stack = set()
    if actor_id in stack:
        raise ValueError(f"循环继承: {actor_id}")
    stack.add(actor_id)

    node = raw.get(actor_id)
    if node is None:
        raise KeyError(actor_id)

    merged: dict[str, Any] = {}
    for parent in _collect_inherits(node):
        if parent not in raw:
            continue
        parent_merged = merge_actor(parent, raw, cache, stack)
        merged = _deep_merge(merged, parent_merged)

    _apply_removals(merged, node)
    for key, val in node.items():
        if key == "Inherits" or key.startswith("Inherits@"):
            continue
        if key.startswith("-"):
            continue
        if isinstance(val, dict) and key in merged and isinstance(merged[key], dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val

    stack.remove(actor_id)
    cache[actor_id] = merged
    return merged


def merge_weapon(
    weapon_id: str,
    raw: dict[str, dict[str, Any]],
    cache: dict[str, dict[str, Any]],
    stack: set[str] | None = None,
) -> dict[str, Any]:
    return merge_actor(weapon_id, raw, cache, stack)


def trait_blocks(merged: dict[str, Any], prefix: str) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for key, val in merged.items():
        if key == prefix or key.startswith(prefix + "@"):
            if isinstance(val, dict):
                out.append((key, val))
    return out


def split_csv(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [p.strip() for p in str(value).split(",") if p.strip()]
