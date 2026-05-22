"""
Tests for _is_video_file extension filter (AUTO-02, AUTO-03).

Video files must trigger ingest; non-video files must be silently ignored.
Case-insensitive matching required.

Run from services/watcher/:
    python -m pytest tests/test_extension_filter.py -v
"""
import pytest

from app.watcher import _is_video_file


class TestVideoExtensionFilter:
    """Supported video extensions trigger ingest (AUTO-02)."""

    @pytest.mark.parametrize("path", [
        "/watch/holiday.mp4",
        "/watch/holiday.MP4",
        "/watch/clip.mov",
        "/watch/clip.MOV",
        "/watch/recording.avi",
        "/watch/recording.AVI",
        "/watch/video.mkv",
        "/watch/video.MKV",
        "/watch/mobile.m4v",
        "/watch/mobile.M4V",
    ])
    def test_video_extensions_return_true(self, path):
        assert _is_video_file(path) is True, (
            f"Expected {path!r} to be recognised as a video file"
        )


class TestNonVideoExtensionFilter:
    """Non-video files must be silently ignored — no upload, no ingest (AUTO-03)."""

    @pytest.mark.parametrize("path", [
        "/watch/readme.txt",
        "/watch/photo.jpg",
        "/watch/photo.JPEG",
        "/watch/document.pdf",
        "/watch/archive.zip",
        "/watch/script.sh",
        "/watch/.hidden",
        "/watch/noextension",
        "/watch/audio.mp3",
    ])
    def test_non_video_extensions_return_false(self, path):
        assert _is_video_file(path) is False, (
            f"Expected {path!r} to be rejected (non-video extension)"
        )
