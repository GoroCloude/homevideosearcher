"""
Shared test fixtures for watcher tests.
Sets required env vars before any app import so tests run without MinIO/Docker.
"""
import os
import sys
from unittest.mock import MagicMock

# Required env vars for config.py (fail-fast keys)
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")


def _mock_if_missing(module_name: str) -> None:
    try:
        __import__(module_name)
    except ModuleNotFoundError:
        sys.modules[module_name] = MagicMock()


for _mod in (
    "minio",
    "minio.error",
    "httpx",
    "watchdog",
    "watchdog.events",
    "watchdog.observers",
    "watchdog.observers.polling",
):
    _mock_if_missing(_mod)
