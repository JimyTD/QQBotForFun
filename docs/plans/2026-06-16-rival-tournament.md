# 王中王锦标赛 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现 8 兵种单败淘汰锦标赛模式（模式 F），含 Pillow 对阵图渲染、12 场比赛调度、夺冠押注、4 阶段出图。

**Architecture:** 锦标赛核心逻辑独立为 `tournament.py`（赛制状态机 + 比赛调度），对阵图渲染独立为 `bracket_renderer.py`（Pillow 绘图）。通过在 `game.py` 新增 `rival_tournament` 模式接入现有框架，复用 `rival_pick.py` 选主题流程。

**Tech Stack:** Python 3.12, Pillow (PIL), asyncio, NoneBot2, 现有 BattleSimulator

---

### Task 1: bracket_renderer.py — Pillow 对阵图渲染器

**Files:**
- Create: `src/plugins/games/aoe3_battle/bracket_renderer.py`

**说明：** 从 `scripts/test_bracket_stages.py` 原型移植为正式模块。关键改动：
- 不硬编码兵种列表，接收参数化的赛制数据
- 字体路径改为跨平台（Docker 环境用 `/usr/share/fonts/` + 自带 msyh 备选）
- 图标路径从 UnitRepo 获取
- 返回 `bytes`（PNG），不写文件

**接口设计：**

```python
@dataclass
class BracketData:
    """对阵图所需的全部数据。"""
    title: str                              # "王中王锦标赛 · 火枪王"
    subtitle: str                           # 当前阶段标题后缀（"抽签"/"八强战"等）
    hint: str                               # 右下角操作提示
    units: list[tuple[str, str]]            # 8 个 (unit_id, display_name)
    qf_results: dict[int, int] | None       # QF match_idx → winner unit_idx (0-7)
    sf_results: dict[int, int] | None       # SF match_idx → winner unit_idx
    champion_idx: int | None
    runner_up_idx: int | None

def render_bracket(data: BracketData) -> bytes:
    """渲染对阵图，返回 PNG bytes。"""

@dataclass 
class RankingData:
    title: str
    ranks: list[tuple[int, str]]   # [(unit_idx, display_name), ...] 1st to 8th

def render_ranking(data: RankingData) -> bytes:
    """渲染排名图，返回 PNG bytes。"""
```

**实现：** 直接移植 `test_bracket_stages.py` 的 `draw_bracket()` 和 `draw_ranking()` 函数，参数化所有硬编码数据。字体用 `_find_font()` 自动检测（Windows msyh → Linux 微软雅黑/思源黑体 → fallback DejaVu）。

---

### Task 2: tournament.py — 锦标赛核心逻辑

**Files:**
- Create: `src/plugins/games/aoe3_battle/tournament.py`

**说明：** 赛制状态机 + 比赛调度。纯逻辑层，不涉及消息发送。

**数据结构：**

```python
@dataclass
class TournamentMatch:
    """一场比赛。"""
    match_id: str          # "QF1"/"LR1"/"SF1"/"3RD"/"FINAL"
    label: str             # "八强第1场"
    unit_a_idx: int        # units[] 中的索引
    unit_b_idx: int
    winner_idx: int | None = None

class TournamentStage(Enum):
    DRAW = "draw"           # 抽签完成，等待开战
    QF = "qf"               # 八强战进行中
    QF_DONE = "qf_done"     # 八强战结束，等待开战
    LOSERS = "losers"       # 败者组排位进行中
    LOSERS_DONE = "losers_done"
    SF = "sf"               # 半决赛进行中
    SF_DONE = "sf_done"     # 半决赛结束
    FINAL = "final"         # 决赛进行中
    FINISHED = "finished"   # 锦标赛结束

@dataclass
class Tournament:
    units: list[tuple[str, str, Unit]]  # (unit_id, display_name, Unit object)
    theme_title: str
    stage: TournamentStage
    matches: dict[str, TournamentMatch]
    final_ranks: list[int]   # unit indices, 1st to 8th
    
    @classmethod
    def create(cls, units, theme_title) -> Tournament:
        """抽签配对，初始化 12 场比赛。"""
    
    def get_current_round_matches(self) -> list[TournamentMatch]:
        """获取当前轮次待打的比赛列表。"""
    
    def record_result(self, match_id: str, winner_idx: int):
        """记录一场比赛结果，自动推进状态。"""
    
    def advance_stage(self):
        """当前轮次全部打完后，推进到下一阶段。"""
    
    def get_bracket_data(self) -> BracketData:
        """生成当前状态的对阵图数据。"""
    
    def get_ranking_data(self) -> RankingData:
        """生成最终排名数据。"""
```

