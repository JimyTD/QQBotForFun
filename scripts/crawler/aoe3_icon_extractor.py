"""AoE3 DE Icon Extractor — 从 ArtUnitsTextures*.bar 批量提取单位 icon 并转 PNG。

产出:
  - resources/aoe3/icons/{unit_id}.png
  - data/aoe3/icon_manifest.json（source: bar | bar_alt | bar_portrait | wiki_api | variant_copy | missing）

依赖: pip install Pillow lz4

用法:
  uv run python scripts/crawler/aoe3_icon_extractor.py
  uv run python scripts/crawler/aoe3_icon_extractor.py --no-wiki
  uv run python scripts/crawler/aoe3_icon_extractor.py --backfill-only
"""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from scripts.crawler.aoe3_bar_extractor import extract_file_data, read_bar_entries

try:
    from PIL import Image
except ImportError:
    print("ERROR: pip install Pillow")
    sys.exit(1)

import xml.etree.ElementTree as ET

# ============================================================
# Config
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GAME_ART_DIR = os.environ.get(
    "AOE3_GAME_ART_DIR",
    r"E:\SteamLibrary\steamapps\common\AoE3DE\Game\Art",
)
GAME_UI_DIR = os.environ.get(
    "AOE3_GAME_UI_DIR",
    r"E:\SteamLibrary\steamapps\common\AoE3DE\Game\UI",
)
EXTRACTED_DIR = Path(os.environ.get("AOE3_EXTRACTED_DIR", r"E:\aoe3_extracted"))
PROTOY_PATH = EXTRACTED_DIR / "protoy.xml"
OUTPUT_DIR = PROJECT_ROOT / "resources" / "aoe3" / "icons"
MANIFEST_PATH = PROJECT_ROOT / "data" / "aoe3" / "icon_manifest.json"
OVERRIDES_PATH = PROJECT_ROOT / "data" / "aoe3" / "icon_overrides.json"

WIKI_API = "https://ageofempires.fandom.com/api.php"
WIKI_USER_AGENT = "QQBotForFun/aoe3_icon_extractor (local data pipeline)"
ICON_SIZE = 128

ICON_BARS = [
    (GAME_ART_DIR, "ArtUnitsTextures1.bar"),
    (GAME_ART_DIR, "ArtUnitsTextures2.bar"),
    (GAME_ART_DIR, "ArtUnitsTextures3.bar"),
    (GAME_ART_DIR, "ArtUnitsTextures4.bar"),
    (GAME_ART_DIR, "ArtUnitsTextures5.bar"),
    (GAME_ART_DIR, "ArtUI.bar"),
    (GAME_ART_DIR, "Art.bar"),
    (GAME_ART_DIR, "ArtObjects.bar"),
    (GAME_ART_DIR, "ArtNuggets.bar"),
    (GAME_UI_DIR, "UIResources1.bar"),
]

_VARIANT_PREFIXES = (
    "deconsulate",
    "deguardian",
    "deicon",
    "de",
    "yp",
    "spc",
    "igc",
    "nat",
    "merc",
    "rev",
    "xp",
    "consulate",
)


@dataclass
class IconRecord:
    source: str = "missing"
    proto_icon: str = ""
    bar_entry: str = ""
    copy_from: str = ""
    note: str = ""


@dataclass
class ExtractOutcome:
    image: Image.Image | None = None
    record: IconRecord = field(default_factory=IconRecord)


