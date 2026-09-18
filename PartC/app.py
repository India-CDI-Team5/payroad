from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import time
import json
import logging
import asyncio
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

app = FastAPI(title="Dynamic Pricing Engine (Part C) - AI Powered")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

# Service URLs for Part A and Part B
PART_A_URL = "http://127.0.0.1:8080"   # Spring Boot default port
PART_B_URL = "http://127.0.0.1:8000"   # Python FastAPI (uvicorn)

class Coordinate(BaseModel):
    lon: float
    lat: float


class FareRequest(BaseModel):
    start: Coordinate
    end: Coordinate


class LockInRequest(BaseModel):
    start: Coordinate
    end: Coordinate


# Configure Tick Logger
tick_logger = logging.getLogger("price_ticks")
tick_logger.setLevel(logging.INFO)
file_handler = logging.FileHandler("price_ticks.jsonl")
file_handler.setFormatter(logging.Formatter("%(message)s"))
tick_logger.addHandler(file_handler)


def log_tick(fare_data: dict, is_lockin: bool = False):
    """Logs the fare calculation snapshot to a JSONL file."""
    log_entry = fare_data.copy()
    log_entry["is_lockin"] = is_lockin
    tick_logger.info(json.dumps(log_entry))


def _calculate_fare(start: Coordinate, end: Coordinate) -> dict:
    """Core logic: Fetches supply/demand from Part A, then calls Part B's AI model for the final fare."""
    # Step 1: Get demand & supply from Part A
    try:
        resp_a = requests.get(
            f"{PART_A_URL}/supply-demand",
            params={"lat": start.lat, "lon": start.lon},
            timeout=5
        )
        resp_a.raise_for_status()
        data_a = resp_a.json()
        demand = data_a.get("demand", 0)
        supply = data_a.get("supply", 0)
        alpha = data_a.get("alpha", 1.0)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch supply-demand data from Part A: {exc}"
        ) from exc

    # Step 2: Pass demand, supply, and coordinates to Part B's AI Model
    try:
        resp_b = requests.post(
            f"{PART_B_URL}/predict-ml-fare",
            json={
                "start": {"lon": start.lon, "lat": start.lat},
                "end": {"lon": end.lon, "lat": end.lat},
                "demand": demand,
                "supply": supply
            },
            timeout=15
        )
        resp_b.raise_for_status()
        data_b = resp_b.json()
        ml_fare = data_b.get("ml_fare", 0.0)
        distance_km = data_b.get("distance_km", 0.0)
        avg_rain = data_b.get("average_rain_mm", 0.0)
        beta = data_b.get("weather_factor", 1.0)
        checkpoints = data_b.get("checkpoints", [])
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch ML fare from Part B: {exc}"
        ) from exc

    # Step 3: Compile and return the results
    return {
        "final_fare": ml_fare,           # AI 가 도출한 최종 요금!
        "pricing_model": "XGBoost",      # 이제 Rule-based가 아닌 ML-based임을 명시
        "alpha": alpha,                  # 참고용 기존 계수
        "beta": beta,                    # 참고용 기존 계수
        "demand": demand,
        "supply": supply,
        "average_rain_mm": avg_rain,
        "distance_km": distance_km,
        "checkpoints": checkpoints,
        "timestamp": time.time()
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "ai-pricing-engine"}


@app.get("/api/config")
def get_config():
    return {"orsApiKey": os.environ.get("ORS_API_KEY", "")}


@app.post("/fare")
def calculate_fare(request: FareRequest):
    """Calculates fare via AI and logs the tick."""
    fare_result = _calculate_fare(request.start, request.end)
    log_tick(fare_result, is_lockin=False)
    return fare_result


@app.post("/lock-in")
def lock_in_fare(request: LockInRequest):
    """Locks the AI-calculated fare and logs it."""
    fare_result = _calculate_fare(request.start, request.end)
    log_tick(fare_result, is_lockin=True)

    return {
        "locked": True,
        "locked_at": time.time(),
        "confirmed_fare": fare_result["final_fare"],
        "breakdown": fare_result
    }


async def fare_generator(start: Coordinate, end: Coordinate):
    """Generator that yields fare data every 3 seconds for SSE."""
    while True:
        try:
            fare_data = await asyncio.to_thread(_calculate_fare, start, end)
            log_tick(fare_data, is_lockin=False)
            yield f"data: {json.dumps(fare_data)}\n\n"
        except Exception as e:
            error_data = {"error": str(e), "timestamp": time.time()}
            yield f"data: {json.dumps(error_data)}\n\n"
        
        await asyncio.sleep(3)


@app.get("/stream-fare")
async def stream_fare(start_lat: float, start_lon: float, end_lat: float, end_lon: float):
    """Server-Sent Events (SSE) endpoint."""
    start = Coordinate(lat=start_lat, lon=start_lon)
    end = Coordinate(lat=end_lat, lon=end_lon)
    
    return StreamingResponse(
        fare_generator(start, end),
        media_type="text/event-stream"
    )
