# AoE3 Battle 1D - Deprecated Creative Reference

This directory is an archive, not a production module.

The old one-dimensional battle lineage lives here so future work can reuse its
ideas without mistaking it for a current engine or an available runtime switch.

## Status

- Removed from the AoE3 battle production path.
- No production code may import anything from this directory.
- The current and only battle implementation is `src/plugins/games/aoe3_battle/simulator2d/`.
- The shared result/event contract is `src/plugins/games/aoe3_battle/battle_contract.py`.
- Do not restore the old `simulator.py` as an alternate engine.

## Contents

- `simulator.py`: the historical one-dimensional tick engine.
- `test_damage_calc.py`: tests that exercised that engine's internals.
- `battle-state-machine.md`: the old one-dimensional state-machine notes.
- `battle-design-1d.md`: extracted historical notes for the one-dimensional model.

These files are retained only as a creative source and implementation history.
New games or mechanics should define their own clean contracts and algorithms.
