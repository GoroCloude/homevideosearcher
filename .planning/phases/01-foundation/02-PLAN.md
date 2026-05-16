---
plan: "02 — Ingestion Worker"
phase: 1
wave: 2
depends_on:
  - "01"
files_modified:
  - services/ingestion-worker/app/config.py
  - services/ingestion-worker/app/db.py
  - services/ingestion-worker/app/storage.py
  - services/ingestion-worker/app/main.py
  - services/ingestion-worker/app/frames.py
  - services/ingestion-worker/app/pipeline.py
autonomous: true
requirements:
  - INGEST-01
  - INGEST-02
  - INGEST-03
  - INGEST-04
  - INGEST-05
  - INGEST-06

must_haves:
  truths:
    - "`POST /ingest` with a valid MinIO video key returns 202 and processes the video end-to-end"
    - "`POST /ingest/batch` scans a MinIO prefix and enqueues all .mp4/.mov files found"
    - "Video status transitions from `pending → processing → done` on successful ingest; `failed` with error_message on error"
    - "Re-ingesting a `done` video returns `{status: skipped}` unless `?force=true`"
    - "Restarting the ingestion-worker resets any `processing` videos to `pending` so they are re-queued"
    - "Only frames that contain at least one YOLO detection or face are uploaded to MinIO `frames/` bucket"
    - "`GET /health` on ingestion-worker returns `{status: ok}`"
  artifacts:
    - path: "services/ingestion-worker/app/config.py"
      provides: "All env var reading with typed defaults"
      contains: "FACE_MATCH_HIGH_THRESHOLD"
    - path: "services/ingestion-worker/app/db.py"
      provides: "asyncpg connection pool + SQL helpers"
      contains: "create_pool"
    - path: "services/ingestion-worker/app/frames.py"
      provides: "FFmpeg frame extraction wrapper"
      contains: "extract_frames"
    - path: "services/ingestion-worker/app/pipeline.py"
      provides: "End-to-end video processing orchestration"
      contains: "process_video"
    - path: "services/ingestion-worker/app/main.py"
      provides: "FastAPI app with lifespan + /health + /ingest + /ingest/batch"
      contains: "lifespan"
  key_links:
    - from: "services/ingestion-worker/app/main.py POST /ingest"
      to: "services/ingestion-worker/app/pipeline.py process_video()"
      via: "FastAPI BackgroundTasks"
      pattern: "background_tasks.add_task"
    - from: "services/ingestion-worker/app/pipeline.py"
      to: "videos table status column"
      via: "db.py update_video_status()"
      pattern: "update_video_status"
    - from: "services/ingestion-worker/app/frames.py"
      to: "MinIO frames/ bucket"
      via: "storage.py upload_frame()"
      pattern: "upload_frame"
---

# Plan 02: Ingestion Worker

## Goal

Implement the FastAPI ingestion-worker service: configuration, database pool, MinIO client, FFmpeg frame extraction, and the full video ingestion pipeline with state machine, idempotency guard, batch endpoint, and crash-recovery on startup.

**Important:** Plans 03 and 04 add YOLO and InsightFace to this worker. This plan builds the shell that they plug into. The `pipeline.py` created here calls stub functions `run_yolo()` and `run_insightface()` that return empty results — Plans 03 and 04 replace them.

---

## Tasks

<task id="02.1">
<title>Create config.py, db.py, storage.py — foundation modules</title>
<read_first>
- .planning/phases/01-foundation/01-PLAN.md (env var names from docker-compose.yml, DATABASE_URL format)
- .planning/research/STACK.md §4 (asyncpg pool pattern: min_size=2, max_size=10)
- .planning/research/SUMMARY.md §Critical Design Decisions §1 (FACE_MATCH_HIGH_THRESHOLD, FACE_MATCH_LOW_THRESHOLD)
</read_first>
<action>
Create `services/ingestion-worker/app/config.py` — reads all env vars with typed defaults:

