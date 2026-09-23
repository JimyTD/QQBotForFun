"""Development-only motion fixtures running the production movement pipeline."""

from __future__ import annotations

import math
from dataclasses import replace

from plugins.aoe3.models import Unit
from plugins.games.aoe3_battle.simulator2d import BattleSimulator2D, Simulation2DConfig
from plugins.games.aoe3_battle.simulator2d.compat import ArmySlot
from plugins.games.aoe3_battle.simulator2d.model import Side, Soldier2D, Vec2

SCENARIOS = {
    "split": ("双侧绕墙", 2, 10.0, False),
    "crowd": ("密集队列", 6, 10.0, False),
    "border": ("贴边绕行", 2, 2.5, False),
    "mirror": ("左右镜像", 2, 10.0, True),
    "mixed": ("多排混合体积", 6, 10.0, False),
    "staggered": ("错列通道", 2, 10.0, False),
    "opening": ("阵亡后通道开放", 2, 10.0, False),
    "moving": ("移动单位堵口", 2, 10.0, False),
}


class _ScenarioSimulator(BattleSimulator2D):
    """Script only obstacle intent; all agents still use production physics."""

    obstacle_destinations: dict[int, Vec2]

    def _desired_velocity(self, soldier):
        destination = self.obstacle_destinations.get(soldier.id)
        if destination is None:
            return super()._desired_velocity(soldier)
        delta = destination - soldier.pos
        if delta.length() < 0.08:
            soldier.stopped = True
            return Vec2(0.0, 0.0), None
        return delta.clamped_length(
            soldier.unit.speed * self.config.tick_interval
        ) / self.config.tick_interval, None


class PathingDemo:
    def __init__(self, scenario: str, seed: int, config: Simulation2DConfig, frame_callback):
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown pathing scenario: {scenario}")
        self.scenario = scenario
        self.seed = seed
        self.config = config
        self.frame_callback = frame_callback

    def run(self) -> None:
        label, count, center, mirror = SCENARIOS[self.scenario]
        mover_unit = Unit(
            id="pathing_mover",
            name="移动单位",
            name_en="Mover",
            hp=100,
            speed=4.0,
            attack_melee=10,
            obstruction_radius_equiv=0.45,
        )
        wall_unit = replace(mover_unit, id="pathing_wall", name="静止障碍", speed=0.0)
        frames = 240
        reached = set()

        def publish(frame):
            frame["diagnostic"] = {
                "scenario": self.scenario,
                "reached": len(reached),
                "total": count,
            }
            self.frame_callback(frame)

        sim = _ScenarioSimulator(
            mover_unit,
            count,
            mover_unit,
            1,
            seed=self.seed,
            config=replace(self.config, max_known_unit_radius=0.9),
            frame_callback=publish,
            match_label=f"绕行检验 · {label}",
        )
        sim.obstacle_destinations = {}
        sim._init_soldiers()
        sim._field_width, sim._field_height = 24.0, 20.0
        movers, target = sim._soldiers[:count], sim._soldiers[count]
        target.x, target.y, target.stopped = 16.0, center, True
        for i, mover in enumerate(movers):
            mover.x = 2.0 - (i // 2) * 1.2
            mover.y = center + (-0.6 if i % 2 == 0 else 0.6)
        if count > 2:
            for mover in movers:
                mover.x += 2.4
        if self.scenario == "mixed":
            for i, mover in enumerate(movers):
                if i % 2:
                    mover.unit = replace(mover_unit, obstruction_radius_equiv=0.7)
                mover.x = 4.4 - (i // 2) * 1.6
                mover.y = center + (-0.8 if i % 2 == 0 else 0.8)
        wall = [
            Soldier2D(100 + i, Side.RED, wall_unit, 100, 100, 8.0, center + i - 2, stopped=True)
            for i in range(5)
        ]
        if self.scenario in ("mixed", "staggered"):
            wall = []
            for row in range(3):
                for i, r in enumerate((0.4, 0.8, 0.45, 0.9, 0.4)):
                    if self.scenario == "staggered" and i == (2 if row % 2 == 0 else 3):
                        continue
                    wall.append(
                        Soldier2D(
                            100 + row * 5 + i,
                            Side.RED,
                            replace(wall_unit, obstruction_radius_equiv=r),
                            100,
                            100,
                            8.0 + row * 1.8,
                            center + (i - 2) * 1.6 + (row % 2) * 0.4,
                            stopped=True,
                        )
                    )
        sim._soldiers.extend(wall)
        sim._soldier_map.update({s.id: s for s in wall})
        sim.red_count += len(wall)
        sim.red_army.append(ArmySlot(wall_unit, len(wall)))
        if mirror:
            for s in sim._soldiers:
                s.x = 24.0 - s.x
                s.facing = math.pi
        sim._spatial_hash.rebuild(sim._soldiers)
        threshold = min(s.x for s in wall) - 1.5 if mirror else max(s.x for s in wall) + 1.5
        if self.scenario == "moving":
            threshold = 12.0
        for tick in range(frames):
            sim._tick = tick
            if self.scenario == "opening" and tick == 25:
                wall[2].alive = False
            if self.scenario == "moving" and tick == 15:
                wall[2].unit = replace(wall_unit, speed=1.5)
                wall[2].stopped = False
                sim.obstacle_destinations[wall[2].id] = Vec2(10.5, center)
            for mover in movers:
                if mover.x < threshold if mirror else mover.x > threshold:
                    reached.add(mover.id)
                if mover.distance_to(target) <= mover.effective_melee_range:
                    mover.stopped = True
                    sim._clear_detour(mover)
            sim._process_movement()
            sim._emit_visual_frame(
                status="finished" if tick == frames - 1 else "running", winner=None, timeout=False
            )
