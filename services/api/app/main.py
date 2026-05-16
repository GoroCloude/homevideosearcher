"""
HomeVideoSearcher API service.
Phase 1: /health only. Full routes added in Phase 2 (Enrollment, Search).
"""
import logging
import os
from fastapi import FastAPI

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)

app = FastAPI(title="HomeVideoSearcher API", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "api"}
