import asyncio
import json

import httpx
from diskcache import Cache

from clients.ors_client import ORS_URL, cache_key, fetch_route, route_body, summarize

ROUTE = {"features": [{"properties": {"summary": {"distance": 12345.0, "duration": 1500.0}},
                       "geometry": {"coordinates": [[77.60, 12.93], [77.65, 12.97], [77.70, 13.00]]}}]}


def test_route_body_keeps_lon_lat_order_and_extras():
    body = route_body([77.6, 12.9], [77.7, 13.0], radiuses=[1000, 1000])
    assert body == {"coordinates": [[77.6, 12.9], [77.7, 13.0]], "instructions": False, "radiuses": [1000, 1000]}


def test_summarize():
    s = summarize(ROUTE)
    assert (s["distance_km"], s["eta_min"], s["coordinate_count"]) == (12.35, 25.0, 3)


def test_fetch_route_sends_key_and_reuses_cache(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=ROUTE)

    async def run():
        cache = Cache(str(tmp_path))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            a = await fetch_route(client, [77.6, 12.9], [77.7, 13.0], api_key="k", cache=cache)
            b = await fetch_route(client, [77.6, 12.9], [77.7, 13.0], api_key="k", cache=cache)
        return a, b, cache

    a, b, cache = asyncio.run(run())
    assert a == b == ROUTE
    assert len(seen) == 1                                   # the second call came from the cache
    assert str(seen[0].url) == ORS_URL
    assert seen[0].headers["Authorization"] == "k"
    assert json.loads(seen[0].content)["coordinates"] == [[77.6, 12.9], [77.7, 13.0]]
    assert cache_key([77.6, 12.9], [77.7, 13.0]) in cache
