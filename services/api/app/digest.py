"""
Digest module — Phase 3.
POST /digest/send : Send unknown cluster thumbnails to Telegram via sendMediaGroup.

Fetches representative frame bytes from MinIO internally (Telegram servers cannot
reach the internal Docker network). Sends up to 10 photos in a single album.
"""
import asyncio
import logging
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from telegram import Bot, InputMediaPhoto
from telegram.error import TelegramError

from . import config
from .db import get_pool
from .storage import get_minio_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["digest"])


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic model
# ─────────────────────────────────────────────────────────────────────────────

class DigestResponse(BaseModel):
    sent:    int
    skipped: bool
    message: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# POST /digest/send
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/digest/send", response_model=DigestResponse)
async def send_digest() -> DigestResponse:
    """
    Send all non-ignored, non-promoted unknown clusters to Telegram as a photo album.

    - No time filter: ALL active unknown clusters are included (per product decision).
    - Up to 10 photos per sendMediaGroup call (Telegram API limit).
    - Returns {sent: 0, skipped: true} if no active clusters with a MinIO frame exist.
    - Returns HTTP 503 if Telegram credentials are not configured.
    """
    # Guard: Telegram credentials must be present
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram not configured: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID",
        )

    pool = await get_pool()
    minio_client = get_minio_client()

    # ── Query clusters with representative frame minio_key ────────────────────
    async with pool.acquire() as conn:
        clusters = await conn.fetch("""
            SELECT
                uc.id::text,
                uc.appearance_count,
                uc.first_seen::text,
                uc.last_seen::text,
                f.minio_key
            FROM unknown_clusters uc
            LEFT JOIN face_detections fd ON fd.id = uc.representative_face_id
            LEFT JOIN frames f ON f.id = fd.frame_id
            WHERE uc.ignored = false
              AND uc.promoted_at IS NULL
              AND f.minio_key IS NOT NULL
            ORDER BY uc.appearance_count DESC
            LIMIT 10
        """)

    if not clusters:
        logger.info("No active clusters with thumbnails — digest skipped")
        return DigestResponse(sent=0, skipped=True, message="No active clusters")

    # ── Fetch frame bytes and build media group ───────────────────────────────
    loop = asyncio.get_running_loop()
    media_group: list[InputMediaPhoto] = []

    for cluster in clusters:
        minio_key = cluster["minio_key"]

        try:
            # minio.get_object() is synchronous — run in thread pool
            response = await loop.run_in_executor(
                None,
                lambda key=minio_key: minio_client.get_object(
                    config.MINIO_BUCKET_FRAMES, key
                ),
            )
            img_bytes = response.read()
            response.close()
            response.release_conn()
        except Exception as exc:
            logger.warning(
                "Could not fetch frame for cluster %s (key=%s): %s",
                cluster["id"], minio_key, exc,
            )
            continue   # skip this cluster, include the rest

        # Build caption: "Unknown person — seen Nx, YYYY-MM-DD → YYYY-MM-DD"
        count = cluster["appearance_count"]
        first = cluster["first_seen"][:10] if cluster["first_seen"] else "?"
        last  = cluster["last_seen"][:10]  if cluster["last_seen"]  else "?"
        caption = f"Unknown person \u2014 seen {count}\u00d7, {first} \u2192 {last}"

        # IMPORTANT: seek(0) required — telegram-python-bot reads from current position
        buf = BytesIO(img_bytes)
        buf.seek(0)
        media_group.append(InputMediaPhoto(media=buf, caption=caption))

    if not media_group:
        logger.info("No frames could be fetched from MinIO — digest skipped")
        return DigestResponse(sent=0, skipped=True, message="No fetchable frames")

    # ── Send via Telegram sendMediaGroup ─────────────────────────────────────
    try:
        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        await bot.send_media_group(
            chat_id=config.TELEGRAM_CHAT_ID,
            media=media_group,
        )
    except TelegramError as exc:
        logger.error("Telegram sendMediaGroup failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Telegram error: {exc}",
        )

    sent = len(media_group)
    logger.info("Digest sent: %d photos to chat %s", sent, config.TELEGRAM_CHAT_ID)
    return DigestResponse(sent=sent, skipped=False)
