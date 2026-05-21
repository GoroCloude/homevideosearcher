"""
Tests for analyze_image_bytes — image decoding and InsightFace wrapper used for enrollment.

Focus areas:
  - EXIF orientation handling (mobile phone portrait photos)
  - Empty / garbage input rejection
  - Face dict contract (required keys, 512-dim unit-vector embedding)
  - Correct use of face.normed_embedding (not face.embedding)
  - InsightFace error resilience

Run from services/api/:
    python -m pytest tests/test_faces_api.py -v
"""
import io
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest
from PIL import Image

from app.faces_api import analyze_image_bytes


# ── Test helpers ──────────────────────────────────────────────────────────────

def _jpeg_bytes(width: int = 200, height: int = 150, color=(100, 150, 200)) -> bytes:
    """Create a minimal solid-color JPEG via PIL (no cv2 encoding quirks)."""
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=color).save(buf, format="JPEG")
    return buf.getvalue()


def _exif_jpeg(width: int, height: int, orientation: int) -> bytes:
    """
    Create a JPEG with an EXIF Orientation tag.

    orientation values (EXIF tag 0x0112):
      1 = normal, 3 = 180°, 6 = 90° CW (portrait shot stored landscape), 8 = 90° CCW
    """
    img = Image.new("RGB", (width, height), color=(128, 128, 128))
    exif = img.getexif()
    exif[0x0112] = orientation
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def _mock_face(det_score: float = 0.95) -> MagicMock:
    """Return a mock InsightFace face object with a unit normed_embedding."""
    raw = np.random.randn(512).astype(np.float32)
    raw /= np.linalg.norm(raw)

    face = MagicMock()
    face.det_score = det_score
    face.normed_embedding = raw
    face.embedding = np.full(512, 99.0, dtype=np.float32)  # deliberately different
    face.bbox = np.array([10.0, 20.0, 110.0, 120.0], dtype=np.float32)
    return face


# ── Basic input handling ──────────────────────────────────────────────────────

class TestAnalyzeImageBytesBasic:
    def test_empty_bytes_returns_empty_list(self):
        result = analyze_image_bytes(b"", MagicMock())
        assert result == []

    def test_garbage_bytes_returns_empty_list(self):
        result = analyze_image_bytes(b"\x00\x01\x02\x03" * 100, MagicMock())
        assert result == []

    def test_valid_jpeg_calls_face_app_get(self):
        face_app = MagicMock()
        face_app.get.return_value = []
        analyze_image_bytes(_jpeg_bytes(), face_app)
        face_app.get.assert_called_once()

    def test_no_faces_in_image_returns_empty_list(self):
        face_app = MagicMock()
        face_app.get.return_value = []
        assert analyze_image_bytes(_jpeg_bytes(), face_app) == []

    def test_insightface_exception_returns_empty_list(self):
        face_app = MagicMock()
        face_app.get.side_effect = RuntimeError("ONNX inference failed")
        assert analyze_image_bytes(_jpeg_bytes(), face_app) == []

    def test_face_without_normed_embedding_is_skipped(self):
        face = _mock_face()
        face.normed_embedding = None
        face_app = MagicMock()
        face_app.get.return_value = [face]
        assert analyze_image_bytes(_jpeg_bytes(), face_app) == []


# ── Face dict contract ────────────────────────────────────────────────────────

class TestFaceDictContract:
    def setup_method(self):
        self.face = _mock_face()
        self.face_app = MagicMock()
        self.face_app.get.return_value = [self.face]
        self.result = analyze_image_bytes(_jpeg_bytes(), self.face_app)

    def test_returns_one_face_dict_per_face(self):
        assert len(self.result) == 1

    def test_face_dict_has_all_required_keys(self):
        keys = self.result[0].keys()
        for key in ("bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2", "det_score", "normed_embedding"):
            assert key in keys, f"Missing key: {key}"

    def test_normed_embedding_is_list(self):
        assert isinstance(self.result[0]["normed_embedding"], list)

    def test_normed_embedding_is_512_dimensional(self):
        assert len(self.result[0]["normed_embedding"]) == 512

    def test_det_score_is_float(self):
        assert isinstance(self.result[0]["det_score"], float)

    def test_bbox_coordinates_are_ints(self):
        r = self.result[0]
        for key in ("bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2"):
            assert isinstance(r[key], int), f"{key} should be int"

    def test_uses_normed_embedding_not_raw_embedding(self):
        """analyze_image_bytes must use face.normed_embedding, NOT face.embedding."""
        r = self.result[0]
        # face.normed_embedding[0] ≠ 99.0 (which is what face.embedding has)
        assert not all(abs(v - 99.0) < 1e-6 for v in r["normed_embedding"]), (
            "Returned embedding looks like face.embedding (all 99.0). "
            "Check that faces_api.py uses face.normed_embedding."
        )

    def test_normed_embedding_is_approximately_unit_vector(self):
        emb = np.array(self.result[0]["normed_embedding"])
        norm = float(np.linalg.norm(emb))
        assert abs(norm - 1.0) < 0.01, f"Expected unit vector, got L2 norm={norm:.4f}"


# ── EXIF orientation ──────────────────────────────────────────────────────────

class TestExifOrientation:
    def test_portrait_photo_stored_landscape_corrected_before_face_detection(self):
        """
        Mobile phones store portrait shots as landscape pixels with EXIF orientation=6.
        exif_transpose() must rotate the image BEFORE passing to InsightFace.
        Without correction: shape (100, 200, 3) → InsightFace sees sideways face.
        With correction:    shape (200, 100, 3) → InsightFace sees upright face.
        """
        face_app = MagicMock()
        face_app.get.return_value = []

        # Physical pixels: 200 wide × 100 tall (landscape)
        # EXIF orientation 6 = 90° CW: viewer should rotate CCW to see portrait
        img_bytes = _exif_jpeg(width=200, height=100, orientation=6)
        analyze_image_bytes(img_bytes, face_app)

        face_app.get.assert_called_once()
        passed_img = face_app.get.call_args[0][0]

        # After exif_transpose(orientation=6): physical 200×100 becomes 100×200 (W×H)
        # NumPy shape = (height, width, channels) = (200, 100, 3)
        assert passed_img.shape == (200, 100, 3), (
            f"Expected (200, 100, 3) after EXIF correction, got {passed_img.shape}. "
            "Phone portrait photos will not be recognised without EXIF correction."
        )

    def test_normal_image_without_exif_dimensions_unchanged(self):
        """Image with no EXIF data passes through with original dimensions."""
        face_app = MagicMock()
        face_app.get.return_value = []

        img_bytes = _jpeg_bytes(width=320, height=240)
        analyze_image_bytes(img_bytes, face_app)

        passed_img = face_app.get.call_args[0][0]
        assert passed_img.shape == (240, 320, 3)

    def test_exif_orientation_1_normal_no_rotation(self):
        """Orientation=1 (normal) → image dimensions should not change."""
        face_app = MagicMock()
        face_app.get.return_value = []

        img_bytes = _exif_jpeg(width=300, height=200, orientation=1)
        analyze_image_bytes(img_bytes, face_app)

        passed_img = face_app.get.call_args[0][0]
        assert passed_img.shape == (200, 300, 3)