# ============================================================
# DDT decoder
# ============================================================
def decode_ddt_to_png(ddt_data: bytes) -> Image.Image | None:
    if len(ddt_data) < 16 or ddt_data[:4] != b"RTS3":
        return None

    width = struct.unpack_from("<I", ddt_data, 8)[0]
    height = struct.unpack_from("<I", ddt_data, 12)[0]
    if width == 0 or height == 0:
        return None

    mip0_offset = struct.unpack_from("<I", ddt_data, 16)[0]
    mip0_size = struct.unpack_from("<I", ddt_data, 20)[0]
    if mip0_offset + mip0_size > len(ddt_data):
        return None

    pixel_data = ddt_data[mip0_offset : mip0_offset + mip0_size]
    expected_dxt1 = (width * height) // 2
    expected_dxt5 = width * height
    expected_bgra = width * height * 4

    try:
        if mip0_size == expected_dxt1:
            img = Image.frombytes("RGBA", (width, height), pixel_data, "bcn", (1,))
        elif mip0_size == expected_dxt5:
            img = Image.frombytes("RGBA", (width, height), pixel_data, "bcn", (3,))
        elif mip0_size == expected_bgra:
            img = Image.frombytes("RGBA", (width, height), pixel_data, "raw", "BGRA")
        else:
            try:
                img = Image.frombytes("RGBA", (width, height), pixel_data, "bcn", (1,))
            except Exception:
                img = Image.frombytes("RGBA", (width, height), pixel_data, "bcn", (3,))
        return img
    except Exception:
        return None


def _try_decode(raw_data: bytes) -> Image.Image | None:
    if raw_data[:8] == b"\x89PNG\r\n\x1a\n":
        return Image.open(BytesIO(raw_data))
    if raw_data[:4] == b"RTS3":
        return decode_ddt_to_png(raw_data)
    return None