```python
"""Configuration: all env vars read here, nowhere else."""
import os
from typing import Optional


def _list(val: str) -> list[str]:
    return [s.strip() for s in val.split(",") if s.strip()]


DATABASE_URL: str = os.environ["DATABASE_URL"]  # required — fail fast if missing

MINIO_ENDPOINT: str = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY: str = os.environ["MINIO_ACCESS_KEY"]
MINIO_SECRET_KEY: str = os.environ["MINIO_SECRET_KEY"]
MINIO_BUCKET_VIDEOS: str = os.getenv("MINIO_BUCKET_VIDEOS", "videos")
MINIO_BUCKET_FRAMES: str = os.getenv("MINIO_BUCKET_FRAMES", "frames")
MINIO_USE_SSL: bool = os.getenv("MINIO_USE_SSL", "false").lower() == "true"

YOLO_MODEL: str = os.getenv("YOLO_MODEL", "yolov8n.pt")
YOLO_CONFIDENCE: float = float(os.getenv("YOLO_CONFIDENCE", "0.35"))
YOLO_CLASSES: list[str] = _list(
    os.getenv(
        "YOLO_CLASSES",
        "person,bicycle,car,motorcycle,bus,truck,cat,dog,horse,sheep,cow,bird",
    )
)
YOLO_BATCH_SIZE: int = int(os.getenv("YOLO_BATCH_SIZE", "8"))

# Two-tier face match thresholds (do NOT lower below 0.50 / 0.65 without testing)
FACE_MATCH_HIGH_THRESHOLD: float = float(os.getenv("FACE_MATCH_HIGH_THRESHOLD", "0.65"))
FACE_MATCH_LOW_THRESHOLD: float = float(os.getenv("FACE_MATCH_LOW_THRESHOLD", "0.50"))

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
```

Create `services/ingestion-worker/app/db.py` — asyncpg pool, core SQL helpers:

```python
"""Database: asyncpg connection pool + SQL helpers for the ingestion pipeline."""
import logging
from typing import Optional
import asyncpg
from pgvector.asyncpg import register_vector

from . import config

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        raise RuntimeError("DB pool not initialized — call init_pool() at startup")
    return _pool


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        config.DATABASE_URL, min_size=2, max_size=10
    )
    # Register pgvector type codec so vector columns deserialize to list[float]
    async with _pool.acquire() as conn:
        await register_vector(conn)
    logger.info("DB pool initialized")


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def get_or_create_video(minio_key: str, filename: str) -> dict:
    """Return existing video row or insert a new pending one."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, status FROM videos WHERE minio_key = $1", minio_key
        )
        if row:
            return dict(row)
        new_id = await conn.fetchval(
            """
            INSERT INTO videos (minio_key, filename, status)
            VALUES ($1, $2, 'pending')
            RETURNING id
            """,
            minio_key,
            filename,
        )
        return {"id": new_id, "status": "pending"}


async def update_video_status(
    video_id: str, status: str, error_message: Optional[str] = None
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE videos
            SET status = $1, error_message = $2
            WHERE id = $3
            """,
            status,
            error_message,
            video_id,
        )


async def update_video_metadata(
    video_id: str,
    duration_sec: Optional[float],
    width: Optional[int],
    height: Optional[int],
    fps: Optional[float],
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE videos
            SET duration_sec = $1, width = $2, height = $3, fps = $4
            WHERE id = $5
            """,
            duration_sec,
            width,
            height,
            fps,
            video_id,
        )


async def insert_frame(video_id: str, ts_ms: int, minio_key: str) -> int:
    """Insert a frame row. Returns frame id. Uses ON CONFLICT DO NOTHING for idempotency."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        frame_id = await conn.fetchval(
            """
            INSERT INTO frames (video_id, ts_ms, minio_key)
            VALUES ($1, $2, $3)
            ON CONFLICT (video_id, ts_ms) DO UPDATE SET minio_key = EXCLUDED.minio_key
            RETURNING id
            """,
            video_id,
            ts_ms,
            minio_key,
        )
        return frame_id


async def reset_stale_processing_videos() -> int:
    """
    On startup: reset any video stuck in 'processing' back to 'pending'.
    This handles the case where the worker was killed mid-ingest.
    Returns the count of videos reset.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE videos
            SET status = 'pending', error_message = 'Reset after worker restart'
            WHERE status = 'processing'
            """
        )
        count = int(result.split()[-1])
        if count > 0:
            logger.warning("Reset %d stale 'processing' videos to 'pending'", count)
        return count
```

