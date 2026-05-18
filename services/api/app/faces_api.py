"""
InsightFace wrapper for the api service (enrollment only).
Loads buffalo_l once at startup; used exclusively for:
  1. Detecting faces in uploaded enrollment photos.
  2. Computing normed_embedding for storage in person_embeddings.

Constraints (mirror ingestion-worker/app/faces.py):
- ALWAYS use face.normed_embedding — NOT face.embedding.
- ctx_id=0 (CPU), det_size=(640, 640).
- Model baked into Docker image at build time — no download occurs here.
"""
import logging

import cv2
import numpy as np
from insightface.app import FaceAnalysis

logger = logging.getLogger(__name__)


def load_face_model() -> FaceAnalysis:
    """Load InsightFace buffalo_l. Call once at api startup (lifespan)."""
    logger.info("Loading InsightFace buffalo_l for api service (enrollment)")
    face_app = FaceAnalysis(
        name="buffalo_l",
        providers=["CPUExecutionProvider"],
    )
    face_app.prepare(ctx_id=0, det_size=(640, 640))
    logger.info("InsightFace buffalo_l loaded for api service")
    return face_app


def analyze_image_bytes(image_data: bytes, face_app: FaceAnalysis) -> list[dict]:
    """
    Decode image bytes and run InsightFace SCRFD + ArcFace.

    Returns a list of face dicts:
        {
            "bbox_x1": int, "bbox_y1": int, "bbox_x2": int, "bbox_y2": int,
            "det_score": float,
            "normed_embedding": list[float],   # 512-dim, L2-normalized
        }

    Returns [] if image cannot be decoded or InsightFace raises.
    Caller must check len(faces) == 0 / > 1 and det_score >= 0.70 themselves.
    """
    arr = np.frombuffer(image_data, dtype=np.uint8)
    img_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img_bgr is None:
        return []   # not a valid image — caller raises 422

    try:
        faces = face_app.get(img_bgr)
    except Exception as exc:
        logger.error("InsightFace inference error: %s", exc)
        return []

    results = []
    for face in faces:
        normed_emb = face.normed_embedding  # CRITICAL: not face.embedding
        if normed_emb is None:
            continue
        bbox = face.bbox  # [x1, y1, x2, y2] floats
        results.append({
            "bbox_x1":         int(bbox[0]),
            "bbox_y1":         int(bbox[1]),
            "bbox_x2":         int(bbox[2]),
            "bbox_y2":         int(bbox[3]),
            "det_score":       float(face.det_score),
            "normed_embedding": normed_emb.tolist(),
        })
    return results
