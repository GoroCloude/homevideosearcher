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
