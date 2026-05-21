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
    # init=register_vector registers the pgvector codec on EVERY connection in the
    # pool, not just one. Without this, executemany() on a different connection
    # fails with "expected str, got list" for vector columns.
    _pool = await asyncpg.create_pool(
        config.DATABASE_URL, min_size=2, max_size=10,
        init=register_vector,
    )
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
