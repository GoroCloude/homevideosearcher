"""Configuration: all env vars read here, nowhere else."""
import os


def _list(val: str) -> list[str]:
    return [s.strip() for s in val.split(",") if s.strip()]


DATABASE_URL: str = os.environ["DATABASE_URL"]  # required — fail fast if missing

MINIO_ENDPOINT: str = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY: str = os.environ["MINIO_ACCESS_KEY"]
MINIO_SECRET_KEY: str = os.environ["MINIO_SECRET_KEY"]
MINIO_BUCKET_VIDEOS: str = os.getenv("MINIO_BUCKET_VIDEOS", "videos")
MINIO_BUCKET_FRAMES: str = os.getenv("MINIO_BUCKET_FRAMES", "frames")
MINIO_USE_SSL: bool = os.getenv("MINIO_USE_SSL", "false").lower() == "true"

YOLO_MODEL: str = os.getenv("YOLO_MODEL", "yolov8n.pt")
YOLO_CONFIDENCE: float = float(os.getenv("YOLO_CONFIDENCE", "0.35"))
YOLO_CLASSES: list[str] = _list(
    os.getenv(
        "YOLO_CLASSES",
        "person,bicycle,car,motorcycle,bus,truck,cat,dog,horse,sheep,cow,bird",
    )
)
YOLO_BATCH_SIZE: int = int(os.getenv("YOLO_BATCH_SIZE", "8"))

# Two-tier face match thresholds (do NOT lower below 0.50 / 0.65 without testing)
FACE_MATCH_HIGH_THRESHOLD: float = float(os.getenv("FACE_MATCH_HIGH_THRESHOLD", "0.65"))
FACE_MATCH_LOW_THRESHOLD: float = float(os.getenv("FACE_MATCH_LOW_THRESHOLD", "0.50"))

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
