"""
Watchdog event handler and async file-processing pipeline.

CRITICAL DESIGN NOTES:
- Use on_closed() NOT on_created(). on_created fires when the inode is created
  (file may still be writing). on_closed fires after the write handle is released.
  Violating this causes corrupt partial-file uploads of large videos.
- on_moved() handles rsync atomic-rename pattern (rsync writes to temp, renames to final).
- asyncio.run_coroutine_threadsafe bridges the sync watchdog thread to the async event loop.
"""
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from watchdog.events import FileSystemEventHandler

from . import config
from . import storage

logger = logging.getLogger(__name__)


# ── Pure helper functions (unit-tested independently) ─────────────────────────

def _is_video_file(path: str) -> bool:
    """Return True if path has a supported video extension (case-insensitive).

    Supported extensions are read from config.VIDEO_EXTENSIONS (default:
    .mp4, .mov, .avi, .mkv, .m4v). Non-video files must be silently ignored.
    """
    return Path(path).suffix.lower() in config.VIDEO_EXTENSIONS


def _make_minio_key(filename: str, mtime: Optional[float] = None) -> str:
    """Generate a deterministic MinIO key for a video upload.

    Format: videos/{YYYYMMDD_HHMMSS}_{filename}

    When mtime is provided (startup_scan path), the timestamp is derived from
    the file's last-modified time — producing the same key for the same physical
    file on every watcher restart. The ingestion worker deduplicates by minio_key
    (SELECT WHERE minio_key = $1), so a stable key allows it to return
    status='skipped' for already-ingested files without duplicate DB records.

    When mtime is None (live on_closed path), datetime.now() is used — ensuring
    two drops of the same filename at different times produce distinct keys.
    """
    dt = datetime.fromtimestamp(mtime) if mtime is not None else datetime.now()
    ts = dt.strftime("%Y%m%d_%H%M%S")
    return f"videos/{ts}_{filename}"


# ── Async processing pipeline ─────────────────────────────────────────────────

async def _post_ingest(minio_key: str) -> dict:
    """POST minio_key to ingestion-worker /ingest. Returns parsed JSON response."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{config.WORKER_URL}/ingest",
            json={"minio_key": minio_key},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()


async def process_file(path: str, mtime: Optional[float] = None) -> None:
    """
    Full file-processing pipeline: extension check → upload → ingest.

    mtime: optional file last-modified timestamp (seconds since epoch). When
    provided (startup_scan path), passed to storage.upload_video so the MinIO
    key is derived from the file's mtime rather than datetime.now() — making
    the key stable across watcher restarts for deduplication.

    State transitions logged as structured lines (AUTO-07):
      DETECTED  <path>
      STABLE    <path>  size=<bytes> bytes
      UPLOADING <path>
      QUEUED    <path>  video_id=<id>
      SKIPPED   <path>  reason=<reason>
      ERROR     <path>  <ExcType>: <message>
    """
    p = Path(path)

    # Extension filter (AUTO-02 / AUTO-03): silently ignore non-video files
    if not _is_video_file(path):
        logger.info("SKIPPED   %s  reason=non_video_extension", path)
        return

    logger.info("DETECTED  %s", path)

    # Guard: file might disappear between event and processing (e.g. temp file)
    if not p.exists():
        logger.info("SKIPPED   %s  reason=file_disappeared", path)
        return

    size = p.stat().st_size
    logger.info("STABLE    %s  size=%d bytes", path, size)

    try:
        # Upload to MinIO via thread pool (fput_object is synchronous I/O)
        # Pass mtime so startup_scan path generates a stable, deterministic key.
        logger.info("UPLOADING %s", path)
        key = await asyncio.to_thread(storage.upload_video, p, mtime)

        # POST to ingestion worker
        data = await _post_ingest(key)
        status = data.get("status", "unknown")
        video_id = data.get("video_id", "")

        if status == "skipped":
            logger.info("SKIPPED   %s  video_id=%s reason=already_ingested", path, video_id)
        else:
            logger.info("QUEUED    %s  video_id=%s", path, video_id)

    except Exception as exc:
        logger.error("ERROR     %s  %s: %s", path, type(exc).__name__, exc)


async def startup_scan(watch_dir: str) -> None:
    """
    On container start, scan watch_dir and process all eligible video files.

    Handles files dropped during watcher downtime (AUTO-04). Each file's mtime
    is passed to process_file so storage.upload_video generates a DETERMINISTIC
    MinIO key (videos/{file_mtime_ts}_{filename}) instead of a datetime.now()-based
    key. Because the ingestion worker deduplicates by minio_key (SELECT WHERE
    minio_key = $1), posting the same stable key on subsequent restarts causes
    the worker to return status='skipped' — preventing duplicate video records.

    New files (never uploaded) are uploaded normally and queued for ingestion.
    """
    watch_path = Path(watch_dir)
    if not watch_path.exists():
        logger.warning(
            "WATCH_DIR does not exist: %s — skipping startup scan", watch_dir
        )
        return

    eligible = [
        f for f in watch_path.iterdir()
        if f.is_file() and _is_video_file(str(f))
    ]

    if not eligible:
        logger.info("Startup scan: no eligible files found in %s", watch_dir)
        return

    logger.info(
        "Startup scan: found %d eligible file(s) in %s — processing",
        len(eligible),
        watch_dir,
    )
    for f in eligible:
        await process_file(str(f), mtime=f.stat().st_mtime)


# ── Watchdog event handler ─────────────────────────────────────────────────────

class VideoHandler(FileSystemEventHandler):
    """
    Watchdog FileSystemEventHandler for the watcher service.

    Submits async process_file coroutines to the main event loop from the
    watchdog background thread using asyncio.run_coroutine_threadsafe().
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self._loop = loop

    def on_closed(self, event) -> None:
        """
        CRITICAL: Use on_closed(), NOT on_created().

        on_created() fires when the OS creates the file inode — the write may
        still be in progress. on_closed() fires only after the last write handle
        to the file is released. This prevents partial-file uploads of large
        videos (e.g. a 2 GB file being copied over a network share).

        Requires watchdog >= 4.0. Pin `watchdog>=4.0` in requirements.txt.
        """
        if not event.is_directory:
            asyncio.run_coroutine_threadsafe(
                process_file(event.src_path),
                self._loop,
            )

    def on_moved(self, event) -> None:
        """
        Handle rsync atomic-rename pattern.

        rsync writes to a temporary file (.fileXXXXXX) then renames it to the
        final filename. The rename triggers on_moved with dest_path = final name.
        Process dest_path (not src_path — the source was a temp file).
        """
        if not event.is_directory:
            asyncio.run_coroutine_threadsafe(
                process_file(event.dest_path),
                self._loop,
            )
