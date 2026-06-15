"""Unit tests for the Milestone 6 reel composition (pure logic, no ffmpeg/DB).

Covers:
* event-count aggregation + intro stats lines (``overlays``),
* Pillow graphics produce PNGs at the requested dimensions (``overlays``),
* music selection against a stubbed R2 listing (``audio``),
* ffmpeg argument/filter-graph construction (``compose``).
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.cv.highlights import audio as audio_mod
from app.cv.highlights import compose as compose_mod
from app.cv.highlights import overlays as overlays_mod
from app.cv.highlights.audio import MusicUnavailableError
from app.cv.highlights.events import (
    EVENT_LAYUP_DUNK,
    EVENT_POSSESSION,
    EVENT_SHOT_ATTEMPT,
    EVENT_SHOT_BLOCK,
)


def _clip(event_type: str, made: bool | None = None) -> SimpleNamespace:
    return SimpleNamespace(event_type=event_type, made=made)


# --------------------------------------------------------------------------- #
# Stats aggregation
# --------------------------------------------------------------------------- #
def test_compute_stats_counts_events_and_made() -> None:
    clips = [
        _clip(EVENT_LAYUP_DUNK, made=True),
        _clip(EVENT_SHOT_ATTEMPT, made=False),
        _clip(EVENT_SHOT_ATTEMPT, made=True),
        _clip(EVENT_SHOT_BLOCK),
        _clip(EVENT_POSSESSION),
    ]
    stats = overlays_mod.compute_stats(clips)

    assert stats.total_clips == 5
    assert stats.made_shots == 2
    assert stats.counts[EVENT_SHOT_ATTEMPT] == 2
    assert stats.counts[EVENT_LAYUP_DUNK] == 1
    assert stats.counts[EVENT_SHOT_BLOCK] == 1
    assert stats.counts[EVENT_POSSESSION] == 1


def test_stats_summary_lines_order_and_filtering() -> None:
    stats = overlays_mod.ReelStats(
        total_clips=3,
        made_shots=1,
        counts={EVENT_LAYUP_DUNK: 2, EVENT_SHOT_ATTEMPT: 1},
    )
    lines = stats.summary_lines()

    assert lines[0] == "3 HIGHLIGHTS"
    # Layup/dunk is ordered before shots; zero-count events are omitted.
    assert "Layup / Dunk" in lines[1]
    assert any("Made" in line for line in lines)
    assert all("Possession" not in line for line in lines)


def test_humanize_event_falls_back_for_unknown() -> None:
    assert overlays_mod.humanize_event(EVENT_SHOT_BLOCK) == "Block"
    assert overlays_mod.humanize_event("steal_event") == "Steal Event"


# --------------------------------------------------------------------------- #
# Pillow graphics
# --------------------------------------------------------------------------- #
def test_render_intro_card_writes_png_at_size(tmp_path: Path) -> None:
    from PIL import Image

    output = tmp_path / "intro.png"
    overlays_mod.render_intro_card(
        output,
        width=1280,
        height=720,
        title="Colton Large  #14",
        subtitle="HoopStar · 2026",
        stats_lines=["12 HIGHLIGHTS", "5  Layup / Dunk"],
    )
    assert output.exists()
    with Image.open(output) as img:
        assert img.size == (1280, 720)


def test_render_lower_third_is_transparent_full_frame(tmp_path: Path) -> None:
    from PIL import Image

    output = tmp_path / "lower.png"
    overlays_mod.render_lower_third(
        output,
        width=1280,
        height=720,
        primary="Colton Large  #14",
        secondary="Layup / Dunk",
    )
    with Image.open(output) as img:
        assert img.size == (1280, 720)
        assert img.mode == "RGBA"
        # Top-left pixel is fully transparent (only the bottom band is drawn).
        assert img.getpixel((0, 0))[3] == 0


def test_render_watermark_applies_opacity(tmp_path: Path) -> None:
    from PIL import Image

    logo = tmp_path / "logo.png"
    Image.new("RGBA", (200, 80), (255, 255, 255, 255)).save(logo)

    output = overlays_mod.render_watermark(
        tmp_path / "wm.png",
        logo_path=logo,
        target_width=100,
        opacity=0.5,
    )
    assert output is not None
    with Image.open(output) as img:
        assert img.width == 100
        # Alpha was scaled down from 255 toward ~127.
        assert img.getchannel("A").getextrema()[1] <= 130


def test_render_watermark_missing_logo_returns_none(tmp_path: Path) -> None:
    result = overlays_mod.render_watermark(
        tmp_path / "wm.png",
        logo_path=tmp_path / "does_not_exist.png",
        target_width=100,
        opacity=0.5,
    )
    assert result is None


# --------------------------------------------------------------------------- #
# Music selection
# --------------------------------------------------------------------------- #
def test_select_music_key_defaults_to_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        audio_mod,
        "list_music_keys",
        lambda: ["assets/music/a.mp3", "assets/music/b.mp3"],
    )
    assert audio_mod.select_music_key() == "assets/music/a.mp3"


def test_select_music_key_matches_basename(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        audio_mod,
        "list_music_keys",
        lambda: ["assets/music/a.mp3", "assets/music/Anthem.mp3"],
    )
    assert audio_mod.select_music_key("anthem.mp3") == "assets/music/Anthem.mp3"


def test_select_music_key_unknown_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio_mod, "list_music_keys", lambda: ["assets/music/a.mp3"])
    with pytest.raises(MusicUnavailableError):
        audio_mod.select_music_key("missing.mp3")


def test_select_music_key_no_music_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio_mod, "list_music_keys", lambda: [])
    assert audio_mod.select_music_key() is None


# --------------------------------------------------------------------------- #
# ffmpeg argument builders
# --------------------------------------------------------------------------- #
def test_build_clip_args_with_audio_and_watermark(tmp_path: Path) -> None:
    segment = compose_mod.ClipSegment(
        clip_path=tmp_path / "clip.mp4",
        lower_third_path=tmp_path / "lt.png",
        output_path=tmp_path / "seg.mp4",
        duration_sec=4.0,
    )
    args = compose_mod.build_clip_args(
        segment,
        width=1280,
        height=720,
        transition_sec=0.5,
        duck_level=0.25,
        watermark_path=tmp_path / "wm.png",
        has_audio=True,
    )
    joined = " ".join(args)
    filter_graph = args[args.index("-filter_complex") + 1]

    assert "[vout]" in filter_graph and "[aout]" in filter_graph
    assert "scale=1280:720:force_original_aspect_ratio=decrease" in filter_graph
    assert "[0:a]volume=0.250" in filter_graph
    # Two overlays (lower third at 0:0, watermark in the corner).
    assert filter_graph.count("overlay=") == 2
    assert "main_w-overlay_w" in filter_graph
    assert joined.endswith(str(segment.output_path))


def test_build_clip_args_without_audio_uses_silence_source(tmp_path: Path) -> None:
    segment = compose_mod.ClipSegment(
        clip_path=tmp_path / "clip.mp4",
        lower_third_path=tmp_path / "lt.png",
        output_path=tmp_path / "seg.mp4",
        duration_sec=3.0,
    )
    args = compose_mod.build_clip_args(
        segment,
        width=1280,
        height=720,
        transition_sec=0.5,
        duck_level=0.25,
        watermark_path=None,
        has_audio=False,
    )
    joined = " ".join(args)
    filter_graph = args[args.index("-filter_complex") + 1]

    assert "anullsrc" in joined
    # One overlay only (lower third); silence input is index 2 (clip=0, lt=1).
    assert filter_graph.count("overlay=") == 1
    assert "[2:a]volume=0.250" in filter_graph


def test_build_music_mix_args_loops_and_mixes(tmp_path: Path) -> None:
    args = compose_mod.build_music_mix_args(
        tmp_path / "concat.mp4",
        tmp_path / "music.mp3",
        music_volume=0.35,
        output_path=tmp_path / "final.mp4",
    )
    joined = " ".join(args)
    filter_graph = args[args.index("-filter_complex") + 1]

    assert "-stream_loop -1" in joined
    assert "volume=0.350" in filter_graph
    assert "amix=inputs=2:duration=first" in filter_graph
    assert "normalize=0" in filter_graph
    assert "-shortest" in joined


def test_write_concat_list_escapes_and_lists(tmp_path: Path) -> None:
    seg_a = tmp_path / "a.mp4"
    seg_b = tmp_path / "b.mp4"
    list_path = compose_mod.write_concat_list([seg_a, seg_b], tmp_path / "list.txt")

    content = list_path.read_text(encoding="utf-8")
    assert f"file '{seg_a}'" in content
    assert f"file '{seg_b}'" in content


def test_render_composition_rejects_empty_clip_specs(tmp_path: Path) -> None:
    with pytest.raises(compose_mod.CompositionError):
        compose_mod.render_composition(
            clip_specs=[],
            intro_png=None,
            width=1280,
            height=720,
            transition_sec=0.5,
            intro_duration_sec=3.0,
            duck_level=0.25,
            music_volume=0.35,
            watermark_path=None,
            music_path=None,
            work_dir=tmp_path / "work",
            output_path=tmp_path / "out.mp4",
        )
