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


_public_client: Optional[Minio] = None


def get_public_minio_client() -> Minio:
    """Return a Minio client configured with MINIO_PUBLIC_ENDPOINT for presigned URL generation.
    Generated URLs must be browser-resolvable. Uses a separate client from the internal one."""
    global _public_client
    if _public_client is None:
        _public_client = Minio(
            config.MINIO_PUBLIC_ENDPOINT,
            access_key=config.MINIO_ACCESS_KEY,
            secret_key=config.MINIO_SECRET_KEY,
            secure=config.MINIO_PUBLIC_USE_SSL,
        )
    return _public_client


def generate_presigned_url(bucket: str, key: str, expires_hours: int = 1) -> str:
    """
    Generate a presigned GET URL valid for `expires_hours` hours.
    Called per-request at redirect time — never called during search queries.
    """
    client = get_public_minio_client()
    url = client.presigned_get_object(
        bucket_name=bucket,
        object_name=key,
        expires=timedelta(hours=expires_hours),
    )
    logger.debug("Generated presigned URL for %s/%s (TTL=%dh)", bucket, key, expires_hours)
    return url


def generate_presigned_upload_url(bucket: str, key: str, expires_minutes: int = 60) -> str:
    """
    Generate a presigned PUT URL valid for expires_minutes minutes.
    MUST use get_public_minio_client() so the returned URL uses MINIO_PUBLIC_ENDPOINT
    and is browser-resolvable. Never use get_minio_client() here — that uses the internal
    Docker hostname which the browser cannot resolve.
    """
    client = get_public_minio_client()
    url = client.presigned_put_object(
        bucket_name=bucket,
        object_name=key,
        expires=timedelta(minutes=expires_minutes),
    )
    logger.debug("Generated presigned PUT URL for %s/%s (TTL=%dm)", bucket, key, expires_minutes)
    return url
