"""Run explicit fast, module, or full pytest scopes without changing pytest defaults."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FAST_PATHS = (
    "tests/scripts/test_run_tests.py",
    "tests/core/test_render.py",
    "tests/core/test_session_route.py",
    "tests/games/aoe3_battle/test_command_surface.py",
    "tests/games/aoe3_battle/test_plugin_registration.py",
    "tests/games/aoe3_battle/test_lineup_draft.py",
    "tests/games/aoe3_battle/test_lineup_room.py",
    "tests/games/aoe3_battle/test_civ_war_opening_renderer.py",
    "tests/games/aoe3_battle/test_cli_tournament.py",
    "tests/games/deep_sea_mission/test_cli_parity.py",
    "tests/games/silent_mark/test_m5_review.py",
    "tests/games/trivia/test_answer_matcher.py",
    "tests/games/turtle_soup/test_flow.py",
    "tests/tools/ask_ai/test_service.py",
    "tests/tools/finance/test_reporter.py",
)

MODULE_PATHS = {
    "core": ("tests/core",),
    "aoe3": ("tests/aoe3",),
    "aoe3_battle": ("tests/games/aoe3_battle",),
    "deep_sea_mission": ("tests/games/deep_sea_mission",),
    "silent_mark": ("tests/games/silent_mark",),
    "trivia": ("tests/games/trivia",),
    "turtle_soup": ("tests/games/turtle_soup",),
    "tools": ("tests/tools", "tests/test_reminder.py"),
    "ask_ai": ("tests/tools/ask_ai",),
    "checkin": ("tests/tools/checkin",),
    "finance": ("tests/tools/finance",),
    "food": ("tests/tools/food",),
    "reminder": ("tests/test_reminder.py",),
    "crawler": ("tests/crawler",),
    "scripts": (
        "tests/scripts",
        "tests/test_aoe3_battle_viewer_2d.py",
        "tests/test_aoe3_aoe_audit_browser.py",
    ),
}


def select_paths(mode: str, modules: Sequence[str] = ()) -> tuple[str, ...]:
    """Resolve an explicit scope; reject unknown names instead of widening it."""
    if mode == "module":
        if not modules:
            raise ValueError("module mode requires at least one module")
        unknown = set(modules) - MODULE_PATHS.keys()
        if unknown:
            raise ValueError(f"Unknown modules: {', '.join(sorted(unknown))}")
        paths = dict.fromkeys(path for name in modules for path in MODULE_PATHS[name])
        return tuple(
            path
            for path in paths
            if not any(Path(parent) in Path(path).parents for parent in paths)
        )
    if modules:
        raise ValueError("Module names can only be used in module mode")
    if mode == "fast":
        return FAST_PATHS
    if mode == "full":
        return ("tests",)
    raise ValueError(f"Unknown test mode: {mode}")


def build_command(
    mode: str,
    modules: Sequence[str] = (),
    *,
    include_slow: bool = False,
    collect_only: bool = False,
) -> list[str]:
    """Build a shell-free pytest invocation using the current Python runtime."""
    if include_slow and mode != "module":
        raise ValueError("--include-slow is only available in module mode")
    paths = select_paths(mode, modules)
    command = [sys.executable, "-m", "pytest", "--strict-markers", "--durations=10"]
    if mode != "full" and not include_slow:
        command.extend(["-m", "not slow"])
    if collect_only:
        command.append("--collect-only")
    return [*command, *paths]


def main(argv: Sequence[str] | None = None) -> int:
    """Print the selected scope and return pytest's exit status unchanged."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--dry-run", action="store_true", help="Print the command without running it"
    )
    common.add_argument(
        "--collect-only", action="store_true", help="Collect tests without running them"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    modes.add_parser("fast", parents=[common], help="Focused smoke, text, and CLI regressions")
    module = modes.add_parser(
        "module", parents=[common], help="Selected modules, excluding slow tests"
    )
    module.add_argument("modules", nargs="+", choices=sorted(MODULE_PATHS))
    module.add_argument(
        "--include-slow", action="store_true", help="Also run slow tests in these modules"
    )
    modes.add_parser("full", parents=[common], help="All tests, including slow tests")
    args = parser.parse_args(argv)

    modules = getattr(args, "modules", ())
    include_slow = getattr(args, "include_slow", False)
    paths = select_paths(args.mode, modules)
    command = build_command(
        args.mode,
        modules,
        include_slow=include_slow,
        collect_only=args.collect_only,
    )
    print(f"Mode: {args.mode}", flush=True)
    print(
        f"Slow tests: {'included' if args.mode == 'full' or include_slow else 'excluded'}",
        flush=True,
    )
    print("Scope:\n" + "\n".join(f"  {path}" for path in paths), flush=True)
    display = subprocess.list2cmdline(command) if sys.platform == "win32" else shlex.join(command)
    print(f"Command: {display}", flush=True)
    if args.dry_run:
        return 0

    started = time.perf_counter()
    try:
        result = subprocess.run(command, cwd=ROOT, check=False)
    except KeyboardInterrupt:
        return 130
    print(
        f"Finished in {time.perf_counter() - started:.1f}s (exit {result.returncode})", flush=True
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
