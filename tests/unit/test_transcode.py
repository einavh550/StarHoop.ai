"""Unit tests for transcode.py — probe_fps and cap_fps."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.cv.transcode import TranscodeError, cap_fps, probe_fps


# --------------------------------------------------------------------------- #
# probe_fps
# --------------------------------------------------------------------------- #
def test_probe_fps_returns_none_when_ffprobe_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: None)
    assert probe_fps("/any/video.mp4") is None


def test_probe_fps_parses_integer_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/ffprobe")

    class _Result:
        stdout = "60/1\n"
        returncode = 0

    monkeypatch.setattr("subprocess.run", lambda *a, **k: _Result())
    assert probe_fps("/any/video.mp4") == pytest.approx(60.0)


def test_probe_fps_parses_fractional_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/ffprobe")

    class _Result:
        stdout = "30000/1001\n"
        returncode = 0

    monkeypatch.setattr("subprocess.run", lambda *a, **k: _Result())
    assert probe_fps("/any/video.mp4") == pytest.approx(29.97, rel=1e-3)


def test_probe_fps_returns_none_on_empty_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/ffprobe")

    class _Result:
        stdout = ""
        returncode = 0

    monkeypatch.setattr("subprocess.run", lambda *a, **k: _Result())
    assert probe_fps("/any/video.mp4") is None


# --------------------------------------------------------------------------- #
# cap_fps
# --------------------------------------------------------------------------- #
def test_cap_fps_returns_src_unchanged_when_already_at_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "game.mp4"
    src.write_bytes(b"video")

    # probe reports 30 fps — exactly at cap, no transcode needed.
    monkeypatch.setattr("app.cv.transcode.probe_fps", lambda _: 30.0)
    ffmpeg_called = {"called": False}

    def _fake_run(*args, **kwargs):
        ffmpeg_called["called"] = True
        return MagicMock(returncode=0)

    monkeypatch.setattr("subprocess.run", _fake_run)

    result = cap_fps(src, max_fps=30)
    assert result == src
    assert not ffmpeg_called["called"]


def test_cap_fps_returns_src_unchanged_when_probe_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "game.mp4"
    src.write_bytes(b"video")

    # probe returns None (ffprobe unavailable) — skip transcoding to be safe.
    monkeypatch.setattr("app.cv.transcode.probe_fps", lambda _: None)
    ffmpeg_called = {"called": False}

    def _fake_run(*args, **kwargs):
        ffmpeg_called["called"] = True
        return MagicMock(returncode=0)

    monkeypatch.setattr("subprocess.run", _fake_run)

    result = cap_fps(src, max_fps=30)
    assert result == src
    assert not ffmpeg_called["called"]


def test_cap_fps_transcodes_when_above_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "game.mp4"
    src.write_bytes(b"video")
    expected_dst = tmp_path / "game_30fps.mp4"

    monkeypatch.setattr("app.cv.transcode.probe_fps", lambda _: 60.0)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/ffmpeg")

    def _fake_run(cmd, **kwargs):
        # Simulate ffmpeg writing the output file.
        expected_dst.write_bytes(b"capped")
        return MagicMock(returncode=0)

    monkeypatch.setattr("subprocess.run", _fake_run)

    result = cap_fps(src, max_fps=30)
    assert result == expected_dst
    assert result.exists()


def test_cap_fps_raises_when_ffmpeg_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "game.mp4"
    src.write_bytes(b"video")

    monkeypatch.setattr("app.cv.transcode.probe_fps", lambda _: 60.0)
    monkeypatch.setattr("shutil.which", lambda _: None)

    with pytest.raises(TranscodeError, match="ffmpeg binary not found"):
        cap_fps(src, max_fps=30)


def test_cap_fps_raises_on_ffmpeg_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "game.mp4"
    src.write_bytes(b"video")

    monkeypatch.setattr("app.cv.transcode.probe_fps", lambda _: 60.0)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/ffmpeg")

    class _FailResult:
        returncode = 1
        stderr = "error: codec not found"

    monkeypatch.setattr("subprocess.run", lambda *a, **k: _FailResult())

    with pytest.raises(TranscodeError, match="failed to cap fps"):
        cap_fps(src, max_fps=30)
