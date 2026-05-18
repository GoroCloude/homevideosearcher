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