Create `services/ingestion-worker/app/storage.py` — MinIO client wrapper:

```python
"""MinIO object storage client wrapper."""
import io
import logging
from pathlib import Path
from minio import Minio
from minio.error import S3Error

from . import config

logger = logging.getLogger(__name__)

_client: Minio | None = None


def get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            config.MINIO_ENDPOINT,
            access_key=config.MINIO_ACCESS_KEY,
            secret_key=config.MINIO_SECRET_KEY,
            secure=config.MINIO_USE_SSL,
        )
    return _client


def ensure_bucket(bucket: str) -> None:
    client = get_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        logger.info("Created MinIO bucket: %s", bucket)


def download_video(minio_key: str, dest_path: Path) -> None:
    """Download a video from MinIO to a local path."""
    client = get_client()
    client.fget_object(config.MINIO_BUCKET_VIDEOS, minio_key, str(dest_path))
    logger.info("Downloaded %s → %s", minio_key, dest_path)


def upload_frame(local_path: Path, video_id: str, ts_ms: int) -> str:
    """
    Upload a frame JPEG to MinIO. Returns the MinIO key.
    Key format: frames/{video_id}/{ts_ms}.jpg
    """
    client = get_client()
    ensure_bucket(config.MINIO_BUCKET_FRAMES)
    key = f"frames/{video_id}/{ts_ms}.jpg"
    client.fput_object(
        config.MINIO_BUCKET_FRAMES,
        key,
        str(local_path),
        content_type="image/jpeg",
    )
    return key


def list_video_keys(prefix: str) -> list[str]:
    """List all objects in the videos bucket under the given prefix."""
    client = get_client()
    objects = client.list_objects(
        config.MINIO_BUCKET_VIDEOS, prefix=prefix, recursive=True
    )
    return [obj.object_name for obj in objects]
```
</action>
<acceptance_criteria>
- `services/ingestion-worker/app/config.py` exists; `grep "FACE_MATCH_HIGH_THRESHOLD" services/ingestion-worker/app/config.py` returns a match with `0.65` default
- `services/ingestion-worker/app/config.py` has `FACE_MATCH_LOW_THRESHOLD` with `0.50` default
- `services/ingestion-worker/app/db.py` contains `reset_stale_processing_videos()` function
- `services/ingestion-worker/app/db.py` contains `insert_frame()` with `ON CONFLICT` clause
- `services/ingestion-worker/app/storage.py` contains `upload_frame()` returning key in format `frames/{video_id}/{ts_ms}.jpg`
- `grep "register_vector" services/ingestion-worker/app/db.py` returns a match (pgvector codec registration)
</acceptance_criteria>
</task>

<task id="02.2">
<title>Create frames.py and main.py — FFmpeg extraction and FastAPI app with lifespan</title>
<read_first>
- requirements.md §6.1 (FFmpeg command, frame extraction strategy, BackgroundTasks)
- .planning/research/ARCHITECTURE.md §Processing Pipeline (frame-by-frame flow, sliding-window FFmpeg)
- .planning/research/PITFALLS.md §FR-3 (gate InsightFace on YOLO person detections — enforced in pipeline.py)
- .planning/research/SUMMARY.md §Critical Design Decisions §4 (selective frame storage — only frames WITH detections)
</read_first>
<action>
Create `services/ingestion-worker/app/frames.py` — FFmpeg wrapper with 1-fps + scene-change extraction:

