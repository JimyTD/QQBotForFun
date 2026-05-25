import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ra2_preset_scan import run_case, judge_rival, judge_spectacle, Side

data = json.loads(Path("data/ra2/lineup_presets.json").read_text(encoding="utf-8"))
print(f"验收 {len(data['presets'])} 条  seeds=6")
print("-" * 70)
passed = 0
for p in data["presets"]:
    red = [tuple(x) for x in p["red"]]
    blue = [tuple(x) for x in p["blue"]]
    st = run_case(red, blue, seeds=6)
    if p["kind"] == "spectacle":
        v, d = judge_spectacle(st, Side.RED if p["counter"] == "red" else Side.BLUE)
    else:
        v, d = judge_rival(st)
    passed += v == "PASS"
    print(f"{v:4} {p['id']:24} u={p['units']:2d}  {d}")
print(f"\n合计 PASS {passed}/{len(data['presets'])}")
