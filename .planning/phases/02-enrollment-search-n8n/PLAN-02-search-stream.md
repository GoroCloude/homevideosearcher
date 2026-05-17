# Plan 02: Search & Stream API

**Phase:** 02 - Enrollment, Search API & n8n Automation  
**Goal:** Implement `POST /search` with full filter set + pagination, `GET /videos/{id}/stream` and `GET /frames/{id}/image` as 302 presigned-URL redirects, `GET /persons/{id}/faces`, and wire all new routers into `main.py` behind the existing bearer token auth.

**Requirements covered:** SEARCH-01, SEARCH-02, SEARCH-03, SEARCH-04, SEARCH-05  
**Depends on:** Plan 01 complete (config.py, db.py, auth.py, persons.py, main.py in place)  
**Wave:** 2 (modifies `main.py` and `persons.py` — both created in Plan 01)

---

## Tasks

### Task 1 — Create `services/api/app/storage.py`

**File:** `services/api/app/storage.py` *(create new)*

MinIO client singleton + presigned URL generator. Pattern mirrors `ingestion-worker/app/storage.py` but exposes `generate_presigned_url()` instead of upload/download helpers.

```python
"""MinIO client wrapper for the api service.

Only purpose in the api service: generate presigned GET URLs for
video streams and frame thumbnails. Upload/download are ingestion-worker concerns.

CRITICAL: never embed presigned URLs in search response bodies.
Always generate on-demand at redirect time (GET /videos/{id}/stream,
GET /frames/{id}/image). Presigned URLs expire in 1 h — stale cached
responses would break thumbnails if URLs were pre-baked into search results.
"""
import logging
from datetime import timedelta
from typing import Optional

from minio import Minio

from . import config

logger = logging.getLogger(__name__)

_client: Optional[Minio] = None


def get_minio_client() -> Minio:
    """Return the shared Minio singleton (initialized on first call)."""
    global _client
    if _client is None:
        _client = Minio(
            config.MINIO_ENDPOINT,
            access_key=config.MINIO_ACCESS_KEY,
            secret_key=config.MINIO_SECRET_KEY,
            secure=config.MINIO_USE_SSL,
        )
    return _client


def generate_presigned_url(bucket: str, key: str, expires_hours: int = 1) -> str:
    """
    Generate a presigned GET URL valid for `expires_hours` hours.
    Called per-request at redirect time — never called during search queries.
    """
    client = get_minio_client()
    url = client.presigned_get_object(
        bucket_name=bucket,
        object_name=key,
        expires=timedelta(hours=expires_hours),
    )
    logger.debug("Generated presigned URL for %s/%s (TTL=%dh)", bucket, key, expires_hours)
    return url
```

---

### Task 2 — Create `services/api/app/search.py`

**File:** `services/api/app/search.py` *(create new)*

`POST /search` with full filter set, OFFSET-based pagination, enriched per-frame response. The `thumbnail_url` field is always the API path `/frames/{id}/image` — **never** a pre-baked MinIO presigned URL.

