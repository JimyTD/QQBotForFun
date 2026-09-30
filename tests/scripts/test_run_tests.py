"""Test scope selection and command execution without launching another suite."""

from __future__ import annotations

import sys
import tomllib
from types import SimpleNamespace

import pytest

from scripts import run_tests


def test_fast_scope_is_explicit_and_paths_exist() -> None:
    paths = run_tests.select_paths("fast")
    assert paths == run_tests.FAST_PATHS
    assert len(paths) == len(set(paths))
    assert all((run_tests.ROOT / path).is_file() for path in paths)
    assert "tests/core/test_render.py" in paths
    assert "tests/games/aoe3_battle/test_plugin_registration.py" in paths
    assert "tests/games/aoe3_battle/test_cli_tournament.py" in paths
    assert "tests/games/aoe3_battle/test_civ_war_lineups.py" not in paths


@pytest.mark.parametrize("name", run_tests.MODULE_PATHS)
def test_module_scope_paths_exist(name: str) -> None:
    assert all(
        (run_tests.ROOT / path).exists() for path in run_tests.select_paths("module", [name])
    )


def test_module_scope_deduplicates_names_and_nested_directories() -> None:
    assert run_tests.select_paths("module", ["core", "core"]) == ("tests/core",)
    assert run_tests.select_paths("module", ["finance", "tools", "reminder"]) == (
        "tests/tools",
        "tests/test_reminder.py",
    )


@pytest.mark.parametrize(
    ("mode", "modules"),
    [("unknown", ()), ("module", ()), ("module", ("unknown",)), ("full", ("core",))],
)
def test_invalid_scope_is_not_silently_widened(mode: str, modules: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        run_tests.select_paths(mode, modules)


@pytest.mark.parametrize(("mode", "modules"), [("fast", ()), ("module", ("core",))])
def test_daily_commands_exclude_slow_tests(mode: str, modules: tuple[str, ...]) -> None:
    command = run_tests.build_command(mode, modules)
    assert command[:3] == [sys.executable, "-m", "pytest"]
    assert command[command.index("-m", 3) + 1] == "not slow"
    assert "--durations=10" in command
    assert "--strict-markers" in command


def test_full_scope_includes_all_tests_without_a_marker_filter() -> None:
    command = run_tests.build_command("full")
    assert command[-1] == "tests"
    assert "-m" not in command[3:]


def test_module_can_include_slow_tests_without_widening_scope() -> None:
    command = run_tests.build_command("module", ["aoe3_battle"], include_slow=True)
    assert command[-1] == "tests/games/aoe3_battle"
    assert "-m" not in command[3:]
    with pytest.raises(ValueError, match="module mode"):
        run_tests.build_command("fast", include_slow=True)


def test_dry_run_prints_scope_without_starting_pytest(monkeypatch, capsys) -> None:
    def unexpected_run(*_args, **_kwargs):
        pytest.fail("dry-run must not launch pytest")

    monkeypatch.setattr(run_tests.subprocess, "run", unexpected_run)
    assert run_tests.main(["full", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "Mode: full" in output
    assert "Slow tests: included" in output
    assert "Scope:\n  tests\n" in output


@pytest.mark.parametrize("exit_code", [0, 1, 2, 5])
def test_runner_preserves_pytest_exit_code_and_uses_repo_cwd(
    monkeypatch,
    tmp_path,
    capsys,
    exit_code: int,
) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=exit_code)

    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    assert run_tests.main(["module", "core", "--collect-only"]) == exit_code
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert "--collect-only" in command
    assert command[-1] == "tests/core"
    assert kwargs == {"cwd": run_tests.ROOT, "check": False}
    assert f"exit {exit_code}" in capsys.readouterr().out


def test_interrupt_returns_nonzero(monkeypatch) -> None:
    def interrupted(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(run_tests.subprocess, "run", interrupted)
    assert run_tests.main(["fast"]) == 130


@pytest.mark.parametrize("args", [[], ["module"], ["module", "typo"], ["fast", "--include-slow"]])
def test_cli_rejects_incomplete_or_invalid_selection(args: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        run_tests.main(args)
    assert exc.value.code == 2


def test_bare_pytest_keeps_full_default_and_registers_slow() -> None:
    with (run_tests.ROOT / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)["tool"]["pytest"]["ini_options"]
    assert config["testpaths"] == ["tests"]
    assert "-m" not in config["addopts"]
    assert any(marker.startswith("slow:") for marker in config["markers"])
