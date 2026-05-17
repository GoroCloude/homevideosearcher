"""
Video processing pipeline.
Orchestrates: download → extract frames → YOLO detection → InsightFace faces → write DB.

CRITICAL DESIGN CONSTRAINTS (do not violate):
1. YOLO runs first on all frames (batch). InsightFace runs second, per-frame.
2. YOLO and InsightFace NEVER run in parallel — sequential only (memory constraint).
3. InsightFace only runs on frames where YOLO detected at least one 'person' class.
4. Only frames WITH at least one detection (YOLO or face) are uploaded to MinIO.
5. Embeddings stored as normed_embedding (face.normed_embedding, not face.embedding).
"""
import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import config
from .db import (
    get_pool,
    insert_frame,
    update_video_metadata,
    update_video_status,
)
from .frames import ExtractedFrame, extract_frames, probe_video_metadata
from .storage import download_video, upload_frame

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    class_name: str
    confidence: float
    bbox_x1: int
    bbox_y1: int
    bbox_x2: int
    bbox_y2: int


@dataclass
class FaceDetection:
    bbox_x1: int
    bbox_y1: int
    bbox_x2: int
    bbox_y2: int
    det_score: float
    normed_embedding: list[float]   # 512-dim, L2-normalized
    matched_person_id: Optional[str]
    match_similarity: Optional[float]
    match_tier: Optional[str]       # 'confident' | 'probable' | None


@dataclass
class ProcessingResult:
    video_id: str
    frames_extracted: int = 0
    frames_stored: int = 0          # only frames with detections
    detections_written: int = 0
    faces_written: int = 0


# ── Stub functions — replaced by Plans 03 and 04 ─────────────────────────────

def run_yolo(
    frame_paths: list[Path],
    yolo_model: Any,
) -> list[list[Detection]]:
    """
    Run YOLOv8 batch inference on a list of frame paths.
    Each call processes up to YOLO_BATCH_SIZE frames.
    Returns one list[Detection] per frame (same order as frame_paths).
    CRITICAL: Never called in parallel with run_insightface — sequential only.
    """
    if yolo_model is None:
        logger.warning("YOLO model not loaded — returning empty detections")
        return [[] for _ in frame_paths]

    from .detect import run_yolo_batch, _resolve_class_ids
    allowed_ids = _resolve_class_ids(config.YOLO_CLASSES)
    return run_yolo_batch(frame_paths, yolo_model, allowed_ids)


