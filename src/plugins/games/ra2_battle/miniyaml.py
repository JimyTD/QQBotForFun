"""OpenRA MiniYaml 轻量解析（Tab 缩进，值可含冒号）。"""

from __future__ import annotations

from typing import Any


def _parse_value(raw: str) -> Any:
    s = raw.strip()
    if not s:
        return ""
    if s.startswith("'") and s.endswith("'"):
        return s[1:-1]
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    if s.lower() in ("yes", "true"):
        return True
    if s.lower() in ("no", "false"):
        return False
    try:
        if "." not in s:
            return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _promote_scalar_to_node(parent: dict[str, Any], key: str, scalar: Any) -> dict[str, Any]:
    """OpenRA 允许 `Key: value` 下再接子节点，合并为 dict。"""
    node: dict[str, Any] = {"@value": scalar}
    parent[key] = node
    return node


def parse_miniyaml(text: str) -> dict[str, Any]:
    """解析单个 OpenRA 规则文件为顶层 actor -> tree。"""
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    pending_scalar: tuple[int, str, dict[str, Any]] | None = None

    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        depth = 0
        while depth < len(raw_line) and raw_line[depth] == "\t":
            depth += 1
        line = raw_line[depth:].strip()
        if not line or line.startswith("#"):
            continue

        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        val_str = rest.strip()

        while len(stack) > 1 and stack[-1][0] >= depth:
            stack.pop()
            pending_scalar = None

        if pending_scalar and depth > pending_scalar[0]:
            _, pkey, pdict = pending_scalar
            scalar = pdict[pkey]
            node = _promote_scalar_to_node(pdict, pkey, scalar)
            stack.append((pending_scalar[0], node))
            pending_scalar = None

        parent = stack[-1][1]

        if val_str == "":
            node: dict[str, Any] = {}
            parent[key] = node
            stack.append((depth, node))
            pending_scalar = None
        else:
            parent[key] = _parse_value(val_str)
            pending_scalar = (depth, key, parent)

    return root


def load_miniyaml_file(path) -> dict[str, Any]:
    from pathlib import Path

    p = Path(path)
    return parse_miniyaml(p.read_text(encoding="utf-8"))
