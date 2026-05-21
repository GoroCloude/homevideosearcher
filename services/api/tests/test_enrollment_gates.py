"""
Tests for POST /persons/{person_id}/enroll — enrollment gate logic.

Gates (in order):
  0. File size <= MAX_UPLOAD_BYTES (10 MB)
  1. Decodable as image (Pillow + OpenCV fallback)
  2. Exactly one face detected by InsightFace
  3. Detector confidence (det_score) >= 0.70
  4. Bounding box >= 80×80 px

Heavy dependencies (DB, InsightFace) are mocked throughout.
Run from services/api/:
    python -m pytest tests/test_enrollment_gates.py -v
"""
import io
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.persons import router as persons_router


# ── Fixtures / helpers ────────────────────────────────────────────────────────

PERSON_ID = str(uuid4())


def _test_app() -> FastAPI:
    """Minimal FastAPI app with persons router (no auth for testing)."""
    app = FastAPI()
    app.include_router(persons_router)
    app.state.face_app = MagicMock()
    return app


def _make_pool(person_exists: bool = True, total_count: int = 3):
    """Return (pool, conn) mocks for asyncpg pool."""
    conn = AsyncMock()
    conn.fetchrow.return_value = {"id": PERSON_ID} if person_exists else None
    conn.fetchval.return_value = total_count
    conn.executemany.return_value = None
    conn.fetch.return_value = []

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = acquire_cm
    return pool, conn


def _jpeg_bytes(width: int = 100, height: int = 100) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(50, 100, 150)).save(buf, format="JPEG")
    return buf.getvalue()


def _valid_face(
    det_score: float = 0.95,
    bbox_x1: int = 0,
    bbox_y1: int = 0,
    bbox_x2: int = 100,
    bbox_y2: int = 100,
) -> dict:
    return {
        "bbox_x1": bbox_x1,
        "bbox_y1": bbox_y1,
        "bbox_x2": bbox_x2,
        "bbox_y2": bbox_y2,
        "det_score": det_score,
        "normed_embedding": [0.0] * 512,
    }


def _enroll(
    person_id: str,
    files: list,
    pool,
    analyze_return=None,
    analyze_side_effect=None,
):
    """Post to /persons/{person_id}/enroll with mocked pool and analyze_image_bytes."""
    app = _test_app()
    client = TestClient(app, raise_server_exceptions=False)

    if analyze_side_effect is not None:
        analyze_patch = patch(
            "app.persons.analyze_image_bytes", side_effect=analyze_side_effect
        )
    else:
        ret = [_valid_face()] if analyze_return is None else analyze_return
        analyze_patch = patch("app.persons.analyze_image_bytes", return_value=ret)

    with (
        patch("app.persons.get_pool", new_callable=AsyncMock) as mock_gp,
        analyze_patch,
    ):
        mock_gp.return_value = pool
        return client.post(f"/persons/{person_id}/enroll", files=files)


# ── Gate 0: file size ─────────────────────────────────────────────────────────

class TestGate0FileSize:
    def test_file_exactly_at_limit_is_accepted(self):
        """File exactly at MAX_UPLOAD_BYTES should not be rejected by the size gate."""
        pool, _ = _make_pool()
        with patch("app.persons.MAX_UPLOAD_BYTES", 200):
            resp = _enroll(
                PERSON_ID,
                [("images", ("f.jpg", b"x" * 200, "image/jpeg"))],
                pool,
            )
        data = resp.json()
        assert not any("exceeds" in r.get("reason", "") for r in data.get("rejected", []))

    def test_file_one_byte_over_limit_is_rejected(self):
        pool, conn = _make_pool()
        with patch("app.persons.MAX_UPLOAD_BYTES", 200):
            resp = _enroll(
                PERSON_ID,
                [("images", ("big.jpg", b"x" * 201, "image/jpeg"))],
                pool,
            )
        data = resp.json()
        assert resp.status_code == 200
        assert data["enrolled"] == 0
        assert len(data["rejected"]) == 1
        assert "exceeds 10 MB" in data["rejected"][0]["reason"]
        conn.executemany.assert_not_called()


# ── Gate 1: image decodability ────────────────────────────────────────────────

