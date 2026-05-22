# Phase 10: Watch-Folder Auto-Ingest — Pattern Map

**Mapped:** 2025-07-13
**Files analyzed:** 8 new/modified files
**Analogs found:** 7 / 8 (1 new pattern: asyncio.Semaphore — no existing analog)

---

## File Classification

| New / Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `docker-compose.yml` (add `watcher` service) | config | request-response | `docker-compose.yml` `ingestion-worker` block (lines 20-48) | exact |
| `services/watcher/Dockerfile` | config | — | `services/ingestion-worker/Dockerfile` (lines 1-43) | exact |
| `services/watcher/app/config.py` | config | — | `services/ingestion-worker/app/config.py` (lines 1-32) | exact |
| `services/watcher/app/main.py` (daemon entry point) | service | event-driven | `services/ingestion-worker/app/main.py` (lines 1-22, lifespan/startup scan) | role-match |
| `services/watcher/app/storage.py` (MinIO upload) | utility | file-I/O | `services/ingestion-worker/app/storage.py` (lines 40-54) | exact |
| `services/watcher/app/watcher.py` (watchdog handler) | service | event-driven | `services/ingestion-worker/app/pipeline.py` (process_video loop) | partial |
| `services/ingestion-worker/app/pipeline.py` (add Semaphore) | service | batch | *(no existing analog — new pattern)* | none |
| `services/ingestion-worker/requirements.txt` (add watchdog) | config | — | `services/ingestion-worker/requirements.txt` | exact |

---

## Pattern Assignments

### 1. Docker Compose — `watcher` service block
**Analog:** `docker-compose.yml` lines 20-48 (`ingestion-worker` service)

**Clone and adjust** (lines 20-48):
```yaml
  ingestion-worker:
    build: ./services/ingestion-worker
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-videosearch}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB:-videosearch}
      MINIO_ENDPOINT: ${MINIO_ENDPOINT:-minio:9000}
      MINIO_ACCESS_KEY: ${MINIO_ACCESS_KEY}
      MINIO_SECRET_KEY: ${MINIO_SECRET_KEY}
      MINIO_BUCKET_VIDEOS: ${MINIO_BUCKET_VIDEOS:-videos}
      MINIO_BUCKET_FRAMES: ${MINIO_BUCKET_FRAMES:-frames}
      MINIO_USE_SSL: ${MINIO_USE_SSL:-false}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
    depends_on:
      postgres:
        condition: service_healthy
    deploy:
      resources:
        limits:
          memory: 5g
    networks:
      - home-infra
```

**What to change for watcher:**
- `build: ./services/watcher`
- Remove `ports` (watcher exposes none)
- Add `WATCH_DIR`, `WORKER_URL`, `WATCH_USE_POLLING` env vars
- Add `volumes:` bind-mount for the local watch folder (e.g., `- ${WATCH_FOLDER:-/data/videos}:/watch:ro`)
- `depends_on:` — add `ingestion-worker` with `condition: service_started` (no healthcheck needed)
- Drop `MINIO_BUCKET_FRAMES`, `DATABASE_URL` (watcher only needs MinIO + worker URL)
- Memory limit: `256m` (watchdog is lightweight)

---

### 2. Dockerfile — `services/watcher/Dockerfile`
**Analog:** `services/ingestion-worker/Dockerfile` (lines 1-43)

**Slim version to copy** (strip ML bake steps; keep uv pattern):
```dockerfile
FROM python:3.11-slim-bookworm                            # line 1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager (same pinned version as all services)
RUN pip install --no-cache-dir uv==0.11.14                # line 14

WORKDIR /app

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt   # line 24

COPY app/ ./app/

ENV PYTHONUNBUFFERED=1                                    # line 41

CMD ["python", "-m", "app.main"]
```

**Key rules:**
- `python:3.11-slim-bookworm` — matches every other service (line 1 of ingestion-worker/Dockerfile)
- `uv==0.11.14` — pinned version, same as ingestion-worker and api Dockerfiles
- `uv pip install --system --no-cache` — project-wide uv invocation pattern (line 24)
- `PYTHONUNBUFFERED=1` — required for streaming Docker logs (line 41)
- **No ML model bake steps** — watcher has no YOLO/InsightFace

---

### 3. Environment Variable Config — `services/watcher/app/config.py`
**Analog:** `services/ingestion-worker/app/config.py` (lines 1-32)

**Pattern to copy** (full file):
```python
"""Configuration: all env vars read here, nowhere else."""
import os

# ── Required (fail fast if missing) ──────────────────────────────────────────
MINIO_ENDPOINT:   str  = os.getenv("MINIO_ENDPOINT", "minio:9000")   # line 11
MINIO_ACCESS_KEY: str  = os.environ["MINIO_ACCESS_KEY"]              # line 12 — required
MINIO_SECRET_KEY: str  = os.environ["MINIO_SECRET_KEY"]              # line 13 — required
MINIO_BUCKET_VIDEOS: str = os.getenv("MINIO_BUCKET_VIDEOS", "videos")# line 14
MINIO_USE_SSL: bool = os.getenv("MINIO_USE_SSL", "false").lower() == "true"  # line 16

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()               # line 32
```

