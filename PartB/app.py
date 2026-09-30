from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from sampler import HTTP_TIMEOUT, assess_route_weather


@asynccontextmanager
async def lifespan(app: FastAPI):
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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/route-weather")
async def route_weather(request: RouteWeatherRequest, http_request: Request):
    start = [request.start.lon, request.start.lat]
    end = [request.end.lon, request.end.lat]

    try:
        return await assess_route_weather(http_request.app.state.http, start, end)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
