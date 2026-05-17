# Phase 2 Research: Enrollment, Search API & n8n Automation

**Researched:** 2026-05-17  
**Domain:** FastAPI enrollment/search endpoints, pgvector cosine search, MinIO presigned URLs, n8n webhook + polling  
**Confidence:** HIGH (verified from existing codebase, schema, stack documents)

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ENROLL-01 | `POST /persons` creates a known person entry | § 8 module list; persons.py router |
| ENROLL-02 | `POST /persons/{id}/enroll` accepts 1–N images; rejects if no face, >1 face, or det_score < 0.7 | § 1 multipart pattern + validation gates |
| ENROLL-03 | At least 5 enrollment images recommended | § 1 error responses; PITFALL FR-2 |
| ENROLL-04 | `DELETE /persons/{id}` removes person + all embeddings (ON DELETE CASCADE) | Schema `known_persons` CASCADE |
| ENROLL-05 | `POST /persons/{id}/rematch` retroactively updates face_detections | § 2 rematch SQL |
| SEARCH-01 | `POST /search` with full filter set | § 4 SQL JOIN pattern |
| SEARCH-02 | Response includes frame_id, video_id, ts_ms, thumbnail_url, detections, faces, pagination | § 4 response shape |
| SEARCH-03 | `GET /videos/{id}/stream` returns 302 to presigned MinIO URL (1h TTL) | § 5 presigned URL pattern |
| SEARCH-04 | `GET /frames/{id}/image` returns 302 to presigned MinIO frame thumbnail URL | § 5 presigned URL pattern |
| SEARCH-05 | Single bearer token auth; `/health` and `/docs` exempt | § 3 auth dependency |
| N8N-01 | n8n workflow: MinIO `s3:ObjectCreated:*` on `videos/` triggers `POST /ingest` | § 6 webhook config |
| N8N-02 | Polling fallback: scheduled scan every 10 minutes for pending videos | § 7 polling approach |
</phase_requirements>

---

## Key Findings

- **Auth is a single FastAPI dependency** — `HTTPBearer` + `Depends(require_token)` on individual routers; `/health` and `/docs` excluded by not attaching the dependency there. The `API_TOKEN` env var is already defined in docker-compose.yml and `.env.example`.
- **InsightFace MUST be added to the api service** — enrollment validation requires SCRFD (face detection) + ArcFace (embedding computation). The existing api `requirements.txt` lacks `insightface` and `onnxruntime`; both must be added, and the api Dockerfile needs model baking.
- **Rematch is a Python loop over person_embeddings, not a single-statement UPDATE** — pgvector's HNSW index only accelerates `ORDER BY ... LIMIT 1` queries; a pure SQL CROSS JOIN skips the index. The correct pattern loops over each enrollment embedding, queries the face_detections HNSW index, collects matches, then runs a single bulk UPDATE.
- **n8n receives MinIO events as plain HTTP POST** — MinIO's webhook notification target is configured via `mc` CLI; n8n uses a standard Webhook node (no special S3 integration required). The payload structure mirrors S3 event notifications.
- **Polling fallback calls `/ingest/batch`** — The ingestion-worker already has `POST /ingest/batch` with full idempotency (skips `done` videos). The n8n polling workflow just calls that endpoint; no new API endpoint needed.

---

## 1. Enrollment API

### Multi-file Upload Pattern

FastAPI accepts multiple files via `List[UploadFile]`:

```python
# Source: FastAPI docs / python-multipart (already in api requirements.txt)
from fastapi import APIRouter, Depends, File, HTTPException, Path, UploadFile
from typing import List

router = APIRouter(prefix="/persons", tags=["persons"])

@router.post("/{person_id}/enroll", status_code=200)
async def enroll_images(
    person_id: UUID = Path(...),
    images: List[UploadFile] = File(..., description="1–N enrollment photos"),
    _token = Depends(require_token),
):
    results = []
    for img_file in images:
        data = await img_file.read()
        # decode with OpenCV, run InsightFace detect-only
        ...
    return {"person_id": str(person_id), "enrolled": len(results), "rejected": [...]}
```

`python-multipart>=0.0.20` is already in `services/api/requirements.txt`.

### Validation Gates (in order — fail fast)

| Gate | Check | Error Response |
|------|-------|----------------|
| File is an image | `cv2.imdecode` returns non-None | `422 {"detail": "File '{name}' is not a valid image"}` |
| At least one face detected | `len(faces) >= 1` | `422 {"detail": "No face detected in '{name}'"}` |
| Exactly one face (no group photos) | `len(faces) == 1` | `422 {"detail": "Multiple faces ({n}) detected in '{name}' — upload a solo photo"}` |
| Detector confidence | `face.det_score >= 0.7` | `422 {"detail": "Face in '{name}' has low detector confidence ({score:.2f}) — use a clearer photo"}` |
| Bounding box minimum size | `(bbox_x2 - bbox_x1) >= 80 and (bbox_y2 - bbox_y1) >= 80` | `422 {"detail": "Face in '{name}' is too small ({w}×{h}px) — use a closer photo"}` |

