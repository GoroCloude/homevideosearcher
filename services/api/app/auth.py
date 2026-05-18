"""Bearer token authentication dependency.

Usage:
    # In main.py router registration — NOT per-endpoint:
    app.include_router(persons_router, dependencies=[Depends(require_token)])

    # /health and /docs are added directly on app (no dependency) — they stay public.
"""
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config

# auto_error=False: we raise our own 401 with a consistent body
_bearer = HTTPBearer(auto_error=False)


async def require_token(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> None:
    """Raise 401 if Authorization: Bearer <token> is missing or wrong."""
    if credentials is None or credentials.credentials != config.API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