```python
"""
Search router: POST /search

Filters (all optional — omit to match all):
    video_ids:            list[UUID]  — restrict to specific videos
    person_ids:           list[UUID]  — frames containing these known persons
    classes:              list[str]   — YOLO class names (e.g. ["person","car"])
    include_unknown_faces: bool       — include frames with unmatched faces
    date_from:            str | None  — ISO 8601 datetime; filter by video.recorded_at
    date_to:              str | None  — ISO 8601 datetime
    min_confidence:       float       — minimum YOLO detection confidence (default 0.0)
    page:                 int         — 1-based page number (default 1)
    page_size:            int         — rows per page (default 20, max 100)

Response:
    results: list of FrameResult
    pagination: { page, page_size, total, has_next }
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from .db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


# ── Request / Response models ─────────────────────────────────────────────────

class SearchRequest(BaseModel):
    video_ids:             Optional[list[UUID]] = None
    person_ids:            Optional[list[UUID]] = None
    classes:               Optional[list[str]]  = None
    include_unknown_faces: bool                 = False
    date_from:             Optional[str]        = None   # ISO 8601
    date_to:               Optional[str]        = None   # ISO 8601
    min_confidence:        float                = 0.0
    page:                  int                  = 1
    page_size:             int                  = 20

    @field_validator("page")
    @classmethod
    def page_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("page must be >= 1")
        return v

    @field_validator("page_size")
    @classmethod
    def page_size_range(cls, v: int) -> int:
        if not (1 <= v <= 100):
            raise ValueError("page_size must be 1–100")
        return v


class DetectionResult(BaseModel):
    class_name:  str
    confidence:  float
    bbox:        list[int]   # [x1, y1, x2, y2]


class FaceResult(BaseModel):
    face_detection_id:  int
    matched_person_id:  Optional[str]
    person_name:        Optional[str]
    match_tier:         Optional[str]
    match_similarity:   Optional[float]
    bbox:               list[int]   # [x1, y1, x2, y2]


class FrameResult(BaseModel):
    frame_id:      int
    video_id:      str
    ts_ms:         int
    thumbnail_url: str          # Always /frames/{id}/image — NOT a presigned URL
    detections:    list[DetectionResult]
    faces:         list[FaceResult]


class PaginationInfo(BaseModel):
    page:       int
    page_size:  int
    total:      int
    has_next:   bool


class SearchResponse(BaseModel):
    results:    list[FrameResult]
    pagination: PaginationInfo


# ── POST /search ──────────────────────────────────────────────────────────────

@router.post("", response_model=SearchResponse)
async def search_frames(body: SearchRequest) -> SearchResponse:
    """
    Search frames by any combination of filters.
    Returns paginated FrameResult list with YOLO detections and face matches.
    """
    pool = await get_pool()

    # Convert UUID lists to str lists for asyncpg
    video_ids_str  = [str(v) for v in body.video_ids]  if body.video_ids  else None
    person_ids_str = [str(p) for p in body.person_ids] if body.person_ids else None

    # ── Count query (for pagination total) ────────────────────────────────────
    count_sql = _build_search_sql(count_only=True)
    frame_sql = _build_search_sql(count_only=False)

    params = _build_params(body, video_ids_str, person_ids_str)
    count_params = params[:-2]  # remove LIMIT + OFFSET from count query

    async with pool.acquire() as conn:
        total_row = await conn.fetchrow(count_sql, *count_params)
        total = int(total_row["total"])

        rows = await conn.fetch(frame_sql, *params)

    if not rows:
        return SearchResponse(
            results=[],
            pagination=PaginationInfo(
                page=body.page,
                page_size=body.page_size,
                total=total,
                has_next=False,
            ),
        )

    frame_ids = [r["frame_id"] for r in rows]
    frame_map  = {r["frame_id"]: r for r in rows}

    # ── Fetch YOLO detections for matching frames ──────────────────────────────
    async with pool.acquire() as conn:
        det_rows = await conn.fetch(
            """
            SELECT frame_id, class_name, confidence,
                   bbox_x1, bbox_y1, bbox_x2, bbox_y2
            FROM detections
            WHERE frame_id = ANY($1::bigint[])
            """,
            frame_ids,
        )

    det_by_frame: dict[int, list[DetectionResult]] = {fid: [] for fid in frame_ids}
    for d in det_rows:
        det_by_frame[d["frame_id"]].append(
            DetectionResult(
                class_name=d["class_name"],
                confidence=float(d["confidence"]),
                bbox=[d["bbox_x1"], d["bbox_y1"], d["bbox_x2"], d["bbox_y2"]],
            )
        )

    # ── Fetch face detections for matching frames ──────────────────────────────
    async with pool.acquire() as conn:
        face_rows = await conn.fetch(
            """
            SELECT
                fd.id AS face_detection_id,
                fd.frame_id,
                fd.matched_person_id::text,
                fd.match_tier,
                fd.match_similarity,
                fd.bbox_x1, fd.bbox_y1, fd.bbox_x2, fd.bbox_y2,
                kp.name AS person_name
            FROM face_detections fd
            LEFT JOIN known_persons kp ON kp.id = fd.matched_person_id
            WHERE fd.frame_id = ANY($1::bigint[])
            """,
            frame_ids,
        )

    face_by_frame: dict[int, list[FaceResult]] = {fid: [] for fid in frame_ids}
    for f in face_rows:
        face_by_frame[f["frame_id"]].append(
            FaceResult(
                face_detection_id=f["face_detection_id"],
                matched_person_id=f["matched_person_id"],
                person_name=f["person_name"],
                match_tier=f["match_tier"],
                match_similarity=float(f["match_similarity"]) if f["match_similarity"] else None,
                bbox=[f["bbox_x1"], f["bbox_y1"], f["bbox_x2"], f["bbox_y2"]],
            )
        )

    # ── Assemble results ───────────────────────────────────────────────────────
    results = [
        FrameResult(
            frame_id=fid,
            video_id=str(frame_map[fid]["video_id"]),
            ts_ms=frame_map[fid]["ts_ms"],
            thumbnail_url=f"/frames/{fid}/image",   # on-demand presigned URL at redirect time
            detections=det_by_frame.get(fid, []),
            faces=face_by_frame.get(fid, []),
        )
        for fid in frame_ids
    ]

    return SearchResponse(
        results=results,
        pagination=PaginationInfo(
            page=body.page,
            page_size=body.page_size,
            total=total,
            has_next=(body.page * body.page_size) < total,
        ),
    )


# ── SQL builder helpers ───────────────────────────────────────────────────────

def _build_search_sql(count_only: bool) -> str:
    """
    Build the search SQL string.
    Parameters (positional):
      $1  video_ids      text[] | NULL
      $2  person_ids     text[] | NULL
      $3  classes        text[] | NULL
      $4  include_unknown_faces  bool
      $5  date_from      timestamptz | NULL
      $6  date_to        timestamptz | NULL
      $7  min_confidence float
      ($8 limit, $9 offset — count_only=False only)
    """
    select = (
        "SELECT COUNT(DISTINCT f.id) AS total"
        if count_only
        else """
        SELECT DISTINCT ON (f.id)
            f.id        AS frame_id,
            f.video_id,
            f.ts_ms
        """
    )
    sql = f"""
        {select}
        FROM frames f
        JOIN videos v ON v.id = f.video_id
        WHERE
            ($1::text[] IS NULL OR f.video_id::text = ANY($1))
            AND ($5::timestamptz IS NULL OR v.recorded_at >= $5::timestamptz)
            AND ($6::timestamptz IS NULL OR v.recorded_at <= $6::timestamptz)
            AND (
                $3::text[] IS NULL
                OR EXISTS (
                    SELECT 1 FROM detections d
                    WHERE d.frame_id = f.id
                      AND d.class_name = ANY($3)
                      AND d.confidence >= $7
                )
            )
            AND (
                $2::text[] IS NULL
                OR EXISTS (
                    SELECT 1 FROM face_detections fd2
                    WHERE fd2.frame_id = f.id
                      AND fd2.matched_person_id::text = ANY($2)
                )
            )
            AND (
                $4 IS FALSE
                OR EXISTS (
                    SELECT 1 FROM face_detections fd3
                    WHERE fd3.frame_id = f.id
                      AND fd3.matched_person_id IS NULL
                )
            )
    """
    if not count_only:
        sql += """
        ORDER BY f.id, v.recorded_at DESC NULLS LAST
        LIMIT $8 OFFSET $9
        """
    return sql


def _build_params(
    body: SearchRequest,
    video_ids_str: Optional[list[str]],
    person_ids_str: Optional[list[str]],
) -> list:
    """Return positional params list for the frame query (includes LIMIT + OFFSET)."""
    offset = (body.page - 1) * body.page_size
    return [
        video_ids_str,                          # $1
        person_ids_str,                         # $2
        body.classes,                           # $3
        body.include_unknown_faces,             # $4
        body.date_from,                         # $5
        body.date_to,                           # $6
        body.min_confidence,                    # $7
        body.page_size,                         # $8  (omitted for count)
        offset,                                 # $9  (omitted for count)
    ]
```

