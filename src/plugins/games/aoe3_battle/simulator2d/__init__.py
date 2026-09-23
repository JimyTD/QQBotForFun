"""Production 2D battle engine for AoE3 simulations.

The 1D simulator is retained only as a historical reference and explicit
development comparison.  The public result/event contract remains shared so
broadcast and economy code does not depend on engine internals.
"""

from .config import Simulation2DConfig
from .engine import BattleSimulator2D

__all__ = ["BattleSimulator2D", "Simulation2DConfig"]