class TestGate1ImageDecodability:
    def test_garbage_bytes_rejected_as_not_valid_image(self):
        pool, _ = _make_pool()
        with (
            patch("app.persons.get_pool", new_callable=AsyncMock) as mock_gp,
            patch("app.persons.analyze_image_bytes", return_value=[]),
        ):
            mock_gp.return_value = pool
            app = _test_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                f"/persons/{PERSON_ID}/enroll",
                files=[("images", ("bad.dat", b"\x00\xff" * 50, "application/octet-stream"))],
            )
        data = resp.json()
        assert data["enrolled"] == 0
        assert data["rejected"][0]["reason"] == "Not a valid image"

    def test_valid_jpeg_with_no_face_detected(self):
        pool, _ = _make_pool()
        with (
            patch("app.persons.get_pool", new_callable=AsyncMock) as mock_gp,
            patch("app.persons.analyze_image_bytes", return_value=[]),
        ):
            mock_gp.return_value = pool
            app = _test_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                f"/persons/{PERSON_ID}/enroll",
                files=[("images", ("face.jpg", _jpeg_bytes(), "image/jpeg"))],
            )
        data = resp.json()
        assert data["enrolled"] == 0
        assert data["rejected"][0]["reason"] == "No face detected"


# ── Gate 2: face count ────────────────────────────────────────────────────────

class TestGate2FaceCount:
    def test_multiple_faces_rejected_with_count_in_message(self):
        pool, _ = _make_pool()
        two_faces = [_valid_face(), _valid_face()]
        resp = _enroll(
            PERSON_ID,
            [("images", ("group.jpg", _jpeg_bytes(), "image/jpeg"))],
            pool,
            analyze_return=two_faces,
        )
        data = resp.json()
        assert data["enrolled"] == 0
        assert "Multiple faces" in data["rejected"][0]["reason"]
        assert "2" in data["rejected"][0]["reason"]


# ── Gate 3: detector confidence ───────────────────────────────────────────────

class TestGate3DetectorConfidence:
    @pytest.mark.parametrize("score", [0.00, 0.50, 0.69])
    def test_below_threshold_rejected(self, score):
        pool, _ = _make_pool()
        resp = _enroll(
            PERSON_ID,
            [("images", ("f.jpg", _jpeg_bytes(), "image/jpeg"))],
            pool,
            analyze_return=[_valid_face(det_score=score)],
        )
        data = resp.json()
        assert data["enrolled"] == 0
        assert "low detector confidence" in data["rejected"][0]["reason"]

    def test_exactly_threshold_0_70_accepted(self):
        pool, _ = _make_pool()
        resp = _enroll(
            PERSON_ID,
            [("images", ("f.jpg", _jpeg_bytes(), "image/jpeg"))],
            pool,
            analyze_return=[_valid_face(det_score=0.70)],
        )
        data = resp.json()
        assert data["enrolled"] == 1
        assert data["rejected"] == []

    def test_above_threshold_accepted(self):
        pool, _ = _make_pool()
        resp = _enroll(
            PERSON_ID,
            [("images", ("f.jpg", _jpeg_bytes(), "image/jpeg"))],
            pool,
            analyze_return=[_valid_face(det_score=0.99)],
        )
        assert resp.json()["enrolled"] == 1


# ── Gate 4: bounding box size ─────────────────────────────────────────────────

class TestGate4BoundingBoxSize:
    def test_small_bbox_rejected(self):
        pool, _ = _make_pool()
        face = _valid_face(bbox_x1=0, bbox_y1=0, bbox_x2=60, bbox_y2=70)
        resp = _enroll(
            PERSON_ID,
            [("images", ("tiny.jpg", _jpeg_bytes(), "image/jpeg"))],
            pool,
            analyze_return=[face],
        )
        data = resp.json()
        assert data["enrolled"] == 0
        assert "too small" in data["rejected"][0]["reason"]

    def test_exactly_80x80_bbox_accepted(self):
        pool, _ = _make_pool()
        face = _valid_face(bbox_x1=0, bbox_y1=0, bbox_x2=80, bbox_y2=80)
        resp = _enroll(
            PERSON_ID,
            [("images", ("f.jpg", _jpeg_bytes(), "image/jpeg"))],
            pool,
            analyze_return=[face],
        )
        assert resp.json()["enrolled"] == 1

    def test_79_wide_bbox_rejected(self):
        """Width 79 < 80 → rejected."""
        pool, _ = _make_pool()
        face = _valid_face(bbox_x1=0, bbox_y1=0, bbox_x2=79, bbox_y2=80)
        resp = _enroll(
            PERSON_ID,
            [("images", ("f.jpg", _jpeg_bytes(), "image/jpeg"))],
            pool,
            analyze_return=[face],
        )
        data = resp.json()
        assert data["enrolled"] == 0
        assert "too small" in data["rejected"][0]["reason"]

    def test_79_tall_bbox_rejected(self):
        """Height 79 < 80 → rejected."""
        pool, _ = _make_pool()
        face = _valid_face(bbox_x1=0, bbox_y1=0, bbox_x2=80, bbox_y2=79)
        resp = _enroll(
            PERSON_ID,
            [("images", ("f.jpg", _jpeg_bytes(), "image/jpeg"))],
            pool,
            analyze_return=[face],
        )
        data = resp.json()
        assert data["enrolled"] == 0


