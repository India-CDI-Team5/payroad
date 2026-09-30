"""OpenRouteService driving routes: the one place that knows the ORS URL, key and request body.

Used by the pricing service (sampler.py, async + cache) and the Model A route generator
(training/route_generator.py, which adds its own quota guard). Run directly to check a route:
    python -m clients.ors_client --start 77.6245,12.9352 --end 77.7066,13.1986
"""
import argparse
import asyncio
import json
import os

import httpx
from dotenv import load_dotenv

# .env lives at the repository root, one level above PartB.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

ORS_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
ORS_KEY = os.environ.get("ORS_API_KEY", "")
ROUTE_TTL_SEC = 60 * 60          # roads rarely change
# Route cache keys stay precise (~11 m): two different trips must never share a route.
ROUTE_KEY_DECIMALS = 4


def route_body(start, end, **extra):
    """Request body for a start/end pair given as [lon, lat]."""
    return {"coordinates": [start, end], "instructions": False, **extra}


def cache_key(start, end):
    d = ROUTE_KEY_DECIMALS
    return f"route:{start[0]:.{d}f},{start[1]:.{d}f}:{end[0]:.{d}f},{end[1]:.{d}f}"


async def fetch_route(client, start, end, api_key=ORS_KEY, cache=None):
    """GeoJSON route between [lon, lat] points. With a diskcache Cache, answers are reused for an hour."""
    key = cache_key(start, end)
    if cache is not None:
        cached = cache.get(key)
        if cached is not None:
            return cached
    response = await client.post(ORS_URL, json=route_body(start, end),
                                 headers={"Authorization": api_key, "Content-Type": "application/json"})
    response.raise_for_status()
    data = response.json()
    if cache is not None:
        cache.set(key, data, expire=ROUTE_TTL_SEC)
    return data


def summarize(data):
    feature = data["features"][0]
    summary = feature["properties"]["summary"]
    coords = feature["geometry"]["coordinates"]
    return {
        "distance_km": round(summary["distance"] / 1000, 2),
        "eta_min": round(summary["duration"] / 60, 2),
        "coordinate_count": len(coords),
        "route_coordinates": coords,
    }


def parse_coord(value):
    lon, lat = (float(v) for v in value.split(","))
    return [lon, lat]


async def _run(start, end):
    async with httpx.AsyncClient(timeout=10) as client:
        return summarize(await fetch_route(client, start, end))


def main():
    parser = argparse.ArgumentParser(description="Fetch a driving route between two points.")
    parser.add_argument("--start", type=parse_coord, default=[77.6245, 12.9352], help="Start coordinate as lon,lat")
    parser.add_argument("--end", type=parse_coord, default=[77.7066, 13.1986], help="End coordinate as lon,lat")
    parser.add_argument("--json", action="store_true", help="Print the result as JSON")
    args = parser.parse_args()

    result = asyncio.run(_run(args.start, args.end))
    if args.json:
        print(json.dumps(result))
        return
    print("Distance (km):", result["distance_km"])
    print("ETA (min):", result["eta_min"])
    print("Number of route coordinates:", result["coordinate_count"])


if __name__ == "__main__":
    main()
