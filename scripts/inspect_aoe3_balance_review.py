"""Readable inspection helper for data/aoe3/balance_review.json."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = json.loads((ROOT / "data" / "aoe3" / "balance_review.json").read_text(encoding="utf-8"))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    rows = [
        row for row in DATA["changed"]
        if row["has_combat_change"] or "economy" in row["groups"]
    ]
    print("META", DATA["meta"])
    print("SUMMARY", DATA["summary"])
    print("COUNTS combat/econ", len(rows), "combat", sum(r["has_combat_change"] for r in rows),
          "econ", sum("economy" in r["groups"] for r in rows),
          "blind", sum(bool(r.get("blind_fields")) for r in rows))
    print("\nFIELDS")
    for field, count in Counter(f for r in rows for f in r["fields"]).most_common():
        print(f"{count:3} {field}")
    print("\nECONOMY")
    for r in rows:
        if "economy" in r["groups"]:
            print(
                f"{r['id']:38} {r['name']:16} score={r['score_delta_pct']!s:>7} "
                f"cost={r.get('cost_delta_pct')!s:>7} {r['fields']}"
            )
            for f in r["fields"]:
                if f in {"cost", "pop", "train_time"}:
                    print(" ", f, r["diffs"][f])
    print("\nBY SCORE")
    for r in sorted(rows, key=lambda x: x["score_delta_pct"] if x["score_delta_pct"] is not None else 9999):
        sim = (r.get("sim") or {}).get("winrate_new")
        print(
            f"{r['id']:38} {r['name'][:18]:18} score={r['score_delta_pct']!s:>8} "
            f"dps={r['dps_delta_pct']!s:>8} sim={sim!s:>5} "
            f"blind={bool(r.get('blind_fields'))} fields={','.join(r['fields'])}"
        )
    print("\nKEY DIFFS")
    keys = {
        "abusgun", "cavalryarcher", "debolaswarrior", "definnishrider",
        "degascenya", "demercharquebusier", "denatholcanjavelineer",
        "denatlipkatatar", "denatmercqizilbash", "denatmercsharktoothbowman",
        "desalooninquisitor", "detank", "deunknownnateaglewarrior",
        "nathorsearcher", "spcxpchiefbravewolf", "spcxpchiefbullbear",
        "spcxpchieftwomoon", "uhlan", "xpbowrider", "xpcouprider",
        "xpeagleknight", "ypeggicecreamtruck", "ypmercarsonist",
        "ypspcishida", "ypurumi", "ypkensei", "denatsudanesedervish",
        "demercroyalhorseman", "natklamathrifleman",
    }
    for r in rows:
        if r["id"] not in keys:
            continue
        print(f"\n### {r['id']} | {r['name']} | score {r['score_delta_pct']} | sim {(r.get('sim') or {}).get('winrate_new')}")
        print("fields:", ", ".join(r["fields"]))
        for field, diff in r["diffs"].items():
            print(f"- {field}: {json.dumps(diff, ensure_ascii=False)}")
        for ref, vals in (r.get("vs_ref") or {}).items():
            print(f"  ref {ref}: old={vals.get('old')} new={vals.get('new')} delta={vals.get('delta')}")


if __name__ == "__main__":
    main()
