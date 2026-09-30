import argparse
import asyncio
import json

import httpx

import os
from dotenv import load_dotenv

# Load .env from root directory (one level up from PartB)
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

API_KEY = os.environ.get("ORS_API_KEY", "")

ROUTE_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
HTTP_TIMEOUT = httpx.Timeout(10.0)


async def fetch_route(client, start, end, api_key=API_KEY):
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json"
    }
    body = {
        "coordinates": [start, end],
        "instructions": False
    }
    response = await client.post(ROUTE_URL, json=body, headers=headers)
    response.raise_for_status()
    return response.json()


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
    latitudes = [str(point[1]) for point in sampled_points]
    longitudes = [str(point[0]) for point in sampled_points]

    weather_url = (
        f"{WEATHER_URL}"
        f"?latitude={','.join(latitudes)}"
        f"&longitude={','.join(longitudes)}"
        "&hourly=temperature_2m,precipitation,wind_speed_10m"
        "&forecast_days=1"
    )
    response = await client.get(weather_url)
    response.raise_for_status()
    return response.json()


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


async def assess_route_weather(client, start, end, api_key=API_KEY):
    route_data = await fetch_route(client, start, end, api_key)

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

    checkpoints = []
    total_weather_score = 0

    for idx, location_weather in enumerate(weather_data):
        arrival_min = arrival_times[idx]
        hour_position = arrival_min / 60
        lower_hour = int(hour_position)
        upper_hour = min(lower_hour + 1, 23)
        fraction = hour_position - lower_hour

        hourly = location_weather["hourly"]

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
