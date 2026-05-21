"""
Videos router: GET /videos/{video_id}/stream
              GET /videos (paginated list)
              GET /videos/{video_id}/stream-url (JSON presigned URL)

Returns a 302 redirect to a MinIO presigned URL (1 h TTL).
Presigned URL is generated on-demand at redirect time — NOT stored anywhere.
"""
import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from . import config
from .db import get_pool
from .storage import generate_presigned_url

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