Validation runs per-image; a batch request reports individual rejections in the response body (`"rejected": [{"filename": "x.jpg", "reason": "..."}]`). Accepted images are stored even if some are rejected (partial success).

### Enrollment Image Count Recommendation

ENROLL-03 says 5 images are "recommended but not enforced in the API." Include a `"warning"` field in the response when `enrolled_count < 5`:

```python
# Example response body
{
  "person_id": "uuid",
  "enrolled": 3,
  "rejected": [],
  "warning": "Only 3 images enrolled. Recognition accuracy is reduced with fewer than 5 images."
}
```

### Embedding Storage

After validation, compute `face.normed_embedding` (same pattern as `faces.py` in ingestion-worker — use `face.normed_embedding`, NOT `face.embedding`) and INSERT into `person_embeddings`:

```sql
INSERT INTO person_embeddings (person_id, normed_embedding, source_image)
VALUES ($1::uuid, $2::vector, $3)
```

The `source_image` field can store the original filename or a MinIO key if you choose to persist the enrollment photo. Storing the filename only (not the image) is acceptable for v1.

---

## 2. Rematch Query

### Why Not a Single SQL UPDATE

The ROADMAP states "single SQL UPDATE" but that's aspirational framing. A pure SQL CROSS JOIN (all `face_detections` × all `person_embeddings` for the new person) does **not** use the HNSW index — pgvector's HNSW accelerates `ORDER BY embedding <=> $1 LIMIT 1` queries only. Without LIMIT, it degrades to sequential scan. For families with 10–50 enrollment images × up to 100K face_detections, this is 500K–5M comparisons on each rematch — potentially very slow.

### Correct Rematch Strategy: Python Loop + HNSW Per Embedding

For each enrollment embedding of the new person, use the existing HNSW index on `face_detections` to find matching unmatched faces:

```python
# Source: adapted from faces.py match_face_embedding() pattern
async def run_rematch(person_id: UUID, pool) -> int:
    """
    Returns count of newly matched face_detections.
    Uses HNSW index on face_detections.normed_embedding.
    """
    high = config.FACE_MATCH_HIGH_THRESHOLD  # 0.65
    low  = config.FACE_MATCH_LOW_THRESHOLD   # 0.50

    # Step 1: load all enrollment embeddings for this person
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, normed_embedding FROM person_embeddings WHERE person_id = $1",
            person_id,
        )

    # Step 2: for each enrollment embedding, find matching face_detections via HNSW
    candidate_matches: dict[int, float] = {}  # face_det_id → best_similarity

    async with pool.acquire() as conn:
        for row in rows:
            # HNSW index used because of ORDER BY <=> LIMIT
            matches = await conn.fetch(
                """
                SELECT id, 1.0 - (normed_embedding <=> $1::vector) AS similarity
                FROM face_detections
                WHERE matched_person_id IS NULL
                  AND normed_embedding <=> $1::vector <= $2   -- distance threshold = 1 - low
                ORDER BY normed_embedding <=> $1::vector
                LIMIT 1000  -- cap per embedding to avoid runaway queries
                """,
                row["normed_embedding"],
                1.0 - low,   # distance = 1 - similarity; low=0.50 → distance <= 0.50
            )
            for m in matches:
                fd_id = m["id"]
                sim   = float(m["similarity"])
                if sim > candidate_matches.get(fd_id, -1):
                    candidate_matches[fd_id] = sim  # keep best similarity across embeddings

    if not candidate_matches:
        return 0

    # Step 3: single bulk UPDATE with the collected matches
    async with pool.acquire() as conn:
        # Build per-ID CASE for match_similarity
        updated = await conn.executemany(
            """
            UPDATE face_detections
            SET matched_person_id = $1,
                match_similarity   = $2,
                match_tier         = CASE WHEN $2 >= $3 THEN 'confident' ELSE 'probable' END
            WHERE id = $4 AND matched_person_id IS NULL
            """,
            [
                (person_id, sim, high, fd_id)
                for fd_id, sim in candidate_matches.items()
            ],
        )
    return len(candidate_matches)
```

### Index Used

- **`face_detections_hnsw_idx`** on `face_detections(normed_embedding vector_cosine_ops)` — m=32, ef_construction=128, ef_search=64 (set globally in docker-compose postgres command)
- The HNSW query is: `ORDER BY normed_embedding <=> $1::vector LIMIT 1000` — this triggers HNSW scan
- The `matched_person_id IS NULL` filter is applied as a post-filter (not index-pushable in pgvector); acceptable for home-scale data