---

### Task 3 — Create `services/api/app/videos.py`

**File:** `services/api/app/videos.py` *(create new)*

```python
"""
Videos router: GET /videos/{video_id}/stream

Returns a 302 redirect to a MinIO presigned URL (1 h TTL).
Presigned URL is generated on-demand at redirect time — NOT stored anywhere.
"""
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from . import config
from .db import get_pool
from .storage import generate_presigned_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/videos", tags=["videos"])


@router.get("/{video_id}/stream")
async def stream_video(video_id: UUID) -> RedirectResponse:
    """
    302 redirect to a presigned MinIO URL for the video file.
    TTL: 1 hour. Client (browser, player) follows the redirect and streams directly
    from MinIO — the api service never proxies the video bytes.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT minio_key FROM videos WHERE id = $1", video_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Video not found")

    url = generate_presigned_url(
        bucket=config.MINIO_BUCKET_VIDEOS,
        key=row["minio_key"],
        expires_hours=1,
    )
    return RedirectResponse(url=url, status_code=302)
```

---

### Task 4 — Create `services/api/app/frames.py`

**File:** `services/api/app/frames.py` *(create new)*

```python
"""
Frames router: GET /frames/{frame_id}/image

Returns a 302 redirect to a MinIO presigned URL for the frame JPEG (1 h TTL).
This is the endpoint that thumbnail_url in /search responses points to.
"""
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from . import config
from .db import get_pool
from .storage import generate_presigned_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/frames", tags=["frames"])


@router.get("/{frame_id}/image")
async def frame_image(frame_id: int) -> RedirectResponse:
    """
    302 redirect to a presigned MinIO URL for the frame thumbnail JPEG.
    TTL: 1 hour. Generated fresh on each request — no caching of presigned URLs.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT minio_key FROM frames WHERE id = $1", frame_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Frame not found")

    url = generate_presigned_url(
        bucket=config.MINIO_BUCKET_FRAMES,
        key=row["minio_key"],
        expires_hours=1,
    )
    return RedirectResponse(url=url, status_code=302)
```

