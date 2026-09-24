# ruff: noqa: RUF001
"""Run the 2D battle engine and serve its live frames to a browser.

This is a development-only visualization entry point.  It does not modify the
production game, betting, economy, or broadcast paths.

Example:
    uv run python scripts/aoe3_battle_viewer_2d.py \
      --red musketeer:80 --blue pikeman:80 --seed 42
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for path in (str(_ROOT), str(_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from plugins.aoe3.models import Unit  # noqa: E402
from plugins.aoe3.repository import UnitRepo  # noqa: E402
from plugins.games.aoe3_battle.civ_war_civs import (  # noqa: E402
    CIV_PROFILES,
)
from plugins.games.aoe3_battle.civ_war_matchup import (  # noqa: E402
    generate_civ_war_lineup,
)
from plugins.games.aoe3_battle.simulator2d import (  # noqa: E402
    BattleSimulator2D,
    Simulation2DConfig,
)
from plugins.games.aoe3_battle.simulator2d.config import (  # noqa: E402
    CollisionMode,
)
from scripts.aoe3_pathing_scenarios import SCENARIOS, PathingDemo  # noqa: E402

VIEWER_DIR = _ROOT / "tools" / "aoe3_battle_viewer_2d"
_ICON_PNG_CACHE: dict[str, bytes] = {}


class SimulationSupersededError(RuntimeError):
    """A newer viewer request owns the frame store."""


class BattleRunner:
    """Own the current development simulation thread."""

    def __init__(self, store: FrameStore) -> None:
        self.store = store
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancelled = threading.Event()
        self._generation = 0
        self._visual_events: list[dict[str, Any]] = []

    def start(self, request: dict[str, Any]) -> None:
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._cancelled.set()
            self._cancelled = threading.Event()
            self._visual_events = []
            self.store.reset()
            thread = threading.Thread(
                target=self._run,
                args=(request, generation, self._cancelled),
                name=f"aoe3-2d-battle-{generation}",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def _run(
        self,
        request: dict[str, Any],
        generation: int,
        cancelled: threading.Event,
    ) -> None:
        try:
            simulator = build_simulator_from_request(
                request,
                frame_callback=lambda frame: self._publish(
                    generation,
                    cancelled,
                    frame,
                ),
            )
            simulator.run()
        except SimulationSupersededError:
            return
        except Exception as exc:
            logging.exception("2D viewer simulation failed")
            try:
                self._publish(
                    generation,
                    cancelled,
                    {
                        "engine": "2d",
                        "status": "error",
                        "tick": 0,
                        "time": 0.0,
                        "field": {"width": 1, "height": 1},
                        "winner": None,
                        "timeout": False,
                        "summary": {},
                        "sides": {},
                        "units": [],
                        "error": str(exc),
                    },
                )
            except SimulationSupersededError:
                return

    def _publish(
        self,
        generation: int,
        cancelled: threading.Event,
        frame: dict[str, Any],
    ) -> None:
        with self._lock:
            if generation != self._generation or cancelled.is_set():
                raise SimulationSupersededError("simulation superseded")
            frame = _attach_visual_events(
                frame,
                self.store.latest(),
                self._visual_events,
            )
            self.store.publish(frame)


def _attach_visual_events(
    frame: dict[str, Any],
    _previous_frame: dict[str, Any] | None,
    event_buffer: list[dict[str, Any]],
) -> dict[str, Any]:
    """Attach real-time visual events with explicit lifetimes and identities."""
    now = float(frame.get("time") or 0.0)
    active = {
        _visual_event_identity(event): event
        for event in event_buffer
        if event.get("expires_at") is None
        or now <= float(event["expires_at"])
    }
    for event in frame.get("visual_events") or []:
        if not isinstance(event, dict):
            continue
        copied = dict(event)
        event_id = _visual_event_identity(copied)
        copied.setdefault("event_id", event_id)
        active[event_id] = copied
    events = list(active.values())
    event_buffer[:] = events
    if events:
        frame = {**frame, "visual_events": events}
    return frame


def _visual_event_identity(event: dict[str, Any]) -> str:
    """Return a stable identity for a visual event across repeated frames."""
    position = (
        round(float(event.get("x") or 0.0), 3),
        round(float(event.get("y") or 0.0), 3),
    )
    return ":".join(
        str(part)
        for part in (
            event.get("type"),
            event.get("aoe_group_id"),
            event.get("splash_target_id"),
            round(float(event.get("time") or 0.0), 3),
            event.get("attacker_id"),
            event.get("target_id"),
            event.get("unit_id"),
            position[0],
            position[1],
            round(float(event.get("radius") or 0.0), 3),
        )
    )


class FrameStore:
    """Thread-safe latest-frame and frame-history store."""

    def __init__(self, history_limit: int) -> None:
        self._lock = threading.Lock()
        self._latest: dict[str, Any] | None = None
        self._frames: list[dict[str, Any]] = []
        self._history_limit = max(1, history_limit)
        self._done = threading.Event()

    def publish(self, frame: dict[str, Any]) -> None:
        with self._lock:
            self._latest = frame
            self._frames.append(frame)
            if len(self._frames) > self._history_limit:
                del self._frames[: len(self._frames) - self._history_limit]
            if frame.get("status") == "finished":
                self._done.set()

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            return self._latest

    def frame(self, index: int) -> dict[str, Any] | None:
        with self._lock:
            if 0 <= index < len(self._frames):
                return self._frames[index]
            return None

    def count(self) -> int:
        with self._lock:
            return len(self._frames)

    def index_of_tick(self, tick: int) -> int:
        with self._lock:
            for index, frame in enumerate(self._frames):
                if frame.get("tick") == tick:
                    return index
            return -1

    def history(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._frames)

    def wait(self, timeout: float) -> bool:
        return self._done.wait(timeout)

    def reset(self) -> None:
        with self._lock:
            self._latest = None
            self._frames.clear()
            self._done.clear()


class ViewerHandler(BaseHTTPRequestHandler):
    """Serve static assets and the latest simulation frame."""

    store: FrameStore
    runner: BattleRunner

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_bytes(
        self,
        data: bytes,
        *,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        if path == "/api/frame":
            frame = self.store.latest()
            if query:
                params = dict(item.split("=", 1) for item in query.split("&") if "=" in item)
                if "index" in params:
                    try:
                        frame = self.store.frame(int(params["index"]))
                    except ValueError:
                        frame = None
                elif "tick" in params:
                    try:
                        index = self.store.index_of_tick(int(params["tick"]))
                        frame = self.store.frame(index) if index >= 0 else None
                    except ValueError:
                        frame = None
            payload = json.dumps(frame, ensure_ascii=False).encode("utf-8")
            self._send_bytes(
                payload,
                content_type="application/json; charset=utf-8",
            )
            return
        if path == "/api/history":
            payload = json.dumps(
                self.store.history(),
                ensure_ascii=False,
            ).encode("utf-8")
            self._send_bytes(
                payload,
                content_type="application/json; charset=utf-8",
            )
            return
        if path == "/api/meta":
            payload = json.dumps(
                {"frames": self.store.count()},
                ensure_ascii=False,
            ).encode("utf-8")
            self._send_bytes(
                payload,
                content_type="application/json; charset=utf-8",
            )
            return
        if path == "/api/catalog":
            self._serve_catalog()
            return
        if path.startswith("/api/icon/"):
            self._serve_icon(path.removeprefix("/api/icon/"))
            return
        if path in ("/", "/index.html"):
            self._serve_file(VIEWER_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path in ("/styles.css", "/styles.css?v=20260923-6"):
            self._serve_file(VIEWER_DIR / "styles.css", "text/css; charset=utf-8")
            return
        if path in ("/app.js", "/app.js?v=20260923-6"):
            self._serve_file(
                VIEWER_DIR / "app.js",
                "application/javascript; charset=utf-8",
            )
            return
        self._send_bytes(
            b"not found",
            content_type="text/plain; charset=utf-8",
            status=HTTPStatus.NOT_FOUND,
        )

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != "/api/start":
            self._send_bytes(
                b"not found",
                content_type="text/plain; charset=utf-8",
                status=HTTPStatus.NOT_FOUND,
            )
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length) or b"{}")
            self.runner.start(request)
            payload = json.dumps(
                {"ok": True, "message": "started"},
                ensure_ascii=False,
            ).encode("utf-8")
            self._send_bytes(
                payload,
                content_type="application/json; charset=utf-8",
            )
        except Exception as exc:
            payload = json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
            ).encode("utf-8")
            self._send_bytes(
                payload,
                content_type="application/json; charset=utf-8",
                status=HTTPStatus.BAD_REQUEST,
            )

    def _serve_catalog(self) -> None:
        repo = UnitRepo.get()
        units = [
            {
                "id": unit.id,
                "name": unit.name or unit.name_en,
                "name_en": unit.name_en,
                "icon_url": f"/api/icon/{unit.id}",
            }
            for unit in repo.all_units
            if repo.get_icon_path(unit) is not None
        ]
        units.sort(key=lambda unit: unit["id"])
        civs = [
            {
                "id": profile.id,
                "name": profile.name,
                "name_en": profile.name_en,
            }
            for profile in CIV_PROFILES
        ]
        payload = json.dumps(
            {"units": units, "civs": civs},
            ensure_ascii=False,
        ).encode("utf-8")
        self._send_bytes(
            payload,
            content_type="application/json; charset=utf-8",
        )

    def _serve_icon(self, unit_id: str) -> None:
        cached = _ICON_PNG_CACHE.get(unit_id)
        if cached is not None:
            self._send_bytes(cached, content_type="image/png")
            return
        repo = UnitRepo.get()
        unit = repo.get_by_id(unit_id)
        path = repo.get_icon_path(unit) if unit is not None else None
        if path is None:
            self._send_bytes(
                b"icon not found",
                content_type="text/plain; charset=utf-8",
                status=HTTPStatus.NOT_FOUND,
            )
            return
        try:
            from plugins.games.aoe3_battle.replay.icons import (
                render_unit_icon_png,
            )

            payload = render_unit_icon_png(path)
            _ICON_PNG_CACHE[unit_id] = payload
            self._send_bytes(payload, content_type="image/png")
        except OSError:
            self._send_bytes(
                b"icon unreadable",
                content_type="text/plain; charset=utf-8",
                status=HTTPStatus.NOT_FOUND,
            )

    def _serve_file(self, path: Path, content_type: str) -> None:
        try:
            self._send_bytes(path.read_bytes(), content_type=content_type)
        except OSError:
            self._send_bytes(
                b"viewer asset missing",
                content_type="text/plain; charset=utf-8",
                status=HTTPStatus.NOT_FOUND,
            )


def _build_simulator(
    *,
    red: str,
    blue: str,
    seed: int | None,
    frame_callback,
    collision_mode: str = CollisionMode.RIGID.value,
) -> BattleSimulator2D:
    repo = UnitRepo.get()

    def parse(spec: str) -> tuple[Unit, int]:
        unit_id, separator, count_text = spec.rpartition(":")
        if not separator or not unit_id or not count_text:
            raise ValueError(f"invalid unit spec: {spec}")
        count = int(count_text)
        if count <= 0:
            raise ValueError(f"count must be positive: {spec}")
        unit = repo.get_by_id(unit_id) or next(
            iter(repo.search(unit_id, limit=1)),
            None,
        )
        if unit is None:
            raise ValueError(f"unit not found: {unit_id}")
        return unit, count

    red_unit, red_count = parse(red)
    blue_unit, blue_count = parse(blue)
    return BattleSimulator2D(
        red_unit,
        red_count,
        blue_unit,
        blue_count,
        seed=seed,
        session_id="viewer2d",
        frame_callback=frame_callback,
        config=Simulation2DConfig(collision_mode=CollisionMode(collision_mode)),
    )


def build_simulator_from_request(
    request: dict[str, Any],
    *,
    frame_callback,
) -> BattleSimulator2D | PathingDemo:
    mode = str(request.get("mode") or "units")
    collision_mode = str(request.get("collision_mode") or CollisionMode.RIGID.value)
    seed = int(request.get("seed", 42))
    if mode == "pathing":
        return PathingDemo(
            str(request.get("scenario") or "split"),
            seed,
            Simulation2DConfig(collision_mode=CollisionMode(collision_mode)),
            frame_callback,
        )
    if mode == "civ_war":
        repo = UnitRepo.get()
        match, _estimate = generate_civ_war_lineup(
            repo,
            str(request["red_civ"]),
            str(request["blue_civ"]),
            age=int(request.get("age", 3)),
            rng=__import__("random").Random(seed),
        )
        simulator = BattleSimulator2D(
            red_army=[(slot.unit, slot.count) for slot in match.red.slots],
            blue_army=[(slot.unit, slot.count) for slot in match.blue.slots],
            seed=seed,
            session_id=f"viewer2d_civwar_{seed}",
            match_label=(
                f"国战 · {match.red_civ_name}（{match.red_strategy}） "
                f"vs {match.blue_civ_name}（{match.blue_strategy}）"
            ),
            frame_callback=frame_callback,
            config=Simulation2DConfig(collision_mode=CollisionMode(collision_mode)),
        )
        return simulator

    return _build_simulator(
        red=str(request.get("red") or "musketeer:40"),
        blue=str(request.get("blue") or "pikeman:40"),
        seed=seed,
        frame_callback=frame_callback,
        collision_mode=collision_mode,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="AoE3 2D battle live viewer")
    parser.add_argument("--red", default="musketeer:80")
    parser.add_argument("--blue", default="pikeman:80")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--history", type=int, default=2400)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--scenario", choices=tuple(SCENARIOS))
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    store = FrameStore(history_limit=args.history)
    runner = BattleRunner(store)
    handler = type(
        "BoundViewerHandler",
        (ViewerHandler,),
        {"store": store, "runner": runner},
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    server_thread = threading.Thread(
        target=server.serve_forever,
        name="aoe3-2d-viewer",
        daemon=True,
    )
    server_thread.start()

    url = f"http://{args.host}:{args.port}/"
    print(f"2D viewer: {url}")
    print(f"red={args.red} blue={args.blue} seed={args.seed}")
    if not args.no_open:
        webbrowser.open(url)

    try:
        runner.start(
            {
                "mode": "pathing" if args.scenario else "units",
                "scenario": args.scenario,
                "red": args.red,
                "blue": args.blue,
                "seed": args.seed,
            }
        )
        print("simulation finished; viewer remains available. Ctrl+C to stop.")
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nviewer stopped")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
