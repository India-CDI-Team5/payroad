"""Routes and samples for Model A evaluation, and the subsets of ml-design v5 §4.1.

Splits are chosen only through load_samples(splits); in_subset never looks at the split.
"""
import os

import numpy as np
import pyarrow.compute as pc
import pyarrow.parquet as pq

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
IST = np.timedelta64(330, "m")                  # same as build_samples: UTC + 5:30, no daylight saving
WET_MM = 0.1
ROUTE_FILES = {"main": "routes.parquet", "holdout": "routes_holdout.parquet"}
SUBSETS = ("MAIN", "ALL", "LONG", "HOLDOUT")


def load_routes():
    """{(route_set, route_id): {cell, s_km, t_min, distance_km, unique_cells, stratum}}."""
    routes = {}
    for route_set, name in ROUTE_FILES.items():
        cols = ["route_id", "cell", "s_km", "t_min", "distance_km", "unique_cells", "stratum"]
        for r in pq.read_table(os.path.join(DATA_DIR, name), columns=cols).to_pylist():
            routes[(route_set, r["route_id"])] = {
                "cell": np.array(r["cell"], dtype=np.int64),
                "s_km": np.array(r["s_km"], dtype=np.float64),
                "t_min": np.array(r["t_min"], dtype=np.float64),
                "distance_km": r["distance_km"],
                "unique_cells": r["unique_cells"],
                "stratum": r["stratum"],
            }
    return routes


def load_samples(splits):
    """Samples whose split is in `splits`, with gt_mm as a float64 array."""
    t = pq.read_table(os.path.join(DATA_DIR, "samples.parquet"))
    t = t.filter(pc.is_in(t.column("split"), value_set=pc.cast(list(splits), t.schema.field("split").type)))
    rows = t.to_pylist()
    for r in rows:
        r["gt_mm"] = np.array(r["gt_mm"], dtype=np.float64)
    return rows


def iso_week(departure_utc):
    """(ISO year, ISO week) of the local (IST) departure date."""
    local = np.datetime64(departure_utc, "m") + IST
    iso = local.astype("datetime64[D]").astype(object).isocalendar()
    return iso[0], iso[1]


def in_subset(sample, route, name):
    u3 = route["unique_cells"] >= 3
    wet = bool(np.max(sample["gt_mm"]) > WET_MM)
    if name == "MAIN":
        return u3 and wet
    if name == "ALL":
        return u3
    if name == "LONG":
        return u3 and wet and route["distance_km"] >= 10
    if name == "HOLDOUT":
        return sample["route_set"] == "holdout" and u3 and wet
    raise ValueError(f"unknown subset {name!r}, expected one of {SUBSETS}")
