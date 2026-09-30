"""Open-Meteo forecasts (serving) and archive (Model A data): the one place that fixes the model.

Training and serving must see the same weather grid, so both endpoints are pinned to
MODEL. Measured on 2026-10-01 (plan v4 §4.1): forecast and archive `ecmwf_ifs` return the
same ~8 x 9 km cells, while the similarly named `ecmwf_ifs025` (0.25 deg) does not.
Points are (lat, lon) throughout this module.
"""
import time

MODEL = "ecmwf_ifs"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_TTL_SEC = 10 * 60       # forecasts update often
# The grid cell is ~7-8 km (docs/weather-grid-resolution.md), so finer cache keys only lower
# the hit rate. 2 decimals (~1.1 km) is coarser than the request but safely finer than a cell.
FORECAST_KEY_DECIMALS = 2


def api_calls(n_locations, days, n_vars=1):
    """Open-Meteo's counting rule (open-meteo.com/en/pricing): more than 10 variables or more
    than 2 weeks per location count fractionally more. Multi-location weighting is not
    documented, so each location counts as its own call (conservative)."""
    return n_locations * max(1.0, days / 14) * max(1.0, n_vars / 10)


def _coords(points):
    return {"latitude": ",".join(f"{p[0]:.5f}" for p in points),
            "longitude": ",".join(f"{p[1]:.5f}" for p in points)}


def _as_list(data):
    return data if isinstance(data, list) else [data]


def forecast_cache_key(points, hourly, forecast_days):
    d = FORECAST_KEY_DECIMALS
    cells = "|".join(f"{p[0]:.{d}f},{p[1]:.{d}f}" for p in points)
    return f"weather:{MODEL}:{hourly}:{forecast_days}:{cells}"


async def fetch_forecast(client, points, hourly, forecast_days=2, cache=None):
    """Hourly forecast per point, in the points' local time (timezone=auto), one entry per point."""
    key = forecast_cache_key(points, hourly, forecast_days)
    if cache is not None:
        cached = cache.get(key)
        if cached is not None:
            return cached
    params = {**_coords(points), "hourly": hourly, "forecast_days": forecast_days,
              "timezone": "auto", "models": MODEL}
    response = await client.get(FORECAST_URL, params=params)
    response.raise_for_status()
    data = _as_list(response.json())
    if cache is not None:
        cache.set(key, data, expire=FORECAST_TTL_SEC)
    return data


def fetch_archive(client, points, start, end, hourly="precipitation", model=MODEL, retries=0, backoff_sec=120):
    """Hourly history (UTC) per point for [start, end]. model=None asks for best_match.

    On HTTP 429 it waits backoff_sec x attempt and retries up to `retries` times.
    """
    params = {**_coords(points), "start_date": start.isoformat(), "end_date": end.isoformat(),
              "hourly": hourly, "timezone": "UTC"}
    if model:
        params["models"] = model
    for attempt in range(retries + 1):
        r = client.get(ARCHIVE_URL, params=params)
        if r.status_code == 200:
            return _as_list(r.json())
        if r.status_code == 429 and attempt < retries:
            time.sleep(backoff_sec * (attempt + 1))
            continue
        raise RuntimeError(f"Open-Meteo {r.status_code}: {r.text[:200]}")
