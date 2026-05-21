"""
Tests for require_token — Bearer token authentication dependency.

Run from services/api/:
    python -m pytest tests/test_auth.py -v
"""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import require_token


@pytest.fixture
def auth_app():
    """FastAPI app with a single protected route for testing."""
    app = FastAPI()

    @app.get("/protected", dependencies=[Depends(require_token)])
    async def protected():
        return {"ok": True}

    return app


class TestRequireToken:
    def test_correct_token_returns_200(self, auth_app, monkeypatch):
        monkeypatch.setattr("app.auth.config.API_TOKEN", "secret123")
        client = TestClient(auth_app, raise_server_exceptions=False)
        resp = client.get("/protected", headers={"Authorization": "Bearer secret123"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_wrong_token_returns_401(self, auth_app, monkeypatch):
        monkeypatch.setattr("app.auth.config.API_TOKEN", "secret123")
        client = TestClient(auth_app, raise_server_exceptions=False)
        resp = client.get("/protected", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401

    def test_missing_authorization_header_returns_401(self, auth_app):
        client = TestClient(auth_app, raise_server_exceptions=False)
        resp = client.get("/protected")
        assert resp.status_code == 401

    def test_non_bearer_scheme_returns_401(self, auth_app, monkeypatch):
        """Authorization: Basic / Token / raw value — must all be rejected."""
        monkeypatch.setattr("app.auth.config.API_TOKEN", "secret123")
        client = TestClient(auth_app, raise_server_exceptions=False)
        resp = client.get("/protected", headers={"Authorization": "secret123"})
        assert resp.status_code == 401

    def test_empty_token_returns_401(self, auth_app, monkeypatch):
        monkeypatch.setattr("app.auth.config.API_TOKEN", "secret123")
        client = TestClient(auth_app, raise_server_exceptions=False)
        resp = client.get("/protected", headers={"Authorization": "Bearer "})
        assert resp.status_code == 401

    def test_response_includes_www_authenticate_header(self, auth_app, monkeypatch):
        monkeypatch.setattr("app.auth.config.API_TOKEN", "secret123")
        client = TestClient(auth_app, raise_server_exceptions=False)
        resp = client.get("/protected")
        assert resp.status_code == 401
        assert "WWW-Authenticate" in resp.headers

    def test_router_integration_missing_token_blocked(self, monkeypatch):
        """Integration: persons router mounted with require_token blocks unauthenticated calls."""
        from app.persons import router as persons_router

        app = FastAPI()
        app.include_router(persons_router, dependencies=[Depends(require_token)])
        monkeypatch.setattr("app.auth.config.API_TOKEN", "real-token")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/persons")
        assert resp.status_code == 401

    def test_router_integration_valid_token_passes_auth(self, monkeypatch):
        """Valid token reaches the route (may fail at DB, but not at auth)."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.persons import router as persons_router

        app = FastAPI()
        app.include_router(persons_router, dependencies=[Depends(require_token)])
        monkeypatch.setattr("app.auth.config.API_TOKEN", "real-token")

        conn = AsyncMock()
        conn.fetch.return_value = []
        acquire_cm = MagicMock()
        acquire_cm.__aenter__ = AsyncMock(return_value=conn)
        acquire_cm.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire_cm

        client = TestClient(app, raise_server_exceptions=False)
        with patch("app.persons.get_pool", new_callable=AsyncMock) as mock_gp:
            mock_gp.return_value = pool
            resp = client.get("/persons", headers={"Authorization": "Bearer real-token"})

        assert resp.status_code != 401
