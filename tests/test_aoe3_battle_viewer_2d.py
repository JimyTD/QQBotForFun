"""Replay fixtures and restart isolation for the development viewer."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from plugins.games.aoe3_battle.simulator2d import Simulation2DConfig
from scripts.aoe3_battle_viewer_2d import (
    BattleRunner,
    FrameStore,
    SimulationSupersededError,
    _attach_visual_events,
)
from scripts.aoe3_pathing_scenarios import SCENARIOS, PathingDemo


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("seed", [1, 7, 42])
def test_diagnostic_paths_reach_the_far_side_without_overlap(scenario, seed):
    frames = []
    PathingDemo(scenario, seed, Simulation2DConfig(), frames.append).run()
    result = frames[-1]["diagnostic"]
    assert result["reached"] == result["total"]
    assert max(f["summary"]["max_overlap"] for f in frames) <= 0.002
    assert [f["tick"] for f in frames] == list(range(len(frames)))
    assert frames[-1]["status"] == "finished"
    for frame in frames:
        assert all("detour_path" in unit for unit in frame["units"])
        assert all(
            0.45 <= unit["x"] <= 23.55 and 0.45 <= unit["y"] <= 19.55 for unit in frame["units"]
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


def test_same_seed_reproduces_the_same_motion_frames():
    first, second = [], []
    PathingDemo("crowd", 42, Simulation2DConfig(), first.append).run()
    PathingDemo("crowd", 42, Simulation2DConfig(), second.append).run()
    assert first == second


def test_viewer_labels_timeline_as_frame_axis():
    html = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "aoe3_battle_viewer_2d"
        / "index.html"
    ).read_text(encoding="utf-8")

    assert "帧轴" in html


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
