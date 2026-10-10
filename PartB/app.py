from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

import quote as quoting
from pricing.base_price import load_constants
from sampler import HTTP_TIMEOUT, assess_route_weather


def load_interpolator():
    """Model A's GP and the grid it was trained on; None when either file is missing."""
    try:
        return quoting.load_model(), quoting.load_cells()
    except (OSError, ValueError, KeyError):
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.interpolator = load_interpolator()
    app.state.pricing = load_constants()
    # One shared client keeps connections alive across requests.
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        app.state.http = client
        yield


app = FastAPI(title="Route Weather Service", lifespan=lifespan)


class Coordinate(BaseModel):
    lon: float
    lat: float


class RouteWeatherRequest(BaseModel):
    start: Coordinate
    end: Coordinate


class LatLng(BaseModel):
    lat: float
    lng: float


class QuoteRequest(BaseModel):
    origin: LatLng
    dest: LatLng
    departureUtc: Optional[datetime] = None
    demand: int = 0
    supply: int = 0


@app.get("/health")
def health(request: Request):
    return {"status": "ok", "interpolatorLoaded": getattr(request.app.state, "interpolator", None) is not None}


@app.post("/quote")
async def quote(request: QuoteRequest, http_request: Request):
    state = http_request.app.state
    departure = request.departureUtc or datetime.now(timezone.utc)
    try:
        if state.interpolator is None:
            raise RuntimeError("Model A interpolator is not loaded")
        model, cells = state.interpolator
        return await quoting.quote(state.http, (request.origin.lat, request.origin.lng),
                                   (request.dest.lat, request.dest.lng), departure, request.demand,
                                   request.supply, model=model, cells=cells, c=state.pricing)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/route-weather")
async def route_weather(request: RouteWeatherRequest, http_request: Request):
    start = [request.start.lon, request.start.lat]
    end = [request.end.lon, request.end.lat]

    try:
        return await assess_route_weather(http_request.app.state.http, start, end)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
