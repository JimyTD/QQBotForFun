"""AoE3 AOE audit browser data contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "scripts" / "aoe3_aoe_audit_browser.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("aoe3_aoe_audit_browser", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_snapshot_separates_units_slots_and_cap_sources():
    snapshot = _load_module().build_snapshot()
    summary = snapshot["summary"]

    assert summary["aoe_units"] == 162
    assert summary["aoe_slots"] == 168
    assert summary["explicit_aoe_slots"] == 158
    assert summary["fallback_aoe_slots"] == 10
    assert summary["cap_units"] == 176
    assert summary["cap_slots"] == 181
    assert summary["cap_without_aoe_slots"] == 23

    assert summary["explicit_aoe_slots"] + summary["fallback_aoe_slots"] == summary["aoe_slots"]
    assert len(snapshot["fallback_aoe_slots"]) == summary["fallback_aoe_slots"]
    assert len(snapshot["cap_without_aoe_slots"]) == summary["cap_without_aoe_slots"]


def test_fallback_cap_uses_merged_base_attack_times_two():
    snapshot = _load_module().build_snapshot()

    for slot in snapshot["fallback_aoe_slots"]:
        assert slot["cap"] == 0
        assert slot["effective_cap"] == slot["fallback_cap"]
        assert slot["fallback_cap"] == slot["attack"] * slot["projectiles"] * 2


def test_aoe_cap_closure_is_exact():
    snapshot = _load_module().build_snapshot()
    categories = snapshot["categories"]
    summary = snapshot["summary"]

    assert categories["aoe_explicit"] == summary["explicit_aoe_slots"]
    assert categories["aoe_fallback"] == summary["fallback_aoe_slots"]
    assert categories["cap_without_aoe"] == summary["cap_without_aoe_slots"]


def test_non_two_x_slots_only_include_explicit_aoe_caps():
    snapshot = _load_module().build_snapshot()
    summary = snapshot["summary"]
    rows = snapshot["non_two_x_slots"]

    assert len(rows) == 59
    assert summary["explicit_two_x_aoe_slots"] == 99
    assert summary["non_two_x_aoe_slots"] == 59
    assert summary["non_two_x_below"] + summary["non_two_x_above"] == 59

    for slot in rows:
        assert slot["aoe_radius"] > 0
        assert slot["cap"] > 0
        assert abs(slot["cap"] - slot["fallback_cap"]) >= 1e-9
        assert slot["cap_ratio"] == round(slot["cap"] / slot["fallback_cap"], 4)
        assert slot["cap_delta_from_2x"] == round(slot["cap"] - slot["fallback_cap"], 2)


def test_geometry_and_outer_falloff_metadata_are_exposed():
    snapshot = _load_module().build_snapshot()
    summary = snapshot["summary"]

    assert summary["geometric_aoe_slots"] == 83
    assert summary["directional_aoe_slots"] == 52
    assert summary["radial_aoe_slots"] == 31
    assert summary["outer_falloff_aoe_slots"] == 31
    assert len(snapshot["geometric_aoe_slots"]) == summary["geometric_aoe_slots"]

    falconet = next(
        slot
        for slot in snapshot["geometric_aoe_slots"]
        if slot["unit_id"] == "falconet" and slot["slot"] == "ranged"
    )
    assert falconet["area_sort_mode"] == "Directional"
    assert falconet["outer_damage_area_distance"] == 0.25
    assert falconet["outer_damage_area_factor"] == 0.2