def _normalize_png(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    if img.size != (ICON_SIZE, ICON_SIZE):
        img = img.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
    return img


def _save_png(img: Image.Image, out_file: Path) -> None:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    _normalize_png(img).save(out_file, format="PNG", optimize=True)


def _decode_entry(bar_path: str, entry: dict) -> Image.Image | None:
    raw_data = extract_file_data(bar_path, entry)
    return _try_decode(raw_data)


def _find_higher_res(
    current_entry: dict,
    current_img: Image.Image,
    bar_index: dict,
) -> tuple[Image.Image | None, str]:
    if min(current_img.size) >= ICON_SIZE:
        return current_img, ""

    orig_name = current_entry["name"].replace("\\", "/").lower()
    portrait_candidates = []
    if "_icon" in orig_name:
        portrait_candidates.append(re.sub(r"_icon(_\d+x\d+)?\.ddt$", "_portrait.ddt", orig_name))
        portrait_candidates.append(re.sub(r"_icon(_\d+x\d+)?\.ddt$", "_icon_portrait.ddt", orig_name))
    dir_part = orig_name.rsplit("/", 1)[0] if "/" in orig_name else ""
    stem_base = re.sub(r"(_icon|_portrait)(_\d+x\d+)?\.ddt$", "", orig_name.rsplit("/", 1)[-1])
    if dir_part:
        portrait_candidates.append(f"{dir_part}/{stem_base}_portrait.ddt")

    for cand in portrait_candidates:
        if cand not in bar_index:
            continue
        alt_bar_path, alt_entry = bar_index[cand]
        try:
            img = _decode_entry(alt_bar_path, alt_entry)
            if img and min(img.size) >= ICON_SIZE:
                return img, alt_entry["name"]
        except Exception:
            continue
    return current_img, ""


def _try_alternatives(original_entry: dict, bar_index: dict) -> tuple[Image.Image | None, str]:
    orig_name = original_entry["name"].replace("\\", "/").lower()
    orig_filename = orig_name.rsplit("/", 1)[-1]
    stem = re.sub(r"(_\d+x\d+)?\.(ddt|png)$", "", orig_filename)

    candidates: list[tuple[str, tuple[str, dict]]] = []
    for name_norm, val in bar_index.items():
        fn = name_norm.rsplit("/", 1)[-1]
        fn_stem = re.sub(r"(_\d+x\d+)?\.(ddt|png)$", "", fn)
        if fn_stem == stem:
            candidates.append((name_norm, val))

    stem_base = re.sub(r"_(icon|portrait)$", "", stem)
    if stem_base != stem:
        for name_norm, val in bar_index.items():
            fn = name_norm.rsplit("/", 1)[-1]
            fn_stem = re.sub(r"(_\d+x\d+)?\.(ddt|png)$", "", fn)
            if fn_stem == f"{stem_base}_portrait" and (name_norm, val) not in candidates:
                candidates.append((name_norm, val))

    def sort_key(item: tuple[str, tuple[str, dict]]) -> int:
        name = item[0]
        if "portrait" in name:
            return 0
        if "_64x64.png" in name:
            return 1
        if name.endswith(".ddt"):
            return 2
        return 3

    candidates.sort(key=sort_key)

    for _, (alt_bar_path, alt_entry) in candidates:
        if alt_entry is original_entry:
            continue
        try:
            img = _decode_entry(alt_bar_path, alt_entry)
            if img:
                return img, alt_entry["name"]
        except Exception:
            continue
    return None, ""


def _extract_from_bar(
    unit_id: str,
    bar_path: str,
    entry: dict,
    bar_index: dict,
    proto_icon: str,
) -> ExtractOutcome:
    record = IconRecord(source="bar", proto_icon=proto_icon, bar_entry=entry["name"])
    try:
        img = _decode_entry(bar_path, entry)
        if img is None:
            img, alt_name = _try_alternatives(entry, bar_index)
            if img:
                record.source = "bar_alt"
                record.bar_entry = alt_name
                record.note = f"primary undecodable: {entry['name']}"
            else:
                record.source = "missing"
                record.note = record.note or f"undecodable: {entry['name']}"
                return ExtractOutcome(None, record)

        portrait_name = ""
        if img is not None and min(img.size) < ICON_SIZE:
            img, portrait_name = _find_higher_res(entry, img, bar_index)
            if portrait_name:
                record.source = "bar_portrait"
                record.bar_entry = portrait_name

        if img is None:
            record.source = "missing"
            record.note = record.note or f"undecodable: {entry['name']}"
            return ExtractOutcome(None, record)
        return ExtractOutcome(img, record)
    except Exception as ex:
        record.source = "missing"
        record.note = str(ex)
        return ExtractOutcome(None, record)


def _load_overrides() -> dict[str, dict]:
    if not OVERRIDES_PATH.exists():
        return {}
    data = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    return data.get("overrides", {})


def _variant_copy_candidates(unit_id: str) -> list[str]:
    out: list[str] = []
    seen = set()

    def add(x: str) -> None:
        if x and x != unit_id and x not in seen:
            seen.add(x)
            out.append(x)

    for prefix in _VARIANT_PREFIXES:
        if unit_id.startswith(prefix) and len(unit_id) > len(prefix):
            add(unit_id[len(prefix):])

    stripped = re.sub(
        r"_(age\d+|imperial|veteran|guard|honored|exalted|disciplined|standard|elite)$",
        "",
        unit_id,
    )
    add(stripped)

    if unit_id.endswith("s") and len(unit_id) > 2:
        add(unit_id[:-1])

    return out


def _proto_icon_copy_candidates(proto_icon: str, output_dir: Path, unit_id: str) -> list[str]:
    if not proto_icon:
        return []

    filename = proto_icon.rsplit("/", 1)[-1]
    stem = re.sub(r"(_icon|_portrait|_64)(_\d+x\d+)?\.png$", "", filename, flags=re.I)
    stem = re.sub(r"(_\d+x\d+)?\.png$", "", stem, flags=re.I)
    tokens = [t for t in stem.split("_") if len(t) > 3]
    if not tokens:
        return []

    icon_ids = sorted(p.stem for p in output_dir.glob("*.png"))
    out: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        if candidate and candidate != unit_id and candidate not in seen:
            seen.add(candidate)
            out.append(candidate)

    for token in reversed(tokens):
        for icon_id in icon_ids:
            if icon_id == token or icon_id.endswith(token):
                add(icon_id)

    return out


def _copy_icon_from(unit_id: str, copy_from: str, output_dir: Path) -> bool:
    src = output_dir / f"{copy_from}.png"
    dst = output_dir / f"{unit_id}.png"
    if not src.exists():
        return False
    try:
        with src.open("rb") as f:
            if f.read(8) != b"\x89PNG\r\n\x1a\n":
                return False
    except OSError:
        return False
    shutil.copy2(src, dst)
    return True


def _wiki_title_candidates(protoy_name: str) -> list[str]:
    base = protoy_name.replace(" ", "_")
    return [
        f"{base}_(Age_of_Empires_III)",
        base,
        protoy_name,
    ]


def _fetch_wiki_icon(protoy_name: str) -> tuple[Image.Image | None, str]:
    for title in _wiki_title_candidates(protoy_name):
        params = urllib.parse.urlencode(
            {
                "action": "query",
                "format": "json",
                "prop": "pageimages",
                "pithumbsize": ICON_SIZE,
                "titles": title,
            }
        )
        url = f"{WIKI_API}?{params}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": WIKI_USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            pages = data.get("query", {}).get("pages", {})
            for page in pages.values():
                if page.get("missing"):
                    continue
                thumb = page.get("thumbnail", {}).get("source")
                if not thumb:
                    continue
                img_req = urllib.request.Request(thumb, headers={"User-Agent": WIKI_USER_AGENT})
                with urllib.request.urlopen(img_req, timeout=20) as img_resp:
                    img = Image.open(BytesIO(img_resp.read()))
                    return _normalize_png(img), title
        except Exception:
            continue
    return None, ""


def _build_icon_path_index(unit_icon_paths: dict[str, str]) -> dict[str, list[str]]:
    idx: dict[str, list[str]] = {}
    for uid, path in unit_icon_paths.items():
        idx.setdefault(path, []).append(uid)
    for ids in idx.values():
        ids.sort(key=len)
    return idx


def _write_manifest(manifest: dict[str, IconRecord]) -> None:
    stats: dict[str, int] = {}
    audit_wiki: list[str] = []
    audit_variant: list[str] = []
    entries: dict[str, dict] = {}

    for unit_id, rec in sorted(manifest.items()):
        stats[rec.source] = stats.get(rec.source, 0) + 1
        item = {
            "source": rec.source,
            "proto_icon": rec.proto_icon,
        }
        if rec.bar_entry:
            item["bar_entry"] = rec.bar_entry
        if rec.copy_from:
            item["copy_from"] = rec.copy_from
        if rec.note:
            item["note"] = rec.note
        entries[unit_id] = item
        if rec.source == "wiki_api":
            audit_wiki.append(unit_id)
        if rec.source == "variant_copy":
            audit_variant.append(unit_id)

    payload = {
        "_comment": "由 aoe3_icon_extractor.py 生成。优先审 audit.wiki_api 与 audit.variant_copy。",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
        "audit": {
            "wiki_api": audit_wiki,
            "variant_copy": audit_variant,
        },
        "entries": entries,
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _shared_icon_copy_from(unit_id: str, icon_path: str, icon_path_index: dict[str, list[str]], output_dir: Path) -> str:
    peers = icon_path_index.get(icon_path, [])
    for peer in peers:
        if peer == unit_id:
            continue
        p = output_dir / f"{peer}.png"
        if p.exists():
            return peer
    return ""


def _has_valid_png(output_dir: Path, unit_id: str) -> bool:
    p = output_dir / f"{unit_id}.png"
    if not p.exists():
        return False
    try:
        with p.open("rb") as f:
            return f.read(8) == b"\x89PNG\r\n\x1a\n"
    except OSError:
        return False


def _resolve_copy_from(
    unit_id: str,
    proto_icon: str,
    icon_path_index: dict[str, list[str]],
    output_dir: Path,
    overrides: dict[str, dict],
) -> tuple[str, str]:
    ov = overrides.get(unit_id, {})
    force_from = ov.get("force_copy_from", "")
    if force_from and _has_valid_png(output_dir, force_from):
        return force_from, "icon_overrides.json"

    copy_from = _shared_icon_copy_from(unit_id, proto_icon, icon_path_index, output_dir)
    if copy_from:
        return copy_from, ""

    for cand in _variant_copy_candidates(unit_id):
        if _has_valid_png(output_dir, cand):
            return cand, ""

    for cand in _proto_icon_copy_candidates(proto_icon, output_dir, unit_id):
        if _has_valid_png(output_dir, cand):
            return cand, f"proto_icon:{proto_icon.rsplit('/', 1)[-1]}"

    return "", ""


def _backfill_unit_icon(
    unit_id: str,
    proto_icon: str,
    protoy_name: str,
    icon_path_index: dict[str, list[str]],
    output_dir: Path,
    overrides: dict[str, dict],
    *,
    use_wiki: bool,
    existing: IconRecord | None = None,
) -> IconRecord:
    rec = existing or IconRecord(proto_icon=proto_icon, source="missing")
    rec.proto_icon = proto_icon or rec.proto_icon

    if _has_valid_png(output_dir, unit_id):
        if rec.source != "missing":
            return rec
        force_from = overrides.get(unit_id, {}).get("force_copy_from", "")
        if force_from:
            rec.source = "variant_copy"
            rec.copy_from = force_from
            rec.note = "icon_overrides.json"
        else:
            rec.source = "bar"
        return rec

    ov = overrides.get(unit_id, {})
    force_from = ov.get("force_copy_from", "")
    if force_from and _copy_icon_from(unit_id, force_from, output_dir):
        rec.source = "variant_copy"
        rec.copy_from = force_from
        rec.note = "icon_overrides.json"
        return rec

    if use_wiki and not ov.get("block_wiki"):
        img, wiki_title = _fetch_wiki_icon(protoy_name or unit_id)
        if img:
            _save_png(img, output_dir / f"{unit_id}.png")
            rec.source = "wiki_api"
            rec.note = wiki_title
            return rec

    copy_from, copy_note = _resolve_copy_from(
        unit_id, proto_icon, icon_path_index, output_dir, overrides
    )
    if copy_from and _copy_icon_from(unit_id, copy_from, output_dir):
        rec.source = "variant_copy"
        rec.copy_from = copy_from
        rec.note = copy_note or ""
        return rec

    rec.source = "missing"
    return rec


def _run_backfill_only(*, use_wiki: bool) -> None:
    if not MANIFEST_PATH.exists():
        print(f"ERROR: {MANIFEST_PATH} not found. Run full extractor first.")
        sys.exit(1)
    if not PROTOY_PATH.exists():
        print(f"ERROR: {PROTOY_PATH} not found.")
        sys.exit(1)

    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    overrides = _load_overrides()
    tree = ET.parse(PROTOY_PATH)
    root = tree.getroot()

    unit_proto_icon: dict[str, str] = {}
    unit_protoy_name: dict[str, str] = {}
    for u in root.findall("unit"):
        icon_path = u.findtext("icon", "").strip()
        if not icon_path:
            continue
        unit_id = u.get("name", "").lower()
        unit_protoy_name[unit_id] = u.get("name", "")
        unit_proto_icon[unit_id] = icon_path.replace("\\", "/").lower()

    icon_path_index = _build_icon_path_index(unit_proto_icon)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    records: dict[str, IconRecord] = {}
    for unit_id, item in payload.get("entries", {}).items():
        records[unit_id] = IconRecord(
            source=item.get("source", "missing"),
            proto_icon=item.get("proto_icon", unit_proto_icon.get(unit_id, "")),
            bar_entry=item.get("bar_entry", ""),
            copy_from=item.get("copy_from", ""),
            note=item.get("note", ""),
        )

    targets = [
        uid
        for uid, rec in records.items()
        if not _has_valid_png(OUTPUT_DIR, uid)
    ]
    print(f"Backfill targets: {len(targets)} (wiki={'on' if use_wiki else 'off'})")

    for i, unit_id in enumerate(targets, 1):
        proto_icon = unit_proto_icon.get(unit_id, records[unit_id].proto_icon)
        protoy_name = unit_protoy_name.get(unit_id, unit_id)
        prev = records[unit_id]
        rec = _backfill_unit_icon(
            unit_id,
            proto_icon,
            protoy_name,
            icon_path_index,
            OUTPUT_DIR,
            overrides,
            use_wiki=use_wiki,
            existing=IconRecord(
                proto_icon=prev.proto_icon or proto_icon,
                bar_entry=prev.bar_entry,
            ),
        )
        if prev.bar_entry and rec.source in ("missing", "variant_copy", "wiki_api"):
            rec.bar_entry = prev.bar_entry
        records[unit_id] = rec
        if i % 10 == 0 or i == len(targets):
            print(f"  [{i}/{len(targets)}] last={unit_id} -> {rec.source}")

    for unit_id, prev in list(records.items()):
        if not _has_valid_png(OUTPUT_DIR, unit_id):
            continue
        if prev.source != "missing":
            continue
        proto_icon = unit_proto_icon.get(unit_id, prev.proto_icon)
        protoy_name = unit_protoy_name.get(unit_id, unit_id)
        records[unit_id] = _backfill_unit_icon(
            unit_id,
            proto_icon,
            protoy_name,
            icon_path_index,
            OUTPUT_DIR,
            overrides,
            use_wiki=False,
            existing=prev,
        )

    _write_manifest(records)
    stats: dict[str, int] = {}
    for rec in records.values():
        stats[rec.source] = stats.get(rec.source, 0) + 1
    print("\n=== Backfill Done ===")
    print(f"  PNG files: {len(list(OUTPUT_DIR.glob('*.png')))}")
    print(f"  Stats: {stats}")
    print(f"  Audit wiki_api: {len([u for u, r in records.items() if r.source == 'wiki_api'])}")
    print(f"  Audit variant_copy: {len([u for u, r in records.items() if r.source == 'variant_copy'])}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Extract AoE3 unit icons")
    parser.add_argument("--no-wiki", action="store_true", help="Skip Fandom Wiki fallback")
    parser.add_argument(
        "--backfill-only",
        action="store_true",
        help="Only wiki/variant-copy missing icons using existing manifest + PNG dir",
    )
    args = parser.parse_args()

    if args.backfill_only:
        print("=== AoE3 Icon Backfill ===\n")
        _run_backfill_only(use_wiki=not args.no_wiki)
        return

    print("=== AoE3 DE Icon Extractor ===\n")

    if not PROTOY_PATH.exists():
        print(f"ERROR: {PROTOY_PATH} not found. Run aoe3_bar_extractor.py first.")
        sys.exit(1)

    overrides = _load_overrides()
    print(f"Loading {PROTOY_PATH.name}...")
    tree = ET.parse(PROTOY_PATH)
    root = tree.getroot()

    unit_icon_paths: dict[str, list[str]] = {}
    unit_proto_icon: dict[str, str] = {}
    unit_protoy_name: dict[str, str] = {}

    for u in root.findall("unit"):
        icon_path = u.findtext("icon", "").strip()
        if not icon_path:
            continue
        unit_id = u.get("name", "").lower()
        unit_protoy_name[unit_id] = u.get("name", "")
        raw = icon_path.replace("\\", "/").lower()
        unit_proto_icon[unit_id] = raw
        candidates = [raw]
        if raw.endswith(".png"):
            candidates.append(raw[:-4] + ".ddt")
        if raw.startswith("resources/art/"):
            stripped = raw[len("resources/art/") :]
            candidates.append(stripped)
            if stripped.endswith(".png"):
                candidates.append(stripped[:-4] + ".ddt")
        unit_icon_paths[unit_id] = candidates

    print(f"  {len(unit_icon_paths)} units with icon paths")

    print("\nScanning BAR files for icons...")
    bar_index: dict[str, tuple[str, dict]] = {}
    for bar_dir, bar_name in ICON_BARS:
        bar_path = os.path.join(bar_dir, bar_name)
        if not os.path.exists(bar_path):
            print(f"  WARNING: {bar_name} not found")
            continue
        for e in read_bar_entries(bar_path):
            name_norm = e["name"].replace("\\", "/").lower()
            if name_norm.endswith(".ddt") or name_norm.endswith(".png"):
                bar_index[name_norm] = (bar_path, e)
    print(f"  {len(bar_index)} DDT/PNG files indexed")

    stem_index: dict[str, tuple[str, dict]] = {}
    for name_norm, val in bar_index.items():
        filename = name_norm.rsplit("/", 1)[-1]
        stem = re.sub(r"_\d+x\d+", "", filename)
        stem = re.sub(r"_\d+\.(ddt|png)$", r".\1", stem)
        stem = re.sub(r"\.(ddt|png)$", "", stem)
        stem_index.setdefault(stem, val)

    match_map: dict[str, tuple[str, dict]] = {}
    unmatched: list[str] = []
    for unit_id, candidates in unit_icon_paths.items():
        found = False
        for cand in candidates:
            if cand in bar_index:
                match_map[unit_id] = bar_index[cand]
                found = True
                break
        if found:
            continue
        for cand in candidates:
            filename = cand.rsplit("/", 1)[-1]
            stem = re.sub(r"_\d+x\d+", "", filename)
            stem = re.sub(r"_\d+\.(ddt|png)$", r".\1", stem)
            stem = re.sub(r"\.(ddt|png)$", "", stem)
            if stem in stem_index:
                match_map[unit_id] = stem_index[stem]
                found = True
                break
        if not found:
            unmatched.append(unit_id)

    print(f"  BAR matched: {len(match_map)}/{len(unit_icon_paths)}")
    print(f"  BAR unmatched: {len(unmatched)}")

    icon_path_index = _build_icon_path_index(unit_proto_icon)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, IconRecord] = {}

    print(f"\nExtracting to {OUTPUT_DIR} ...")

    # Pass 1: BAR
    for unit_id, (bar_path, entry) in match_map.items():
        outcome = _extract_from_bar(
            unit_id, bar_path, entry, bar_index, unit_proto_icon.get(unit_id, "")
        )
        if outcome.image:
            _save_png(outcome.image, OUTPUT_DIR / f"{unit_id}.png")
        manifest[unit_id] = outcome.record

    # Pass 2: overrides + wiki + variant_copy for units still missing PNG
    for unit_id in unit_icon_paths:
        if _has_valid_png(OUTPUT_DIR, unit_id):
            continue

        proto_icon = unit_proto_icon.get(unit_id, "")
        prev = manifest.get(unit_id, IconRecord(proto_icon=proto_icon, source="missing"))
        rec = _backfill_unit_icon(
            unit_id,
            proto_icon,
            unit_protoy_name.get(unit_id, unit_id),
            icon_path_index,
            OUTPUT_DIR,
            overrides,
            use_wiki=not args.no_wiki,
            existing=prev,
        )
        manifest[unit_id] = rec

    # Unmatched BAR entries also get pass-2 above; ensure all in manifest
    for unit_id in unit_icon_paths:
        manifest.setdefault(
            unit_id,
            IconRecord(source="missing", proto_icon=unit_proto_icon.get(unit_id, "")),
        )

    _write_manifest(manifest)

    png_count = len(list(OUTPUT_DIR.glob("*.png")))
    stats = {}
    for rec in manifest.values():
        stats[rec.source] = stats.get(rec.source, 0) + 1

    print("\n=== Done ===")
    print(f"  PNG files: {png_count}")
    print(f"  Manifest: {MANIFEST_PATH}")
    print(f"  Stats: {stats}")
    print(f"  Audit wiki_api: {len([u for u, r in manifest.items() if r.source == 'wiki_api'])}")
    print(f"  Audit variant_copy: {len([u for u, r in manifest.items() if r.source == 'variant_copy'])}")


if __name__ == "__main__":
    main()
