"""Local read-only browser for AoE3 AOE and damage-cap coverage.

Usage:
    uv run python scripts/aoe3_aoe_audit_browser.py
    uv run python scripts/aoe3_aoe_audit_browser.py --port 8766
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "tools" / "aoe3_aoe_audit_browser"
ICON_DIR = ROOT / "resources" / "aoe3" / "icons"
UNITS_PATH = ROOT / "seeds" / "aoe3" / "units.json"

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover - legacy Windows console fallback
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def _positive(value: object) -> bool:
    try:
        return float(value or 0) > 0
    except (TypeError, ValueError):
        return False


def _number(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_snapshot() -> dict:
    units = json.loads(UNITS_PATH.read_text(encoding="utf-8"))
    slots: list[dict] = []
    unit_ids_with_aoe: set[str] = set()
    unit_ids_with_cap: set[str] = set()

    for unit in units:
        unit_slots: list[dict] = []
        for slot_name in ("ranged", "melee"):
            radius = _number(unit.get(f"aoe_radius_{slot_name}")) or 0
            cap = _number(unit.get(f"damage_cap_{slot_name}"))
            cap_value = cap or 0
            base_damage = _number(unit.get(f"attack_{slot_name}")) or 0
            projectiles = _number(unit.get(f"num_projectiles_{slot_name}")) or 1
            if radius <= 0 and cap_value <= 0:
                continue

            fallback_cap = base_damage * projectiles * 2
            effective_cap = cap_value if cap_value > 0 else fallback_cap
            slot = {
                "unit_id": unit.get("id", ""),
                "name": unit.get("name") or unit.get("name_en") or unit.get("id", ""),
                "name_en": unit.get("name_en") or "",
                "age": unit.get("age") or "",
                "slot": slot_name,
                "icon": (
                    f"/icons/{unit.get('id')}.png"
                    if (ICON_DIR / f"{unit.get('id')}.png").is_file()
                    else None
                ),
                "aoe_radius": radius,
                "cap": cap_value,
                "fallback_cap": fallback_cap,
                "effective_cap": effective_cap,
                "cap_source": "explicit" if cap_value > 0 else "fallback",
                "attack": base_damage,
                "projectiles": projectiles,
                "rof": _number(unit.get(f"rof_{slot_name}")) or 0,
                "damage_type": unit.get(f"damage_type_{slot_name}") or "",
                "area_sort_mode": unit.get(f"area_sort_mode_{slot_name}") or "",
                "outer_damage_area_distance": _number(
                    unit.get(f"outer_damage_area_distance_{slot_name}")
                ) or 0,
                "outer_damage_area_factor": _number(
                    unit.get(f"outer_damage_area_factor_{slot_name}")
                ) or 0,
                "basedamagecap": bool(unit.get(f"basedamagecap_{slot_name}", False)),
            }
            unit_slots.append(slot)
            slots.append(slot)

        if any(s["aoe_radius"] > 0 for s in unit_slots):
            unit_ids_with_aoe.add(unit["id"])
        if any(s["cap"] > 0 for s in unit_slots):
            unit_ids_with_cap.add(unit["id"])

    aoe_slots = [slot for slot in slots if slot["aoe_radius"] > 0]
    cap_slots = [slot for slot in slots if slot["cap"] > 0]
    explicit_aoe_slots = [slot for slot in aoe_slots if slot["cap"] > 0]
    fallback_aoe_slots = [slot for slot in aoe_slots if slot["cap"] <= 0]
    cap_without_aoe_slots = [slot for slot in cap_slots if slot["aoe_radius"] <= 0]
    explicit_two_x_slots = [
        slot for slot in explicit_aoe_slots if abs(slot["cap"] - slot["fallback_cap"]) < 1e-9
    ]
    non_two_x_slots = [
        slot for slot in explicit_aoe_slots if abs(slot["cap"] - slot["fallback_cap"]) >= 1e-9
    ]

    for slot in slots:
        slot["cap_ratio"] = (
            round(slot["cap"] / slot["fallback_cap"], 4) if slot["cap"] > 0 else None
        )
        slot["cap_delta_from_2x"] = (
            round(slot["cap"] - slot["fallback_cap"], 2) if slot["cap"] > 0 else None
        )

    non_two_x_slots.sort(
        key=lambda slot: (
            abs(slot["cap_delta_from_2x"]),
            slot["name"],
            slot["slot"],
        ),
        reverse=True,
    )
    geometric_aoe_slots = [
        slot
        for slot in aoe_slots
        if slot["area_sort_mode"]
        or slot["outer_damage_area_distance"] > 0
        or slot["outer_damage_area_factor"] > 0
    ]
    directional_slots = [
        slot
        for slot in aoe_slots
        if slot["area_sort_mode"].strip().lower() == "directional"
    ]
    radial_slots = [
        slot
        for slot in aoe_slots
        if slot["area_sort_mode"].strip().lower() == "radial"
    ]
    outer_falloff_slots = [
        slot
        for slot in aoe_slots
        if slot["outer_damage_area_distance"] > 0
        and slot["outer_damage_area_factor"] > 0
    ]

    aoe_unit_ids = sorted(unit_ids_with_aoe)
    covered_aoe_unit_ids = sorted(
        {
            slot["unit_id"]
            for slot in explicit_aoe_slots
        }
    )
    units_all_aoe_covered = sum(
        all(
            slot["cap"] > 0
            for slot in aoe_slots
            if slot["unit_id"] == unit_id
        )
        for unit_id in aoe_unit_ids
    )

    summary = {
        "total_units": len(units),
        "aoe_units": len(aoe_unit_ids),
        "aoe_slots": len(aoe_slots),
        "explicit_aoe_slots": len(explicit_aoe_slots),
        "fallback_aoe_slots": len(fallback_aoe_slots),
        "explicit_aoe_slot_pct": round(
            len(explicit_aoe_slots) / len(aoe_slots) * 100, 2
        )
        if aoe_slots
        else 0,
        "fallback_aoe_slot_pct": round(
            len(fallback_aoe_slots) / len(aoe_slots) * 100, 2
        )
        if aoe_slots
        else 0,
        "units_all_aoe_covered": units_all_aoe_covered,
        "units_all_aoe_covered_pct": round(
            units_all_aoe_covered / len(aoe_unit_ids) * 100, 2
        )
        if aoe_unit_ids
        else 0,
        "units_with_missing_aoe_cap": len(
            {slot["unit_id"] for slot in fallback_aoe_slots}
        ),
        "cap_units": len(unit_ids_with_cap),
        "cap_slots": len(cap_slots),
        "cap_without_aoe_slots": len(cap_without_aoe_slots),
        "covered_aoe_units": len(covered_aoe_unit_ids),
        "explicit_two_x_aoe_slots": len(explicit_two_x_slots),
        "non_two_x_aoe_slots": len(non_two_x_slots),
        "non_two_x_below": sum(slot["cap"] < slot["fallback_cap"] for slot in non_two_x_slots),
        "non_two_x_above": sum(slot["cap"] > slot["fallback_cap"] for slot in non_two_x_slots),
        "geometric_aoe_slots": len(geometric_aoe_slots),
        "directional_aoe_slots": len(directional_slots),
        "radial_aoe_slots": len(radial_slots),
        "outer_falloff_aoe_slots": len(outer_falloff_slots),
    }

    categories = {
        "aoe_explicit": len(explicit_aoe_slots),
        "aoe_fallback": len(fallback_aoe_slots),
        "cap_without_aoe": len(cap_without_aoe_slots),
        "no_aoe_no_cap": len(units) * 2
        - len(aoe_slots)
        - len(cap_without_aoe_slots),
    }

    return {
        "generated_from": str(UNITS_PATH.relative_to(ROOT)),
        "summary": summary,
        "categories": categories,
        "slots": slots,
        "aoe_slots": aoe_slots,
        "fallback_aoe_slots": fallback_aoe_slots,
        "cap_without_aoe_slots": cap_without_aoe_slots,
        "explicit_two_x_slots": explicit_two_x_slots,
        "non_two_x_slots": non_two_x_slots,
        "geometric_aoe_slots": geometric_aoe_slots,
        "directional_aoe_slots": directional_slots,
        "radial_aoe_slots": radial_slots,
        "outer_falloff_aoe_slots": outer_falloff_slots,
    }


class RequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:
        return

    def end_headers(self) -> None:
        if self.path.startswith(("/app.js", "/styles.css", "/index.html")):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/snapshot":
            try:
                self._json(build_snapshot())
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path.startswith("/icons/"):
            icon_name = Path(parsed.path).name
            if icon_name != Path(icon_name).name or not icon_name.endswith(".png"):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            icon_path = ICON_DIR / icon_name
            if icon_path.is_file():
                body = icon_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def _json(self, payload: dict, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local AoE3 AOE audit browser")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()

    if not STATIC_DIR.is_dir():
        raise SystemExit(f"Missing browser assets: {STATIC_DIR}")
    if not UNITS_PATH.is_file():
        raise SystemExit(f"Missing unit seed: {UNITS_PATH}")

    server = ThreadingHTTPServer((args.host, args.port), RequestHandler)
    print(f"AoE3 AOE Audit Browser: http://{args.host}:{args.port}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
