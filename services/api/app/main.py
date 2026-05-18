"""
HomeVideoSearcher API service — Phase 2 complete.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from . import config
from .auth import require_token
from .db import close_pool, init_pool
from .persons import router as persons_router

LOG_LEVEL = config.LOG_LEVEL
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """
    Startup:
      1. Initialize asyncpg DB pool.
      2. Load InsightFace buffalo_l (baked into image — no download).
    Shutdown: close DB pool.
    No YOLO loaded here — api service uses InsightFace only (for enrollment).
    """
    await init_pool()
    logger.info("Loading InsightFace buffalo_l for enrollment")
    from .faces_api import load_face_model
    application.state.face_app = load_face_model()
    logger.info("InsightFace buffalo_l ready (api service)")
    yield
    await close_pool()
    logger.info("API service shutdown complete")


app = FastAPI(
    title="HomeVideoSearcher API",
    version="0.2.0",
    lifespan=lifespan,
)


# ── Unprotected endpoints (no token required) ─────────────────────────────────
@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "api"}


# ── Protected routers (bearer token required) ─────────────────────────────────
# require_token dependency is applied at router level — ALL routes in each
# router are protected. /health and /docs stay unprotected.
app.include_router(persons_router, dependencies=[Depends(require_token)])

from .search import router as search_router
from .videos import router as videos_router
from .frames import router as frames_router

app.include_router(search_router,  dependencies=[Depends(require_token)])
app.include_router(videos_router,  dependencies=[Depends(require_token)])
app.include_router(frames_router,  dependencies=[Depends(require_token)])
