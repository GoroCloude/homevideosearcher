"""MinIO object storage client wrapper."""
import logging
from pathlib import Path
from minio import Minio

from . import config

logger = logging.getLogger(__name__)

_client: Minio | None = None


def get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            config.MINIO_ENDPOINT,
            access_key=config.MINIO_ACCESS_KEY,
            secret_key=config.MINIO_SECRET_KEY,
            secure=config.MINIO_USE_SSL,
        )
    return _client


def ensure_bucket(bucket: str) -> None:
    client = get_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        logger.info("Created MinIO bucket: %s", bucket)


def download_video(minio_key: str, dest_path: Path) -> None:
    """Download a video from MinIO to a local path."""
    client = get_client()
    client.fget_object(config.MINIO_BUCKET_VIDEOS, minio_key, str(dest_path))
    logger.info("Downloaded %s → %s", minio_key, dest_path)


def upload_frame(local_path: Path, video_id: str, ts_ms: int) -> str:
    """
    Upload a frame JPEG to MinIO. Returns the MinIO key.
    Key format: frames/{video_id}/{ts_ms}.jpg
    """
    client = get_client()
    ensure_bucket(config.MINIO_BUCKET_FRAMES)
    key = f"frames/{video_id}/{ts_ms}.jpg"
    client.fput_object(
        config.MINIO_BUCKET_FRAMES,
        key,
        str(local_path),
        content_type="image/jpeg",
    )
    return key


def list_video_keys(prefix: str) -> list[str]:
    """List all objects in the videos bucket under the given prefix."""
    client = get_client()
    objects = client.list_objects(
        config.MINIO_BUCKET_VIDEOS, prefix=prefix, recursive=True
    )
    return [obj.object_name for obj in objects]
