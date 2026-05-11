from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_dashboard_loads_without_token_when_token_is_not_configured(monkeypatch):
    monkeypatch.delenv("DASHBOARD_APP_TOKEN", raising=False)
    get_settings.cache_clear()

    response = TestClient(app).get("/dashboard")

    assert response.status_code == 200
    assert "Odoo Customer Panel" in response.text


def test_dashboard_rejects_invalid_token(monkeypatch):
    monkeypatch.setenv("DASHBOARD_APP_TOKEN", "secret")
    get_settings.cache_clear()

    response = TestClient(app).get("/dashboard?token=wrong")

    assert response.status_code == 401


def test_dashboard_search_returns_empty_payload_without_lookup(monkeypatch):
    monkeypatch.delenv("DASHBOARD_APP_TOKEN", raising=False)
    get_settings.cache_clear()

    response = TestClient(app).get("/api/dashboard/search")

    assert response.status_code == 200
    assert response.json() == {"partner": None, "matches": [], "leads": [], "orders": []}
