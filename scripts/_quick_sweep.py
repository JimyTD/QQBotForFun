"""Quick sweep for remaining fast archetypes only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
# import from scan script
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ra2_preset_scan import batch_sweep_all, merge_presets, write_validated_file, BATCH_SWEEPS, sweep_pair_rival, OUT_PATH
import json

# 只扫快 archetype
QUICK = [
    x for x in BATCH_SWEEPS
    if x[0] in ("ggi", "ltnk", "sub")
]

found = []
for red_id, blue_id, rc, bc, prefix, tr, tb in QUICK:
    found.extend(
        sweep_pair_rival(
            red_id, blue_id, rc, bc,
            id_prefix=prefix, title_red=tr, title_blue=tb,
            seeds=5, pass_only=True,
        )
    )

existing = json.loads(OUT_PATH.read_text(encoding="utf-8")).get("presets", [])
merged = merge_presets(existing, found)
write_validated_file(merged, seeds=5)
print(f"quick sweep +{len(found)} PASS, total {len(merged)}")
