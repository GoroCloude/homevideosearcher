# Plan 01: Face Enrollment API

**Phase:** 02 - Enrollment, Search API & n8n Automation  
**Goal:** Add InsightFace to the api service, expose full person enrollment endpoints (create, enroll, delete, rematch, list), and wire the api lifespan to load the buffalo_l model once at startup.

**Requirements covered:** ENROLL-01, ENROLL-02, ENROLL-03, ENROLL-04, ENROLL-05  
**Depends on:** Phase 1 complete (postgres, ingestion-worker, api stub running)  
**Wave:** 1 (no Plan 02 files touched here)

---

## Tasks

### Task 1 — Schema migration: add `notes TEXT` to `known_persons`

**File:** `db/migrations/002_add_notes_to_known_persons.sql` *(create new)*

```sql
-- Phase 2 migration: add optional notes field to known_persons.
-- Safe to run multiple times (IF NOT EXISTS guard).
ALTER TABLE known_persons
    ADD COLUMN IF NOT EXISTS notes TEXT;
```

**How to apply** (document in task for executor):
```bash
docker compose exec postgres \
  psql -U videosearch -d videosearch \
  -c "ALTER TABLE known_persons ADD COLUMN IF NOT EXISTS notes TEXT;"
```

Verify: `docker compose exec postgres psql -U videosearch -d videosearch -c "\d known_persons"` — output must show a `notes` column of type `text`.

---

### Task 2 — Update `services/api/requirements.txt`

**File:** `services/api/requirements.txt` *(modify)*

