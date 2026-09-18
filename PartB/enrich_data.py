"""
enrich_data.py
--------------
Enriches match_result.csv with weather features from Open-Meteo API.
Since all simulation data occurs within a narrow time window, we assign
synthetic hour variation (0-23) to simulate a full day of operations,
then map each record to the actual hourly weather forecast for Bengaluru.

Output: match_result_enriched.csv
"""
import csv
import json
import random
import urllib.request

# Bengaluru center (same as SimulationBootstrap.java)
CENTER_LAT = 12.9716
CENTER_LON = 77.5946

WEATHER_URL = (
    f"https://api.open-meteo.com/v1/forecast"
    f"?latitude={CENTER_LAT}&longitude={CENTER_LON}"
    f"&hourly=temperature_2m,precipitation,wind_speed_10m"
    f"&forecast_days=1"
)

def fetch_hourly_weather():
    """Fetch 24-hour weather forecast for Bengaluru from Open-Meteo."""
    print("Fetching weather data from Open-Meteo API...")
    req = urllib.request.Request(WEATHER_URL)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())

    hourly = data["hourly"]
    weather_by_hour = {}
    for i in range(24):
        weather_by_hour[i] = {
            "temperature": hourly["temperature_2m"][i],
            "rain": hourly["precipitation"][i],
            "wind": hourly["wind_speed_10m"][i],
        }
    print("Weather data fetched successfully.")
    return weather_by_hour


def score_weather(temp, rain, wind):
    """Same scoring logic as sampler.py for consistency."""
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


def enrich():
    weather_by_hour = fetch_hourly_weather()

    # Read original data
    with open("match_result.csv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Original data: {len(rows)} records")

    # Assign synthetic hours (uniform 0-23) for time variation
    random.seed(42)
    enriched = []
    for row in rows:
        hour = random.randint(0, 23)
        weather = weather_by_hour[hour]

        w_score = score_weather(
            weather["temperature"], weather["rain"], weather["wind"]
        )
        weather_factor = round(1 + w_score * 0.1, 2)

        enriched.append({
            "DEMAND_IN_RADIUS": row["DEMAND_IN_RADIUS"],
            "SUPPLY_IN_RADIUS": row["SUPPLY_IN_RADIUS"],
            "PICKUP_DISTANCE_KM": row["PICKUP_DISTANCE_KM"],
            "HOUR": hour,
            "TEMPERATURE": weather["temperature"],
            "RAIN": weather["rain"],
            "WIND": weather["wind"],
            "WEATHER_SCORE": w_score,
            "WEATHER_FACTOR": weather_factor,
            "SURGE": row["SURGE"],
            "BASE_FARE": row["BASE_FARE"],
            "FINAL_FARE": row["FINAL_FARE"],
        })

    # Write enriched data
    output_file = "match_result_enriched.csv"
    fieldnames = list(enriched[0].keys())
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(enriched)

    print(f"Enriched data saved to {output_file} ({len(enriched)} records)")


if __name__ == "__main__":
    enrich()
