"""/quote with ORS and Open-Meteo replaced by canned answers (card B8). No network."""
import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import app as service
import quote as quoting
from geo import haversine_km
from pricing.base_price import load_constants

CONTRACT_KEYS = {"basePrice", "baseDry", "distanceKm", "durationMin", "avgRainMm", "rainStdMm", "weatherFactor",
                 "surge", "routePolyline", "uniqueCells", "apiCallsUsed", "method", "fallback"}
DEPARTURE = datetime(2026, 10, 8, 3, 0, tzinfo=timezone.utc)
HOURS = [f"2026-10-0{d}T{h:02d}:00" for d in (8, 9) for h in range(24)]


def row_cells():
    """Four neighbouring cells of the grid row nearest 12.97° N, west to east."""
    cells = quoting.load_cells()
    lat = min({c[0] for c in cells}, key=lambda x: abs(x - 12.97))
    row = sorted(c for c in cells if c[0] == lat)
    mid = len(row) // 2
    return row[mid - 2:mid + 2]


def straight_route(a, b, n=60, minutes=30):
    """ORS-style GeoJSON for a straight line from a to b, both (lat, lon)."""
    coords = [[a[1] + (b[1] - a[1]) * i / (n - 1), a[0] + (b[0] - a[0]) * i / (n - 1)] for i in range(n)]
    km = haversine_km(a[0], a[1], b[0], b[1])
    return {"features": [{"properties": {"summary": {"distance": km * 1000, "duration": minutes * 60}},
                          "geometry": {"coordinates": coords}}]}


def fake_apis(monkeypatch, route, rain):
    calls = {"route": 0, "forecast": [], "hourly": []}

    async def fake_route(client, start, end, api_key=None, cache=None):
        calls["route"] += 1
        return route

    async def fake_forecast(client, points, hourly, forecast_days=2, cache=None):
        calls["forecast"].append(list(points))
        calls["hourly"].append(hourly)
        return [{"utc_offset_seconds": 19800, "hourly": {"time": HOURS, "precipitation": [rain] * len(HOURS)}}
                for _ in points]

    monkeypatch.setattr(quoting, "fetch_route", fake_route)
    monkeypatch.setattr(quoting, "fetch_forecast", fake_forecast)
    return calls


def run_quote(origin, dest, demand=0, supply=0):
    return asyncio.run(quoting.quote(None, origin, dest, DEPARTURE, demand, supply))


def test_four_cells_cost_two_calls_and_dry_weather_is_factor_one(monkeypatch):
    cells = row_cells()
    calls = fake_apis(monkeypatch, straight_route(cells[0], cells[3]), rain=0.0)

    q = run_quote(cells[0], cells[3])

    assert set(q) == CONTRACT_KEYS
    assert q["uniqueCells"] == 4
    assert q["apiCallsUsed"] == 2
    assert q["method"] == "M2" and q["fallback"] is None
    assert q["weatherFactor"] == 1.0 and q["avgRainMm"] == 0.0
    c = load_constants()
    assert q["baseDry"] == pytest.approx(c["baseFee"] + c["perKm"] * q["distanceKm"], abs=0.1)
    assert q["surge"] == 0.7                       # demand 0 / max(supply, 1) clips to surgeMin, as in Part A
    assert q["basePrice"] == pytest.approx(q["baseDry"] * 0.7, abs=0.01)
    # One multi-coordinate request for exactly the chosen cell centres, precipitation only.
    assert len(calls["forecast"]) == 1
    assert len(calls["forecast"][0]) == 2 and set(calls["forecast"][0]) <= set(cells)
    assert calls["hourly"] == ["precipitation"]


def test_rain_everywhere_raises_the_price(monkeypatch):
    cells = row_cells()
    fake_apis(monkeypatch, straight_route(cells[0], cells[3]), rain=2.0)

    q = run_quote(cells[0], cells[3], demand=3, supply=5)

    c = load_constants()
    assert q["avgRainMm"] == pytest.approx(2.0, abs=1e-6)       # the GP fills a flat field flat
    assert q["rainStdMm"] >= 0
    assert q["weatherFactor"] == pytest.approx(1 + (2.0 - c["uncertaintyWeight"] * q["rainStdMm"]) * c["betaCoef"],
                                               abs=1e-3)
    assert q["surge"] == 0.7
    assert q["basePrice"] == pytest.approx(q["baseDry"] * 0.7 * q["weatherFactor"], abs=0.02)


def test_outside_the_grid_falls_back_to_even_sampling(monkeypatch):
    a, b = (12.40, 77.50), (12.40, 77.60)                       # south of the bbox
    calls = fake_apis(monkeypatch, straight_route(a, b), rain=1.0)

    q = run_quote(a, b)

    assert set(q) == CONTRACT_KEYS
    assert q["fallback"] == "OUTSIDE_GRID" and q["method"] == "B1"
    assert q["apiCallsUsed"] == 6 == len(calls["forecast"][0])  # ~10.8 km → determine_sample_count = 6
    assert q["avgRainMm"] == 1.0 and q["rainStdMm"] == 0.0


def test_same_request_same_answer(monkeypatch):
    cells = row_cells()
    fake_apis(monkeypatch, straight_route(cells[0], cells[3]), rain=0.5)
    assert run_quote(cells[0], cells[3]) == run_quote(cells[0], cells[3])


def test_polyline_matches_googles_example():
    assert quoting.encode_polyline([(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]) == "_p~iF~ps|U_ulLnnqC_mqNvxq`@"


def test_endpoint_and_health(monkeypatch):
    cells = row_cells()
    fake_apis(monkeypatch, straight_route(cells[0], cells[3]), rain=0.0)
    body = {"origin": {"lat": cells[0][0], "lng": cells[0][1]}, "dest": {"lat": cells[3][0], "lng": cells[3][1]},
            "departureUtc": "2026-10-08T03:00:00Z", "demand": 3, "supply": 5}
    with TestClient(service.app) as client:
        assert client.get("/health").json() == {"status": "ok", "interpolatorLoaded": True}
        r = client.post("/quote", json=body)
    assert r.status_code == 200
    assert set(r.json()) == CONTRACT_KEYS
    assert r.json()["apiCallsUsed"] == 2


def test_endpoint_returns_502_on_upstream_error(monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("ORS down")

    monkeypatch.setattr(quoting, "fetch_route", broken)
    with TestClient(service.app) as client:
        r = client.post("/quote", json={"origin": {"lat": 12.97, "lng": 77.59}, "dest": {"lat": 12.93, "lng": 77.62}})
    assert r.status_code == 502
