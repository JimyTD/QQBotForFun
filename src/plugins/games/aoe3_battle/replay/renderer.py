"""Pillow renderer and H.264 encoder for battle replays."""

from __future__ import annotations

import io
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .model import Replay, ReplayFrame
from .timeline import PlaybackPlan, build_playback_plan

logger = logging.getLogger("aoe3_battle.replay.renderer")


WIDTH = 960
HEIGHT = 540
FPS = 10
SCENE_TOP = 108
SCENE_BOTTOM = 472
HUD_BOTTOM = 98
BACKGROUND = (32, 39, 43)
SCENE = (45, 56, 59)
GRID = (58, 71, 75)
PANEL = (26, 32, 36)
RED = (239, 83, 80)
BLUE = (76, 141, 255)
TEXT = (232, 240, 242)
MUTED = (166, 180, 186)
WHITE = (247, 251, 252)
PROJECTILE_RANGED = (235, 225, 190)
PROJECTILE_MELEE = (216, 207, 186)
AOE_RING = (196, 196, 170)
DEATH_MARK = (226, 205, 160)
ICON_SIZE = 64
ICON_CACHE_LIMIT = 64
PROJECTILE_LIFETIME = 0.25
AOE_LIFETIME = 0.3
DEATH_MARK_LIFETIME = 0.6


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "C:/Windows/Fonts/simhei.ttf",
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    value = text
    while value and draw.textlength(value + "…", font=font) > max_width:
        value = value[:-1]
    return value + "…" if value else ""