**New vars to add for watcher (same pattern — os.getenv with default):**
```python
WATCH_DIR:        str  = os.getenv("WATCH_DIR", "/watch")
WORKER_URL:       str  = os.getenv("WORKER_URL", "http://ingestion-worker:8001")
WATCH_USE_POLLING: bool = os.getenv("WATCH_USE_POLLING", "false").lower() == "true"
VIDEO_EXTENSIONS: set  = {e.strip() for e in os.getenv(
    "VIDEO_EXTENSIONS", ".mp4,.mov,.avi,.mkv,.m4v"
).split(",")}
```

**Rules:** required vars use `os.environ["KEY"]` (raises `KeyError` at startup if missing); optional vars use `os.getenv("KEY", default)`.

---

### 4. Python Main Entry Point — `services/watcher/app/main.py`
**Analog:** `services/ingestion-worker/app/main.py` (lines 1-54)

**Startup + logging bootstrap pattern** (lines 1-22):
```python
import asyncio
import logging
from contextlib import asynccontextmanager                # line 7

from . import config

LOG_LEVEL = config.LOG_LEVEL
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))  # line 21
logger = logging.getLogger(__name__)                                    # line 22
```

**Lifespan / startup scan pattern** (lines 25-54):
```python
@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup: init DB pool, load ML models, recover stale videos."""
    # 1. Initialize database connection pool
    await init_pool()
    # 2. Recovery: reset any videos stuck in 'processing' from a previous crash
    await reset_stale_processing_videos()
    ...
    yield
    # Shutdown
    await close_pool()
    logger.info("Shutdown complete")
```

**For watcher, the lifespan becomes:**
```python
async def main():
    logging.basicConfig(level=getattr(logging, config.LOG_LEVEL, logging.INFO))
    logger.info("Watcher starting. watch_dir=%s polling=%s", config.WATCH_DIR, config.WATCH_USE_POLLING)

    # Startup scan (AUTO-04): queue files not yet ingested
    await startup_scan(config.WATCH_DIR)

    # Start watchdog observer
    await run_observer(config.WATCH_DIR)

if __name__ == "__main__":
    asyncio.run(main())
```

---

### 5. MinIO Upload — `services/watcher/app/storage.py`
**Analog:** `services/ingestion-worker/app/storage.py` (lines 1-54)

**Client singleton pattern** (lines 10-23) — copy verbatim:
```python
from minio import Minio
from . import config

_client: Minio | None = None

def get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            config.MINIO_ENDPOINT,
            access_key=config.MINIO_ACCESS_KEY,
            secret_key=config.MINIO_SECRET_KEY,
            secure=config.MINIO_USE_SSL,
            region="us-east-1",
        )
    return _client
```

**`fput_object` upload pattern** (lines 40-54) — copy and adapt for videos:
```python
def upload_frame(local_path: Path, video_id: str, ts_ms: int) -> str:
    client = get_client()
    ensure_bucket(config.MINIO_BUCKET_FRAMES)
    key = f"frames/{video_id}/{ts_ms}.jpg"
    client.fput_object(                          # ← use fput_object (path-based)
        config.MINIO_BUCKET_FRAMES,
        key,
        str(local_path),
        content_type="image/jpeg",
    )
    return key
```

**Watcher adaptation** — upload video to `videos/` prefix:
```python
def upload_video(local_path: Path) -> str:
    """Upload a video file to MinIO videos bucket. Returns the MinIO key."""
    client = get_client()
    ensure_bucket(config.MINIO_BUCKET_VIDEOS)
    key = f"videos/{local_path.name}"
    client.fput_object(
        config.MINIO_BUCKET_VIDEOS,
        key,
        str(local_path),
        content_type="video/mp4",
    )
    logger.info("UPLOADING %s → minio://%s/%s", local_path.name, config.MINIO_BUCKET_VIDEOS, key)
    return key
```

**`ensure_bucket` utility** (lines 26-29) — copy verbatim:
```python
def ensure_bucket(bucket: str) -> None:
    client = get_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        logger.info("Created MinIO bucket: %s", bucket)
```

---

### 6. POST /ingest Call — request shape from `services/ingestion-worker/app/main.py`
**Analog:** `services/ingestion-worker/app/main.py` lines 62-68 and 84-151

**Request model** (lines 62-63):
```python
class IngestRequest(BaseModel):
    minio_key: str          # e.g. "videos/myvideo.mp4"
```

**Response model** (lines 66-69):
```python
class IngestResponse(BaseModel):
    status: str             # "queued" | "skipped" | "requeued"
    video_id: Optional[str] = None
    message: Optional[str] = None
```

