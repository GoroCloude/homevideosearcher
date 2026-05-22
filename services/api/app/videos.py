"""
Videos router: GET /videos/{video_id}/stream
              GET /videos (paginated list)
              GET /videos/{video_id}/stream-url (JSON presigned URL)

Returns a 302 redirect to a MinIO presigned URL (1 h TTL).
Presigned URL is generated on-demand at redirect time — NOT stored anywhere.
"""
import logging
import os
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from . import config
from .db import get_pool
from .storage import generate_presigned_url, generate_presigned_upload_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/videos", tags=["videos"])


class VideoListItem(BaseModel):
    id:               str
    minio_key:        str
    status:           str
    error_message:    Optional[str] = None
    recorded_at:      Optional[str] = None
    duration_sec:     Optional[float] = None
    frame_count:      int
    detection_count:  int
    face_count:       int
    ingested_at:      str

class VideoListResponse(BaseModel):
    results:   List[VideoListItem]
    total:     int
    page:      int
    page_size: int
    has_next:  bool

class StreamUrlResponse(BaseModel):
    url: str


class UploadUrlRequest(BaseModel):
    filename: str  # original filename from browser; sanitized server-side before use

class UploadUrlResponse(BaseModel):
    url: str        # presigned PUT URL — browser sends video bytes directly to this URL
    key: str        # MinIO object key, e.g. "videos/video.mp4" — pass to POST /ingest-api/ingest
    expires_in: int  # seconds until URL expires (always 3600)


@router.post("/upload-url", response_model=UploadUrlResponse)
async def get_upload_url(body: UploadUrlRequest) -> UploadUrlResponse:
    """
    Returns a presigned MinIO PUT URL for direct browser → MinIO upload.
    Auth: inherited from videos_router registration with Depends(require_token) in main.py.

    Security — T1 (path traversal): filename sanitized with os.path.basename before building key.
    Security — T2 (scope leak): key always prefixed with 'videos/' — prefix is never user-controlled.
    Security — T3 (unauth access): require_token dependency on router; no code change needed.
    """
    # T1: Strip all path separators (handles both / from POSIX and \ from Windows browsers).
    # Replace backslashes first so os.path.basename sees a forward-slash path.
    safe_name = os.path.basename(body.filename.replace("\\", "/")).strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid filename")

    # T2: Hardcoded 'videos/' prefix — user cannot set the bucket or path prefix.
    key = f"videos/{safe_name}"
    url = generate_presigned_upload_url(
        bucket=config.MINIO_BUCKET_VIDEOS,
        key=key,
        expires_minutes=60,
    )
    return UploadUrlResponse(url=url, key=key, expires_in=3600)


@router.get("", response_model=VideoListResponse)
async def list_videos(page: int = 1, page_size: int = 50) -> VideoListResponse:
    """List all ingested videos with aggregate counts. Auth required (sensitive data)."""
    pool = await get_pool()
    offset = (page - 1) * page_size
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM videos")
        rows = await conn.fetch(
            """
            SELECT
                v.id::text,
                v.minio_key,
                v.status,
                v.error_message,
                v.recorded_at::text,
                v.duration_sec,
                COUNT(DISTINCT f.id)  AS frame_count,
                COUNT(DISTINCT d.id)  AS detection_count,
                COUNT(DISTINCT fd.id) AS face_count,
                v.ingested_at::text   AS ingested_at
            FROM videos v
            LEFT JOIN frames         f  ON f.video_id = v.id
            LEFT JOIN detections     d  ON d.frame_id = f.id
            LEFT JOIN face_detections fd ON fd.frame_id = f.id
            GROUP BY v.id
            ORDER BY v.ingested_at DESC
            LIMIT $1 OFFSET $2
            """,
            page_size, offset
        )
    items = [VideoListItem(**dict(r)) for r in rows]
    return VideoListResponse(
        results=items,
        total=total,
        page=page,
        page_size=page_size,
        has_next=(offset + page_size) < total,
    )


