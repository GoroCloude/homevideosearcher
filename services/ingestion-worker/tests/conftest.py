"""
Shared test fixtures for ingestion-worker tests.

Sets required env vars and mocks ALL non-stdlib dependencies before any app
import, so tests can run without the full ML/DB stack installed.
In Docker (requirements.txt installed) the mocks are overridden by the real
packages, but they still apply since sys.modules.setdefault won't replace
an already-imported module.
"""
import os
import sys
from unittest.mock import MagicMock

# ── Required env vars ─────────────────────────────────────────────────────────
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/testdb")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")

# ── Mock non-stdlib packages (skip if already importable) ─────────────────────
def _mock_if_missing(module_name: str) -> None:
    try:
        __import__(module_name)
    except ModuleNotFoundError:
        sys.modules[module_name] = MagicMock()


for _mod in (
    "insightface",
    "insightface.app",
    "ultralytics",
    "asyncpg",
    "pgvector",
    "pgvector.asyncpg",
    "minio",
    "minio.error",
    "cv2",
    "numpy",
):
    _mock_if_missing(_mod)