### Two-Tier Threshold

Rematch applies the same `0.65 / 0.50` thresholds as the ingestion pipeline. Use `config.FACE_MATCH_HIGH_THRESHOLD` and `config.FACE_MATCH_LOW_THRESHOLD` — read from env vars, not hardcoded.

### What Rematch Does NOT Do

- Does not re-match faces that are already matched to another person
- Does not re-run YOLO or FFmpeg
- Does not touch `unknown_cluster_id` — cluster cleanup is Phase 3's job

---

## 3. Auth Pattern

### FastAPI HTTPBearer Dependency

```python
# services/api/app/auth.py
import os
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)
_API_TOKEN: str = os.environ["API_TOKEN"]   # fail-fast at startup if missing

async def require_token(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> None:
    if credentials is None or credentials.credentials != _API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
```

### Exempting /health and /docs

Apply the dependency at the **router level**, not on the FastAPI app globally. The `/health` endpoint and the `/docs` + `/openapi.json` routes are added to the base `app` without authentication:

```python
# main.py — NO global dependency
app = FastAPI(title="HomeVideoSearcher API", version="0.2.0", lifespan=lifespan)

# Unprotected: /health (no dependency)
@app.get("/health")
async def health():
    return {"status": "ok", "service": "api"}

# Protected routers: include with dependency
from .auth import require_token
app.include_router(persons_router, dependencies=[Depends(require_token)])
app.include_router(search_router,  dependencies=[Depends(require_token)])
app.include_router(videos_router,  dependencies=[Depends(require_token)])
app.include_router(frames_router,  dependencies=[Depends(require_token)])
```

FastAPI's built-in `/docs` (Swagger UI) and `/openapi.json` are never protected by default — they stay accessible without a token, which is acceptable for a private self-hosted system.

### 401 Response Shape

```json
{
  "detail": "Invalid or missing bearer token"
}
```

Header: `WWW-Authenticate: Bearer` (standard RFC 6750 format).

---

## 4. Search Query

### SQL JOIN Pattern

```sql
-- POST /search core query (parametric WHERE clauses added dynamically)
SELECT DISTINCT ON (f.id)
    f.id            AS frame_id,
    f.video_id,
    f.ts_ms,
    f.minio_key     AS frame_minio_key
FROM frames f

-- YOLO detections filter (classes)
LEFT JOIN detections d ON d.frame_id = f.id

-- Face detections filter (person_ids, include_unknown_faces)
LEFT JOIN face_detections fd ON fd.frame_id = f.id

-- Join to get person name for response enrichment
LEFT JOIN known_persons kp ON kp.id = fd.matched_person_id

-- Video date filter
JOIN videos v ON v.id = f.video_id

WHERE
    -- Date range (optional)
    ($date_from::timestamptz IS NULL OR v.recorded_at >= $date_from)
    AND ($date_to::timestamptz IS NULL OR v.recorded_at <= $date_to)

    -- Video ID filter (optional)
    AND ($video_ids::uuid[] IS NULL OR f.video_id = ANY($video_ids))

    -- YOLO class filter (optional) — frame must have at least one matching detection
    AND ($classes::text[] IS NULL OR EXISTS (
        SELECT 1 FROM detections d2
        WHERE d2.frame_id = f.id
          AND d2.class_name = ANY($classes)
          AND d2.confidence >= $min_confidence
    ))

    -- Person ID filter (optional) — frame must have at least one matching face
    AND ($person_ids::uuid[] IS NULL OR EXISTS (
        SELECT 1 FROM face_detections fd2
        WHERE fd2.frame_id = f.id
          AND fd2.matched_person_id = ANY($person_ids)
    ))

    -- Unknown faces filter: include frames with unmatched faces
    AND (
        $include_unknown_faces IS FALSE
        OR EXISTS (
            SELECT 1 FROM face_detections fd3
            WHERE fd3.frame_id = f.id
              AND fd3.matched_person_id IS NULL
        )
    )

ORDER BY f.id, v.recorded_at DESC

LIMIT $page_size OFFSET ($page - 1) * $page_size
```

### Response Shape

After fetching the frame IDs, run two secondary queries to build the full response:

```python
# Per-frame response enrichment:
# 1. Fetch YOLO detections for each frame_id
# 2. Fetch face_detections (with person name) for each frame_id
# 3. Generate presigned thumbnail URL for f.minio_key

{
  "results": [
    {
      "frame_id": 12345,
      "video_id": "uuid",
      "ts_ms": 15000,
      "thumbnail_url": "/frames/12345/image",   # API redirect URL, NOT direct presigned
      "detections": [
        {"class_name": "person", "confidence": 0.87, "bbox": [x1,y1,x2,y2]}
      ],
      "faces": [
        {
          "face_detection_id": 789,
          "matched_person_id": "uuid",
          "person_name": "Alice",
          "match_tier": "confident",
          "match_similarity": 0.82,
          "bbox": [x1,y1,x2,y2]
        }
      ]
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total": 143,
    "has_next": true
  }
}
```

