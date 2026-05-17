"""
InsightFace face recognition wrapper.

Key constraints (do not violate):
1. Model is loaded ONCE at startup (load_face_model). Never re-loaded per frame.
2. Always use face.normed_embedding (NOT face.embedding) — L2-normalized 512-dim vector.
3. Run InsightFace on the FULL FRAME (not YOLO person crops) — SCRFD handles detection.
4. YOLO and InsightFace run SEQUENTIALLY — this function is never called in parallel.
5. Two-tier threshold:
   - similarity >= FACE_MATCH_HIGH_THRESHOLD (0.65) → match_tier = 'confident'
   - FACE_MATCH_LOW_THRESHOLD (0.50) <= similarity < 0.65 → match_tier = 'probable'
   - similarity < FACE_MATCH_LOW_THRESHOLD (0.50) → matched_person_id = NULL, match_tier = NULL
6. Faces with no match (or no known persons enrolled) are stored with matched_person_id=NULL.
   These are the "unknown pool" that Phase 3 HDBSCAN clustering consumes.
"""
import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from insightface.app import FaceAnalysis

from . import config

logger = logging.getLogger(__name__)


def load_face_model() -> FaceAnalysis:
    """
    Load InsightFace buffalo_l model pack.
    Called once at worker startup, 2 seconds after YOLO loads (staggered to prevent
    simultaneous memory spike on 8 GB RAM host).
    Model is baked into Docker image at build time — no download occurs here.
    """
    logger.info("Loading InsightFace buffalo_l (SCRFD + ArcFace R100)")
    face_app = FaceAnalysis(
        name="buffalo_l",
        providers=["CPUExecutionProvider"],
    )
    # ctx_id=0 for CPU; det_size=(640,640) for full-resolution face detection
    face_app.prepare(ctx_id=0, det_size=(640, 640))
    logger.info("InsightFace buffalo_l loaded successfully")
    return face_app


def analyze_frame(
    frame_path: Path,
    face_app: FaceAnalysis,
) -> list[dict]:
    """
    Run InsightFace SCRFD + ArcFace on a single frame (full frame, not crop).
    Returns a list of raw face dicts — each has:
        bbox_x1, bbox_y1, bbox_x2, bbox_y2: int pixel coordinates
        det_score: float — SCRFD face detector confidence
        normed_embedding: list[float] (512-dim, L2-normalized)

    Caller (run_insightface in pipeline.py) is responsible for pgvector matching.
    """
    frame_bgr = cv2.imread(str(frame_path))
    if frame_bgr is None:
        logger.warning("Could not read frame image: %s", frame_path)
        return []

    try:
        faces = face_app.get(frame_bgr)
    except Exception as exc:
        logger.error("InsightFace inference failed on %s: %s", frame_path.name, exc)
        return []

    results = []
    for face in faces:
        # CRITICAL: use face.normed_embedding, not face.embedding
        # normed_embedding is L2-normalized (unit vector) — correct for cosine similarity
        # face.embedding is raw (unnormalized) — DO NOT use for DB storage
        normed_emb = face.normed_embedding
        if normed_emb is None:
            logger.debug("Face has no normed_embedding — skipped (det_score=%.3f)", face.det_score)
            continue

        # Sanity check: normed_embedding should be unit vector (L2 norm ≈ 1.0)
        # If this fires, something is wrong with the InsightFace version or usage
        norm = float(np.linalg.norm(normed_emb))
        if abs(norm - 1.0) > 0.01:
            logger.warning(
                "normed_embedding L2 norm=%.4f (expected ~1.0) — "
                "check InsightFace version; do NOT use face.embedding instead",
                norm,
            )

        bbox = face.bbox  # [x1, y1, x2, y2] as floats
        results.append({
            "bbox_x1": int(bbox[0]),
            "bbox_y1": int(bbox[1]),
            "bbox_x2": int(bbox[2]),
            "bbox_y2": int(bbox[3]),
            "det_score": float(face.det_score),
            "normed_embedding": normed_emb.tolist(),   # convert numpy → list for pgvector
        })

    return results


async def match_face_embedding(
    normed_embedding: list[float],
    pool,
) -> tuple[Optional[str], Optional[float], Optional[str]]:
    """
    Search person_embeddings table via pgvector HNSW cosine similarity.
    Returns (matched_person_id, similarity, match_tier).

    Two-tier threshold:
        similarity >= FACE_MATCH_HIGH_THRESHOLD → (person_id, sim, 'confident')
        FACE_MATCH_LOW_THRESHOLD <= sim < HIGH  → (person_id, sim, 'probable')
        sim < FACE_MATCH_LOW_THRESHOLD          → (None, similarity, None) — genuine unknown

    Uses the HNSW index (m=32, ef_construction=128) with ef_search=64 set at DB level.
    Searches ALL embeddings for the best match (a person may have multiple enrollment images).

    pgvector cosine distance operator (<=>): distance = 1 - cosine_similarity
    So similarity = 1 - distance.

    Even when similarity is below the low threshold, the similarity value is returned
    for audit logging (stored in match_similarity column even when matched_person_id is NULL).
    """
    high = config.FACE_MATCH_HIGH_THRESHOLD   # 0.65
    low = config.FACE_MATCH_LOW_THRESHOLD     # 0.50

    async with pool.acquire() as conn:
        # Best match: lowest cosine distance = highest cosine similarity
        # LIMIT 1 leverages the HNSW index efficiently
        row = await conn.fetchrow(
            """
            SELECT
                pe.person_id::text AS person_id,
                1.0 - (pe.normed_embedding <=> $1::vector) AS similarity
            FROM person_embeddings pe
            ORDER BY pe.normed_embedding <=> $1::vector
            LIMIT 1
            """,
            normed_embedding,
        )

    if row is None:
        # No persons enrolled yet — store as unknown
        return None, None, None

    similarity = float(row["similarity"])
    person_id = row["person_id"]

    if similarity >= high:
        return person_id, similarity, "confident"
    elif similarity >= low:
        return person_id, similarity, "probable"
    else:
        # Below low threshold — genuine unknown, enters HDBSCAN pool (Phase 3)
        return None, similarity, None
