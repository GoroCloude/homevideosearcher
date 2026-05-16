"""
HomeVideoSearcher — Ingestion Worker service.
Phase 1: /health only. Full ingestion pipeline added in Phase 2.
"""
import logging
import os
from fastapi import FastAPI

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)

app = FastAPI(title="HomeVideoSearcher Ingestion Worker", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "ingestion-worker"}
