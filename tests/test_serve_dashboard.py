from fastapi.testclient import TestClient

from serve import app


def test_local_server_serves_dashboard_and_api_from_one_origin():
    client = TestClient(app)

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "SimAPI v3 — Physics Validation" in dashboard.text
    assert "dashboard_extras.js" in dashboard.text

    health = client.get("/v1/health")
    assert health.status_code == 200

    extras = client.get("/dashboard_extras.js")
    assert extras.status_code == 200
    assert "simapiRenderEpisodeChips" in extras.text