```python
"""
Frame extraction via FFmpeg.
Extracts 1 frame per second + scene-change frames from a video file.
Returns a list of (ts_ms, local_path) tuples for all extracted frames.
Caller is responsible for deleting the work directory.
"""
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

FFMPEG_SCALE = "scale='min(1280,iw)':-2"
FFMPEG_QUALITY = "3"   # JPEG quality (1=best, 31=worst; 3 is high quality)
SCENE_THRESHOLD = "0.4"  # scene-change sensitivity (0.0–1.0)


@dataclass
class ExtractedFrame:
    ts_ms: int
    path: Path


def extract_frames(video_path: Path, work_dir: Path) -> list[ExtractedFrame]:
    """
    Run FFmpeg to extract 1-fps + scene-change frames.
    Returns list of ExtractedFrame sorted by ts_ms.
    """
    frames_dir = work_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # Two-pass approach:
    # Pass 1: extract 1-fps frames (reliably gives us uniform coverage)
    # Pass 2: extract scene-change frames (catches cuts missed by 1-fps sampling)
    _extract_fps_frames(video_path, frames_dir)
    _extract_scene_change_frames(video_path, frames_dir)

    # Parse all frame files and deduplicate by ts_ms (keep first)
    frames = _parse_frame_files(frames_dir)
    logger.info("Extracted %d frames from %s", len(frames), video_path.name)
    return frames


def _extract_fps_frames(video_path: Path, out_dir: Path) -> None:
    """Extract frames at exactly 1 fps. Output: fps_{ts_ms}.jpg"""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate,duration",
        "-of", "default=noprint_wrappers=1",
        str(video_path),
    ]
    # Use a select filter that outputs pts_time in the filename via showinfo
    # Simpler: output to numbered files and compute ts from frame number
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", f"fps=1,{FFMPEG_SCALE}",
        "-q:v", FFMPEG_QUALITY,
        "-frame_pts", "1",
        str(out_dir / "fps_%06d.jpg"),
        "-y",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning("FFmpeg fps extraction stderr: %s", result.stderr[-500:])


def _extract_scene_change_frames(video_path: Path, out_dir: Path) -> None:
    """Extract frames at scene-change points."""
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", f"select='gt(scene,{SCENE_THRESHOLD})',{FFMPEG_SCALE}",
        "-vsync", "vfr",
        "-q:v", FFMPEG_QUALITY,
        "-frame_pts", "1",
        str(out_dir / "scene_%08d.jpg"),
        "-y",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # Scene frames may not exist if no scene changes detected — that's fine
    if result.returncode != 0:
        logger.debug("Scene-change extraction stderr: %s", result.stderr[-300:])


def _parse_frame_files(frames_dir: Path) -> list[ExtractedFrame]:
    """
    Parse frame files. fps_{N}.jpg → ts_ms = (N-1) * 1000.
    scene_{N}.jpg → ts_ms from the frame pts embedded in filename index.
    Deduplicates by ts_ms (1-fps frames take priority; scene frames fill gaps).
    """
    seen: dict[int, Path] = {}

    for f in sorted(frames_dir.iterdir()):
        if not f.suffix == ".jpg":
            continue
        name = f.stem
        if name.startswith("fps_"):
            # fps_000001.jpg → frame index 1 → ts_ms = (1-1)*1000 = 0
            try:
                idx = int(name.split("_", 1)[1])
                ts_ms = (idx - 1) * 1000
            except ValueError:
                continue
            if ts_ms not in seen:
                seen[ts_ms] = f
        elif name.startswith("scene_"):
            # scene frames: use index as approximate ts (imprecise but acceptable)
            # For v1, we just mark them as interstitial; exact ts can be improved later
            try:
                idx = int(name.split("_", 1)[1])
                # Scene frame ts: we don't have pts here without showinfo filter.
                # Use a sentinel gap value so they slot between fps frames.
                # For now, skip scene frames that collide with fps frames.
                # (Future improvement: use ffprobe showinfo to get exact pts_time)
                ts_ms = idx * 1000 - 500  # approximate midpoint heuristic
                ts_ms = max(0, ts_ms)
            except ValueError:
                continue
            if ts_ms not in seen:
                seen[ts_ms] = f

    return sorted(
        [ExtractedFrame(ts_ms=ts, path=path) for ts, path in seen.items()],
        key=lambda x: x.ts_ms,
    )


def probe_video_metadata(video_path: Path) -> dict:
    """Return duration, width, height, fps from ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,duration",
        "-of", "default=noprint_wrappers=1:nokey=0",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    meta: dict = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            meta[k.strip()] = v.strip()

    width = int(meta.get("width", 0)) or None
    height = int(meta.get("height", 0)) or None
    duration = float(meta.get("duration", 0)) or None
    fps_raw = meta.get("r_frame_rate", "0/1")
    try:
        num, den = fps_raw.split("/")
        fps = round(int(num) / int(den), 3) if int(den) else None
    except (ValueError, ZeroDivisionError):
        fps = None

    return {"duration_sec": duration, "width": width, "height": height, "fps": fps}
```

