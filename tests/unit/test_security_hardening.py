from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from src.core.config import Settings, get_settings
from src.main import app

STRONG = "x" * 40


def _make(**kwargs: Any) -> Settings:
    """Construit des Settings isolés du fichier .env."""
    return Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]


def _prod(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "ENVIRONMENT": "production",
        "SECRET_KEY": STRONG,
        "WHATSAPP_APP_SECRET": "app-secret-real",
        "WHATSAPP_VERIFY_TOKEN": "verify-real",
        "DATABASE_URL": "postgresql+asyncpg://u:strongpw@db:5432/x",
        "ADMIN_PASSWORD": "a-very-strong-password",
        "PARTNER_API_KEY": "p" * 24,
        "CORS_ORIGINS": "https://lexbenin.emmanuelhoudji.com",
    }
    base.update(overrides)
    return _make(**base)


def test_production_valid_config_ok():
    s = _prod()
    assert s.docs_enabled is False
    assert s.get_cors_origins() == ["https://lexbenin.emmanuelhoudji.com"]


@pytest.mark.parametrize(
    "override",
    [
        {"SECRET_KEY": "super_secret_key_change_in_production_min_32_characters"},
        {"SECRET_KEY": "short"},
        {"WHATSAPP_APP_SECRET": "meta_app_secret_key_change_in_production"},
        {"WHATSAPP_VERIFY_TOKEN": "lexbenin_webhook_verify_token"},
        {"DATABASE_URL": "postgresql+asyncpg://lexbenin:lexbenin_secret_pass@db/x"},
        {"ADMIN_PASSWORD": ""},
        {"ADMIN_PASSWORD": "short"},
        {"PARTNER_API_KEY": ""},
        {"PARTNER_API_KEY": "short"},
        {"CORS_ORIGINS": "*"},
    ],
)
def test_production_rejects_insecure_values(override):
    with pytest.raises(ValidationError):
        _prod(**override)


def test_development_allows_defaults_and_docs():
    s = _make(ENVIRONMENT="development")
    assert s.docs_enabled is True


def test_docs_override():
    assert _prod(ENABLE_API_DOCS=True).docs_enabled is True


@pytest.mark.asyncio
async def test_corpus_upload_requires_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "ADMIN_API_KEY", "k")
    files = {"file": ("c.json", b"{}", "application/json")}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        missing = await ac.post("/api/v1/legal/admin/corpus/upload", files=files)
        wrong = await ac.post(
            "/api/v1/legal/admin/corpus/upload", files=files, headers={"X-API-Key": "bad"}
        )
    assert missing.status_code == 401
    assert wrong.status_code == 401


@pytest.mark.asyncio
async def test_corpus_upload_disabled_without_configured_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "ADMIN_API_KEY", "")
    files = {"file": ("c.json", b"{}", "application/json")}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        res = await ac.post(
            "/api/v1/legal/admin/corpus/upload", files=files, headers={"X-API-Key": ""}
        )
    assert res.status_code == 503


@pytest.mark.asyncio
async def test_admin_panel_requires_login():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        res = await ac.get("/admin/", follow_redirects=False)
    assert res.status_code in (302, 303, 307)
    assert "login" in res.headers["location"]


@pytest.mark.asyncio
async def test_admin_login_flow(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "ADMIN_USERNAME", "root")
    monkeypatch.setattr(s, "ADMIN_PASSWORD", "correct-horse-battery")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        bad = await ac.post(
            "/admin/login",
            data={"username": "root", "password": "nope"},
            follow_redirects=False,
        )
        good = await ac.post(
            "/admin/login",
            data={"username": "root", "password": "correct-horse-battery"},
            follow_redirects=False,
        )
    assert bad.status_code == 400
    assert good.status_code in (302, 303)


@pytest.mark.asyncio
async def test_cors_blocks_unknown_origin():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        res = await ac.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in res.headers


@pytest.mark.asyncio
async def test_readiness_ok_and_down(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    import src.main as main_mod

    ok_conn = MagicMock()
    ok_conn.execute = AsyncMock()
    ok_ctx = MagicMock()
    ok_ctx.__aenter__ = AsyncMock(return_value=ok_conn)
    ok_ctx.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(main_mod, "async_engine", MagicMock(connect=lambda: ok_ctx))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        res = await ac.get("/health/ready")
        assert res.status_code == 200

        bad_ctx = MagicMock()
        bad_ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("down"))
        bad_ctx.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(main_mod, "async_engine", MagicMock(connect=lambda: bad_ctx))
        res = await ac.get("/health/ready")
        assert res.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/legal/partner/escalations"),
        ("get", "/api/v1/legal/partner/metrics"),
        ("patch", "/api/v1/legal/partner/escalations/abc"),
    ],
)
async def test_partner_routes_require_key(monkeypatch, method, path):
    monkeypatch.setattr(get_settings(), "PARTNER_API_KEY", "right-key-0123456789ab")
    kwargs: dict[str, Any] = {"json": {"status": "RESOLVED"}} if method == "patch" else {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        missing = await getattr(ac, method)(path, **kwargs)
        wrong = await getattr(ac, method)(path, headers={"X-Partner-Key": "nope"}, **kwargs)
    assert missing.status_code == 401
    assert wrong.status_code == 401


@pytest.mark.asyncio
async def test_partner_routes_disabled_without_configured_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "PARTNER_API_KEY", "")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        res = await ac.get("/api/v1/legal/partner/metrics")
    assert res.status_code == 503
