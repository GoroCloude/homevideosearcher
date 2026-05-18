"""Configuration: all env vars read here, nowhere else.
Pattern mirrors ingestion-worker/app/config.py exactly.
"""
import os

DATABASE_URL:              str   = os.environ["DATABASE_URL"]        # fail-fast if missing
MINIO_ENDPOINT:            str   = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY:          str   = os.environ["MINIO_ACCESS_KEY"]
MINIO_SECRET_KEY:          str   = os.environ["MINIO_SECRET_KEY"]
MINIO_BUCKET_VIDEOS:       str   = os.getenv("MINIO_BUCKET_VIDEOS", "videos")
MINIO_BUCKET_FRAMES:       str   = os.getenv("MINIO_BUCKET_FRAMES", "frames")
MINIO_USE_SSL:             bool  = os.getenv("MINIO_USE_SSL", "false").lower() == "true"
API_TOKEN:                 str   = os.environ["API_TOKEN"]           # fail-fast if missing
FACE_MATCH_HIGH_THRESHOLD: float = float(os.getenv("FACE_MATCH_HIGH_THRESHOLD", "0.65"))
FACE_MATCH_LOW_THRESHOLD:  float = float(os.getenv("FACE_MATCH_LOW_THRESHOLD", "0.50"))
LOG_LEVEL:                 str   = os.getenv("LOG_LEVEL", "INFO").upper()
