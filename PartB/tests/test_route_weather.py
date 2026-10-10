"""/route-weather end to end with ORS and Open-Meteo replaced by canned answers."""
import httpx
from diskcache import Cache
from fastapi.testclient import TestClient

import app as service
import sampler

HOURS = [f"2026-10-0{d}T{h:02d}:00" for d in (1, 2) for h in range(24)]
FORECAST = {"utc_offset_seconds": 19800,
            "hourly": {"time": HOURS, "temperature_2m": [30] * 48,
                       "precipitation": [1.0] * 48, "wind_speed_10m": [10] * 48}}
ROUTE = {"features": [{"properties": {"summary": {"distance": 8000, "duration": 1200}},
                       "geometry": {"coordinates": [[77.0 + i * 0.001, 12.0] for i in range(40)]}}]}


def handler(request):
    if "openrouteservice" in str(request.url):
        return httpx.Response(200, json=ROUTE)
    assert request.url.params["models"] == "ecmwf_ifs"     # serving uses the training grid
    points = len(request.url.params["latitude"].split(","))
    return httpx.Response(200, json=[FORECAST] * points)


def test_route_weather(tmp_path, monkeypatch):
    monkeypatch.setattr(sampler, "cache", Cache(str(tmp_path)))
    with TestClient(service.app) as client:
        client.app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        r = client.post("/route-weather", json={"start": {"lon": 77.0, "lat": 12.0}, "end": {"lon": 77.04, "lat": 12.0}})
    assert r.status_code == 200
    body = r.json()
    assert body["distance_km"] == 8.0
    assert body["sample_count"] == 4
    # 1 mm of rain everywhere scores 2 per checkpoint -> factor 1 + 2 x 0.1
    assert body["weather_factor"] == 1.2


def test_health():
    with TestClient(service.app) as client:
        assert client.get("/health").json()["status"] == "ok"