class ReplayRenderer:
    """Render a public replay to H.264 MP4 bytes."""

    def __init__(self, *, width: int = WIDTH, height: int = HEIGHT, fps: int = FPS) -> None:
        self.width = width
        self.height = height
        self.fps = fps
        self._font_small = _font(14)
        self._font = _font(16)
        self._font_bold = _font(18, bold=True)
        self._font_title = _font(24, bold=True)
        self._icon_cache: dict[tuple[str, str], Image.Image] = {}
        self._faded_icon_cache: dict[tuple[int, int], Image.Image] = {}

    def render(self, replay: Replay) -> bytes:
        """Render and encode a replay, returning MP4 bytes."""
        return self.render_many([replay])

    def render_many(self, replays: list[Replay]) -> bytes:
        """Render one or more replays into a single H.264 video."""
        if not replays or any(not replay.frames for replay in replays):
            raise ValueError("replay contains no frames")

        imageio_ffmpeg = __import__("imageio_ffmpeg")
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        with tempfile.TemporaryDirectory(prefix="aoe3_replay_") as temp_dir:
            output = Path(temp_dir) / "battle.mp4"
            command = [
                ffmpeg,
                "-y",
                "-f",
                "rawvideo",
                "-vcodec",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-s",
                f"{self.width}x{self.height}",
                "-r",
                str(self.fps),
                "-i",
                "-",
                "-an",
                "-loglevel",
                "error",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-profile:v",
                "high",
                "-level",
                "4.1",
                "-crf",
                "22",
                "-maxrate",
                "1200k",
                "-bufsize",
                "2400k",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-g",
                str(self.fps * 2),
                str(output),
            ]
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            try:
                assert process.stdin is not None
                for image in self.iter_images_many(replays):
                    process.stdin.write(image.tobytes())
                process.stdin.close()
                stderr = process.stderr.read() if process.stderr else b""
                return_code = process.wait()
            except BaseException:
                process.kill()
                process.wait()
                raise
            if return_code != 0:
                raise RuntimeError(
                    "ffmpeg replay encoding failed: "
                    + stderr.decode("utf-8", errors="replace")[-2000:]
                )
            return output.read_bytes()

    def render_to_path(self, replay: Replay, path: Path) -> Path:
        """Render a replay directly to a file path."""
        path.write_bytes(self.render(replay))
        return path

    def iter_images(self, replay: Replay):
        """Yield rendered RGB frames for one replay."""
        yield from self.iter_images_many([replay])

    def iter_images_many(self, replays: list[Replay]):
        """Yield rendered RGB frames with adaptive source-time sampling."""
        intro_frames = self.fps * 2
        if len(replays) > 1:
            outro_frames = self.fps
        else:
            outro_frames = self.fps * 3
        for replay in replays:
            plan = build_playback_plan(replay)
            self._icon_cache.clear()
            self._faded_icon_cache.clear()
            for _ in range(intro_frames):
                yield self._render_intro(replay)
            for _output_time, source_time in plan.iter_output_samples(self.fps):
                yield self._render_frame(
                    replay,
                    self._frame_at(replay, source_time),
                    plan=plan,
                )
            for _ in range(outro_frames):
                yield self._render_outro(replay, plan=plan)

    @staticmethod
    def _frame_at(replay: Replay, source_time: float) -> ReplayFrame:
        """Select the nearest captured frame for one mapped source timestamp."""
        if not replay.frames:
            raise ValueError("replay contains no frames")
        low = 0
        high = len(replay.frames) - 1
        while low < high:
            middle = (low + high) // 2
            if replay.frames[middle].time < source_time:
                low = middle + 1
            else:
                high = middle
        if low == 0:
            return replay.frames[0]
        before = replay.frames[low - 1]
        after = replay.frames[low]
        if abs(before.time - source_time) <= abs(after.time - source_time):
            return before
        return after

    def _render_intro(self, replay: Replay) -> Image.Image:
        image = Image.new("RGB", (self.width, self.height), BACKGROUND)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, self.width, 8), fill=(225, 185, 75))
        title = replay.match_label or "帝国3斗蛐蛐 · 二维战场"
        draw.text((32, 38), _fit_text(draw, title, self._font_title, self.width - 64), font=self._font_title, fill=TEXT)
        draw.text((32, 82), "红方", font=self._font, fill=RED)
        draw.text((self.width // 2 + 24, 82), "蓝方", font=self._font, fill=BLUE)
        draw.text((32, 112), _fit_text(draw, replay.red_label, self._font_bold, 380), font=self._font_bold, fill=TEXT)
        draw.text(
            (self.width // 2 + 24, 112),
            _fit_text(draw, replay.blue_label, self._font_bold, 380),
            font=self._font_bold,
            fill=TEXT,
        )
        draw.text((32, 150), f"{replay.red_count} 单位", font=self._font, fill=MUTED)
        draw.text((self.width // 2 + 24, 150), f"{replay.blue_count} 单位", font=self._font, fill=MUTED)
        draw.text((32, self.height - 54), "战场态势回放 · 无调试数据", font=self._font, fill=MUTED)
        return image

    def _render_outro(
        self,
        replay: Replay,
        *,
        plan: PlaybackPlan | None = None,
    ) -> Image.Image:
        image = Image.new("RGB", (self.width, self.height), BACKGROUND)
        draw = ImageDraw.Draw(image)
        result = replay.result
        winner = replay.winner
        if winner == "red":
            result_text = "红方胜利"
            color = RED
        elif winner == "blue":
            result_text = "蓝方胜利"
            color = BLUE
        else:
            result_text = "平局"
            color = (225, 185, 75)
        draw.rectangle((0, 0, self.width, 8), fill=color)
        draw.text((32, 52), "战斗结束", font=self._font_bold, fill=MUTED)
        draw.text((32, 94), result_text, font=_font(42, bold=True), fill=color)
        duration = float(result.get("duration", replay.duration))
        draw.text((32, 164), f"战斗时长 {duration:.1f} 秒", font=self._font, fill=TEXT)
        draw.text((32, 202), f"剩余兵力  红 {result.get('red_alive', 0)}  /  蓝 {result.get('blue_alive', 0)}", font=self._font, fill=MUTED)
        if result.get("timeout"):
            draw.text((32, 240), "超时判定", font=self._font, fill=(225, 185, 75))
        return image

    def _render_frame(
        self,
        replay: Replay,
        frame: ReplayFrame,
        *,
        plan: PlaybackPlan | None = None,
    ) -> Image.Image:
        image = Image.new("RGB", (self.width, self.height), BACKGROUND)
        draw = ImageDraw.Draw(image)
        self._draw_hud(draw, replay, frame, plan=plan)
        self._draw_scene(image, draw, replay, frame)
        self._draw_subtitle(draw, replay, frame)
        return image

    def _draw_hud(
        self,
        draw: ImageDraw.ImageDraw,
        replay: Replay,
        frame: ReplayFrame,
        *,
        plan: PlaybackPlan | None = None,
    ) -> None:
        red = frame.sides.get("red", {})
        blue = frame.sides.get("blue", {})
        draw.rectangle((0, 0, self.width, HUD_BOTTOM), fill=PANEL)
        draw.text((20, 12), "红方", font=self._font_small, fill=RED)
        draw.text((self.width - 76, 12), "蓝方", font=self._font_small, fill=BLUE)
        draw.text(
            (20, 31),
            f"{red.get('alive', 0)}/{red.get('initial_count', replay.red_count)}",
            font=self._font_bold,
            fill=TEXT,
        )
        draw.text(
            (self.width - 120, 31),
            f"{blue.get('alive', 0)}/{blue.get('initial_count', replay.blue_count)}",
            font=self._font_bold,
            fill=TEXT,
        )
        self._draw_bar(draw, 92, 55, 290, float(red.get("hp_ratio", 0)), RED)
        self._draw_bar(draw, self.width - 382, 55, 290, float(blue.get("hp_ratio", 0)), BLUE)
        label = replay.match_label or "二维战场"
        draw.text(
            (self.width // 2, 10),
            _fit_text(draw, label, self._font, 360),
            anchor="ma",
            font=self._font,
            fill=WHITE,
        )
        draw.text(
            (self.width // 2, 34),
            f"{frame.time:05.1f}s",
            anchor="ma",
            font=self._font,
            fill=MUTED,
        )
        if plan is not None and plan.max_speed > 1.01:
            draw.text(
                (self.width // 2 + 58, 48),
                f"×{plan.speed_at(frame.time):.1f}",
                font=self._font_small,
                fill=(196, 205, 190),
            )
        red_composition = self._composition_text(red)
        blue_composition = self._composition_text(blue)
        if red_composition:
            draw.text((20, 76), red_composition, font=self._font_small, fill=MUTED)
        if blue_composition:
            draw.text(
                (self.width - 20, 76),
                blue_composition,
                anchor="ra",
                font=self._font_small,
                fill=MUTED,
            )

    @staticmethod
    def _composition_text(side: dict[str, Any]) -> str:
        parts = []
        for item in side.get("composition") or []:
            name = str(item.get("name") or item.get("unit_id") or "")
            count = int(item.get("count") or 0)
            if name and count > 0:
                parts.append(f"{name}×{count}")
        if len(parts) > 4:
            return " · ".join(parts[:4]) + f" · 等{len(parts) - 4}种"
        return " · ".join(parts)

    def _draw_bar(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        width: int,
        ratio: float,
        color: tuple[int, int, int],
    ) -> None:
        draw.rectangle((x, y, x + width, y + 10), fill=(7, 11, 9), outline=(60, 78, 66))
        fill_width = max(0, min(width, int(width * ratio)))
        if fill_width:
            draw.rectangle((x, y, x + fill_width, y + 10), fill=color)

    def _draw_scene(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        replay: Replay,
        frame: ReplayFrame,
    ) -> None:
        draw.rectangle(
            (20, SCENE_TOP, self.width - 20, SCENE_BOTTOM),
            fill=SCENE,
            outline=GRID,
        )
        field_width = max(1.0, float(frame.field.get("width", 1.0)))
        field_height = max(1.0, float(frame.field.get("height", 1.0)))
        pad = 22
        scale = min(
            (self.width - 40 - pad * 2) / field_width,
            (SCENE_BOTTOM - SCENE_TOP - pad * 2) / field_height,
        )
        offset_x = 20 + ((self.width - 40) - field_width * scale) / 2
        offset_y = SCENE_TOP + ((SCENE_BOTTOM - SCENE_TOP) - field_height * scale) / 2

        for index in range(1, 8):
            x = offset_x + field_width * scale * index / 8
            draw.line((x, offset_y, x, offset_y + field_height * scale), fill=(30, 48, 37))

        units = frame.units
        by_id = {int(unit.get("id", -1)): unit for unit in units}
        self._draw_projectiles(draw, replay, frame, by_id, scale, offset_x, offset_y)
        self._draw_aoe_rings(draw, replay, frame, scale, offset_x, offset_y)
        self._draw_death_marks(draw, replay, frame, scale, offset_x, offset_y)

        for unit in units:
            x = offset_x + float(unit.get("x", 0)) * scale
            y = offset_y + float(unit.get("y", 0)) * scale
            hp_ratio = float(unit.get("hp", 0)) / max(1.0, float(unit.get("max_hp", 1)))
            color = RED if unit.get("side") == "red" else BLUE
            opacity = 0.42 + max(0.0, min(1.0, hp_ratio)) * 0.58
            radius = max(
                4,
                min(
                    ICON_SIZE // 2,
                    round(float(unit.get("radius") or 0.45) * scale),
                ),
            )
            size = radius * 2
            icon = self._unit_icon(unit, color)
            if icon is None:
                draw_circle = tuple(int(channel * opacity) for channel in color)
                draw.ellipse(
                    (x - radius, y - radius, x + radius, y + radius),
                    fill=draw_circle,
                )
            else:
                faded = self._faded_icon(icon, opacity)
                icon_size = max(1, round(size))
                rendered_icon = faded.resize(
                    (icon_size, icon_size),
                    Image.Resampling.LANCZOS,
                )
                image.paste(
                    rendered_icon,
                    (round(x - icon_size / 2), round(y - icon_size / 2)),
                    rendered_icon,
                )
                draw.ellipse(
                    (x - size / 2, y - size / 2, x + size / 2, y + size / 2),
                    outline=color,
                    width=2,
                )
            if unit.get("stopped"):
                draw.ellipse(
                    (x - size / 2 + 2, y - size / 2 + 2, x + size / 2 - 2, y + size / 2 - 2),
                    outline=(196, 207, 202),
                )

    def _draw_projectiles(
        self,
        draw: ImageDraw.ImageDraw,
        replay: Replay,
        frame: ReplayFrame,
        by_id: dict[int, dict[str, Any]],
        scale: float,
        offset_x: float,
        offset_y: float,
    ) -> None:
        for event in replay.events:
            if event.event_type != "ATTACK" or event.data.get("is_splash"):
                continue
            age = frame.time - event.time
            if age < 0 or age > PROJECTILE_LIFETIME:
                continue
            attacker = by_id.get(int(event.data.get("attacker_id", -1)))
            target = by_id.get(int(event.data.get("target_id", -1)))
            if attacker is None or target is None:
                continue
            start_x = offset_x + float(attacker.get("x", 0)) * scale
            start_y = offset_y + float(attacker.get("y", 0)) * scale
            end_x = offset_x + float(target.get("x", 0)) * scale
            end_y = offset_y + float(target.get("y", 0)) * scale
            progress = min(1.0, age / PROJECTILE_LIFETIME)
            tip_x = start_x + (end_x - start_x) * progress
            tip_y = start_y + (end_y - start_y) * progress
            mode = str(event.data.get("mode") or "")
            color = PROJECTILE_MELEE if "melee" in mode else PROJECTILE_RANGED
            if mode == "melee":
                draw.arc(
                    (start_x - 12, start_y - 12, start_x + 12, start_y + 12),
                    start=0,
                    end=180,
                    fill=color,
                    width=2,
                )
            else:
                tail = 0.18
                tail_x = start_x + (end_x - start_x) * max(0.0, progress - tail)
                tail_y = start_y + (end_y - start_y) * max(0.0, progress - tail)
                draw.line((tail_x, tail_y, tip_x, tip_y), fill=color, width=2)
                draw.ellipse((tip_x - 2, tip_y - 2, tip_x + 2, tip_y + 2), fill=color)

    def _draw_aoe_rings(
        self,
        draw: ImageDraw.ImageDraw,
        replay: Replay,
        frame: ReplayFrame,
        scale: float,
        offset_x: float,
        offset_y: float,
    ) -> None:
        seen: set[tuple[float, float, float, float]] = set()
        for event in replay.events:
            if event.event_type != "AOE_SPLASH" or event.x is None or event.y is None:
                continue
            radius = float(event.data.get("radius") or event.data.get("aoe_radius") or 3.0)
            key = (
                round(event.time, 3),
                round(float(event.x), 3),
                round(float(event.y), 3),
                radius,
            )
            if key in seen:
                continue
            seen.add(key)
            age = frame.time - event.time
            if age < 0 or age > AOE_LIFETIME:
                continue
            progress = min(1.0, age / AOE_LIFETIME)
            current = radius * scale * (0.45 + 0.55 * progress)
            x = offset_x + event.x * scale
            y = offset_y + event.y * scale
            color = tuple(
                int(channel * (0.75 - 0.35 * progress))
                for channel in AOE_RING
            )
            draw.ellipse(
                (x - current, y - current, x + current, y + current),
                outline=color,
                width=2,
            )

    def _draw_death_marks(
        self,
        draw: ImageDraw.ImageDraw,
        replay: Replay,
        frame: ReplayFrame,
        scale: float,
        offset_x: float,
        offset_y: float,
    ) -> None:
        for event in replay.events:
            if event.event_type != "DEATH" or event.x is None or event.y is None:
                continue
            age = frame.time - event.time
            if age < 0 or age > DEATH_MARK_LIFETIME:
                continue
            alpha = 1.0 - age / DEATH_MARK_LIFETIME
            color = tuple(int(channel * alpha) for channel in DEATH_MARK)
            x = offset_x + event.x * scale
            y = offset_y + event.y * scale
            draw.line((x - 5, y - 5, x + 5, y + 5), fill=color, width=2)
            draw.line((x - 5, y + 5, x + 5, y - 5), fill=color, width=2)

    def _unit_icon(
        self,
        unit: dict[str, Any],
        color: tuple[int, int, int],
    ) -> Image.Image | None:
        unit_id = str(unit.get("unit_id") or "")
        side = str(unit.get("side") or "")
        if not unit_id:
            return None
        key = (unit_id, side)
        cached = self._icon_cache.get(key)
        if cached is not None:
            return cached
        if len(self._icon_cache) >= ICON_CACHE_LIMIT:
            return None
        try:
            from src.plugins.aoe3.repository import UnitRepo

            unit_model = UnitRepo.get().get_by_id(unit_id)
            path = UnitRepo.get().get_icon_path(unit_model) if unit_model else None
            if path is None:
                return None
            with Image.open(path) as source:
                icon = source.convert("RGBA")
            side_color = (36, 43, 47)
            canvas = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (*side_color, 255))
            fitted = icon.copy()
            fitted.thumbnail((ICON_SIZE - 8, ICON_SIZE - 8), Image.Resampling.LANCZOS)
            canvas.paste(
                fitted,
                ((ICON_SIZE - fitted.width) // 2, (ICON_SIZE - fitted.height) // 2),
                fitted,
            )
            mask = Image.new("L", (ICON_SIZE, ICON_SIZE), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, ICON_SIZE - 1, ICON_SIZE - 1), fill=255)
            canvas.putalpha(mask)
            self._icon_cache[key] = canvas
            return canvas
        except Exception:
            logger.debug("failed to cache replay icon unit=%s", unit_id, exc_info=True)
            return None

    def _faded_icon(self, icon: Image.Image, opacity: float) -> Image.Image:
        if opacity >= 0.995:
            return icon
        bucket = max(1, min(10, round(opacity * 10)))
        key = (id(icon), bucket)
        cached = self._faded_icon_cache.get(key)
        if cached is None:
            cached = icon.copy()
            alpha = cached.getchannel("A").point(
                lambda value: int(value * bucket / 10)
            )
            cached.putalpha(alpha)
            self._faded_icon_cache[key] = cached
        return cached

    def _draw_subtitle(
        self,
        draw: ImageDraw.ImageDraw,
        replay: Replay,
        frame: ReplayFrame,
    ) -> None:
        death = next(
            (
                event
                for event in reversed(replay.events)
                if event.event_type == "DEATH"
                and event.time <= frame.time
                and frame.time - event.time <= 2.2
            ),
            None,
        )
        if death is None:
            return
        victim = str(
            death.data.get("soldier_name")
            or death.data.get("victim_name")
            or "单位"
        )
        killer = str(
            death.data.get("killer_name")
            or death.data.get("attacker_name")
            or ""
        )
        text = f"{killer} 击杀 {victim}" if killer else f"{victim} 阵亡"
        box_width = min(self.width - 80, int(draw.textlength(text, font=self._font) + 32))
        x = (self.width - box_width) / 2
        draw.rectangle((x, 434, x + box_width, 466), fill=(6, 10, 8))
        draw.text(
            (x + 16, 441),
            _fit_text(draw, text, self._font, box_width - 32),
            font=self._font,
            fill=TEXT,
        )

    def _render_scene_png(self, replay: Replay) -> bytes:
        """Render a final-state PNG for diagnostics or send fallback."""
        frame = replay.frames[-1]
        image = self._render_frame(replay, frame)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
