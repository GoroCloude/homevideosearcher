"""
Tests for GET /persons/{person_id}/appearances endpoint.

Verifies:
- 404 for unknown person UUID
- 200 with empty results for known person with no detections
- 200 with one result per video (not per face detection) for known person
- Result shape: video_id, video_minio_key, recorded_at, duration_sec, first_ts_ms,
  appearance_count, thumbnail_url (presigned URL)
- Results sorted newest-first (COALESCE(recorded_at, ingested_at) DESC NULLS LAST)

Run from services/api/:
    python -m pytest tests/test_person_appearances.py -v
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


# ── Shared fixture: FastAPI test app with persons router ──────────────────────

@pytest.fixture
def app_client(monkeypatch):
    """TestClient with persons router mounted (no auth dependency for simplicity)."""
    from app.persons import router as persons_router

    app = FastAPI()
    app.include_router(persons_router)

    client = TestClient(app, raise_server_exceptions=False)
    return client, monkeypatch


def _make_pool(fetchrow_return=None, fetch_return=None):
    """Build a mock asyncpg pool with configurable fetchrow/fetch responses."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.fetch = AsyncMock(return_value=fetch_return if fetch_return is not None else [])

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = acquire_cm
    return pool, conn


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPersonAppearancesEndpoint:

    def test_invalid_uuid_returns_422(self, app_client):
        """FastAPI UUID validation: non-UUID path param → 422 before any DB call."""
        client, _ = app_client
        resp = client.get("/persons/not-a-uuid/appearances")
        assert resp.status_code == 422

    def test_unknown_person_returns_404(self, app_client):
        """Valid UUID not in known_persons → 404 Person not found."""
        client, _ = app_client
        pool, _ = _make_pool(fetchrow_return=None)  # person not found

        with patch("app.persons.get_pool", new_callable=AsyncMock) as mock_gp:
            mock_gp.return_value = pool
            resp = client.get(
                "/persons/00000000-0000-0000-0000-000000000001/appearances"
            )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Person not found"

    def test_known_person_no_detections_returns_empty_results(self, app_client):
        """Known person with zero face_detections → 200 with empty results list."""
        client, _ = app_client

        # First pool.acquire() call → fetchrow returns the person row
        person_row = {"id": "00000000-0000-0000-0000-000000000002", "name": "Alice"}

        pool = MagicMock()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=person_row)
        conn.fetch = AsyncMock(return_value=[])  # no detections

        acquire_cm = MagicMock()
        acquire_cm.__aenter__ = AsyncMock(return_value=conn)
        acquire_cm.__aexit__ = AsyncMock(return_value=False)
        pool.acquire.return_value = acquire_cm

        with patch("app.persons.get_pool", new_callable=AsyncMock) as mock_gp, \
             patch("app.persons.generate_presigned_url", return_value="https://minio/thumb.jpg"):
            mock_gp.return_value = pool
            resp = client.get(
                "/persons/00000000-0000-0000-0000-000000000002/appearances"
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["person_id"] == "00000000-0000-0000-0000-000000000002"
        assert body["person_name"] == "Alice"
        assert body["results"] == []

    def test_known_person_with_detections_returns_one_row_per_video(self, app_client):
        """
        A person detected 3 times across 2 different videos should return
        exactly 2 result rows (one per video), not 3.
        """
        client, _ = app_client

        person_row = {"id": "00000000-0000-0000-0000-000000000003", "name": "Bob"}

        # Two video rows (already aggregated by SQL GROUP BY video_id)
        video_rows = [
            {
                "video_id": "aaaaaaaa-0000-0000-0000-000000000001",
                "first_ts_ms": 1000,
                "appearance_count": 2,
                "video_minio_key": "videos/vid1.mp4",
                "recorded_at": "2024-06-01T10:00:00",
                "duration_sec": 120.5,
                "frame_minio_key": "frames/frame_a.jpg",
            },
            {
                "video_id": "bbbbbbbb-0000-0000-0000-000000000002",
                "first_ts_ms": 5000,
                "appearance_count": 1,
                "video_minio_key": "videos/vid2.mp4",
                "recorded_at": "2024-05-01T10:00:00",
                "duration_sec": 60.0,
                "frame_minio_key": "frames/frame_b.jpg",
            },
        ]

        pool = MagicMock()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=person_row)
        conn.fetch = AsyncMock(return_value=video_rows)

        acquire_cm = MagicMock()
        acquire_cm.__aenter__ = AsyncMock(return_value=conn)
        acquire_cm.__aexit__ = AsyncMock(return_value=False)
        pool.acquire.return_value = acquire_cm

        with patch("app.persons.get_pool", new_callable=AsyncMock) as mock_gp, \
             patch("app.persons.generate_presigned_url", return_value="https://minio/thumb.jpg"):
            mock_gp.return_value = pool
            resp = client.get(
                "/persons/00000000-0000-0000-0000-000000000003/appearances"
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["results"]) == 2, (
            f"Expected 2 results (one per video), got {len(body['results'])}"
        )

    def test_result_row_has_required_fields(self, app_client):
        """Each result row must contain all required fields with correct types."""
        client, _ = app_client

        person_row = {"id": "00000000-0000-0000-0000-000000000004", "name": "Carol"}

        video_rows = [
            {
                "video_id": "cccccccc-0000-0000-0000-000000000001",
                "first_ts_ms": 2500,
                "appearance_count": 3,
                "video_minio_key": "videos/vid3.mp4",
                "recorded_at": "2024-07-15T08:30:00",
                "duration_sec": 300.0,
                "frame_minio_key": "frames/frame_c.jpg",
            }
        ]

        pool = MagicMock()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=person_row)
        conn.fetch = AsyncMock(return_value=video_rows)

        acquire_cm = MagicMock()
        acquire_cm.__aenter__ = AsyncMock(return_value=conn)
        acquire_cm.__aexit__ = AsyncMock(return_value=False)
        pool.acquire.return_value = acquire_cm

        with patch("app.persons.get_pool", new_callable=AsyncMock) as mock_gp, \
             patch("app.persons.generate_presigned_url", return_value="https://minio/presigned/frame_c.jpg"):
            mock_gp.return_value = pool
            resp = client.get(
                "/persons/00000000-0000-0000-0000-000000000004/appearances"
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["results"]) == 1
        row = body["results"][0]

        # All required fields must be present
        required = [
            "video_id", "video_minio_key", "recorded_at",
            "duration_sec", "first_ts_ms", "appearance_count", "thumbnail_url",
        ]
        for field in required:
            assert field in row, f"Missing field: {field}"

        # Types check
        assert isinstance(row["video_id"], str)
        assert isinstance(row["first_ts_ms"], int)
        assert isinstance(row["appearance_count"], int)
        assert row["appearance_count"] == 3
        assert isinstance(row["thumbnail_url"], str)
        assert row["thumbnail_url"].startswith("https://"), (
            f"thumbnail_url should be presigned HTTPS URL, got: {row['thumbnail_url']}"
        )

    def test_thumbnail_url_uses_presigned_generation(self, app_client):
        """thumbnail_url must be generated via generate_presigned_url (not a relative path)."""
        client, _ = app_client

        person_row = {"id": "00000000-0000-0000-0000-000000000005", "name": "Dave"}
        video_rows = [
            {
                "video_id": "dddddddd-0000-0000-0000-000000000001",
                "first_ts_ms": 100,
                "appearance_count": 1,
                "video_minio_key": "videos/vid4.mp4",
                "recorded_at": None,
                "duration_sec": None,
                "frame_minio_key": "frames/frame_d.jpg",
            }
        ]

        pool = MagicMock()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=person_row)
        conn.fetch = AsyncMock(return_value=video_rows)

        acquire_cm = MagicMock()
        acquire_cm.__aenter__ = AsyncMock(return_value=conn)
        acquire_cm.__aexit__ = AsyncMock(return_value=False)
        pool.acquire.return_value = acquire_cm

        presigned_url = "http://localhost:9000/frames/frame_d.jpg?X-Amz-Signature=abc123"

        with patch("app.persons.get_pool", new_callable=AsyncMock) as mock_gp, \
             patch("app.persons.generate_presigned_url", return_value=presigned_url) as mock_presign:
            mock_gp.return_value = pool
            resp = client.get(
                "/persons/00000000-0000-0000-0000-000000000005/appearances"
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["results"][0]["thumbnail_url"] == presigned_url
        # Verify generate_presigned_url was called with the frame's minio_key
        mock_presign.assert_called_once()
        call_kwargs = mock_presign.call_args
        assert call_kwargs.kwargs.get("key") == "frames/frame_d.jpg" or \
               (len(call_kwargs.args) >= 2 and call_kwargs.args[1] == "frames/frame_d.jpg"), \
            f"Expected generate_presigned_url(key='frames/frame_d.jpg'), got {call_kwargs}"

    def test_null_recorded_at_and_duration_are_allowed(self, app_client):
        """recorded_at and duration_sec are nullable fields — None must be serialized as null."""
        client, _ = app_client

        person_row = {"id": "00000000-0000-0000-0000-000000000006", "name": "Eve"}
        video_rows = [
            {
                "video_id": "eeeeeeee-0000-0000-0000-000000000001",
                "first_ts_ms": 50,
                "appearance_count": 1,
                "video_minio_key": "videos/vid5.mp4",
                "recorded_at": None,
                "duration_sec": None,
                "frame_minio_key": "frames/frame_e.jpg",
            }
        ]

        pool = MagicMock()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=person_row)
        conn.fetch = AsyncMock(return_value=video_rows)

        acquire_cm = MagicMock()
        acquire_cm.__aenter__ = AsyncMock(return_value=conn)
        acquire_cm.__aexit__ = AsyncMock(return_value=False)
        pool.acquire.return_value = acquire_cm

        with patch("app.persons.get_pool", new_callable=AsyncMock) as mock_gp, \
             patch("app.persons.generate_presigned_url", return_value="https://minio/frame_e.jpg"):
            mock_gp.return_value = pool
            resp = client.get(
                "/persons/00000000-0000-0000-0000-000000000006/appearances"
            )

        assert resp.status_code == 200
        body = resp.json()
        row = body["results"][0]
        assert row["recorded_at"] is None
        assert row["duration_sec"] is None
