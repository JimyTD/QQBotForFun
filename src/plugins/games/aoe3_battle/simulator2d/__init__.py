"""Independent 2D replacement engine for AoE3 battle simulations.

The 1D simulator remains the production implementation until this package is
explicitly selected by a caller.  The public result/event contract is shared
with the 1D engine so broadcast and economy code do not need to know which
engine produced a battle.
"""

from .config import Simulation2DConfig
from .engine import BattleSimulator2D

__all__ = ["BattleSimulator2D", "Simulation2DConfig"]