**Endpoint contract** (lines 84-89):
```
POST http://ingestion-worker:8001/ingest
Content-Type: application/json
Body: {"minio_key": "videos/<filename>"}
Response 202: {"status": "queued", "video_id": "<uuid>"}
Response 202: {"status": "skipped", "video_id": "<uuid>", "message": "..."}
```

**Watcher HTTP call pattern** (use `httpx` async):
```python
import httpx

async def call_ingest(minio_key: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{config.WORKER_URL}/ingest",
            json={"minio_key": minio_key},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
```

---

### 7. Structured Logging — state transition log lines
**Analog:** `services/ingestion-worker/app/pipeline.py` (lines 170-271) and `main.py` (lines 20-22)

**Bootstrap** (main.py lines 20-22 — copy verbatim):
```python
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)
```

**State transition log style** (pipeline.py lines 172, 191, 200, 238, 262-270):
```python
logger.info("[%s] Starting pipeline for %s", video_id[:8], minio_key)     # short prefix
logger.info("[%s] Extracted %d frames", video_id[:8], len(frames))
logger.warning("[%s] No frames extracted — marking done (empty video?)", video_id[:8])
logger.error("[%s] Failed to upload frame ts=%d: %s", video_id[:8], frame.ts_ms, exc)
logger.info(
    "[%s] Done. frames_extracted=%d stored=%d detections=%d faces=%d",
    video_id[:8], result.frames_extracted, result.frames_stored, ...
)
```

**Watcher state transitions to log** (mirror same `[prefix] STATE value` style):
```python
logger.info("DETECTED  %s", path)
logger.info("STABLE    %s  size=%d bytes", path, size)
logger.info("UPLOADING %s → minio://videos/%s", path, filename)
logger.info("QUEUED    %s  video_id=%s", path, video_id)
logger.info("SKIPPED   %s  reason=already_ingested", path)
logger.error("ERROR     %s  %s: %s", path, type(exc).__name__, exc)
```

---

### 8. asyncio.Semaphore — `services/ingestion-worker/app/pipeline.py` (new addition)
**Analog:** None — no existing Semaphore usage in the codebase.

**Pattern from Python stdlib / RESEARCH.md:**
```python
# Module-level semaphore (one slot = no concurrent ML runs)
_pipeline_sem = asyncio.Semaphore(1)

async def process_video(video_id, minio_key, yolo_model, face_app):
    async with _pipeline_sem:          # blocks until prior run completes
        # ... existing pipeline body unchanged ...
```

**Insert at:** `services/ingestion-worker/app/pipeline.py` line 156 (before `async def process_video`):
```python
# ── Concurrency guard (OOM prevention on 8 GB host) ─────────────────────────
# Only one YOLO + InsightFace run at a time. Additional requests queue here.
_pipeline_sem: asyncio.Semaphore = asyncio.Semaphore(1)
```

Then wrap `process_video` body (line 167 onwards) with `async with _pipeline_sem:`.

---

## Shared Patterns

### Logging Bootstrap
**Source:** `services/ingestion-worker/app/main.py` lines 20-22
**Apply to:** `services/watcher/app/main.py` (top of file)
```python
LOG_LEVEL = config.LOG_LEVEL
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)
```

### MinIO Client Singleton
**Source:** `services/ingestion-worker/app/storage.py` lines 10-23
**Apply to:** `services/watcher/app/storage.py` (copy verbatim, only bucket constant changes)

### `os.environ` vs `os.getenv` Convention
**Source:** `services/ingestion-worker/app/config.py` lines 9-16
**Apply to:** `services/watcher/app/config.py`
- `os.environ["KEY"]` — required secrets (MINIO_ACCESS_KEY, MINIO_SECRET_KEY): raises KeyError at import time if absent
- `os.getenv("KEY", default)` — optional tuning vars (WATCH_DIR, WORKER_URL, LOG_LEVEL, etc.)

### uv + python:3.11-slim-bookworm Dockerfile Template
**Source:** `services/ingestion-worker/Dockerfile` lines 1, 14, 24, 41
**Apply to:** `services/watcher/Dockerfile`
```dockerfile
FROM python:3.11-slim-bookworm
RUN pip install --no-cache-dir uv==0.11.14
RUN uv pip install --system --no-cache -r requirements.txt
ENV PYTHONUNBUFFERED=1
```

---

## No Analog Found

| File / Pattern | Role | Data Flow | Reason |
|---|---|---|---|
| `asyncio.Semaphore(1)` in `pipeline.py` | concurrency guard | — | No existing semaphore/lock usage anywhere in codebase; purely additive change |
| `watchdog` `FileSystemEventHandler` + `on_closed()` | event-driven handler | event-driven | No file-system watchers exist; closest structural analog is `process_video` background task loop |
| `PollingObserver` toggle | config-driven observer swap | — | No runtime observer-class selection in codebase |

---

## Metadata

**Analog search scope:** `docker-compose.yml`, `services/ingestion-worker/` (Dockerfile, app/\*.py), `services/api/` (Dockerfile, app/config.py, app/storage.py)
**Files scanned:** 12
**Pattern extraction date:** 2025-07-13
