from fastapi.testclient import TestClient

from app.main import app
from app.db.session import get_db


class _FakeSession:
    def execute(self, _query):
        return None


def _fake_get_db():
    yield _FakeSession()


def test_health_route_returns_ok() -> None:
    app.dependency_overrides[get_db] = _fake_get_db
    with TestClient(app) as client:
        response = client.get("/health/")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "connected"
