"""Deal list for the mechanism experiments (ml-design v5 §6.1, card B10): data/experiment/deals.csv.

One row per test-split sample of the main routes, by sample_id. The experiment runner reads this file
instead of calling any API. base_price uses the true route-mean rain m (s = 0, surge = 1).

This reads the test split's ground truth, but only to build mechanism inputs; it is not a Model A
evaluation and runs after the freeze commit (card B5), so it cannot influence the frozen configuration.

Run from PartB/:  python -m training.export_deals
"""
import csv
import json
import os

import numpy as np
import pyarrow.parquet as pq

from weather.data import DATA_DIR, ROUTE_FILES, WET_MM, load_routes, load_samples

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
PRICING = os.path.join(ROOT, "config", "pricing-constants.json")
OUT_PATH = os.path.join(ROOT, "data", "experiment", "deals.csv")
COLUMNS = ("deal_id", "sample_id", "distance_km", "origin_lat", "origin_lng", "base_dry", "m_true", "beta",
           "base_price", "wet")


def beta(r, s, c):
    """β(r, s) of ml-design v5 §5.1 with the frozen constants (until card B8's pricing/base_price.py)."""
    return 1 + min(max(r - c["uncertaintyWeight"] * s, 0.0) * c["betaCoef"], c["betaCap"])


def origins():
    t = pq.read_table(os.path.join(DATA_DIR, ROUTE_FILES["main"]), columns=["route_id", "origin_lat", "origin_lon"])
    return {r["route_id"]: (r["origin_lat"], r["origin_lon"]) for r in t.to_pylist()}


def rows(constants):
    routes = load_routes()
    origin = origins()
    samples = [s for s in load_samples(["test"]) if s["route_set"] == "main"]
    out = []
    for smp in sorted(samples, key=lambda s: s["sample_id"]):
        route = routes[("main", smp["route_id"])]
        km = float(route["distance_km"])
        m_true = float(np.mean(smp["gt_mm"]))
        base_dry = constants["baseFee"] + constants["perKm"] * km
        b = beta(m_true, 0.0, constants)
        lat, lng = origin[smp["route_id"]]
        out.append({
            "deal_id": f"S{smp['sample_id']}", "sample_id": smp["sample_id"], "distance_km": km,
            "origin_lat": lat, "origin_lng": lng, "base_dry": base_dry, "m_true": m_true, "beta": b,
            "base_price": round(base_dry * b, 2), "wet": int(np.max(smp["gt_mm"]) > WET_MM),
        })
    return out


def fmt(value):
    return f"{value:.4f}" if isinstance(value, float) else str(value)


def write(rows_, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(COLUMNS)
        for r in rows_:
            w.writerow([fmt(r[c]) for c in COLUMNS])


def main():
    with open(PRICING, encoding="utf-8") as f:
        constants = json.load(f)
    out = rows(constants)
    write(out, OUT_PATH)
    wet = sum(r["wet"] for r in out)
    print(f"{len(out)} deals, wet {wet} ({wet / len(out):.3f}) -> {OUT_PATH}")


if __name__ == "__main__":
    main()