**Important:** `thumbnail_url` should point to the API's `GET /frames/{id}/image` (which generates a presigned URL on-demand), NOT a pre-baked presigned URL. This avoids embedding expiring URLs in the response body.

### Pagination Strategy

Use **OFFSET + LIMIT** (not cursor-based). Rationale:
- Home system: realistic max is 10K–100K frames. OFFSET pagination is fast at these scales.
- The search UI is read-heavy, single-user. No need for cursor complexity.
- Default `page_size=20`, max `page_size=100` (enforce in Pydantic validator).

For total count, run a separate `SELECT COUNT(DISTINCT f.id) FROM frames f ... (same WHERE)` — or skip the total for v1 and return `has_next: true/false` based on whether LIMIT+1 rows returned.

---

## 5. Presigned URL Streaming

### MinIO Python SDK Pattern

```python
# Source: minio==7.2.20 SDK (already in api requirements.txt)
# VERIFIED: minio Python SDK presigned_get_object signature

from minio import Minio
from datetime import timedelta

def get_minio_client() -> Minio:
    return Minio(
        endpoint=config.MINIO_ENDPOINT,
        access_key=config.MINIO_ACCESS_KEY,
        secret_key=config.MINIO_SECRET_KEY,
        secure=config.MINIO_USE_SSL,
    )

def generate_presigned_url(bucket: str, key: str, expires_hours: int = 1) -> str:
    client = get_minio_client()
    return client.presigned_get_object(
        bucket_name=bucket,
        object_name=key,
        expires=timedelta(hours=expires_hours),
    )
```

### 302 Redirect Endpoint

```python
# Source: FastAPI RedirectResponse pattern
from fastapi import APIRouter
from fastapi.responses import RedirectResponse

@router.get("/videos/{video_id}/stream")
async def stream_video(
    video_id: UUID,
    _token = Depends(require_token),
):
    # Fetch minio_key from videos table
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT minio_key FROM videos WHERE id = $1", video_id
        )
    if not row:
        raise HTTPException(404, "Video not found")

    url = generate_presigned_url(config.MINIO_BUCKET_VIDEOS, row["minio_key"], expires_hours=1)
    return RedirectResponse(url=url, status_code=302)


@router.get("/frames/{frame_id}/image")
async def frame_image(
    frame_id: int,
    _token = Depends(require_token),
):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT minio_key FROM frames WHERE id = $1", frame_id
        )
    if not row:
        raise HTTPException(404, "Frame not found")

    url = generate_presigned_url(config.MINIO_BUCKET_FRAMES, row["minio_key"], expires_hours=1)
    return RedirectResponse(url=url, status_code=302)
```

### TTL Recommendation

- **Video stream:** 1 hour (large file; browser needs time to buffer and seek)
- **Frame thumbnail:** 1 hour (consistent with video; short enough to avoid stale cache issues)

**Do NOT pre-generate presigned URLs and embed them in search results.** Always generate on-demand at redirect time. This avoids the SS-3 pitfall (expired URLs in cached search results).

---

## 6. n8n MinIO Webhook

### Overview

MinIO supports bucket event notifications via webhooks. When a new object is created in the `videos/` bucket, MinIO POSTs an event payload to a configured URL — which is the n8n webhook node.

### Configuration Steps

**Step 1: Create a MinIO notification target (run on the host or via mc CLI)**

```bash
# Register a webhook notification target in MinIO
mc admin config set myminio notify_webhook:n8n_ingest \
    endpoint="http://n8n:5678/webhook/minio-ingest" \
    queue_limit="0" \
    enable="on"

# Restart MinIO to apply
mc admin service restart myminio
```

**Step 2: Add event subscription to the videos bucket**

```bash
mc event add myminio/videos arn:minio:sqs::n8n_ingest:webhook \
    --event s3:ObjectCreated:* \
    --prefix "videos/"   # optional: restrict to video prefix
```

**Step 3: n8n Webhook Node configuration**

