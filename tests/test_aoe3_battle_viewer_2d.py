"""Replay fixtures and restart isolation for the development viewer."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.aoe3_battle_viewer_2d import (
    BattleRunner,
    FrameStore,
    SimulationSupersededError,
    _attach_visual_events,
    _build_custom_simulator,
    loadout_options,
)


def test_superseded_run_cannot_publish_an_error_over_new_frames():
    store = FrameStore(100)
    runner = BattleRunner(store)
    runner._generation = 2
    frame = {"tick": 0, "status": "running"}
    runner._publish(2, threading.Event(), frame)
    with patch(
        "scripts.aoe3_battle_viewer_2d.build_simulator_from_request",
        side_effect=ValueError("old request failed"),
    ):
        runner._run({}, 1, threading.Event())
    assert store.history() == [frame]
    with pytest.raises(SimulationSupersededError):
        runner._publish(1, threading.Event(), {"tick": 1})
    assert store.history() == [frame]


def test_viewer_labels_timeline_as_frame_axis():
    html = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "aoe3_battle_viewer_2d"
        / "index.html"
    ).read_text(encoding="utf-8")

    assert "帧轴" in html
    assert "绕行检验" not in html
    assert "自选阵容" in html


def test_loadout_options_lists_units_and_techs_for_civ():
    options = loadout_options(civ_id="British", age=3, unit_ids=["musketeer"])
    unit_ids = {unit["id"] for unit in options["units"]}
    assert "musketeer" in unit_ids
    assert options["civ_id"] == "British"
    assert all("summary" in tech and "id" in tech for tech in options["techs"])


def test_loadout_options_full_pool_reaches_mercenaries_and_natives():
    options = loadout_options(
        civ_id="DEMaltese",
        age=3,
        unit_ids=["dehoopthrower", "demercamazon"],
        full_pool=True,
    )
    units = {unit["id"]: unit for unit in options["units"]}
    assert options["full_pool"] is True
    assert len(units) > 200
    assert units["dehoopthrower"]["kind"] == ""
    assert units["demercamazon"]["kind"] == "佣兵"
    # The lineup includes a full-pool mercenary, so its techs must still resolve.
    assert any(tech["id"] == "DEHCFlameThrowers" for tech in options["techs"])


def test_custom_simulator_accepts_mixed_classes_in_full_pool():
    simulator = _build_custom_simulator(
        {
            "red": {
                "civ": "DEMaltese",
                "age": 3,
                "units": ["dehoopthrower"],
                "counts": [4],
                "techs": [],
                "full_pool": True,
            },
            "blue": {
                "civ": "DEHausa",
                "age": 3,
                "units": ["demercamazon"],
                "counts": [2],
                "techs": [],
                "full_pool": True,
            },
        },
        frame_callback=lambda _frame: None,
        seed=1,
    )
    assert simulator.red_army[0].unit.id == "dehoopthrower"
    assert simulator.blue_army[0].unit.id == "demercamazon"


def test_custom_simulator_builds_requested_lineup():
    frames: list[dict] = []
    simulator = _build_custom_simulator(
        {
            "red": {"civ": "British", "age": 3, "units": ["musketeer"], "counts": [5], "techs": []},
            "blue": {"civ": "French", "age": 3, "units": ["pikeman"], "counts": [5], "techs": []},
        },
        frame_callback=frames.append,
        seed=1,
    )
    assert simulator.red_army[0].unit.id == "musketeer"
    assert simulator.red_army[0].count == 5
    assert simulator.blue_army[0].unit.id == "pikeman"


def test_custom_simulator_balances_blue_to_red_budget():
    frames: list[dict] = []
    simulator = _build_custom_simulator(
        {
            "red": {
                "civ": "British",
                "age": 3,
                "units": ["musketeer", "hussar"],
                "counts": [20, 10],
                "techs": [],
            },
            "blue": {
                "civ": "French",
                "age": 3,
                "units": ["pikeman"],
                "counts": [3],
                "techs": [],
            },
            "balance_blue": True,
        },
        frame_callback=frames.append,
        seed=1,
    )
    from plugins.games.aoe3_battle.lineup import _unit_cost

    red_cost = sum(_unit_cost(slot.unit) * slot.count for slot in simulator.red_army)
    blue_cost = sum(_unit_cost(slot.unit) * slot.count for slot in simulator.blue_army)
    assert blue_cost <= red_cost
    assert simulator.blue_army[0].count >= 1


def test_visual_events_keep_real_events_alive_until_expiry():
    current = {
        "time": 0.1,
        "visual_events": [
            {
                "type": "attack",
                "attacker_id": 1,
                "target_id": 2,
                "time": 0.1,
                "expires_at": 0.35,
            }
        ]
    }
    event_buffer = []

    decorated = _attach_visual_events(current, None, event_buffer)
    with_history = _attach_visual_events(
        {"time": 0.2, "visual_events": []},
        None,
        event_buffer,
    )

    assert decorated["visual_events"][0]["type"] == "attack"
    assert with_history["visual_events"][0]["type"] == "attack"
    assert len(event_buffer) == 1
    assert (
        decorated["visual_events"][0]["event_id"]
        == with_history["visual_events"][0]["event_id"]
    )


def test_visual_events_deduplicate_repeated_identity_without_merging_distinct_events():
    event_buffer = []
    first = {
        "time": 0.1,
        "visual_events": [
            {
                "type": "attack",
                "attacker_id": 1,
                "target_id": 2,
                "time": 0.1,
                "expires_at": 0.35,
                "x": 15.0,
                "y": 12.0,
            },
            {
                "type": "attack",
                "attacker_id": 3,
                "target_id": 2,
                "time": 0.1,
                "expires_at": 0.35,
                "x": 15.0,
                "y": 12.0,
            },
        ],
    }
    repeated = {
        "time": 0.2,
        "visual_events": [dict(first["visual_events"][0])],
    }

    decorated = _attach_visual_events(first, None, event_buffer)
    with_history = _attach_visual_events(repeated, None, event_buffer)

    assert len(decorated["visual_events"]) == 2
    assert len(with_history["visual_events"]) == 2
    assert len(event_buffer) == 2


def test_visual_event_buffer_drops_expired_events():
    event_buffer = [
        {
            "type": "attack",
            "time": 0.0,
            "expires_at": 0.25,
        }
    ]
    current = {"time": 1.0, "units": []}

    decorated = _attach_visual_events(current, None, event_buffer)

    assert decorated == current
    assert event_buffer == []


def test_aoe_visual_event_continues_across_frames() -> None:
    event_buffer = []
    first = {
        "time": 0.1,
        "visual_events": [
            {
                "type": "aoe",
                "aoe_group_id": "1:1:2",
                "splash_target_id": 2,
                "x": 10.0,
                "y": 10.0,
                "radius": 4.0,
                "time": 0.1,
                "expires_at": 0.6,
            }
        ],
    }

    decorated = _attach_visual_events(first, None, event_buffer)
    later = _attach_visual_events(
        {"time": 0.5, "visual_events": []},
        None,
        event_buffer,
    )
    expired = _attach_visual_events(
        {"time": 0.7, "visual_events": []},
        None,
        event_buffer,
    )

    assert decorated["visual_events"][0]["aoe_group_id"] == "1:1:2"
    assert later["visual_events"][0]["splash_target_id"] == 2
    assert expired["visual_events"] == []
