import argparse
import json

import requests

import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

API_KEY = os.environ.get("ORS_API_KEY", "")

ROUTE_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"


def fetch_route(start, end, api_key=API_KEY):
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json"
    }
    body = {
        "coordinates": [start, end],
        "instructions": False
    }
    response = requests.post(ROUTE_URL, json=body, headers=headers)
    response.raise_for_status()
    return response.json()


def get_route_summary(start, end, api_key=API_KEY):
    data = fetch_route(start, end, api_key)

    distance = data["features"][0]["properties"]["summary"]["distance"]
    duration = data["features"][0]["properties"]["summary"]["duration"]
    route_coordinates = data["features"][0]["geometry"]["coordinates"]

    return {
        "distance_km": round(distance / 1000, 2),
        "eta_min": round(duration / 60, 2),
        "coordinate_count": len(route_coordinates),
        "route_coordinates": route_coordinates,
    }


def parse_coord(value):
    lon, lat = (float(v) for v in value.split(","))
    return [lon, lat]


def main():
    parser = argparse.ArgumentParser(description="Fetch a driving route between two points.")
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

    result = get_route_summary(args.start, args.end)

    if args.json:
        print(json.dumps(result))
        return

    print("Distance (km):", result["distance_km"])
    print("ETA (min):", result["eta_min"])
    print("Number of route coordinates:", result["coordinate_count"])


if __name__ == "__main__":
    main()
