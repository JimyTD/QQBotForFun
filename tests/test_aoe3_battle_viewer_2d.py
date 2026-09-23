"""Replay fixtures and restart isolation for the development viewer."""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from plugins.games.aoe3_battle.simulator2d import Simulation2DConfig
from scripts.aoe3_battle_viewer_2d import BattleRunner, FrameStore, SimulationSupersededError
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