**赛制流程：**
1. `create()` → 随机配对 8 兵为 4 组，初始化 QF1-4
2. QF 结束 → 败者进入 LR1/LR2，胜者进入 SF
3. LR 结束 → 7/8名战、5/6名战
4. SF 结束 → 季军战、决赛
5. 决赛结束 → 生成 1-8 名排名

---

### Task 3: lineup.py — generate_tournament_lineup

**Files:**
- Modify: `src/plugins/games/aoe3_battle/lineup.py`

**说明：** 新增 `generate_tournament_lineup()` 函数，从主题池抽 8 个不同兵种。

```python
def generate_tournament_lineup(
    repo: UnitRepo,
    theme_id: str,
    *,
    budget: int = 10000,
    age: int = 3,
    rng: random.Random | None = None,
) -> list[tuple[str, str, "Unit"]] | str:
    """抽 8 个不同兵种用于锦标赛。返回 [(unit_id, display_name, Unit), ...] 或错误文本。"""
```

每场比赛的阵容（红蓝各 1 种兵 + LCM 平衡）在 `tournament.py` 中按需调用现有 `approx_lcm_budget()` 生成。

---

### Task 4: game.py — 新增 rival_tournament 模式

**Files:**
- Modify: `src/plugins/games/aoe3_battle/game.py`

**说明：** 
1. MODES 列表新增 `GameMode(id="rival_tournament", ...)`
2. `on_create` 新增 `elif mode_id == "rival_tournament":` 分支，调用 `generate_tournament_lineup`，创建 `Tournament` 实例
3. `on_start` 新增锦标赛分支：发送赛前对阵图 + 押注提示
4. `on_player_action` 新增锦标赛分支：
   - 押注阶段：序号 1-8 押注夺冠
   - 轮间阶段：`开战` 推进下一轮
5. 新增 `_run_tournament_round` 方法：逐场运行模拟 → 精简播报 → 更新对阵图
6. 新增 `_settle_tournament_bets` 方法：按夺冠结果结算

**状态机（ctx.state["phase"]）：**
```
tournament_betting → tournament_qf → tournament_waiting 
→ tournament_losers → tournament_waiting
→ tournament_sf → tournament_waiting  
→ tournament_final → ended
```

---

### Task 5: rival_pick.py — 支持锦标赛入口

**Files:**
- Modify: `src/plugins/games/aoe3_battle/rival_pick.py`

**说明：** 
1. `_PendingPick` 新增 `tournament: bool = False` 字段
2. 新增 `start_tournament_pick()` 函数：与 `start_theme_pick()` 类似，但 `tournament=True`
3. `_launch_with_theme` 根据 `tournament` 字段决定 config `mode` 为 `"rival_tournament"` 还是 `"rival"`

---

### Task 6: game_launcher 注册 + commands.py 押注指令

**Files:**
- Modify: `src/plugins/games/aoe3_battle/commands.py` — 新增序号 1-8 押注
- Modify: `src/plugins/games/aoe3_battle/__init__.py` — 更新描述

**说明：**
- `commands.py` 中锦标赛押注在 `on_player_action` 里处理（群友发 1-8 序号），与王中王选主题的数字兜底区分：**只有 mode == "rival_tournament" 且 phase == "tournament_betting" 时才拦截序号**，其他时候序号走选主题逻辑

---

### Task 7: broadcaster.py — 锦标赛精简播报

**Files:**
- Modify: `src/plugins/games/aoe3_battle/broadcaster.py`

**说明：** 新增 `MODE_TOURNAMENT` 常量和对应的精简播报模式：
- 不输出开战话术
- 不输出全灭播报 
- 不输出详细战斗动态
- 只输出：标题行 + 血条 + 各方存活/击杀/伤害统计 + 胜者晋级提示

---

### Task 8: 集成测试 + CLI adapter

**Files:**
- Create: `tests/games/aoe3_battle/test_tournament.py`
- Modify: `scripts/cli_adapters/` — 如果需要 CLI 适配（暂缓，CLI parity 可后续补）

**测试内容：**
- Tournament 状态机：创建 → 记录结果 → 阶段推进 → 排名生成
- BracketData 生成正确性
- 渲染器不报错（输出 PNG bytes 非空）
- 12 场比赛全部跑完后排名完整

---

### 执行顺序

1. **Task 1** bracket_renderer.py（独立，可先做）
2. **Task 2** tournament.py（依赖 Task 1 的 BracketData）
3. **Task 3** lineup.py 新增函数（小改动）
4. **Task 4** game.py 核心接入（最大改动，依赖 Task 2+3）
5. **Task 5** rival_pick.py 锦标赛入口
6. **Task 6** commands + __init__
7. **Task 7** broadcaster 精简播报
8. **Task 8** 测试
