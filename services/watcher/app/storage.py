"""MinIO client for the watcher service — uploads video files to the videos bucket.

Mirrors ingestion-worker/app/storage.py singleton pattern (lines 10-23, 26-29, 40-54).
"""
import logging
from pathlib import Path
from typing import Optional

from minio import Minio

from . import config

logger = logging.getLogger(__name__)

_client: Optional[Minio] = None


def get_client() -> Minio:
    """Return the shared Minio singleton (initialised on first call)."""
    global _client
    if _client is None:
        _client = Minio(
            config.MINIO_ENDPOINT,
            access_key=config.MINIO_ACCESS_KEY,
            secret_key=config.MINIO_SECRET_KEY,
            secure=config.MINIO_USE_SSL,
            region="us-east-1",
        )
    return _client


def ensure_bucket(bucket: str) -> None:
    client = get_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        logger.info("Created MinIO bucket: %s", bucket)


def upload_video(local_path: Path, mtime: Optional[float] = None) -> str:
    """Upload a video file to MinIO. Returns the MinIO key.

    Key scheme: videos/{YYYYMMDD_HHMMSS}_{original_filename}

    When mtime is provided (startup_scan path), the timestamp is derived from
    the file's last-modified time — producing the SAME key for the same physical
    file on every watcher restart. This allows the ingestion worker's minio_key
    deduplication (SELECT WHERE minio_key = $1) to correctly return status='skipped'
    for already-ingested files, preventing duplicate video records on restart.

    When mtime is None (live on_closed path), datetime.now() is used — ensuring
    two drops of the same filename at different times produce distinct keys.
    Uses fput_object (path-based) — same pattern as ingestion-worker/storage.py:upload_frame.
    """
    from datetime import datetime

    client = get_client()
    ensure_bucket(config.MINIO_BUCKET_VIDEOS)
    dt = datetime.fromtimestamp(mtime) if mtime is not None else datetime.now()
    ts = dt.strftime("%Y%m%d_%H%M%S")
    key = f"videos/{ts}_{local_path.name}"
    client.fput_object(
        config.MINIO_BUCKET_VIDEOS,
        key,
        str(local_path),
        content_type="video/mp4",
    )
    logger.info(
        "UPLOADING %s → minio://%s/%s", local_path.name, config.MINIO_BUCKET_VIDEOS, key
    )
    return key