# ── Batch behaviour ───────────────────────────────────────────────────────────

class TestBatchBehaviour:
    def test_all_gates_pass_inserts_embedding_into_db(self):
        pool, conn = _make_pool(total_count=1)
        resp = _enroll(
            PERSON_ID,
            [("images", ("good.jpg", _jpeg_bytes(), "image/jpeg"))],
            pool,
        )
        data = resp.json()
        assert resp.status_code == 200
        assert data["enrolled"] == 1
        assert data["rejected"] == []

        conn.executemany.assert_called_once()
        _, rows = conn.executemany.call_args[0]
        assert len(rows) == 1
        assert rows[0][0] == PERSON_ID      # person_id
        assert rows[0][2] == "good.jpg"     # source_image filename

    def test_partial_batch_accepted_and_rejected_separated(self):
        pool, conn = _make_pool(total_count=1)
        jpeg = _jpeg_bytes()

        call_count = 0

        def analyze_side_effect(data, face_app):
            nonlocal call_count
            call_count += 1
            return [_valid_face()] if call_count == 1 else []

        resp = _enroll(
            PERSON_ID,
            [
                ("images", ("good.jpg", jpeg, "image/jpeg")),
                ("images", ("bad.jpg", jpeg, "image/jpeg")),
            ],
            pool,
            analyze_side_effect=analyze_side_effect,
        )
        data = resp.json()
        assert data["enrolled"] == 1
        assert len(data["rejected"]) == 1
        assert data["rejected"][0]["filename"] == "bad.jpg"

        _, rows = conn.executemany.call_args[0]
        assert len(rows) == 1
        assert rows[0][2] == "good.jpg"

    def test_executemany_not_called_when_all_rejected(self):
        pool, conn = _make_pool()
        resp = _enroll(
            PERSON_ID,
            [("images", ("f.jpg", _jpeg_bytes(), "image/jpeg"))],
            pool,
            analyze_return=[_valid_face(det_score=0.30)],
        )
        assert resp.json()["enrolled"] == 0
        conn.executemany.assert_not_called()

    def test_warning_when_total_enrolled_below_5(self):
        pool, _ = _make_pool(total_count=3)
        data = _enroll(
            PERSON_ID,
            [("images", ("f.jpg", _jpeg_bytes(), "image/jpeg"))],
            pool,
        ).json()
        assert data["warning"] is not None
        assert "3" in data["warning"]

    def test_no_warning_when_total_enrolled_is_exactly_5(self):
        pool, _ = _make_pool(total_count=5)
        data = _enroll(
            PERSON_ID,
            [("images", ("f.jpg", _jpeg_bytes(), "image/jpeg"))],
            pool,
        ).json()
        assert data["warning"] is None

    def test_no_warning_when_total_enrolled_above_5(self):
        pool, _ = _make_pool(total_count=10)
        data = _enroll(
            PERSON_ID,
            [("images", ("f.jpg", _jpeg_bytes(), "image/jpeg"))],
            pool,
        ).json()
        assert data["warning"] is None


# ── Error paths ───────────────────────────────────────────────────────────────

class TestErrorPaths:
    def test_unknown_person_returns_404(self):
        pool, _ = _make_pool(person_exists=False)
        resp = _enroll(
            PERSON_ID,
            [("images", ("f.jpg", _jpeg_bytes(), "image/jpeg"))],
            pool,
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_empty_file_handled_gracefully(self):
        """Zero-byte upload should be rejected (no crash)."""
        pool, _ = _make_pool()
        with (
            patch("app.persons.get_pool", new_callable=AsyncMock) as mock_gp,
            patch("app.persons.analyze_image_bytes", return_value=[]),
        ):
            mock_gp.return_value = pool
            app = _test_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                f"/persons/{PERSON_ID}/enroll",
                files=[("images", ("empty.jpg", b"", "image/jpeg"))],
            )
        data = resp.json()
        assert resp.status_code == 200
        assert data["enrolled"] == 0
        assert len(data["rejected"]) == 1