---

### Task 5 — Add `GET /persons/{person_id}/faces` to `services/api/app/persons.py`

**File:** `services/api/app/persons.py` *(modify — append to existing router)*

Add the following endpoint and Pydantic models to the **bottom** of the existing `persons.py` file (after the `rematch_person` function). Do not change any existing code.

```python
# ── GET /persons/{person_id}/faces ────────────────────────────────────────────
# Append these models and endpoint after rematch_person() in persons.py

class PersonFaceResult(BaseModel):
    face_detection_id: int
    frame_id:          int
    video_id:          str
    ts_ms:             int
    match_tier:        Optional[str]
    match_similarity:  Optional[float]
    det_score:         Optional[float]
    thumbnail_url:     str    # /frames/{frame_id}/image


class PersonFacesResponse(BaseModel):
    person_id:  str
    results:    list[PersonFaceResult]
    pagination: dict


@router.get("/{person_id}/faces", response_model=PersonFacesResponse)
async def list_person_faces(
    person_id: UUID,
    page: int = 1,
    page_size: int = 20,
) -> PersonFacesResponse:
    """
    Paginated list of face_detections matched to this person.
    Returns frame context (video_id, ts_ms) and thumbnail URL for each face.
    """
    if page < 1:
        raise HTTPException(status_code=422, detail="page must be >= 1")
    if not (1 <= page_size <= 100):
        raise HTTPException(status_code=422, detail="page_size must be 1–100")

    pool = await get_pool()

    # Verify person exists
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM known_persons WHERE id = $1", person_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")

    offset = (page - 1) * page_size

    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM face_detections WHERE matched_person_id = $1",
            person_id,
        )
        rows = await conn.fetch(
            """
            SELECT
                fd.id   AS face_detection_id,
                fd.frame_id,
                f.video_id::text,
                f.ts_ms,
                fd.match_tier,
                fd.match_similarity,
                fd.det_score
            FROM face_detections fd
            JOIN frames f ON f.id = fd.frame_id
            WHERE fd.matched_person_id = $1
            ORDER BY f.ts_ms DESC
            LIMIT $2 OFFSET $3
            """,
            person_id,
            page_size,
            offset,
        )

    results = [
        PersonFaceResult(
            face_detection_id=r["face_detection_id"],
            frame_id=r["frame_id"],
            video_id=r["video_id"],
            ts_ms=r["ts_ms"],
            match_tier=r["match_tier"],
            match_similarity=float(r["match_similarity"]) if r["match_similarity"] else None,
            det_score=float(r["det_score"]) if r["det_score"] else None,
            thumbnail_url=f"/frames/{r['frame_id']}/image",
        )
        for r in rows
    ]

    return PersonFacesResponse(
        person_id=str(person_id),
        results=results,
        pagination={
            "page":      page,
            "page_size": page_size,
            "total":     int(total),
            "has_next":  (page * page_size) < int(total),
        },
    )
```

---

### Task 6 — Update `services/api/app/main.py` to include new routers

**File:** `services/api/app/main.py` *(modify)*

Replace the three comment lines at the bottom of the file with actual router imports and includes:

**Find** (the comment block left by Plan 01):
```python
# Plan 02 will append:
# app.include_router(search_router,  dependencies=[Depends(require_token)])
# app.include_router(videos_router,  dependencies=[Depends(require_token)])
# app.include_router(frames_router,  dependencies=[Depends(require_token)])
```

**Replace with:**
```python
from .search import router as search_router
from .videos import router as videos_router
from .frames import router as frames_router

app.include_router(search_router,  dependencies=[Depends(require_token)])
app.include_router(videos_router,  dependencies=[Depends(require_token)])
app.include_router(frames_router,  dependencies=[Depends(require_token)])
```

