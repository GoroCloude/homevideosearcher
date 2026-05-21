"""
Shared test fixtures for api service tests.

Sets required env vars and mocks ALL non-stdlib dependencies before any app
module is imported, because app/config.py reads env vars at module-import time.
"""
import os
import sys
from unittest.mock import MagicMock

# ── Required env vars (must be set before importing any app.* module) ─────────
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/testdb")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("API_TOKEN", "test-token-for-tests")


def _mock_if_missing(module_name: str) -> None:
    try:
        __import__(module_name)
    except ModuleNotFoundError:
        sys.modules[module_name] = MagicMock()


for _mod in (
    "insightface",
    "insightface.app",
    "asyncpg",
    "pgvector",
    "pgvector.asyncpg",
    "minio",
    "minio.error",
    "cv2",
    "numpy",
):
    _mock_if_missing(_mod)
