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
