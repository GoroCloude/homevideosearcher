"""
Tests for _make_minio_key MinIO key generation (collision prevention).

Key scheme: videos/{YYYYMMDD_HHMMSS}_{original_filename}
Timestamp prefix prevents collision when the same filename is dropped twice.

Run from services/watcher/:
    python -m pytest tests/test_minio_key_scheme.py -v
"""
import re
import time
from datetime import datetime
from unittest.mock import patch

import pytest

from app.watcher import _make_minio_key


class TestMinioKeyFormat:
    def test_key_starts_with_videos_prefix(self):
        key = _make_minio_key("holiday.mp4")
        assert key.startswith("videos/"), f"Key must start with 'videos/', got: {key!r}"

    def test_key_ends_with_original_filename(self):
        key = _make_minio_key("my_birthday_party.mp4")
        assert key.endswith("my_birthday_party.mp4"), (
            f"Original filename must be preserved at end of key, got: {key!r}"
        )

    def test_key_matches_timestamp_pattern(self):
        """Key must match videos/YYYYMMDD_HHMMSS_{filename}."""
        key = _make_minio_key("clip.mov")
        pattern = r"^videos/\d{8}_\d{6}_clip\.mov$"
        assert re.match(pattern, key), (
            f"Key {key!r} does not match expected pattern {pattern}"
        )

    def test_key_for_filename_with_spaces(self):
        """Filenames with spaces must be preserved verbatim."""
        key = _make_minio_key("my holiday 2025.mp4")
        assert "my holiday 2025.mp4" in key

    def test_filename_preserves_original_extension(self):
        for filename in ("video.mkv", "clip.MOV", "recording.AVI"):
            key = _make_minio_key(filename)
            assert key.endswith(filename), (
                f"Extension must be preserved for {filename!r}, got: {key!r}"
            )


class TestMinioKeyCollisionPrevention:
    def test_same_filename_different_timestamps_produce_different_keys(self):
        """
        The timestamp prefix ensures two drops of the same filename produce
        different MinIO keys — preventing silent overwrite of first upload.
        """
        with patch("app.watcher.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 1, 12, 0, 0)
            key1 = _make_minio_key("video.mp4")  # no mtime → uses datetime.now() (mocked)

        with patch("app.watcher.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 1, 12, 0, 1)
            key2 = _make_minio_key("video.mp4")  # no mtime → uses datetime.now() (mocked)

        assert key1 != key2, (
            "Two live events with same filename at different times must produce different keys "
            f"(got key1={key1!r} key2={key2!r})"
        )

        # mtime-based keys are deterministic: same mtime → same key (startup_scan dedup)
        key_a = _make_minio_key("video.mp4", mtime=1_700_000_000.0)
        key_b = _make_minio_key("video.mp4", mtime=1_700_000_000.0)
        assert key_a == key_b, (
            "Same filename + same mtime must produce identical key (startup_scan restart dedup) "
            f"(got key_a={key_a!r} key_b={key_b!r})"
        )

        # different mtime → different key
        key_c = _make_minio_key("video.mp4", mtime=1_700_000_001.0)
        assert key_a != key_c, "Different mtime must produce different key"