| Field | Value |
|-------|-------|
| HTTP Method | POST |
| Path | `minio-ingest` |
| Authentication | None (internal Docker network, protected by ingestion-worker's own logic) |
| Response Mode | Immediately |

### MinIO Event Payload Format

MinIO sends a payload compatible with the S3 event notification format [ASSUMED]:

```json
{
  "EventName": "s3:ObjectCreated:Put",
  "Key": "videos/camera01/2024-01-15_21-30.mp4",
  "Records": [
    {
      "eventVersion": "2.0",
      "eventSource": "minio:s3",
      "eventName": "s3:ObjectCreated:Put",
      "s3": {
        "bucket": {
          "name": "videos"
        },
        "object": {
          "key": "videos/camera01/2024-01-15_21-30.mp4",
          "size": 45678901,
          "contentType": "video/mp4"
        }
      }
    }
  ]
}
```

### n8n Workflow: Event-Driven Ingest

```
[Webhook Node] → [Function Node: extract key] → [HTTP Request: POST /ingest]
```

**Function Node** (extract MinIO key):
```javascript
// n8n expression in HTTP Request body
const key = $json.body.Key || $json.body.Records[0].s3.object.key;
return [{ json: { minio_key: key } }];
```

**HTTP Request Node:**
- Method: POST
- URL: `http://ingestion-worker:8001/ingest`
- Body: `{"minio_key": "{{$json.minio_key}}"}`
- Auth: None (internal Docker network)

**File extension guard** — add an IF node after the Function Node to skip non-video files:
```javascript
// IF node condition
$json.minio_key.match(/\.(mp4|mov|avi|mkv)$/i) !== null
```

### Alternative: mc CLI Watch (if MinIO webhook is unreliable)

[ASSUMED] If MinIO's webhook notification proves unreliable (missed events are a known STACK.md concern), use `mc watch` in a lightweight sidecar container that pipes events to the ingestion-worker.

---

## 7. n8n Polling Fallback

### Approach

The ingestion-worker already has `POST /ingest/batch` which:
- Scans a MinIO prefix for video files
- Checks each video's status in the DB
- Skips `done` videos (idempotent)
- Enqueues `pending` and `failed` videos

The n8n polling workflow simply calls this endpoint on a schedule:

```
[Schedule Trigger: every 10 min] → [HTTP Request: POST /ingest/batch]
```

**HTTP Request Node:**
- Method: POST  
- URL: `http://ingestion-worker:8001/ingest/batch`
- Body:
  ```json
  {
    "prefix": "videos/",
    "force": false
  }
  ```
- Auth: None (internal Docker network; ingestion-worker has no auth)

### Why Call ingestion-worker Directly (Not via api service)

- The ingestion-worker is the owner of the ingest pipeline — calling it directly avoids an extra hop through the api service
- The api service is authenticated; the internal polling workflow does not need to carry an `API_TOKEN`
- The ingestion-worker already handles its own idempotency

### Polling Frequency

10 minutes (as specified in N8N-02). With the event-driven webhook as primary trigger, polling is purely a fallback for missed events. 10 minutes is the worst-case delay for a video that the webhook missed.

### n8n Schedule Trigger Config

```
Rule: */10 * * * *   (every 10 minutes)
```

Or use n8n's Cron node with `0/10 * * * *`.

---

## 8. API Service Structure

### Current State

`services/api/app/` currently contains only:
- `__init__.py` (empty)
- `main.py` (Phase 1 stub: `GET /health` only)

### Phase 2 Module List

```
services/api/app/
├── __init__.py          (existing, empty)
├── main.py              (replace: add lifespan, DB pool, InsightFace load, routers)
├── config.py            (new: same pattern as ingestion-worker/app/config.py)
├── db.py                (new: asyncpg pool, get_pool, init_pool, close_pool helpers)
├── storage.py           (new: MinIO client, generate_presigned_url)
├── auth.py              (new: require_token dependency)
├── persons.py           (new: router POST /persons, POST /persons/{id}/enroll,
│                               DELETE /persons/{id}, POST /persons/{id}/rematch)
├── search.py            (new: router POST /search)
├── videos.py            (new: router GET /videos/{id}/stream)
└── frames.py            (new: router GET /frames/{id}/image)
```

### `config.py` for api Service

Same pattern as ingestion-worker — plain `os.environ` / `os.getenv`, no pydantic-settings:

```python
# services/api/app/config.py
import os

DATABASE_URL:           str   = os.environ["DATABASE_URL"]
MINIO_ENDPOINT:         str   = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY:       str   = os.environ["MINIO_ACCESS_KEY"]
MINIO_SECRET_KEY:       str   = os.environ["MINIO_SECRET_KEY"]
MINIO_BUCKET_VIDEOS:    str   = os.getenv("MINIO_BUCKET_VIDEOS", "videos")
MINIO_BUCKET_FRAMES:    str   = os.getenv("MINIO_BUCKET_FRAMES", "frames")
MINIO_USE_SSL:          bool  = os.getenv("MINIO_USE_SSL", "false").lower() == "true"
API_TOKEN:              str   = os.environ["API_TOKEN"]
FACE_MATCH_HIGH_THRESHOLD: float = float(os.getenv("FACE_MATCH_HIGH_THRESHOLD", "0.65"))
FACE_MATCH_LOW_THRESHOLD:  float = float(os.getenv("FACE_MATCH_LOW_THRESHOLD", "0.50"))
LOG_LEVEL:              str   = os.getenv("LOG_LEVEL", "INFO").upper()
```

### `main.py` lifespan

```python
@asynccontextmanager
async def lifespan(application: FastAPI):
    await init_pool()                        # asyncpg pool
    from .faces_api import load_face_model
    application.state.face_app = load_face_model()  # InsightFace for enrollment
    yield
    await close_pool()
```

### `db.py` (re-use ingestion-worker pattern)

Copy `db.py` from ingestion-worker as a starting point — same `init_pool()`, `close_pool()`, `get_pool()` pattern using asyncpg with pgvector codec registration. Do NOT share module between services (they are independent Docker images).

### Router Registration

```python
# main.py
app.include_router(persons_router, dependencies=[Depends(require_token)])
app.include_router(search_router,  dependencies=[Depends(require_token)])
app.include_router(videos_router,  dependencies=[Depends(require_token)])
app.include_router(frames_router,  dependencies=[Depends(require_token)])
```

---

## 9. Upload Limits & File Handling

### Default Limits

FastAPI / Starlette has no built-in upload size limit. The practical limit comes from:
- uvicorn default: no hard limit (bounded by available RAM)
- python-multipart: streams to memory by default

For enrollment photos (typically 1–5 MB each), no special configuration is needed. A sensible soft limit to enforce in the endpoint:

```python
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB per image

for img_file in images:
    data = await img_file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File '{img_file.filename}' exceeds 10 MB limit")
```

### No uvicorn Configuration Needed

Do NOT set `--limit-max-requests` or `--timeout-keep-alive` differently for uploads. The default uvicorn config handles enrollment-size uploads without issue.

### Image Decoding Pattern

```python
import cv2
import numpy as np

def decode_image(data: bytes) -> np.ndarray | None:
    """Decode uploaded bytes to OpenCV BGR array."""
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img  # None if not a valid image
```

This avoids writing the upload to disk — decode in memory directly from the bytes buffer.

### Content-Type Validation

Do NOT rely on `Content-Type` header for validation (easily spoofed). Rely on `cv2.imdecode` returning `None` for invalid images.

---

## 10. InsightFace in API Service

### Decision: Load at Startup in api Service

The api service must run InsightFace independently of the ingestion-worker. Reasons:
- Services are independent Docker images (a design rule in this project)
- Calling ingestion-worker from api service creates coupling and an unauthenticated internal API surface
- Enrollment is the only use of InsightFace in the api service; the model is needed for both face detection AND embedding computation

### Memory Impact

| Service | RSS at Steady State |
|---------|---------------------|
| ingestion-worker | ~2.5 GB (YOLO + InsightFace + ONNX working memory) |
| api service | ~1.8 GB (InsightFace only — no YOLO) |
| PostgreSQL | ~1.0 GB |
| OS + buffers | ~1.5 GB |
| **Total** | **~6.8 GB** |

This fits within 8 GB with ~1.2 GB headroom. During heavy ingestion (ingestion-worker near 5 GB limit), the api service's 1.8 GB may cause swap activity if an enrollment happens simultaneously.

**Mitigation:**
1. Add `deploy.resources.limits.memory: 2g` to the `api` service in `docker-compose.yml`
2. Do NOT run an enrollment while actively ingesting a large video (document in ops guide)
3. InsightFace in the api service uses ONLY `CPUExecutionProvider` and `det_size=(640,640)` — same as ingestion-worker

### api Service Dockerfile Change

The api service's `Dockerfile` must be updated to:
1. Add `insightface==0.7.3` and `onnxruntime==1.26.0` and `opencv-python-headless>=4.10` to `requirements.txt`
2. Bake the `buffalo_l` model at build time (same pattern as ingestion-worker):

```dockerfile
# Add to services/api/Dockerfile after pip install step
RUN python -c "\
from insightface.app import FaceAnalysis; \
app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']); \
app.prepare(ctx_id=0, det_size=(640,640))"
```

### `faces_api.py` Module (New, in api service)

Create a stripped-down version of `faces.py` for the api service — only `load_face_model()` and `analyze_frame()`. No `match_face_embedding()` (that's for the enrollment flow which computes the embedding itself). The api service's enrollment flow:

```python
# In persons.py router
face_app = request.app.state.face_app
faces = analyze_frame_from_bytes(image_bytes, face_app)  # returns list of face dicts
```

---

## Pitfalls to Avoid

### Pitfall P1: Embedding `face.embedding` Instead of `face.normed_embedding` in Enrollment

**What goes wrong:** If the enrollment code uses `face.embedding` (raw) but the ingestion pipeline stores `face.normed_embedding` (L2-normalized), similarity scores between enrollment embeddings and detection embeddings will be wrong — the person is never matched in pgvector cosine search.

**Prevention:** Create a single `analyze_frame_from_bytes()` function that always accesses `face.normed_embedding` and includes the L2 norm sanity check from `faces.py`. Copy the norm check verbatim from ingestion-worker.

---

### Pitfall P2: Auth Dependency Applied Globally (Blocks /docs and /health)

**What goes wrong:** Adding `dependencies=[Depends(require_token)]` to the FastAPI constructor (not the router) applies the dependency to ALL routes including `/docs`, `/openapi.json`, and `/health`. The Swagger UI becomes inaccessible without a token, and the Docker Compose healthcheck fails.

**Prevention:** Apply `Depends(require_token)` at `app.include_router(...)` level, not at `FastAPI(...)` constructor level. The `/health` route remains unprotected. Verified: SEARCH-05 explicitly requires `/health` and `/docs` to be exempt.

---

### Pitfall P3: Presigned URLs Embedded in Search Response Body

**What goes wrong:** `POST /search` response body includes pre-generated presigned URLs (e.g., `"thumbnail_url": "https://minio:9000/frames/...?X-Amz-Expires=3600&..."`). React Query caches this response for minutes. After 1 hour the embedded URLs expire, but the React Query cache still serves them — thumbnails become 403 broken images without any page reload.

**Prevention (PITFALLS.md SS-3):** Always return `/frames/{id}/image` (the API redirect URL) as `thumbnail_url`, never a pre-baked MinIO presigned URL. The 302 redirect generates a fresh presigned URL on every thumbnail request.

---

### Pitfall P4: Rematch Only Targets `matched_person_id IS NULL`

**What goes wrong:** After enrolling "Alice" and running rematch, some of Alice's faces in old footage were marked as "probable" match to "Bob" (a different person with lower quality images). These faces have `matched_person_id = Bob` and are skipped by the `IS NULL` filter in the rematch query, remaining incorrectly attributed.

**Mitigation (documented trade-off):** For v1, rematch only targets `matched_person_id IS NULL`. This is the ROADMAP spec. The reason is safety: re-assigning `probable` matches to a different person risks incorrect re-attribution. If a user needs to fix this, they can re-ingest the video with `?force=true`. Document this limitation in the API response: `"note": "Rematch only updates previously unmatched faces."`.

---

### Pitfall P5: MinIO Webhook Fires on ALL Object Types

**What goes wrong:** The MinIO `s3:ObjectCreated:*` event fires for every object written to the `videos/` bucket — including intermediate `.part` files, `.tmp` files, or thumbnail frames if the buckets are misconfigured. The n8n workflow calls `POST /ingest` with an invalid key, the ingestion-worker returns an error, and n8n marks the execution as failed repeatedly.

**Prevention:**
1. Add an IF node in the n8n workflow: check `{{$json.minio_key.match(/\.(mp4|mov|avi|mkv)$/i)}}` — skip non-video files
2. The ingestion-worker already has this check in `POST /ingest/batch` but not in `POST /ingest` (single video) — add a file extension check to `POST /ingest` too

---

### Pitfall P6: InsightFace in api Service Not Baked at Build Time

**What goes wrong:** The api service Dockerfile doesn't include the InsightFace model baking step (only the ingestion-worker had it in Phase 1). First deployment of the updated api container triggers a 280 MB download of `buffalo_l` at startup, which:
- Fails on first startup (network dependency)
- Takes 2+ minutes, causing Docker healthcheck failures
- Writes partial files if interrupted

**Prevention:** Add the InsightFace model bake RUN step to `services/api/Dockerfile` in Plan 1 of this phase (before any code that imports InsightFace).

---

### Pitfall P7: asyncpg Pool Not Registered with pgvector Codec in api Service

**What goes wrong:** The ingestion-worker's `db.py` registers the pgvector codec with asyncpg at pool creation time. The api service's new `db.py` (copy-adapted) must also register this codec, otherwise:
- Inserting `normed_embedding` vectors into `person_embeddings` fails with "cannot adapt type list"
- Fetching vector columns returns raw binary instead of Python lists

**Prevention:** Copy the pgvector codec registration from `ingestion-worker/app/db.py` verbatim into `api/app/db.py`. Pattern: `await pgvector.asyncpg.register(conn)` on each acquired connection, or at pool creation via the `init` callback.

---

## Wave Grouping Recommendation

Phase 2 has 3 plans as specified in ROADMAP.md. Suggested task distribution:

### Plan 1: Face Enrollment API (4–5 tasks)

**Scope:** All enrollment endpoints + api service foundation

| Task | Actions |
|------|---------|
| 1.1 | `config.py`, `db.py`, `storage.py` for api service (copy/adapt from ingestion-worker) |
| 1.2 | `auth.py` — `require_token` dependency; update `main.py` with lifespan + router registration |
| 1.3 | Add `insightface`, `onnxruntime`, `opencv-python-headless` to `api/requirements.txt`; update `api/Dockerfile` with model baking; add `deploy.resources.limits.memory: 2g` to docker-compose.yml |
| 1.4 | `faces_api.py` — `load_face_model()` + `analyze_frame_from_bytes()` (stripped from ingestion-worker `faces.py`) |
| 1.5 | `persons.py` — `POST /persons`, `POST /persons/{id}/enroll`, `DELETE /persons/{id}`, `POST /persons/{id}/rematch` |

**Dependencies:** Plan 1 must complete before Plans 2 and 3 (api foundation is shared).

---

### Plan 2: Search & Stream API (3–4 tasks)

**Scope:** Search query, pagination, presigned URL redirects

| Task | Actions |
|------|---------|
| 2.1 | `search.py` — `POST /search` with all filters, JOIN query, OFFSET pagination |
| 2.2 | `videos.py` — `GET /videos/{id}/stream` → 302 presigned URL |
| 2.3 | `frames.py` — `GET /frames/{id}/image` → 302 presigned URL |
| 2.4 | Integration smoke test: enroll a person, ingest a video, search by person_id, stream video, fetch frame |

---

### Plan 3: n8n Workflows (2–3 tasks)

**Scope:** MinIO webhook trigger + polling fallback, documented with export JSON

| Task | Actions |
|------|---------|
| 3.1 | n8n Workflow #1: MinIO webhook → POST /ingest (with file extension guard IF node); export JSON to `docs/n8n/workflow-minio-trigger.json` |
| 3.2 | n8n Workflow #2: Schedule every 10 min → POST /ingest/batch; export JSON to `docs/n8n/workflow-polling-fallback.json` |
| 3.3 | Documentation: `docs/n8n-setup.md` covering MinIO notification target configuration (`mc event add`), n8n workflow import instructions, and environment variables |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | MinIO event payload format includes `Key` and `Records[0].s3.object.key` fields | § 6 | n8n Function Node expression needs different field path; easy to fix by inspecting first event |
| A2 | n8n is accessible at `http://n8n:5678` on the `home-infra` Docker network | § 6 | Webhook URL in MinIO `mc event add` command would be wrong; check actual n8n container name |
| A3 | `mc admin config set` syntax for webhook notification target is current for the MinIO version deployed | § 6 | Different mc/MinIO version may require different syntax; check MinIO Console UI as fallback |
| A4 | `asyncpg.executemany` exists for bulk parameterized updates | § 2 | May need `conn.executemany()` or loop over `conn.execute()` — check asyncpg 0.31.0 docs |

---

## Sources

### Primary (HIGH confidence — codebase verified)
- `services/api/requirements.txt` — confirmed packages installed in api service
- `services/api/app/main.py` — current Phase 1 stub (health only)
- `services/ingestion-worker/app/faces.py` — InsightFace patterns to replicate
- `services/ingestion-worker/app/config.py` — config pattern to follow
- `services/ingestion-worker/app/main.py` — lifespan pattern, FastAPI startup
- `db/init/001_schema.sql` — authoritative schema (tables, columns, indexes, constraints)
- `docker-compose.yml` — service config, env vars, network name
- `.planning/research/STACK.md` — verified stack versions (insightface 0.7.3, asyncpg 0.31.0, minio 7.2.20)
- `.planning/research/PITFALLS.md` — FR-2, FR-4, FR-5, SS-3 directly applicable to Phase 2

### Secondary (MEDIUM confidence — training + official library docs)
- MinIO notification configuration via `mc event add` [ASSUMED — verify against deployed MinIO version]
- n8n Webhook node + Schedule Trigger node [ASSUMED — n8n is already deployed; verify exact node names]
- FastAPI `HTTPBearer` + `Security()` auth pattern [HIGH — standard FastAPI pattern]
- MinIO Python SDK `presigned_get_object()` signature [HIGH — minio==7.2.20 in requirements.txt]

---

## Environment Availability

| Dependency | Required By | Available | Notes |
|------------|------------|-----------|-------|
| PostgreSQL + pgvector | All endpoints | ✓ (Phase 1 complete) | HNSW indexes on face_detections and person_embeddings |
| MinIO | Presigned URLs, bucket events | ✓ (external, home-infra) | Already running, already configured in .env.example |
| n8n | N8N-01, N8N-02 | ✓ (external, home-infra) | Already running; needs workflow import |
| InsightFace buffalo_l in api image | ENROLL-02 | ✗ (not yet in api Dockerfile) | Plan 1 Task 1.3 adds it |
| `python-multipart` | File upload | ✓ (already in api requirements.txt) | No action needed |

**Missing dependencies requiring action:**
- InsightFace + ONNX Runtime not in api `requirements.txt` and not baked into api Docker image — must be added in Plan 1 before any enrollment endpoint can work.
