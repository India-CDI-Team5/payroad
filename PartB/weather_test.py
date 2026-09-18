import requests

lat = 12.9352
lon = 77.6245

url = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={lat}"
    f"&longitude={lon}"
    "&hourly=temperature_2m,precipitation,wind_speed_10m"
    "&forecast_days=1"
)

response = requests.get(url)

print("Status Code:", response.status_code)

data = response.json()
print(data["hourly"].keys())

print(data.keys())
print("Time:")
print(data["hourly"]["time"][:5])

print()

print("Temperature:")
print(data["hourly"]["temperature_2m"][:5])

print()

print("Rain:")
print(data["hourly"]["precipitation"][:5])

print()

print("Wind:")
print(data["hourly"]["wind_speed_10m"][:5])