Also update the version string in the `FastAPI(...)` constructor from `"0.2.0"` to `"0.2.0"` (no change needed; already set in Plan 01).

**Full `main.py` after Plan 02 edits:**
```python
"""
HomeVideoSearcher API service — Phase 2 complete.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from . import config
from .auth import require_token
from .db import close_pool, init_pool
from .frames import router as frames_router
from .persons import router as persons_router
from .search import router as search_router
from .videos import router as videos_router

LOG_LEVEL = config.LOG_LEVEL
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "api"}


app.include_router(persons_router, dependencies=[Depends(require_token)])
app.include_router(search_router,  dependencies=[Depends(require_token)])
app.include_router(videos_router,  dependencies=[Depends(require_token)])
app.include_router(frames_router,  dependencies=[Depends(require_token)])
```

---

## Verification

After executing all tasks, verify the following:

- [ ] `docker compose up api` logs show no import errors for search, videos, frames routers
- [ ] `GET /docs` (Swagger UI) at `http://localhost:8000/docs` shows all 9 routes: `/health`, `/persons` (5 routes), `/search`, `/videos/{id}/stream`, `/frames/{id}/image` — accessible without a token
- [ ] `POST /search` with an empty body `{}` and valid Bearer token returns `{"results":[],"pagination":{"page":1,"page_size":20,"total":0,"has_next":false}}` (or actual data if videos already ingested)
- [ ] `POST /search` with `{"person_ids":["<uuid-of-enrolled-person>"]}` returns frames where that person appears (verify by checking DB: `SELECT COUNT(*) FROM face_detections WHERE matched_person_id = '<uuid>'`)
- [ ] `POST /search` response `thumbnail_url` values are of form `/frames/{id}/image` — NOT presigned MinIO URLs
- [ ] `GET /frames/{id}/image` with valid Bearer token and real frame_id returns HTTP 302 with `Location:` header pointing to MinIO presigned URL starting with `http://`
- [ ] Opening the presigned URL directly in browser (no token needed) returns the JPEG thumbnail
- [ ] `GET /videos/{id}/stream` with valid Bearer token returns HTTP 302 with presigned URL; following it in browser or VLC plays the video
- [ ] `GET /persons/{id}/faces` returns paginated face detection list with `thumbnail_url` per face
- [ ] `POST /search` without Bearer token returns 401 `{"detail":"Invalid or missing bearer token"}`
- [ ] `POST /search` with `{"page_size":101}` returns 422 validation error
- [ ] `GET /frames/999999/image` returns 404 `{"detail":"Frame not found"}`
- [ ] `GET /videos/00000000-0000-0000-0000-000000000000/stream` returns 404 `{"detail":"Video not found"}`

---

## Threat Model

- **Presigned URL leakage via cached search responses:** `thumbnail_url` in search results is `/frames/{id}/image` — an internal API path, not a presigned URL. The presigned URL is generated fresh per-redirect with a 1-hour TTL. A client caching the search response does not get a stale presigned URL. (If `thumbnail_url` were a pre-baked presigned URL it would become a broken link after 1h.) This is enforced by the `f"/frames/{fid}/image"` pattern in `search.py` — never call `generate_presigned_url()` inside `search_frames()`.

- **Unauthorized access to video content via MinIO direct URL:** The presigned URL TTL is 1 hour. After expiry the URL stops working. A user who captures the presigned URL from a 302 Location header has a 1-hour window to share it. For a private self-hosted system on a home network, this is acceptable. If the system is exposed to the internet: consider reducing TTL to 15 minutes for thumbnails.

- **Search result information disclosure (person names):** `POST /search` is behind Bearer token auth. The response includes `person_name` in face results — this is expected behavior for an authenticated API. No PII exposure to unauthenticated callers.

- **SQL injection via search filters:** All filter values are passed as asyncpg parameterized queries (`$1`, `$2`, etc.). The `_build_search_sql()` function uses only positional parameters — no string interpolation of user input into the SQL string. `ANY($1::text[])` cast patterns are safe.

- **Search amplification / response size:** `page_size` is capped at 100 by `SearchRequest.page_size_range` validator. Each result includes up to N detections and M faces — for extreme frames this could be large. Mitigation: the secondary queries (`detections`, `face_detections`) use `WHERE frame_id = ANY($1::bigint[])` which is bounded by the page size (max 100 frame IDs). Response sizes are bounded.
