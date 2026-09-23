"""Pillow renderer and H.264 encoder for battle replays."""

from __future__ import annotations

import io
import logging
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .model import Replay, ReplayFrame

logger = logging.getLogger("aoe3_battle.replay.renderer")


WIDTH = 960
HEIGHT = 540
FPS = 10
SCENE_TOP = 96
SCENE_BOTTOM = 472
HUD_TOP = 16
HUD_BOTTOM = 84
TIMELINE_TOP = 484
TIMELINE_BOTTOM = 526
BACKGROUND = (13, 20, 17)
SCENE = (20, 32, 25)
GRID = (45, 63, 51)
RED = (239, 83, 80)
BLUE = (76, 141, 255)
TEXT = (237, 246, 240)
MUTED = (146, 166, 152)
WHITE = (245, 250, 247)
BLACK = (5, 8, 6)


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
        """Yield rendered RGB frames for one or more replays."""
        intro_frames = self.fps * 2
        if len(replays) > 1:
            outro_frames = self.fps
        else:
            outro_frames = self.fps * 3
        for replay in replays:
            for _ in range(intro_frames):
                yield self._render_intro(replay)
            for frame in replay.frames:
                yield self._render_frame(replay, frame)
            for _ in range(outro_frames):
                yield self._render_outro(replay)

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

    def _render_outro(self, replay: Replay) -> Image.Image:
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

    def _render_frame(self, replay: Replay, frame: ReplayFrame) -> Image.Image:
        image = Image.new("RGB", (self.width, self.height), BACKGROUND)
        draw = ImageDraw.Draw(image)
        self._draw_hud(draw, replay, frame)
        self._draw_scene(draw, replay, frame)
        self._draw_subtitle(draw, replay, frame)
        self._draw_timeline(draw, replay, frame)
        return image

    def _draw_hud(self, draw: ImageDraw.ImageDraw, replay: Replay, frame: ReplayFrame) -> None:
        red = frame.sides.get("red", {})
        blue = frame.sides.get("blue", {})
        draw.rectangle((0, 0, self.width, HUD_BOTTOM), fill=(17, 26, 21))
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
        self._draw_bar(draw, 92, 38, 290, float(red.get("hp_ratio", 0)), RED)
        self._draw_bar(draw, self.width - 410, 38, 290, float(blue.get("hp_ratio", 0)), BLUE)
        label = replay.match_label or "二维战场"
        draw.text(
            (self.width // 2 - 180, 22),
            _fit_text(draw, label, self._font, 360),
            font=self._font,
            fill=WHITE,
        )
        draw.text((self.width // 2 - 40, 49), f"{frame.time:05.1f}s", font=self._font, fill=MUTED)

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
        draw: ImageDraw.ImageDraw,
        replay: Replay,
        frame: ReplayFrame,
    ) -> None:
        draw.rectangle((20, SCENE_TOP, self.width - 20, SCENE_BOTTOM), fill=SCENE, outline=GRID)
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
        for event in replay.events:
            if event.event_type != "DEATH" or event.x is None or event.y is None:
                continue
            if abs(event.time - frame.time) > 0.35:
                continue
            x = offset_x + event.x * scale
            y = offset_y + event.y * scale
            draw.line((x - 6, y - 6, x + 6, y + 6), fill=(255, 208, 96), width=2)
            draw.line((x - 6, y + 6, x + 6, y - 6), fill=(255, 208, 96), width=2)
        for unit in units:
            target_id = unit.get("target_id")
            if target_id is None:
                continue
            target = by_id.get(int(target_id))
            if target is None:
                continue
            color = RED if unit.get("side") == "red" else BLUE
            draw.line(
                (
                    offset_x + float(unit.get("x", 0)) * scale,
                    offset_y + float(unit.get("y", 0)) * scale,
                    offset_x + float(target.get("x", 0)) * scale,
                    offset_y + float(target.get("y", 0)) * scale,
                ),
                fill=tuple(channel // 3 for channel in color),
                width=1,
            )

        for unit in units:
            x = offset_x + float(unit.get("x", 0)) * scale
            y = offset_y + float(unit.get("y", 0)) * scale
            hp_ratio = float(unit.get("hp", 0)) / max(1.0, float(unit.get("max_hp", 1)))
            color = RED if unit.get("side") == "red" else BLUE
            radius = max(2.2, min(6.0, float(unit.get("radius", 0.45)) * scale))
            alpha = 0.38 + 0.62 * max(0.0, min(1.0, hp_ratio))
            unit_color = tuple(int(channel * alpha) for channel in color)
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=unit_color)
            if unit.get("stopped"):
                draw.ellipse(
                    (x - radius - 1, y - radius - 1, x + radius + 1, y + radius + 1),
                    outline=WHITE,
                )

    def _draw_timeline(
        self,
        draw: ImageDraw.ImageDraw,
        replay: Replay,
        frame: ReplayFrame,
    ) -> None:
        draw.rectangle((20, TIMELINE_TOP, self.width - 20, TIMELINE_BOTTOM), fill=(17, 26, 21))
        left = 36
        right = self.width - 36
        draw.line((left, 505, right, 505), fill=(70, 88, 76), width=2)
        duration = max(0.1, replay.duration)
        marker_x = left + (right - left) * min(1.0, frame.time / duration)
        draw.ellipse((marker_x - 4, 501, marker_x + 4, 509), fill=(225, 185, 75))
        first_attack = next(
            (event.time for event in replay.events if event.event_type == "ATTACK"),
            None,
        )
        first_death = next(
            (event.time for event in replay.events if event.event_type == "DEATH"),
            None,
        )
        for label, event_time, color in (
            ("接敌", first_attack, (225, 185, 75)),
            ("伤亡", first_death, (239, 83, 80)),
        ):
            if event_time is None:
                continue
            event_x = left + (right - left) * min(1.0, event_time / duration)
            draw.line((event_x, 499, event_x, 511), fill=color, width=2)
            draw.text(
                (event_x - 18, 488),
                label,
                font=self._font_small,
                fill=color,
            )
        draw.text((right - 100, 488), f"{frame.time:.1f}s", font=self._font_small, fill=MUTED)

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
