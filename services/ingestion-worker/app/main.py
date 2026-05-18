"""
HomeVideoSearcher — Ingestion Worker
FastAPI service. Models loaded once at startup via lifespan event.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from pydantic import BaseModel

from . import config
from .db import close_pool, init_pool, reset_stale_processing_videos
from .pipeline import process_video, ProcessingResult
from .storage import list_video_keys, get_client

LOG_LEVEL = config.LOG_LEVEL
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup: init DB pool, load ML models, recover stale videos."""
    # 1. Initialize database connection pool
    await init_pool()

    # 2. Recovery: reset any videos stuck in 'processing' from a previous crash
    await reset_stale_processing_videos()

    # 3. Load ML models (Plans 03 and 04 add real implementations here)
    #    YOLO loads first; InsightFace loads 2 seconds later (memory spike stagger)
    logger.info("Loading YOLO model: %s", config.YOLO_MODEL)
    from .detect import load_yolo_model, _resolve_class_ids
    application.state.yolo = load_yolo_model()
    active_ids = _resolve_class_ids(config.YOLO_CLASSES)
    logger.info("YOLO active classes: %s → IDs: %s", config.YOLO_CLASSES, active_ids)
    logger.info("YOLO model ready")

    await asyncio.sleep(2)                 # 2-second gap before InsightFace load

    logger.info("Loading InsightFace buffalo_l (2s after YOLO to avoid RSS spike)")
    from .faces import load_face_model
    application.state.face_app = load_face_model()
    logger.info("InsightFace buffalo_l ready")

    yield

    # Shutdown: close DB pool
    await close_pool()
    logger.info("Shutdown complete")


app = FastAPI(title="HomeVideoSearcher Ingestion Worker", version="0.1.0", lifespan=lifespan)


# ── Request / Response models ────────────────────────────────────────────────

class IngestRequest(BaseModel):
    minio_key: str


class IngestResponse(BaseModel):
    status: str          # "queued" | "skipped" | "requeued"
    video_id: Optional[str] = None
    message: Optional[str] = None


class BatchIngestRequest(BaseModel):
    prefix: str          # MinIO prefix to scan, e.g. "videos/2024/"
    force: bool = False


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "ingestion-worker"}


@app.post("/ingest", response_model=IngestResponse, status_code=202)
async def ingest(
    request: IngestRequest,
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Re-process even if status=done"),
) -> IngestResponse:
    """
    Enqueue a single video for processing.
    If the video is already 'done' and force=False, returns status='skipped'.
    If force=True, resets the video and re-processes from scratch.
    """
    from .db import get_or_create_video, update_video_status, get_pool

    minio_key = request.minio_key.strip()
    filename = minio_key.split("/")[-1]

    # ── Defensive extension filter ────────────────────────────────────────
    # Guard against MinIO webhook firing for non-video uploads
    # (e.g., thumbnails, motion-detection images, config files).
    _VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
    _ext = Path(filename).suffix.lower()
    if _ext not in _VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported file type '{_ext}'. "
                f"Accepted: {', '.join(sorted(_VIDEO_EXTENSIONS))}"
            ),
        )
    # ─────────────────────────────────────────────────────────────────────

    # Check existing status
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, status FROM videos WHERE minio_key = $1", minio_key
        )

    if row and row["status"] == "done" and not force:
        return IngestResponse(
            status="skipped",
            video_id=str(row["id"]),
            message="Video already processed. Use ?force=true to re-process.",
        )

    if row and force:
        # Reset for reprocessing — delete existing frames/detections (cascade)
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM frames WHERE video_id = $1", row["id"]
            )
            await update_video_status(str(row["id"]), "pending")
        video_id = str(row["id"])
    else:
        video = await get_or_create_video(minio_key, filename)
        video_id = str(video["id"])

    # Queue background processing
    background_tasks.add_task(
        process_video,
        video_id=video_id,
        minio_key=minio_key,
        yolo_model=app.state.yolo,
        face_app=app.state.face_app,
    )
    logger.info("Queued video %s (id=%s)", minio_key, video_id)

    return IngestResponse(status="queued", video_id=video_id)


@app.post("/ingest/batch", status_code=202)
async def ingest_batch(
    request: BatchIngestRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """
    Scan a MinIO prefix and enqueue all video files found.
    Supported extensions: .mp4, .mov, .avi, .mkv
    """
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
    keys = list_video_keys(request.prefix)
    video_keys = [k for k in keys if any(k.lower().endswith(ext) for ext in VIDEO_EXTENSIONS)]

    if not video_keys:
        return {"status": "ok", "queued": 0, "message": f"No videos found under prefix '{request.prefix}'"}

    from .db import get_or_create_video, update_video_status, get_pool

    queued = 0
    skipped = 0
    for minio_key in video_keys:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, status FROM videos WHERE minio_key = $1", minio_key
            )
        if row and row["status"] == "done" and not request.force:
            skipped += 1
            continue

        filename = minio_key.split("/")[-1]
        if row and request.force:
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM frames WHERE video_id = $1", row["id"])
                await update_video_status(str(row["id"]), "pending")
            video_id = str(row["id"])
        else:
            video = await get_or_create_video(minio_key, filename)
            video_id = str(video["id"])

        background_tasks.add_task(
            process_video,
            video_id=video_id,
            minio_key=minio_key,
            yolo_model=app.state.yolo,
            face_app=app.state.face_app,
        )
        queued += 1

    logger.info("Batch: queued=%d skipped=%d prefix=%s", queued, skipped, request.prefix)
    return {
        "status": "ok",
        "queued": queued,
        "skipped": skipped,
        "prefix": request.prefix,
    }
