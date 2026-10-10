"""basePrice = (baseFee + perKm × d) × surge(D, S) × β(r, s) (docs/pricing-constants.md).

The constants come only from config/pricing-constants.json, frozen in card B5.
"""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
# ../config/pricing-constants.json seen from PartB/, resolved so any working directory works.
DEFAULT_PATH = os.path.normpath(os.path.join(HERE, "..", "..", "config", "pricing-constants.json"))


def load_constants(path=DEFAULT_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def surge(demand, supply, c=None):
    """clip(D / max(S, 1), surgeMin, surgeMax) rounded half up to 0.1, the same as Part A's SupplyDemandService."""
    c = c or load_constants()
    ratio = demand / max(supply, 1)
    clipped = max(c["surgeMin"], min(c["surgeMax"], ratio))
    return math.floor(clipped * 10 + 0.5) / 10


def beta(r, s, c):
    return 1 + min(max(r - c["uncertaintyWeight"] * s, 0.0) * c["betaCoef"], c["betaCap"])


def base_dry(distance_km, c):
    return c["baseFee"] + c["perKm"] * distance_km


def base_price(distance_km, demand, supply, r, s, c):
    return round(base_dry(distance_km, c) * surge(demand, supply, c) * beta(r, s, c), 2)