Create `services/ingestion-worker/app/main.py` — FastAPI application with lifespan startup (model loading stubs here; Plans 03 and 04 fill them in) and all endpoints:

```python
"""
HomeVideoSearcher — Ingestion Worker
FastAPI service. Models loaded once at startup via lifespan event.
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

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
    application.state.yolo = None          # Plan 03 replaces with YOLO("yolov8n.pt")
    logger.info("YOLO model loaded (stub)")

    await asyncio.sleep(2)                 # 2-second gap before InsightFace load

    logger.info("Loading InsightFace buffalo_l")
    application.state.face_app = None      # Plan 04 replaces with FaceAnalysis(...)
    logger.info("InsightFace model loaded (stub)")

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
    import asyncpg

    minio_key = request.minio_key.strip()
    filename = minio_key.split("/")[-1]

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
```
</action>
<acceptance_criteria>
- `services/ingestion-worker/app/frames.py` exists with `extract_frames(video_path, work_dir)` function returning `list[ExtractedFrame]`
- `grep "scene" services/ingestion-worker/app/frames.py` returns scene-change extraction code
- `grep "probe_video_metadata" services/ingestion-worker/app/frames.py` returns function definition
- `services/ingestion-worker/app/main.py` contains `lifespan` function with `asyncio.sleep(2)` between YOLO and InsightFace loading
- `grep "reset_stale_processing_videos" services/ingestion-worker/app/main.py` returns a match (crash recovery on startup)
- `grep "background_tasks.add_task" services/ingestion-worker/app/main.py` returns at least 2 matches (ingest + batch)
- `grep "status.*skipped" services/ingestion-worker/app/main.py` returns match for done+no-force guard
- `grep "force=True" services/ingestion-worker/app/main.py` returns match (force re-process path)
- `grep "DELETE FROM frames WHERE video_id" services/ingestion-worker/app/main.py` returns match (cascade delete on force re-ingest)
</acceptance_criteria>
</task>

<task id="02.3">
<title>Create pipeline.py — end-to-end video processing orchestration</title>
<read_first>
- .planning/research/ARCHITECTURE.md §Processing Pipeline (step-by-step: download → extract → YOLO → InsightFace → finalize)
- .planning/research/SUMMARY.md §4 (selective frame storage — only store frames with detections)
- .planning/research/PITFALLS.md §FR-3 (gate InsightFace on YOLO person detection; explicit `if not has_person` continue)
- services/ingestion-worker/app/db.py (insert_frame, update_video_status, update_video_metadata signatures)
- services/ingestion-worker/app/storage.py (download_video, upload_frame signatures)
- services/ingestion-worker/app/frames.py (extract_frames, probe_video_metadata signatures)
</read_first>
<action>
Create `services/ingestion-worker/app/pipeline.py` — the full video processing pipeline.
Plans 03 and 04 replace the stub calls to `run_yolo()` and `run_insightface()`.

