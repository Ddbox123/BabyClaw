from fastapi.testclient import TestClient

from core.web.app import create_app


def _seed_dist(tmp_path):
    dist_dir = tmp_path / "web-dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<!doctype html><html><body>app shell</body></html>", encoding="utf-8")
    return dist_dir


def test_index_html_is_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr("core.web.app.WEB_DIST", _seed_dist(tmp_path))
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate, max-age=0"


def test_spa_fallback_index_html_is_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr("core.web.app.WEB_DIST", _seed_dist(tmp_path))
    client = TestClient(create_app())

    response = client.get("/chat")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate, max-age=0"
