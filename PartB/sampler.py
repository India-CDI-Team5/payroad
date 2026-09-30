import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
from diskcache import Cache

import os

from clients.meteo_client import fetch_forecast
from clients.ors_client import ORS_KEY, fetch_route

HTTP_TIMEOUT = httpx.Timeout(10.0)
WEATHER_VARIABLES = "temperature_2m,precipitation,wind_speed_10m"

# On-disk cache shared across restarts and worker processes (ORS routes and forecasts).
CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
cache = Cache(CACHE_DIR)


def determine_sample_count(distance_km):
    if distance_km < 10:
        return 4
    elif distance_km < 30:
        return 6
    elif distance_km < 60:
        return 9
    return 12


def sample_route(route_coordinates, sample_count):
    total_points = len(route_coordinates)
    interval = total_points // (sample_count - 1)

    sampled_points = [
        route_coordinates[i * interval] for i in range(sample_count - 1)
    ]
    sampled_points.append(route_coordinates[-1])
    return sampled_points


async def fetch_weather(client, sampled_points):
    """Forecast at each sampled route point ([lon, lat]), pinned to the training model."""
    points = [(p[1], p[0]) for p in sampled_points]
    return await fetch_forecast(client, points, WEATHER_VARIABLES, forecast_days=2, cache=cache)


def score_weather(temp, rain, wind):
    score = 0

    if rain > 2:
        score += 3
    elif rain > 0.5:
        score += 2
    elif rain > 0:
        score += 1

    if wind > 25:
        score += 2
    elif wind > 15:
        score += 1

    if temp > 35:
        score += 1

    return score


def hourly_position(hourly_times, utc_offset_sec, now_utc, arrival_min):
    """Fractional index into the hourly arrays for the moment the driver reaches a point.

    Open-Meteo (timezone=auto) returns local-time stamps starting at 00:00 today,
    so the index is how many hours the arrival time is past that first stamp.
    Clamped to the forecast range so late trips never index out of bounds.
    """
    first = datetime.fromisoformat(hourly_times[0])
    local_now = (now_utc + timedelta(seconds=utc_offset_sec)).replace(tzinfo=None)
    arrival = local_now + timedelta(minutes=arrival_min)
    position = (arrival - first).total_seconds() / 3600
    return min(max(position, 0.0), len(hourly_times) - 1)


async def assess_route_weather(client, start, end, api_key=ORS_KEY, now_utc=None):
    route_data = await fetch_route(client, start, end, api_key, cache=cache)

    distance = route_data["features"][0]["properties"]["summary"]["distance"]
    duration = route_data["features"][0]["properties"]["summary"]["duration"]
    distance_km = distance / 1000
    duration_min = duration / 60

    sample_count = determine_sample_count(distance_km)
    route_coordinates = route_data["features"][0]["geometry"]["coordinates"]
    sampled_points = sample_route(route_coordinates, sample_count)

    arrival_gap = duration_min / (sample_count - 1)
    arrival_times = [round(i * arrival_gap, 2) for i in range(sample_count)]

    weather_data = await fetch_weather(client, sampled_points)
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    checkpoints = []
    total_weather_score = 0

    for idx, location_weather in enumerate(weather_data):
        arrival_min = arrival_times[idx]
        hourly = location_weather["hourly"]

        hour_position = hourly_position(
            hourly["time"], location_weather["utc_offset_seconds"], now_utc, arrival_min
        )
        lower_hour = int(hour_position)
        upper_hour = min(lower_hour + 1, len(hourly["time"]) - 1)
        fraction = hour_position - lower_hour

        def interpolate(field):
            lower = hourly[field][lower_hour]
            upper = hourly[field][upper_hour]
            return lower + (upper - lower) * fraction

        temp = round(interpolate("temperature_2m"), 2)
        rain = round(interpolate("precipitation"), 2)
        wind = round(interpolate("wind_speed_10m"), 2)

        weather_score = score_weather(temp, rain, wind)
        total_weather_score += weather_score

        checkpoints.append({
            "point": idx + 1,
            "location": sampled_points[idx],
            "arrival_min": arrival_min,
            "temperature_c": temp,
            "rain_mm": rain,
            "wind_kmh": wind,
            "weather_score": weather_score,
        })

    average_weather_score = total_weather_score / sample_count
    weather_factor = round(1 + average_weather_score * 0.1, 2)

    return {
        "distance_km": round(distance_km, 2),
        "eta_min": round(duration_min, 2),
        "sample_count": sample_count,
        "checkpoints": checkpoints,
        "total_weather_score": total_weather_score,
        "average_weather_score": round(average_weather_score, 2),
        "weather_factor": weather_factor,
    }


def parse_coord(value):
    lon, lat = (float(v) for v in value.split(","))
    return [lon, lat]


async def run(args):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        return await assess_route_weather(client, args.start, args.end)


def main():
    parser = argparse.ArgumentParser(
        description="Assess weather risk along a driving route."
    )
    parser.add_argument(
        "--start", type=parse_coord, default=[77.6245, 12.9352],
        help="Start coordinate as lon,lat"
    )
    parser.add_argument(
        "--end", type=parse_coord, default=[77.7066, 13.1986],
        help="End coordinate as lon,lat"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Print the result as JSON instead of a human-readable report"
    )
    args = parser.parse_args()

    result = asyncio.run(run(args))

    if args.json:
        print(json.dumps(result))
        return

    print("Distance (km):", result["distance_km"])
    print("ETA (min):", result["eta_min"])
    print("Sample Points:", result["sample_count"])

    print("\nRoute Checkpoints:\n")
    for cp in result["checkpoints"]:
        print(
            f"P{cp['point']}: "
            f"Location={cp['location']} "
            f"Arrival={cp['arrival_min']} min "
            f"Temp={cp['temperature_c']}°C "
            f"Rain={cp['rain_mm']}mm "
            f"Wind={cp['wind_kmh']}km/h "
            f"Score={cp['weather_score']}"
        )

    print("\nTotal Weather Score:", result["total_weather_score"])
    print("Average Weather Score:", result["average_weather_score"])
    print("Weather Factor:", result["weather_factor"])


if __name__ == "__main__":
    main()
