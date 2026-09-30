from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import json
import os
import xgboost as xgb
import pandas as pd

from sampler import HTTP_TIMEOUT, assess_route_weather


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One shared client keeps connections alive across requests.
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        app.state.http = client
        yield


app = FastAPI(title="Route Weather & AI Pricing Service", lifespan=lifespan)

# Load XGBoost AI Pricing Model
MODEL_PATH = "xgb_pricing_model.json"
xgb_model = None
if os.path.exists(MODEL_PATH):
    xgb_model = xgb.XGBRegressor()
    xgb_model.load_model(MODEL_PATH)
    print(f"Successfully loaded AI Pricing Model from {MODEL_PATH}")
else:
    print(f"Warning: AI model not found at {MODEL_PATH}")


class Coordinate(BaseModel):
    lon: float
    lat: float


class RouteWeatherRequest(BaseModel):
    start: Coordinate
    end: Coordinate


class AIPricingRequest(BaseModel):
    start: Coordinate
    end: Coordinate
    demand: float
    supply: float


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": xgb_model is not None}


@app.post("/route-weather")
async def route_weather(request: RouteWeatherRequest, http_request: Request):
    start = [request.start.lon, request.start.lat]
    end = [request.end.lon, request.end.lat]

    try:
        return await assess_route_weather(http_request.app.state.http, start, end)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/predict-ml-fare")
async def predict_ml_fare(request: AIPricingRequest, http_request: Request):
    """
    Predicts the optimal fare using the trained XGBoost model.
    Takes demand and supply from Part A, and calculates rain & distance internally.
    """
    if xgb_model is None:
        raise HTTPException(status_code=500, detail="AI Model not loaded.")

    start = [request.start.lon, request.start.lat]
    end = [request.end.lon, request.end.lat]

    try:
        # 1. Get distance and weather from routing module
        route_info = await assess_route_weather(http_request.app.state.http, start, end)
        distance = route_info.get("distance_km", 0.0)
        
        # Calculate average rain across checkpoints
        checkpoints = route_info.get("checkpoints", [])
        avg_rain = sum(cp.get("rain_mm", 0.0) for cp in checkpoints) / max(len(checkpoints), 1)

        # 2. Prepare features for XGBoost: ['demand', 'supply', 'rain', 'distance']
        features = pd.DataFrame([{
            'demand': request.demand,
            'supply': request.supply,
            'rain': avg_rain,
            'distance': distance
        }])

        # 3. Predict AI Fare
        predicted_fare = float(xgb_model.predict(features)[0])
        
        # Fallback safety (fares shouldn't be negative or excessively low)
        predicted_fare = max(30.0, predicted_fare)

        return {
            "ml_fare": round(predicted_fare, 2),
            "distance_km": distance,
            "average_rain_mm": round(avg_rain, 2),
            "weather_factor": route_info.get("weather_factor", 1.0),
            "checkpoints": checkpoints,
            "inputs": {
                "demand": request.demand,
                "supply": request.supply,
                "rain": round(avg_rain, 2),
                "distance": round(distance, 2)
            }
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI Prediction failed: {exc}") from exc