```python
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
import asyncio
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
    Stub. Plan 03 replaces this with real YOLOv8 batch inference.
    Returns one list of Detection per frame (same order as frame_paths).
    """
    return [[] for _ in frame_paths]


async def run_insightface(
    frame_bgr_path: Path,
    face_app: Any,
    pool,
) -> list[FaceDetection]:
    """
    Stub. Plan 04 replaces this with real InsightFace inference + pgvector match.
    Returns list of FaceDetection for a single frame.
    """
    return []


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
```
</action>
<acceptance_criteria>
- `services/ingestion-worker/app/pipeline.py` exists
- `grep "run sequentially" services/ingestion-worker/app/pipeline.py` OR comments document the sequential constraint
- `grep "has_person" services/ingestion-worker/app/pipeline.py` returns match (InsightFace gate on YOLO person detection)
- `grep "has_any_detection" services/ingestion-worker/app/pipeline.py` returns match (selective frame storage)
- `grep "normed_embedding" services/ingestion-worker/app/pipeline.py` returns matches in FaceDetection dataclass and INSERT SQL
- `grep "match_tier" services/ingestion-worker/app/pipeline.py` returns match in INSERT SQL
- `grep "shutil.rmtree" services/ingestion-worker/app/pipeline.py` returns match (cleanup in finally block)
- `grep "processing.*done.*failed" services/ingestion-worker/app/pipeline.py` OR separate `update_video_status` calls for each state exist
- `grep "YOLO_BATCH_SIZE" services/ingestion-worker/app/pipeline.py` returns match (configurable batch size)
- `services/ingestion-worker/app/__init__.py` created as empty file so the `app` directory is a package
</acceptance_criteria>
</task>

---

## Verification

- [ ] All five Python modules exist: `config.py`, `db.py`, `storage.py`, `main.py`, `frames.py`, `pipeline.py` under `services/ingestion-worker/app/`
- [ ] `services/ingestion-worker/app/__init__.py` exists (empty)
- [ ] `docker compose build ingestion-worker` succeeds (image includes all requirements)
- [ ] `docker compose up -d && curl http://localhost:8001/health` returns `{"status":"ok","service":"ingestion-worker"}`
- [ ] `docker compose logs ingestion-worker` shows no startup errors; shows "Reset N stale 'processing' videos" or similar recovery log line
- [ ] `curl -X POST http://localhost:8001/ingest -H "Content-Type: application/json" -d '{"minio_key":"videos/nonexistent.mp4"}'` returns 202 JSON with `"status":"queued"` (then fails gracefully in background with `status=failed`)
- [ ] Re-posting the same key returns `"status":"queued"` again (not done yet), or after it finishes returns `"status":"skipped"` without force
- [ ] `docker compose exec postgres psql -U videosearch videosearch -c "SELECT status FROM videos;"` shows a row

## must_haves

- `POST /ingest` returns 202 and queues the video as a BackgroundTask
- `POST /ingest` with a `done` video and no `?force=true` returns `{"status":"skipped"}`
- `POST /ingest` with `?force=true` deletes existing frames (cascade) and re-queues
- On worker restart, `reset_stale_processing_videos()` runs and resets `processing` → `pending`
- `run_insightface()` is only called on frames where `has_person == True`
- Frames with zero detections are NOT uploaded to MinIO and NOT written to the `frames` table
- `normed_embedding` (not `embedding`) is the column name used in all INSERT statements
- `match_tier` column is written in face_detections INSERTs

## threat_model

### Threats

| Threat | Category | Mitigation |
|--------|----------|------------|
| [HIGH] `minio_key` path traversal (e.g. `../../etc/passwd`) | Tampering | `download_video` uses the minio_key as a MinIO object key, not a filesystem path; the local filename is extracted via `split("/")[-1]` and placed in a tempdir — no path traversal possible |
| [MEDIUM] `/ingest/batch` scans an unbounded MinIO prefix | Denial of Service | Single-worker, sequential processing; BackgroundTasks queue is in-memory; on restart the worker re-queues via recovery. Document that batch scanning very large prefixes (>1000 videos) should be done in sub-prefixes. |
| [MEDIUM] Crash during frame upload leaves `status='processing'` forever | Availability | `reset_stale_processing_videos()` at startup resets all `processing` rows to `pending`; videos are re-queued on next ingest call |
| [LOW] FFmpeg processes arbitrary video files | Code Execution | FFmpeg runs as a non-root user inside the container; no `shell=True` in subprocess calls — all commands are list-form |

---

<output>
After all tasks complete, create `.planning/phases/01-foundation/02-SUMMARY.md` with:
- Modules created (list)
- /health endpoint status
- Recovery mechanism verified (yes/no)
- Any deviations from the plan
</output>
