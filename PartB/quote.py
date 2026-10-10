"""POST /quote (plan v6 §3.4, card B8): the base price of one trip from Model A.

ORS route → a point every 500 m → the U weather cells it crosses → k = ceil(servingBudgetRatio × U)
cells picked by M2 before any call → one multi-coordinate forecast request for those cell centres →
GP fills the other points → r (route mean of the posterior mean) and s (std of the posterior
route means) → β(r, s) → basePrice. The response keys are the /quote contract of card A4.
"""
import json
import math
import os
from datetime import timezone

import numpy as np

import sampler
from clients.meteo_client import fetch_forecast
from clients.ors_client import fetch_route
from geo import in_bbox, nearest_cell, resample
from pricing.base_price import base_dry, beta, load_constants, surge
from weather.methods import DRAW_SEED, gp_fill, select_m2
from weather.oracle import RouteOracle

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "models", "gp_interpolator.json")
CELLS_PATH = os.path.join(HERE, "data", "grid_cells.json")
STEP_KM = 0.5
SERVING_SEED = 0                    # ml-design v5 §8.1: serving draws use seed 0, not 42 + sample_id
HOURLY = "precipitation"


def load_model(path=MODEL_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_cells(path=CELLS_PATH):
    with open(path, encoding="utf-8") as f:
        return [tuple(c) for c in json.load(f)["cells"]]


def encode_polyline(points_latlon, precision=5):
    """Google's encoded polyline algorithm (developers.google.com/maps/documentation/utilities/polylinealgorithm)."""
    factor = 10 ** precision
    out, prev_lat, prev_lng = [], 0, 0
    for lat, lng in points_latlon:
        ilat, ilng = round(lat * factor), round(lng * factor)
        for delta in (ilat - prev_lat, ilng - prev_lng):
            v = ~(delta << 1) if delta < 0 else delta << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        prev_lat, prev_lng = ilat, ilng
    return "".join(out)


def arrival_value(entry, departure_utc, t_min):
    """Forecast precipitation when the trip reaches a point t_min after departure: linear between
    the two surrounding hours, clamped to the forecast range (build_samples.arrival_values' rule)."""
    hourly = entry["hourly"]
    pos = sampler.hourly_position(hourly["time"], entry["utc_offset_seconds"], departure_utc, t_min)
    lo = int(pos)
    hi = min(lo + 1, len(hourly["time"]) - 1)
    f = pos - lo
    return float(hourly[HOURLY][lo]) * (1 - f) + float(hourly[HOURLY][hi]) * f


async def quote(client, origin, dest, departure_utc, demand, supply, model=None, cells=None, c=None):
    """origin and dest are (lat, lng); departure_utc is an aware datetime. Returns the contract's dict."""
    c = c or load_constants()
    if departure_utc.tzinfo is None:
        departure_utc = departure_utc.replace(tzinfo=timezone.utc)

    route = await fetch_route(client, [origin[1], origin[0]], [dest[1], dest[0]], cache=sampler.cache)
    feature = route["features"][0]
    summary = feature["properties"]["summary"]
    distance_km = summary["distance"] / 1000
    duration_min = summary["duration"] / 60
    coords_lonlat = feature["geometry"]["coordinates"]
    coords = [(p[1], p[0]) for p in coords_lonlat]

    pts = resample(coords, STEP_KM)
    total = pts[-1][2] or 1.0
    s_km = np.array([p[2] for p in pts])
    t_min = s_km / total * duration_min

    if all(in_bbox(p[0], p[1]) for p in pts):
        cells = cells or load_cells()
        model = model or load_model()
        r, s, U, calls = await _model_a(client, pts, s_km, t_min, departure_utc, model, cells, c)
        method, fallback = "M2", None
    else:
        r, s, calls = await _outside_grid(client, coords_lonlat, distance_km, duration_min, departure_utc)
        U, method, fallback = None, "B1", "OUTSIDE_GRID"

    sg = surge(demand, supply, c)
    b = beta(r, s, c)
    dry = base_dry(distance_km, c)
    return {
        "basePrice": round(dry * sg * b, 2),
        "baseDry": round(dry, 2),
        "distanceKm": round(distance_km, 2),
        "durationMin": round(duration_min, 2),
        "avgRainMm": round(r, 4),
        "rainStdMm": round(s, 4),
        "weatherFactor": round(b, 4),
        "surge": sg,
        "routePolyline": encode_polyline(coords),
        "uniqueCells": U,
        "apiCallsUsed": calls,
        "method": method,
        "fallback": fallback,
    }


async def _model_a(client, pts, s_km, t_min, departure_utc, model, cells, c):
    cell = np.array([nearest_cell(p[0], p[1], cells) for p in pts])
    oracle = RouteOracle(cell, np.zeros(len(cell)))      # select_m2 reads only positions, never values
    U = oracle.U
    k = max(1, math.ceil(c["servingBudgetRatio"] * U))
    chosen = select_m2(oracle, s_km, t_min, k, model)

    forecast = await fetch_forecast(client, [cells[i] for i in chosen], HOURLY, forecast_days=2, cache=sampler.cache)
    by_cell = dict(zip(chosen, forecast))
    obs_idx = np.nonzero(np.isin(cell, chosen))[0]
    obs_y = np.array([arrival_value(by_cell[cell[i].item()], departure_utc, t_min[i]) for i in obs_idx])

    # gp_fill seeds its draws with DRAW_SEED + sample_id; this sample_id makes that seed SERVING_SEED.
    res = gp_fill(s_km, t_min, obs_idx, obs_y, model, sample_id=SERVING_SEED - DRAW_SEED,
                  draws=int(c["servingDraws"]), calls=len(chosen))
    return float(np.mean(res.y_hat)), float(np.std(res.mean_draws)), U, len(chosen)


async def _outside_grid(client, coords_lonlat, distance_km, duration_min, departure_utc):
    """The old even sampling (sampler.determine_sample_count points), averaged: r, s = 0."""
    n = sampler.determine_sample_count(distance_km)
    points = sampler.sample_route(coords_lonlat, n)
    forecast = await fetch_forecast(client, [(p[1], p[0]) for p in points], HOURLY, forecast_days=2,
                                    cache=sampler.cache)
    t = [duration_min * i / (n - 1) for i in range(n)]
    values = [arrival_value(entry, departure_utc, ti) for entry, ti in zip(forecast, t)]
    return float(np.mean(values)), 0.0, n
