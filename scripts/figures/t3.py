"""T3: forecast calls and cache keys (results/tables/T3_calls.csv, T3_cache.csv, card B8).

The two inputs live in results/tables/ too; this writes T3.md, T3_table.csv and T3_cache_table.csv
and never touches T3_calls.csv or T3_cache.csv.
"""
import csv
import os

import style

CALL_LABELS = {
    "current_points": "Current: one call per sampled point",
    "current_cells": "Current points, duplicate cells removed",
    "all_cells_U": "Every crossed cell (U)",
    "proposed_M2": "Proposed: M2, k = ⌈U/2⌉",
}
CACHE_LABELS = {
    "current_points_2dp": "Current points, 2-decimal coordinate key",
    "current_points_cell": "Current points, cell-centre key",
    "proposed_M2_cell": "Proposed M2 cells, cell-centre key",
}
CALL_HEADER = ["Method", "Routes", "Mean calls", "Median calls", "Total calls", "Saving vs current"]
CACHE_HEADER = ["Key scheme", "Trips", "Lookups", "Unique keys", "Hit rate", "API calls"]


def _md(header, rows):
    return ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"] + \
        ["| " + " | ".join(r) + " |" for r in rows]


def _csv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    return path


def make(results_dir, out_dir):
    d = os.path.join(results_dir, "tables")
    calls = style.read_csv(os.path.join(d, "T3_calls.csv"))
    cache = style.read_csv(os.path.join(d, "T3_cache.csv"))
    call_rows = [[CALL_LABELS.get(r["method"], r["method"]), style.fmt_int(r["routes"]), style.fmt(r["mean_calls"]),
                  style.fmt(r["median_calls"]), style.fmt_int(r["total_calls"]), style.fmt(r["saving_vs_current"])]
                 for r in calls]
    cache_rows = [[CACHE_LABELS.get(r["key_scheme"], r["key_scheme"]), style.fmt_int(r["trips"]),
                   style.fmt_int(r["lookups"]), style.fmt_int(r["unique_keys"]), style.fmt(r["hit_rate"]),
                   style.fmt_int(r["api_calls"])] for r in cache]
    ttl = cache[0]["ttl_min"] if cache else "10"

    os.makedirs(out_dir, exist_ok=True)
    md = ["### T3. Forecast calls per route and cache keys", "", "Held-out routes:", ""] + _md(CALL_HEADER, call_rows)
    md += ["", f"Cache within one {ttl}-minute TTL window:", ""] + _md(CACHE_HEADER, cache_rows)
    md_path = os.path.join(out_dir, "T3.md")
    with open(md_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md) + "\n")
    return [md_path, _csv(os.path.join(out_dir, "T3_table.csv"), CALL_HEADER, call_rows),
            _csv(os.path.join(out_dir, "T3_cache_table.csv"), CACHE_HEADER, cache_rows)]
