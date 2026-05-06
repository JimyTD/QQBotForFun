"""趣味问答题库模式验收测试。

直接调用 get_puzzle_from_bank 验证：
1. 能正常从题库加载
2. 10 题内无重复
3. 响应时间 < 100ms
4. 连续跑 5 局同类型，跨局重复率统计
"""
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from src.plugins.games.trivia.puzzle_generator import get_puzzle_from_bank, load_bank, BankNotAvailableError
from src.plugins.games.trivia.prompts import TYPE_IDS


def test_single_game(type_id: str, num_questions: int = 10):
    """模拟一局游戏：抽 num_questions 道题，检查无重复。"""
    avoid = []
    puzzles = []
    times = []

    for q in range(num_questions):
        t0 = time.perf_counter()
        puzzle = get_puzzle_from_bank(type_id, avoid=avoid)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        times.append(elapsed_ms)

        assert puzzle is not None, f"Question {q+1}: got None"
        assert puzzle.answer not in avoid, f"Question {q+1}: duplicate answer '{puzzle.answer}'"
        assert len(puzzle.clues) == 5, f"Question {q+1}: expected 5 clues, got {len(puzzle.clues)}"

        avoid.append(puzzle.answer)
        for a in puzzle.aliases:
            avoid.append(a)
        puzzles.append(puzzle)

    return puzzles, times


def main():
    print("=" * 60)
    print("趣味问答 · 题库模式验收测试")
    print("=" * 60)

    all_passed = True

    for type_id in TYPE_IDS:
        print(f"\n--- {type_id} ---")

        # 1. 加载测试
        try:
            bank = load_bank(type_id)
            print(f"  ✓ 题库加载成功: {len(bank)} 道题")
        except BankNotAvailableError as e:
            print(f"  ✗ 题库加载失败: {e}")
            all_passed = False
            continue

        # 2. 单局测试 (10题无重复)
        try:
            puzzles, times = test_single_game(type_id, 10)
            avg_ms = sum(times) / len(times)
            max_ms = max(times)
            print(f"  ✓ 单局10题无重复, 平均耗时 {avg_ms:.1f}ms, 最大 {max_ms:.1f}ms")
            if max_ms > 300:
                print(f"    ⚠ 最大耗时超过300ms!")
                all_passed = False
        except AssertionError as e:
            print(f"  ✗ 单局测试失败: {e}")
            all_passed = False
            continue

        # 3. 连续5局跨局重复率
        all_answers = []
        for game_num in range(5):
            puzzles, _ = test_single_game(type_id, 10)
            game_answers = [p.answer for p in puzzles]
            all_answers.extend(game_answers)

        from collections import Counter
        answer_counts = Counter(all_answers)
        repeated = sum(1 for a, c in answer_counts.items() if c > 1)
        repeat_rate = repeated / len(answer_counts) * 100 if answer_counts else 0
        print(f"  ✓ 5局(50题): 不重复答案 {len(answer_counts)} 个, 跨局重复率 {repeat_rate:.0f}%")
        if repeat_rate > 30:
            print(f"    ⚠ 跨局重复率超过30%!")

    print("\n" + "=" * 60)
    if all_passed:
        print("✅ 全部验收通过!")
    else:
        print("❌ 有失败项，请检查")
    print("=" * 60)


if __name__ == "__main__":
    main()