async def run_insightface(
    frame_bgr_path: Path,
    face_app: Any,
    pool,
) -> list[FaceDetection]:
    """
    Run InsightFace buffalo_l on a single frame, then match each face against
    person_embeddings via pgvector HNSW cosine search.

    Returns one FaceDetection per detected face in the frame.

    CRITICAL DESIGN POINTS:
    - Called ONLY on frames where YOLO detected 'person' (enforced in process_video)
    - Runs AFTER all YOLO batch inference is complete (sequential, never parallel)
    - Uses face.normed_embedding (NOT face.embedding) — L2-normalized 512-dim vector
    - Stores YOLO person detections and face detections in SEPARATE tables (FACE-05)
    - Unmatched faces (similarity < LOW_THRESHOLD or no persons enrolled):
        matched_person_id = NULL, match_tier = NULL → enters HDBSCAN pool (Phase 3)
    """
    if face_app is None:
        logger.warning("InsightFace not loaded — returning empty face detections")
        return []

    from .faces import analyze_frame, match_face_embedding

    # Step 1: Detect faces and compute ArcFace embeddings (full frame, not YOLO crop)
    raw_faces = analyze_frame(frame_bgr_path, face_app)

    if not raw_faces:
        return []

    # Step 2: Match each face against enrolled persons via pgvector HNSW
    face_detections: list[FaceDetection] = []
    for raw in raw_faces:
        normed_emb = raw["normed_embedding"]

        matched_person_id, similarity, match_tier = await match_face_embedding(
            normed_emb, pool
        )

        face_detections.append(
            FaceDetection(
                bbox_x1=raw["bbox_x1"],
                bbox_y1=raw["bbox_y1"],
                bbox_x2=raw["bbox_x2"],
                bbox_y2=raw["bbox_y2"],
                det_score=raw["det_score"],
                normed_embedding=normed_emb,
                matched_person_id=matched_person_id,
                match_similarity=similarity,
                match_tier=match_tier,
            )
        )

    # Log tier breakdown for observability
    confident = sum(1 for f in face_detections if f.match_tier == "confident")
    probable = sum(1 for f in face_detections if f.match_tier == "probable")
    unknown = sum(1 for f in face_detections if f.match_tier is None)
    logger.debug(
        "Frame %s: %d faces — confident=%d probable=%d unknown=%d",
        frame_bgr_path.name,
        len(face_detections),
        confident,
        probable,
        unknown,
    )

    return face_detections


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def process_video(
    video_id: str,
    minio_key: str,
    yolo_model: Any,
    face_app: Any,
) -> ProcessingResult:
    """
    Full pipeline for one video. Called as a FastAPI BackgroundTask.
    State machine: pending → processing → done | failed
    """
    result = ProcessingResult(video_id=video_id)
    work_dir = Path(tempfile.mkdtemp(prefix=f"hvs_{video_id}_"))

    try:
        await update_video_status(video_id, "processing")
        logger.info("[%s] Starting pipeline for %s", video_id[:8], minio_key)

        # ── Step 1: Download video from MinIO ────────────────────────────────
        video_path = work_dir / minio_key.split("/")[-1]
        download_video(minio_key, video_path)

        # ── Step 2: Probe metadata ────────────────────────────────────────────
        meta = probe_video_metadata(video_path)
        await update_video_metadata(
            video_id,
            meta.get("duration_sec"),
            meta.get("width"),
            meta.get("height"),
            meta.get("fps"),
        )

        # ── Step 3: Extract frames ────────────────────────────────────────────
        frames: list[ExtractedFrame] = extract_frames(video_path, work_dir)
        result.frames_extracted = len(frames)
        logger.info("[%s] Extracted %d frames", video_id[:8], len(frames))

        if not frames:
            logger.warning("[%s] No frames extracted — marking done (empty video?)", video_id[:8])
            await update_video_status(video_id, "done")
            return result

        # ── Step 4: YOLO batch inference (all frames) ─────────────────────────
        # YOLO runs first on ALL frames in batches of YOLO_BATCH_SIZE.
        # Result: one list[Detection] per frame, in the same order as `frames`.
        logger.info("[%s] Running YOLO on %d frames", video_id[:8], len(frames))
        frame_paths = [f.path for f in frames]
        all_yolo_results: list[list[Detection]] = []

        for batch_start in range(0, len(frame_paths), config.YOLO_BATCH_SIZE):
            batch = frame_paths[batch_start : batch_start + config.YOLO_BATCH_SIZE]
            batch_results = run_yolo(batch, yolo_model)
            all_yolo_results.extend(batch_results)
            logger.debug(
                "[%s] YOLO batch %d/%d: %d detections",
                video_id[:8],
                batch_start // config.YOLO_BATCH_SIZE + 1,
                (len(frame_paths) + config.YOLO_BATCH_SIZE - 1) // config.YOLO_BATCH_SIZE,
                sum(len(r) for r in batch_results),
            )

        # ── Step 5: InsightFace per-frame (only on frames with person detections)
        # InsightFace runs AFTER YOLO. Never parallel. Only on 'person' frames.
        pool = await get_pool()

        for i, frame in enumerate(frames):
            yolo_detections = all_yolo_results[i] if i < len(all_yolo_results) else []
            has_person = any(d.class_name == "person" for d in yolo_detections)

            # Run InsightFace only on frames with at least one 'person' YOLO detection
            face_detections: list[FaceDetection] = []
            if has_person and face_app is not None:
                face_detections = await run_insightface(frame.path, face_app, pool)

            # Selective frame storage: only upload frames that have any detection
            has_any_detection = bool(yolo_detections) or bool(face_detections)
            if not has_any_detection:
                continue   # Skip frames with nothing detected — don't waste MinIO space

            # Upload frame to MinIO
            try:
                frame_minio_key = upload_frame(frame.path, video_id, frame.ts_ms)
            except Exception as exc:
                logger.error("[%s] Failed to upload frame ts=%d: %s", video_id[:8], frame.ts_ms, exc)
                continue

            # Write frame row to DB
            frame_id = await insert_frame(video_id, frame.ts_ms, frame_minio_key)
            result.frames_stored += 1

            # Write YOLO detections
            if yolo_detections:
                await _write_detections(pool, frame_id, yolo_detections)
                result.detections_written += len(yolo_detections)

            # Write InsightFace face detections
            if face_detections:
                await _write_face_detections(pool, frame_id, face_detections)
                result.faces_written += len(face_detections)
                # NOTE (FACE-05): YOLO detections and InsightFace face detections are written
                # to separate tables (detections vs face_detections). A 'person' YOLO detection
                # means "a person-shaped object exists" — back turned, far away, no face visible.
                # A face_detection means "a face was detected and embedded". Both are stored
                # independently. The face pipeline runs only when has_person=True, but may
                # find 0 faces even when YOLO found a 'person' (face not visible to camera).

        # ── Step 6: Finalize ──────────────────────────────────────────────────
        await update_video_status(video_id, "done")
        logger.info(
            "[%s] Done. frames_extracted=%d stored=%d detections=%d faces=%d",
            video_id[:8],
            result.frames_extracted,
            result.frames_stored,
            result.detections_written,
            result.faces_written,
        )
        return result

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.exception("[%s] Pipeline failed: %s", video_id[:8], error_msg)
        await update_video_status(video_id, "failed", error_message=error_msg)
        raise

    finally:
        # Always clean up the working directory
        shutil.rmtree(work_dir, ignore_errors=True)


# ── DB write helpers ─────────────────────────────────────────────────────────

async def _write_detections(pool, frame_id: int, detections: list[Detection]) -> None:
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO detections (frame_id, class_name, confidence,
                                    bbox_x1, bbox_y1, bbox_x2, bbox_y2)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            [
                (
                    frame_id,
                    d.class_name,
                    d.confidence,
                    d.bbox_x1,
                    d.bbox_y1,
                    d.bbox_x2,
                    d.bbox_y2,
                )
                for d in detections
            ],
        )


async def _write_face_detections(
    pool, frame_id: int, faces: list[FaceDetection]
) -> None:
    """
    Write face detections. normed_embedding is stored as a pgvector column.
    match_tier is 'confident', 'probable', or NULL (for unmatched faces).
    """
    async with pool.acquire() as conn:
        for face in faces:
            await conn.execute(
                """
                INSERT INTO face_detections (
                    frame_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                    det_score, normed_embedding,
                    matched_person_id, match_similarity, match_tier
                ) VALUES ($1, $2, $3, $4, $5, $6, $7::vector, $8, $9, $10)
                """,
                frame_id,
                face.bbox_x1,
                face.bbox_y1,
                face.bbox_x2,
                face.bbox_y2,
                face.det_score,
                face.normed_embedding,
                face.matched_person_id,
                face.match_similarity,
                face.match_tier,
            )
