"""王中王锦标赛 CLI 适配器的完整路径测试。"""

from __future__ import annotations

import sys
import random
from pathlib import Path
from types import SimpleNamespace

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cli_adapters.aoe3_battle import AoE3BattleCLIAdapter  # noqa: E402
from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.battle_contract import Side
from plugins.games.aoe3_battle.lineup import generate_tournament_lineup
from plugins.games.aoe3_battle.tournament import Tournament


class _FakeBattle:
    def __init__(self, *, red_army, blue_army, **kwargs) -> None:
        self.red_alive = []
        self.blue_alive = []

    def run(self):
        winner = random.choice([Side.RED, Side.BLUE])
        self.red_alive = [object()] if winner == Side.RED else []
        self.blue_alive = [object()] if winner == Side.BLUE else []
        return SimpleNamespace(
            winner=winner,
            red_alive=self.red_alive,
            blue_alive=self.blue_alive,
        )


def test_cli_tournament_completes_all_twelve_matches(monkeypatch) -> None:
    repo = UnitRepo.get()
    result = generate_tournament_lineup(
        repo,
        "musketeer",
        age=3,
        rng=random.Random(42),
    )
    assert not isinstance(result, str)

    adapter = AoE3BattleCLIAdapter()
    adapter._tournament = Tournament.create(
        result,
        "火枪王",
        age=3,
        rng=random.Random(42),
    )
    adapter._tournament_bets = {"CLI玩家": 0}
    adapter._budget = 10000

    monkeypatch.setattr(
        "cli_adapters.aoe3_battle.BattleSimulator2D",
        _FakeBattle,
    )
    monkeypatch.setattr(
        "cli_adapters.aoe3_battle.prompt",
        lambda _msg="": "开战",
    )

    import asyncio

    asyncio.run(adapter._play_tournament())

    assert adapter._tournament.stage.value == "finished"
    assert len(adapter._tournament.final_ranks) == 8
    assert len(set(adapter._tournament.final_ranks)) == 8
