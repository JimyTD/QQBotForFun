"""Tournament icons keep their original player color across rounds and ranks."""

from io import BytesIO

import pytest
from PIL import Image

from src.plugins.aoe3.icons import PLAYER_ICON_BACKGROUNDS
from src.plugins.games.aoe3_battle.bracket_renderer import (
    COLORS,
    BracketData,
    RankingData,
    _load_icon,
    render_bracket,
    render_ranking,
)


def test_verified_player_palette():
    assert PLAYER_ICON_BACKGROUNDS == (
        (45, 45, 245),
        (210, 40, 40),
        (224, 224, 30),
        (145, 15, 243),
        (42, 212, 58),
        (234, 135, 0),
        (28, 194, 219),
        (235, 97, 235),
    )
    assert len(set(PLAYER_ICON_BACKGROUNDS)) == 8


@pytest.fixture
def icon_path(tmp_path):
    path = tmp_path / "transparent.png"
    Image.new("RGBA", (128, 128), (0, 0, 0, 0)).save(path)
    return path


@pytest.mark.parametrize("stage", ["pre", "qf_done", "sf_done", "final"])
@pytest.mark.parametrize("champion", [2, 5])
def test_bracket_keeps_player_colors_after_advancement(icon_path, stage, champion):
    qf = {0: 1, 1: 2, 2: 5, 3: 6}
    sf = {0: 2, 1: 5}
    data = BracketData(
        title="Tournament",
        stage_label="",
        hint="",
        units=[(str(i), f"Unit {i + 1}") for i in range(8)],
        icon_paths=[icon_path] * 8,
        stage=stage,
        qf_results=qf if stage != "pre" else {},
        sf_results=sf if stage in ("sf_done", "final") else {},
        champion_idx=champion if stage == "final" else None,
        runner_up_idx=(2 if champion == 5 else 5) if stage == "final" else None,
    )
    original = icon_path.read_bytes()
    with Image.open(BytesIO(render_bracket(data))) as image:
        assert image.size == (940, 660)
        assert image.getchannel("A").getextrema() == (255, 255)

        def assert_color(x, y, idx, *, dim=False):
            color = PLAYER_ICON_BACKGROUNDS[idx]
            if dim:
                color = tuple(int(channel * 0.25) for channel in color)
            assert image.getpixel((x, y)) == (*color, 255)

        # Sample near each icon's corner, outside the elimination cross.
        for idx in range(8):
            y = 95 + (idx // 2) * 140 + (idx % 2) * 55
            dim = stage != "pre" and idx not in qf.values()
            assert_color(37, y - 20, idx, dim=dim)

        if stage != "pre":
            for slot, idx in qf.items():
                y = 122 + slot * 140
                dim = stage in ("sf_done", "final") and idx not in sf.values()
                assert_color(252, y - 17, idx, dim=dim)

        if stage in ("sf_done", "final"):
            for slot, idx in sf.items():
                y = 192 + slot * 280
                assert_color(462, y - 17, idx, dim=stage == "final" and idx != champion)

        if stage == "final":
            assert_color(677, 305, champion)
            for slot, idx in sf.items():
                color = COLORS["gold"] if idx == champion else COLORS["silver"]
                assert image.getpixel((650, 192 + slot * 280)) == (*color, 255)

    assert icon_path.read_bytes() == original


def test_ranking_uses_unit_index_not_rank(icon_path):
    order = [5, 2, 6, 1, 7, 3, 0, 4]
    data = RankingData(
        title="Ranking",
        ranks=[(idx, f"Unit {idx + 1}") for idx in order],
        icon_paths=[icon_path] * 8,
    )
    with Image.open(BytesIO(render_ranking(data))) as image:
        assert image.getchannel("A").getextrema() == (255, 255)
        for rank, idx in enumerate(order):
            assert image.getpixel((70, 57 + rank * 54)) == (*PLAYER_ICON_BACKGROUNDS[idx], 255)


@pytest.mark.parametrize("missing", [None, "missing.png"])
def test_missing_icon_stays_opaque_gray(tmp_path, missing):
    path = tmp_path / missing if missing else None
    icon = _load_icon(path, 38, PLAYER_ICON_BACKGROUNDS[0])
    assert icon.size == (38, 38)
    assert icon.getpixel((0, 0)) == (60, 60, 65, 255)
