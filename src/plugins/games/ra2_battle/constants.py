"""与 OpenRA 对齐的常量（见 FieldLoader / Locomotor / Mobile）。"""

from __future__ import annotations

CELL_WDIST = 1024
TICK_SECONDS = 0.04  # 25 tick/s，与 OpenRA 默认一致
MAX_TICKS = 15000  # 10 分钟上限

# 默认斗蛐蛐舞台（格）
DEFAULT_ARENA_W = 32
DEFAULT_ARENA_H = 16

# 步兵同格上限（SharesCell 时）
INFANTRY_PER_CELL = 3

# 航母旁补给（Rearmable，tick 数近似 OpenRA 停靠补给）
REARM_TICKS = 50

# OpenRA 默认 BurstDelays（yaml 未写且 Burst>1 时）
DEFAULT_BURST_DELAY = 5