Add the following lines (mirror of ingestion-worker's insightface block):
```
insightface==0.7.3
onnxruntime==1.26.0
opencv-python-headless>=4.10
cython
numpy<2.0
```

**Full file after edit** (preserve existing entries, add these before the final blank line):
```
fastapi==0.136.1
uvicorn[standard]==0.35.0
asyncpg==0.31.0
pgvector==0.4.2
minio==7.2.20
python-multipart>=0.0.20
pydantic>=2.0
scikit-learn==1.8.0
python-telegram-bot>=22.0,<23.0
python-dotenv>=1.0
insightface==0.7.3
onnxruntime==1.26.0
opencv-python-headless>=4.10
cython
numpy<2.0
```

**Note:** `scikit-learn` and `python-telegram-bot` are already in the file — keep them; they are used in Phase 3. Do NOT remove them.

---

### Task 3 — Update `services/api/Dockerfile`

**File:** `services/api/Dockerfile` *(replace entirely)*

```dockerfile
FROM python:3.11-slim-bookworm

# System dependencies: build tools for insightface C extensions + runtime libs.
# Mirrors ingestion-worker/Dockerfile exactly.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.11.14

WORKDIR /app

# Pre-install insightface build-time deps BEFORE full requirements.txt.
# insightface==0.7.3 compiles Cython extensions — cython + numpy must exist first.
RUN uv pip install --system --no-cache "cython" "numpy<2.0"

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY app/ ./app/

# ── Bake InsightFace buffalo_l model at build time ────────────────────────────
# Downloads ~280 MB (SCRFD-10G + ArcFace R100) → ~/.insightface/models/buffalo_l/
# Build fails fast if model download fails (no silent fallback to runtime download).
RUN python -c "\
from insightface.app import FaceAnalysis; \
app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']); \
app.prepare(ctx_id=0, det_size=(640, 640)); \
print('InsightFace buffalo_l baked successfully')"
# ─────────────────────────────────────────────────────────────────────────────

# ONNX Runtime thread count for i5-6200 (dual-core, 4 HT threads)
ENV OMP_NUM_THREADS=4
ENV ONNX_DISABLE_GLOBAL_THREAD_POOL=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Note:** No `ffmpeg` needed (api service doesn't process video frames). `libgl1` + `libglib2.0-0` are required by OpenCV headless at import time even with the headless build.

---

### Task 4 — Update `docker-compose.yml`: api service memory cap + face thresholds

**File:** `docker-compose.yml` *(modify api service block only)*

Under the `api:` service, add `deploy.resources.limits.memory: 2g` and add the two face threshold env vars (so api service reads the same thresholds as ingestion-worker):

```yaml
  api:
    build: ./services/api
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-videosearch}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB:-videosearch}
      MINIO_ENDPOINT: ${MINIO_ENDPOINT:-minio:9000}
      MINIO_ACCESS_KEY: ${MINIO_ACCESS_KEY}
      MINIO_SECRET_KEY: ${MINIO_SECRET_KEY}
      MINIO_BUCKET_VIDEOS: ${MINIO_BUCKET_VIDEOS:-videos}
      MINIO_BUCKET_FRAMES: ${MINIO_BUCKET_FRAMES:-frames}
      MINIO_USE_SSL: ${MINIO_USE_SSL:-false}
      API_TOKEN: ${API_TOKEN}
      API_CORS_ORIGINS: ${API_CORS_ORIGINS:-http://localhost:8080}
      FACE_MATCH_HIGH_THRESHOLD: ${FACE_MATCH_HIGH_THRESHOLD:-0.65}
      FACE_MATCH_LOW_THRESHOLD: ${FACE_MATCH_LOW_THRESHOLD:-0.50}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
    ports:
      - "${API_PORT:-8000}:8000"
    depends_on:
      postgres:
        condition: service_healthy
    deploy:
      resources:
        limits:
          memory: 2g
    networks:
      - home-infra
```

---

### Task 5 — Create `services/api/app/config.py`

**File:** `services/api/app/config.py` *(create new)*

```python
"""Configuration: all env vars read here, nowhere else.
Pattern mirrors ingestion-worker/app/config.py exactly.
"""
import os

DATABASE_URL:              str   = os.environ["DATABASE_URL"]        # fail-fast if missing
MINIO_ENDPOINT:            str   = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY:          str   = os.environ["MINIO_ACCESS_KEY"]
MINIO_SECRET_KEY:          str   = os.environ["MINIO_SECRET_KEY"]
MINIO_BUCKET_VIDEOS:       str   = os.getenv("MINIO_BUCKET_VIDEOS", "videos")
MINIO_BUCKET_FRAMES:       str   = os.getenv("MINIO_BUCKET_FRAMES", "frames")
MINIO_USE_SSL:             bool  = os.getenv("MINIO_USE_SSL", "false").lower() == "true"
API_TOKEN:                 str   = os.environ["API_TOKEN"]           # fail-fast if missing
FACE_MATCH_HIGH_THRESHOLD: float = float(os.getenv("FACE_MATCH_HIGH_THRESHOLD", "0.65"))
FACE_MATCH_LOW_THRESHOLD:  float = float(os.getenv("FACE_MATCH_LOW_THRESHOLD", "0.50"))
LOG_LEVEL:                 str   = os.getenv("LOG_LEVEL", "INFO").upper()
```

---

### Task 6 — Create `services/api/app/db.py`

**File:** `services/api/app/db.py` *(create new)*

Copy the asyncpg pool pattern from `ingestion-worker/app/db.py` — same three functions, nothing more (no ingest-specific helpers):

```python
"""Database: asyncpg connection pool.
Same pattern as ingestion-worker/app/db.py.
Do NOT share this module between services — each service is an independent Docker image.
"""
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
    # Register pgvector codec so vector(512) columns deserialize to list[float]
    async with _pool.acquire() as conn:
        await register_vector(conn)
    logger.info("DB pool initialized")


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
```

---

### Task 7 — Create `services/api/app/auth.py`

**File:** `services/api/app/auth.py` *(create new)*

```python
"""Bearer token authentication dependency.

Usage:
    # In main.py router registration — NOT per-endpoint:
    app.include_router(persons_router, dependencies=[Depends(require_token)])

    # /health and /docs are added directly on app (no dependency) — they stay public.
"""
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config

# auto_error=False: we raise our own 401 with a consistent body
_bearer = HTTPBearer(auto_error=False)


async def require_token(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> None:
    """Raise 401 if Authorization: Bearer <token> is missing or wrong."""
    if credentials is None or credentials.credentials != config.API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
```

---

### Task 8 — Create `services/api/app/faces_api.py`

**File:** `services/api/app/faces_api.py` *(create new)*

Stripped-down InsightFace wrapper for the api service — only `load_face_model()` and `analyze_image_bytes()`. No `match_face_embedding()` (matching is not needed here; enrollment inserts the embedding directly).

```python
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
```

---

### Task 9 — Create `services/api/app/persons.py`

**File:** `services/api/app/persons.py` *(create new)*

All five enrollment-related endpoints on a single router. The `require_token` dependency is **not** added per-endpoint here — it is applied at router-include time in `main.py`.

```python
"""
Person enrollment router.
Endpoints:
    POST   /persons                       — create known person
    GET    /persons                       — list all with enrollment count
    POST   /persons/{person_id}/enroll   — upload 1-N face images
    DELETE /persons/{person_id}          — delete person + embeddings (CASCADE)
    POST   /persons/{person_id}/rematch  — retroactively match face_detections
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

from . import config
from .db import get_pool
from .faces_api import analyze_image_bytes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/persons", tags=["persons"])

# ── Max upload size guard ─────────────────────────────────────────────────────
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB per image

# ── Pydantic models ───────────────────────────────────────────────────────────

class CreatePersonRequest(BaseModel):
    name: str
    notes: Optional[str] = None


class PersonResponse(BaseModel):
    id: str
    name: str
    notes: Optional[str]
    created_at: str
    enrollment_count: int = 0


class EnrollResponse(BaseModel):
    person_id: str
    enrolled: int
    rejected: list[dict]
    warning: Optional[str] = None


class RematchResponse(BaseModel):
    person_id: str
    matched: int


# ── POST /persons ─────────────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED, response_model=PersonResponse)
async def create_person(body: CreatePersonRequest) -> PersonResponse:
    """Create a known person record. Name must be unique."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO known_persons (name, notes)
                VALUES ($1, $2)
                RETURNING id::text, name, notes, created_at::text
                """,
                body.name,
                body.notes,
            )
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"A person named '{body.name}' already exists",
                )
            raise
    return PersonResponse(
        id=row["id"],
        name=row["name"],
        notes=row["notes"],
        created_at=row["created_at"],
        enrollment_count=0,
    )


# ── GET /persons ──────────────────────────────────────────────────────────────

@router.get("", response_model=list[PersonResponse])
async def list_persons() -> list[PersonResponse]:
    """List all known persons with their embedding count."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                kp.id::text,
                kp.name,
                kp.notes,
                kp.created_at::text,
                COUNT(pe.id)::int AS enrollment_count
            FROM known_persons kp
            LEFT JOIN person_embeddings pe ON pe.person_id = kp.id
            GROUP BY kp.id, kp.name, kp.notes, kp.created_at
            ORDER BY kp.name
            """
        )
    return [
        PersonResponse(
            id=r["id"],
            name=r["name"],
            notes=r["notes"],
            created_at=r["created_at"],
            enrollment_count=r["enrollment_count"],
        )
        for r in rows
    ]


# ── POST /persons/{person_id}/enroll ─────────────────────────────────────────

@router.post("/{person_id}/enroll", response_model=EnrollResponse)
async def enroll_images(
    person_id: UUID,
    request: Request,
    images: list[UploadFile] = File(..., description="1–N enrollment photos"),
) -> EnrollResponse:
    """
    Upload 1–N face photos for a known person.
    Each image is validated:
      1. Decodable as an image by OpenCV
      2. Exactly one face detected
      3. det_score >= 0.70
      4. Bounding box >= 80×80 px
      5. File size <= 10 MB
    Accepted images are inserted into person_embeddings even if some are rejected.
    A warning is returned when total enrolled count (all-time) < 5.
    """
    face_app = request.app.state.face_app

    # Verify person exists
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM known_persons WHERE id = $1", person_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")

    enrolled_this_call: list[dict] = []
    rejected: list[dict] = []

    for img_file in images:
        fname = img_file.filename or "upload"
        data = await img_file.read()

        # Gate 0: file size
        if len(data) > MAX_UPLOAD_BYTES:
            rejected.append({"filename": fname, "reason": f"File exceeds 10 MB limit"})
            continue

        # Gate 1: decodable image
        faces = analyze_image_bytes(data, face_app)
        if not isinstance(faces, list) or (len(faces) == 0 and len(data) > 0):
            # analyze_image_bytes returns [] for invalid images
            # distinguish "no face" from "bad image" by re-checking decode
            import cv2, numpy as np
            arr = np.frombuffer(data, dtype=np.uint8)
            if cv2.imdecode(arr, cv2.IMREAD_COLOR) is None:
                rejected.append({"filename": fname, "reason": "Not a valid image"})
                continue
            rejected.append({"filename": fname, "reason": "No face detected"})
            continue

        # Gate 2: exactly one face
        if len(faces) == 0:
            rejected.append({"filename": fname, "reason": "No face detected"})
            continue
        if len(faces) > 1:
            rejected.append({
                "filename": fname,
                "reason": f"Multiple faces ({len(faces)}) detected — upload a solo photo",
            })
            continue

        face = faces[0]

        # Gate 3: detector confidence
        if face["det_score"] < 0.70:
            rejected.append({
                "filename": fname,
                "reason": f"Face has low detector confidence ({face['det_score']:.2f}) — use a clearer photo",
            })
            continue

        # Gate 4: bounding box minimum size
        w = face["bbox_x2"] - face["bbox_x1"]
        h = face["bbox_y2"] - face["bbox_y1"]
        if w < 80 or h < 80:
            rejected.append({
                "filename": fname,
                "reason": f"Face is too small ({w}×{h}px) — use a closer photo",
            })
            continue

        enrolled_this_call.append({
            "filename": fname,
            "normed_embedding": face["normed_embedding"],
        })

    # Bulk-insert accepted embeddings
    if enrolled_this_call:
        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO person_embeddings (person_id, normed_embedding, source_image)
                VALUES ($1::uuid, $2::vector, $3)
                """,
                [
                    (str(person_id), e["normed_embedding"], e["filename"])
                    for e in enrolled_this_call
                ],
            )

    # Total enrollment count (all-time, not just this call)
    async with pool.acquire() as conn:
        total_count = await conn.fetchval(
            "SELECT COUNT(*) FROM person_embeddings WHERE person_id = $1",
            person_id,
        )

    warning = None
    if total_count < 5:
        warning = (
            f"Only {total_count} image(s) enrolled. "
            "Recognition accuracy is reduced with fewer than 5 images."
        )

    return EnrollResponse(
        person_id=str(person_id),
        enrolled=len(enrolled_this_call),
        rejected=rejected,
        warning=warning,
    )


# ── DELETE /persons/{person_id} ───────────────────────────────────────────────

@router.delete("/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person(person_id: UUID) -> None:
    """
    Delete a known person and all their embeddings.
    Cascades automatically via ON DELETE CASCADE on person_embeddings.
    face_detections.matched_person_id is SET NULL on cascade.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM known_persons WHERE id = $1", person_id
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Person not found")


# ── POST /persons/{person_id}/rematch ─────────────────────────────────────────

@router.post("/{person_id}/rematch", response_model=RematchResponse)
async def rematch_person(person_id: UUID) -> RematchResponse:
    """
    Retroactively scan ALL unmatched face_detections and update any that
    now match this person's embeddings (using the HNSW index).

    Algorithm (Python loop — NOT a SQL CROSS JOIN, which skips the HNSW index):
      1. Load all normed_embeddings from person_embeddings for this person.
      2. For each embedding, query face_detections HNSW index (LIMIT 1000 per embedding).
      3. Collect best similarity per face_detection_id across all embeddings.
      4. Single executemany UPDATE for all matched face_detections.

    Only updates face_detections where matched_person_id IS NULL (no re-matching
    faces already assigned to another person).
    """
    pool = await get_pool()

    # Verify person exists
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM known_persons WHERE id = $1", person_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")

    high = config.FACE_MATCH_HIGH_THRESHOLD  # 0.65
    low  = config.FACE_MATCH_LOW_THRESHOLD   # 0.50

    # Step 1: load all enrollment embeddings for this person
    async with pool.acquire() as conn:
        emb_rows = await conn.fetch(
            "SELECT id, normed_embedding FROM person_embeddings WHERE person_id = $1",
            person_id,
        )

    if not emb_rows:
        return RematchResponse(person_id=str(person_id), matched=0)

    # Step 2: for each enrollment embedding, find matching unmatched face_detections
    # Uses face_detections HNSW index (ORDER BY <=> LIMIT activates HNSW scan)
    candidate_matches: dict[int, float] = {}  # face_detection_id → best_similarity

    async with pool.acquire() as conn:
        for emb_row in emb_rows:
            matches = await conn.fetch(
                """
                SELECT id, 1.0 - (normed_embedding <=> $1::vector) AS similarity
                FROM face_detections
                WHERE matched_person_id IS NULL
                  AND normed_embedding <=> $1::vector <= $2
                ORDER BY normed_embedding <=> $1::vector
                LIMIT 1000
                """,
                emb_row["normed_embedding"],
                1.0 - low,   # distance <= (1 - low_threshold) → similarity >= low
            )
            for m in matches:
                fd_id = m["id"]
                sim   = float(m["similarity"])
                if sim > candidate_matches.get(fd_id, -1.0):
                    candidate_matches[fd_id] = sim

    if not candidate_matches:
        return RematchResponse(person_id=str(person_id), matched=0)

    # Step 3: single bulk UPDATE
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            UPDATE face_detections
            SET
                matched_person_id = $1::uuid,
                match_similarity   = $2,
                match_tier         = CASE WHEN $2 >= $3 THEN 'confident' ELSE 'probable' END
            WHERE id = $4
              AND matched_person_id IS NULL
            """,
            [
                (str(person_id), sim, high, fd_id)
                for fd_id, sim in candidate_matches.items()
            ],
        )

    logger.info(
        "Rematch person %s: %d face_detections updated",
        person_id, len(candidate_matches),
    )
    return RematchResponse(person_id=str(person_id), matched=len(candidate_matches))
```

---

### Task 10 — Update `services/api/app/main.py`

**File:** `services/api/app/main.py` *(replace entirely)*

Replace the Phase 1 stub with the full lifespan + router registration. Plan 02 will add more router includes to this file.

```python
"""
HomeVideoSearcher API service.
Phase 2: Enrollment endpoints + lifespan model load.
         Search/stream endpoints added in Phase 2 Plan 02.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from . import config
from .auth import require_token
from .db import close_pool, init_pool
from .persons import router as persons_router

LOG_LEVEL = config.LOG_LEVEL
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """
    Startup:
      1. Initialize asyncpg DB pool.
      2. Load InsightFace buffalo_l (baked into image — no download).
    Shutdown: close DB pool.
    No YOLO loaded here — api service uses InsightFace only (for enrollment).
    """
    await init_pool()
    logger.info("Loading InsightFace buffalo_l for enrollment")
    from .faces_api import load_face_model
    application.state.face_app = load_face_model()
    logger.info("InsightFace buffalo_l ready (api service)")
    yield
    await close_pool()
    logger.info("API service shutdown complete")


app = FastAPI(
    title="HomeVideoSearcher API",
    version="0.2.0",
    lifespan=lifespan,
)


# ── Unprotected endpoints (no token required) ─────────────────────────────────
@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "api"}


# ── Protected routers (bearer token required) ─────────────────────────────────
# require_token dependency is applied at router level — ALL routes in each
# router are protected. /health and /docs stay unprotected.
app.include_router(persons_router, dependencies=[Depends(require_token)])

# Plan 02 will append:
# app.include_router(search_router,  dependencies=[Depends(require_token)])
# app.include_router(videos_router,  dependencies=[Depends(require_token)])
# app.include_router(frames_router,  dependencies=[Depends(require_token)])
```

---

## Verification

After executing all tasks, verify the following:

- [ ] `docker compose build api` completes without error (InsightFace buffalo_l bake prints "InsightFace buffalo_l baked successfully")
- [ ] `docker compose up api` starts cleanly; logs show "InsightFace buffalo_l ready (api service)"
- [ ] `curl http://localhost:8000/health` returns `{"status":"ok","service":"api"}` — no token required
- [ ] `curl -X POST http://localhost:8000/persons -H "Content-Type: application/json" -d '{"name":"Alice"}' ` returns 401 (no token)
- [ ] Same request with `-H "Authorization: Bearer <API_TOKEN>"` returns 201 with a UUID
- [ ] `GET /persons` returns the created person with `enrollment_count: 0`
- [ ] `POST /persons/{id}/enroll` with a clear solo face photo returns `enrolled: 1`, no rejection
- [ ] `POST /persons/{id}/enroll` with a blank/random image returns `enrolled: 0`, rejection reason "No face detected" or "Not a valid image"
- [ ] `POST /persons/{id}/enroll` with a group photo returns rejection reason "Multiple faces (N) detected"
- [ ] After enrolling 3 images, response contains `warning: "Only 3 image(s) enrolled..."`
- [ ] `DELETE /persons/{id}` returns 204; subsequent `GET /persons` no longer shows the person
- [ ] `POST /persons/{id}/rematch` on a person with embeddings returns `{"person_id":"...","matched":N}` (N ≥ 0)
- [ ] `docker compose exec postgres psql -U videosearch -d videosearch -c "\d known_persons"` shows `notes` column
- [ ] `docker compose exec postgres psql -U videosearch -d videosearch -c "SELECT pg_size_pretty(pg_relation_size('person_embeddings_hnsw_idx'));"` returns a non-zero size after enrollment

---

## Threat Model

- **Enrollment image injection (SSRF/path traversal):** Images are decoded entirely in memory via `cv2.imdecode(np.frombuffer(...))` — no disk write, no filename-derived path used. Mitigation: current decode-only pattern is safe; enforce 10 MB size cap (Task 9 `MAX_UPLOAD_BYTES`).

- **Bearer token brute-force:** `API_TOKEN` is compared with `==` (constant-time? No — Python `str ==` is not constant-time). For a self-hosted system on a private network this is acceptable; document that token should be at least 32 random characters. If exposed to internet: add rate limiting in a future Phase (nginx `limit_req_zone`).

- **Rematch runaway query:** LIMIT 1000 per embedding (Task 9 rematch) caps total DB rows scanned per rematch call. A person with 50 enrollment images × 1000 candidates = 50 K DB rows max — acceptable. Without LIMIT this could scan the full `face_detections` table.

- **InsightFace crash leaks full stacktrace in 500 response:** `analyze_image_bytes()` wraps the `face_app.get()` call in a try/except that logs the error and returns `[]`. FastAPI default 500 handler returns `{"detail":"Internal Server Error"}` — no stacktrace exposed. Verify `DEBUG=false` is not set (it defaults to false in uvicorn production mode).

- **Memory exhaustion via concurrent enrollments:** InsightFace buffalo_l processes one image at a time. Concurrent enrollment requests share the same `face_app` instance (not thread-safe for concurrent calls). Mitigation: add an `asyncio.Lock` around the `face_app.get()` call in `analyze_image_bytes()` in a follow-up if concurrent enrollment is needed. For Phase 2 (single user, self-hosted) sequential requests are acceptable.
