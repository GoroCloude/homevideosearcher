"""Configuration: all env vars read here, nowhere else.
Pattern mirrors ingestion-worker/app/config.py exactly.
"""
import os

# ── Required (fail fast if missing) ──────────────────────────────────────────
MINIO_ACCESS_KEY: str = os.environ["MINIO_ACCESS_KEY"]   # KeyError at startup if absent
MINIO_SECRET_KEY: str = os.environ["MINIO_SECRET_KEY"]   # KeyError at startup if absent

# ── Optional with defaults ────────────────────────────────────────────────────
MINIO_ENDPOINT:      str  = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_BUCKET_VIDEOS: str  = os.getenv("MINIO_BUCKET_VIDEOS", "videos")
MINIO_USE_SSL:       bool = os.getenv("MINIO_USE_SSL", "false").lower() == "true"

WATCH_DIR:           str  = os.getenv("WATCH_DIR", "/watch")
WORKER_URL:          str  = os.getenv("WORKER_URL", "http://ingestion-worker:8001")
WATCH_USE_POLLING:   bool = os.getenv("WATCH_USE_POLLING", "false").lower() == "true"

# VIDEO_EXTENSIONS: set of lowercase dot-prefixed extensions
# Default covers the 5 supported formats. Operator can override via env var.
VIDEO_EXTENSIONS: set[str] = {
    e.strip().lower()
    for e in os.getenv("VIDEO_EXTENSIONS", ".mp4,.mov,.avi,.mkv,.m4v").split(",")
}

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