@router.get("/{video_id}/stream-url", response_model=StreamUrlResponse)
async def stream_video_url(video_id: UUID) -> StreamUrlResponse:
    """
    Returns presigned MinIO URL as JSON. Used by the UI for timestamp-seek:
      JS fetches this → opens `${url}#t=${ts_ms/1000}` in new tab.
    The existing GET /{video_id}/stream (302) is preserved for backward compat.
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
    return StreamUrlResponse(url=url)


class VideoDetail(BaseModel):
    id:              str
    filename:        str           # basename of minio_key, e.g. "family_bbq.mp4"
    minio_key:       str           # full MinIO key, e.g. "videos/family_bbq.mp4"
    status:          str
    error_message:   Optional[str] = None
    recorded_at:     Optional[str] = None
    duration_sec:    Optional[float] = None
    ingested_at:     str
    frame_count:     int
    detection_count: int
    face_count:      int
    stream_url:      str           # presigned GET URL — 1h TTL, generated on-demand


@router.get("/{video_id}", response_model=VideoDetail)
async def get_video_detail(video_id: UUID) -> VideoDetail:
    """
    Returns full video metadata plus a presigned stream URL.
    Auth: inherited from videos_router registration in main.py.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                v.id::text,
                v.minio_key,
                v.status,
                v.error_message,
                v.recorded_at::text,
                v.duration_sec,
                v.ingested_at::text,
                COUNT(DISTINCT f.id)   AS frame_count,
                COUNT(DISTINCT d.id)   AS detection_count,
                COUNT(DISTINCT fd.id)  AS face_count
            FROM videos v
            LEFT JOIN frames          f  ON f.video_id = v.id
            LEFT JOIN detections      d  ON d.frame_id = f.id
            LEFT JOIN face_detections fd ON fd.frame_id = f.id
            WHERE v.id = $1
            GROUP BY v.id, v.minio_key, v.status, v.error_message,
                     v.recorded_at, v.duration_sec, v.ingested_at
            """,
            video_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Video not found")
    stream_url = generate_presigned_url(
        bucket=config.MINIO_BUCKET_VIDEOS,
        key=row["minio_key"],
        expires_hours=1,
    )
    return VideoDetail(
        id=row["id"],
        filename=row["minio_key"].split("/")[-1],
        minio_key=row["minio_key"],
        status=row["status"],
        error_message=row["error_message"],
        recorded_at=row["recorded_at"],
        duration_sec=row["duration_sec"],
        ingested_at=row["ingested_at"],
        frame_count=row["frame_count"],
        detection_count=row["detection_count"],
        face_count=row["face_count"],
        stream_url=stream_url,
    )


class DetectionItem(BaseModel):
    id:            str
    frame_id:      str
    ts_ms:         int           # millisecond offset within video
    thumbnail_url: str           # presigned GET URL for frame thumbnail (MINIO_BUCKET_FRAMES)
    label:         str           # YOLO class label, e.g. "person", "car"
    confidence:    float
    bbox_json:     str           # JSON string of bounding box coords


@router.get("/{video_id}/detections", response_model=List[DetectionItem])
async def list_video_detections(video_id: UUID) -> List[DetectionItem]:
    """
    Returns all YOLO detection records for the video ordered by timestamp.
    Each item includes a presigned frame thumbnail URL (1h TTL).
    Auth: inherited from videos_router registration in main.py.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Verify video exists first
        exists = await conn.fetchval(
            "SELECT 1 FROM videos WHERE id = $1", video_id
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Video not found")

        rows = await conn.fetch(
            """
            SELECT
                d.id::text         AS id,
                d.frame_id::text   AS frame_id,
                f.ts_ms,
                f.minio_key        AS frame_minio_key,
                d.label,
                d.confidence,
                d.bbox_json
            FROM detections d
            JOIN frames f ON f.id = d.frame_id
            WHERE f.video_id = $1
            ORDER BY f.ts_ms, d.id
            """,
            video_id,
        )
    return [
        DetectionItem(
            id=r["id"],
            frame_id=r["frame_id"],
            ts_ms=r["ts_ms"],
            thumbnail_url=generate_presigned_url(
                bucket=config.MINIO_BUCKET_FRAMES,
                key=r["frame_minio_key"],
                expires_hours=1,
            ),
            label=r["label"],
            confidence=r["confidence"],
            bbox_json=r["bbox_json"],
        )
        for r in rows
    ]


class FaceItem(BaseModel):
    id:               str
    frame_id:         str
    ts_ms:            int           # millisecond offset within video
    thumbnail_url:    str           # presigned GET URL for frame thumbnail (MINIO_BUCKET_FRAMES)
    person_name:      str           # persons.name, unknown_clusters.label_name, or "Unknown Cluster #<uuid8>"
    appearance_count: int           # total appearances of this person/cluster in this video


@router.get("/{video_id}/faces", response_model=List[FaceItem])
async def list_video_faces(video_id: UUID) -> List[FaceItem]:
    """
    Returns all face detection records for the video ordered by timestamp.
    person_name resolution priority:
      1. persons.name  (when matched_person_id is set)
      2. unknown_clusters.label_name  (when unknown_cluster_id is set and label_name is not null)
      3. "Unknown Cluster #<first-8-chars-of-cluster-UUID>"  (fallback)
    appearance_count: total rows sharing the same matched_person_id or unknown_cluster_id in this video.
    Auth: inherited from videos_router registration in main.py.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM videos WHERE id = $1", video_id
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Video not found")

        rows = await conn.fetch(
            """
            SELECT
                fd.id::text              AS id,
                fd.frame_id::text        AS frame_id,
                f.ts_ms,
                f.minio_key              AS frame_minio_key,
                p.name                   AS person_name,
                uc.label_name            AS cluster_label,
                LEFT(uc.id::text, 8)     AS cluster_id_prefix,
                COUNT(fd.id) OVER (
                    PARTITION BY COALESCE(
                        fd.matched_person_id::text,
                        fd.unknown_cluster_id::text
                    )
                )                        AS appearance_count
            FROM face_detections fd
            JOIN frames f ON f.id = fd.frame_id
            LEFT JOIN persons p ON p.id = fd.matched_person_id
            LEFT JOIN unknown_clusters uc ON uc.id = fd.unknown_cluster_id
            WHERE f.video_id = $1
            ORDER BY f.ts_ms, fd.id
            """,
            video_id,
        )

    items: List[FaceItem] = []
    for r in rows:
        # Resolve display name in priority order
        if r["person_name"] is not None:
            name = r["person_name"]
        elif r["cluster_label"] is not None:
            name = r["cluster_label"]
        else:
            name = f"Unknown Cluster #{r['cluster_id_prefix'] or 'unknown'}"

        items.append(FaceItem(
            id=r["id"],
            frame_id=r["frame_id"],
            ts_ms=r["ts_ms"],
            thumbnail_url=generate_presigned_url(
                bucket=config.MINIO_BUCKET_FRAMES,
                key=r["frame_minio_key"],
                expires_hours=1,
            ),
            person_name=name,
            appearance_count=r["appearance_count"],
        ))
    return items


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
