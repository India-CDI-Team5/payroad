"""Post-hoc description (no test, no tuning): calls per request along the whole Hyderabad request stream.

Rebuilds exactly the pre-registered stream of training.city_replication (same wet hours, 300 windows, N = 20,
seed [20261018, 20]) and counts, per request, the calls of
  previous  the previous system: 4/6/9/12 evenly spaced points by distance (posthoc_extra.sample_count), nearest
            value; its cache key is the request's point set, so only a repeated identical request in the same
            10-minute window is free;
  cell      every crossed cell once, no sharing between requests (error 0 by definition);
  F         every crossed cell, shared 10-minute cache (error 0), recomputed here to check the stream is identical
            to results/shared_gp_city/summary.json (full_calls).
The shared GP (G), neighbour rule (N) and fixed point-centre budget (P) at matched calls are read from that summary.
Error = mean |route-mean error| over MAIN-like trips, as in shared_gp.run_windows.

Run from PartB/ (Docker):  python -m training.stream_calls   -> results/shared_gp_city/stream_calls.json
"""
import json
import os
import sys

import numpy as np

from training import city_replication as cr
from training import shared_gp as sg
from training.posthoc_extra import sample_count
from weather.methods import run
from weather.oracle import RouteOracle

N = cr.N_PRIMARY


def previous_and_cell(windows):
    calls_prev = calls_cell = trips = 0
    err, n_main = 0.0, 0
    for w in windows:
        seen = set()
        for tr in w["trips"]:
            r, y = tr["route"], tr["y"]
            n = min(sample_count(r["distance_km"]), len(r["s_km"]))
            key = (id(r), n)
            if key not in seen:
                seen.add(key)
                calls_prev += n
            calls_cell += int(r["unique_cells"])
            trips += 1
            if tr["main"]:
                o = RouteOracle(r["cell"], y)
                res = run("B1", o, r["s_km"], r["t_min"], n)
                err += abs(float(np.mean(res.y_hat)) - float(np.mean(y)))
                n_main += 1
    return {"previous": {"calls": calls_prev / trips, "mae": err / n_main},
            "cell": {"calls": calls_cell / trips, "mae": 0.0}, "trips": trips, "main_trips": n_main}


def main():
    cells = cr.load_cells()
    times, precip = cr.load_weather(len(cells))
    routes = cr.load_routes()
    hours = sg.wet_hours(times, precip, lambda wk: True)
    sg.WINDOWS = cr.WINDOWS
    wins = sg.make_windows(times, precip, hours, routes, N, np.random.default_rng([cr.SEED, N]))
    out = previous_and_cell(wins)
    model, _ = cr.final_eval.load_models()
    ctx = {"xy": cr.city_xy(cells), "model": model, "kr": sg.Kriger(cr.city_xy(cells)), "precip": precip}
    out["F"] = dict(zip(("calls", "mae"), sg.calls_mae(sg.run_windows("F", None, wins, ctx))))
    with open(os.path.join(cr.OUT, "summary.json"), encoding="utf-8") as f:
        row = json.load(f)["runs"][f"N{N}_f{cr.FRAC_PRIMARY}"]
    out["F_in_summary"] = row["full_calls"]
    out["stream_identical"] = bool(abs(out["F"]["calls"] - row["full_calls"]) < 1e-9)
    for m in ("G", "N", "P"):
        out[m] = {"calls": row[m]["calls"], "mae": row[m]["mae"]}
    out["note"] = "post hoc, descriptive; previous/cell/F counted on the pre-registered stream, G/N/P from summary.json"
    with open(os.path.join(cr.OUT, "stream_calls.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
