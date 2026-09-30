import asyncio
from datetime import date

import httpx
import pytest
from diskcache import Cache

from clients.meteo_client import (ARCHIVE_URL, FORECAST_URL, MODEL, api_calls, fetch_archive,
                                  fetch_forecast)

POINT = {"latitude": 12.970123, "longitude": 77.56364, "hourly": {"time": [], "precipitation": []}}


def test_model_is_the_training_grid():
    # ecmwf_ifs025 looks similar but is a 0.25 deg grid: training and serving would diverge.
    assert MODEL == "ecmwf_ifs"


def test_forecast_pins_model_local_time_and_caches(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=[POINT, POINT])

    async def run():
        cache = Cache(str(tmp_path))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            points = [(12.97, 77.59), (13.19, 77.70)]
            a = await fetch_forecast(client, points, "precipitation", cache=cache)
            b = await fetch_forecast(client, points, "precipitation", cache=cache)
        return a, b

    a, b = asyncio.run(run())
    assert a == b and len(a) == 2
    assert len(seen) == 1
    params = seen[0].url.params
    assert str(seen[0].url).startswith(FORECAST_URL)
    assert params["models"] == MODEL and params["timezone"] == "auto" and params["forecast_days"] == "2"
    assert params["latitude"] == "12.97000,13.19000" and params["longitude"] == "77.59000,77.70000"


def test_archive_pins_model_unless_best_match_is_asked():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=POINT)       # a single point comes back as an object

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        out = fetch_archive(client, [(12.97, 77.59)], date(2025, 8, 1), date(2025, 8, 14))
        fetch_archive(client, [(12.97, 77.59)], date(2025, 8, 1), date(2025, 8, 14), model=None)
    assert out == [POINT]
    assert str(seen[0].url).startswith(ARCHIVE_URL)
    assert seen[0].url.params["models"] == MODEL and seen[0].url.params["timezone"] == "UTC"
    assert "models" not in seen[1].url.params


def test_archive_retries_on_rate_limit_then_fails_loudly():
    replies = iter([httpx.Response(429, text="slow down"), httpx.Response(200, json=POINT)])
    with httpx.Client(transport=httpx.MockTransport(lambda r: next(replies))) as client:
        assert fetch_archive(client, [(12.97, 77.59)], date(2025, 8, 1), date(2025, 8, 1),
                             retries=1, backoff_sec=0) == [POINT]

    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, text="bad date"))) as client:
        with pytest.raises(RuntimeError, match="400: bad date"):
            fetch_archive(client, [(12.97, 77.59)], date(2025, 8, 1), date(2025, 8, 1))


def test_api_calls_rule():
    assert api_calls(1, 14) == 1
    assert api_calls(1, 28) == 2
    assert api_calls(3, 7, n_vars=15) == 4.5
