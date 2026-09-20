"""Content assertions for the generated AoE3 balance report."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "docs" / "demo" / "aoe3-balance-20260917" / "index.html"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    text = HTML.read_text(encoding="utf-8")
    m = re.search(r"const DATA = (.*?);\n    const changed", text, re.S)
    assert m, "embedded DATA not found"
    data = json.loads(m.group(1))

    assert len(data["changed"]) == 105
    assert len(data["added"]) == 65
    assert len(data["removed"]) == 6
    assert data["meta"]["changed"] == 225
    assert data["meta"]["combat_changed"] == 86

    contradictions = []
    for row in data["changed"]:
        delta = row["scoreDelta"]
        if delta is None:
            continue
        if row["direction"] == "增强" and delta < 0:
            contradictions.append((row["id"], row["direction"], delta, row["summary"]))
        if row["direction"] == "削弱" and delta > 0:
            contradictions.append((row["id"], row["direction"], delta, row["summary"]))
    assert not contradictions, contradictions

    by_id = {row["id"]: row for row in data["changed"]}
    assert by_id["denatlipkatatar"]["summary"].startswith("削弱")
    assert "12.5 → 10" in by_id["denatlipkatatar"]["summary"]
    assert by_id["cavalryarcher"]["impact"] == "机制型"
    assert "新增 6.5 近战攻击" in by_id["cavalryarcher"]["summary"]
    assert by_id["degascenya"]["summary"].startswith("结构性调整")
    assert by_id["ypspcishida"]["excluded"] is True
    assert by_id["spcxpchiefbravewolf"]["excluded"] is True

    missing_icons = [
        row["id"] for row in data["changed"]
        if row["icon"] and not (HTML.parent / row["icon"]).exists()
    ]
    assert not missing_icons, missing_icons

    print("report assertions passed")
    print("changed=105 added=65 removed=6")
    print("contradictions=0")


if __name__ == "__main__":
    main()
