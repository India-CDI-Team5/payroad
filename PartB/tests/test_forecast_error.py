"""training/forecast_error.py with a fake forecast file (card B9). No network."""
import csv
import gzip
import json

import numpy as np
import pyarrow.parquet as pq
import pytest

from pricing.base_price import load_constants
from training import forecast_error as fe
from training.build_samples import load_cells

C = load_constants()
CELLS = [(12.97, 77.56), (12.97, 77.64)]
HOURS = [f"2024-06-01T{h:02d}:00" for h in range(24)] + [f"2024-06-02T{h:02d}:00" for h in range(24)]


def fake_raw(tmp_path, series):
    raw = tmp_path / "raw"
    raw.mkdir()
    for i, values in enumerate(series):
        with open(raw / f"{i:03d}.json", "w", encoding="utf-8") as f:
            json.dump({"latitude": CELLS[i][0], "longitude": CELLS[i][1],
                       "hourly": {"time": HOURS, fe.VARIABLE: values}}, f)
    return raw


def route(cells, t_min):
    return {"cell": np.array(cells), "t_min": np.array(t_min, dtype=float), "s_km": np.zeros(len(cells)),
            "distance_km": 10.0, "unique_cells": len(set(cells)), "stratum": "short"}


def sample(sid, dep, gt, split="test"):
    gt = np.array(gt, dtype=float)
    return {"sample_id": sid, "route_set": "main", "route_id": 0, "split": split, "departure_utc": dep,
            "gt_mm": gt, "route_mean_mm": float(gt.mean())}


def test_parquet_keeps_the_cells_columns_and_load_cells_reads_it(tmp_path):
    raw = fake_raw(tmp_path, [[0.0] * 48, [1.0] * 47 + [None]])
    out = tmp_path / "fc.parquet"
    fe.write_parquet(CELLS, raw, str(out))
    assert pq.read_table(out).column_names == ["cell", "lat", "lon", "time_utc", "precipitation_mm", "rain_mm",
                                               "weather_code"]
    times, precip = load_cells(str(out))
    assert precip.shape == (2, 48)
    assert np.isnan(precip[1, 47]) and precip[1, 0] == 1.0
    assert times[0] == np.datetime64("2024-06-01T00:00")


def test_forecast_mean_interpolates_in_time_and_skips_trips_outside_the_period():
    times = np.array(HOURS, dtype="datetime64[m]")
    precip = np.vstack([np.arange(48, dtype=float), np.full(48, 2.0)])
    r = {("main", 0): route([0, 1], [0.0, 30.0])}
    inside = sample(1, "2024-06-01T10:00", [0, 0])
    before = sample(2, "2024-05-31T23:00", [0, 0])
    after = sample(3, "2024-06-02T23:30", [0, 0])
    m = fe.forecast_means([inside, before, after], r, times, precip)
    assert set(m) == {1}
    assert m[1] == pytest.approx((10.0 + 2.0) / 2)       # cell 0 at 10:00, cell 1 at 10:30


def test_nan_in_the_forecast_drops_the_sample():
    times = np.array(HOURS, dtype="datetime64[m]")
    precip = np.vstack([np.full(48, np.nan), np.ones(48)])
    m = fe.forecast_means([sample(1, "2024-06-01T05:00", [0, 0])], {("main", 0): route([0, 1], [0, 10])}, times, precip)
    assert m == {}


def test_evaluate_counts_flips_errors_and_m1(tmp_path):
    times = np.array(HOURS, dtype="datetime64[m]")
    precip = np.vstack([np.full(48, 3.0), np.full(48, 0.0)])     # cell 0 says 3 mm/h, cell 1 says dry
    routes = {("main", 0): route([0, 0], [0, 10]), ("main", 1): route([1, 1], [0, 10])}
    s_wet_hit = sample(10, "2024-06-01T05:00", [2.0, 2.0])            # true 2.0 -> fc 3.0: both surcharged
    s_flip = dict(sample(11, "2024-06-01T05:00", [2.0, 2.0]), route_id=1)  # true 2.0 -> fc 0.0: flips
    s_dry = sample(12, "2024-06-01T05:00", [0.0, 0.0])                # not wet: excluded
    s_train = sample(13, "2024-06-01T05:00", [2.0, 2.0], split="train")
    row, counts = fe.evaluate([s_wet_hit, s_flip, s_dry, s_train], routes, times, precip, {10: 0.2, 11: 0.4}, C)
    assert row["n"] == 2 and counts["test_wet"] == 2
    assert row["mae_fc"] == pytest.approx((1.0 + 2.0) / 2)
    assert row["flip_rate"] == pytest.approx(0.5)
    assert row["m1_mae_rho50"] == pytest.approx(0.3)
    assert row["p90_abs_err"] == pytest.approx(1.9)

    path = tmp_path / "out" / "forecast_error.csv"
    fe.write_csv(str(path), row)
    with open(path, newline="", encoding="utf-8") as f:
        out = list(csv.DictReader(f))
    assert list(out[0]) == fe.COLUMNS and out[0]["n"] == "2"


def test_m1_errors_reads_only_m1_at_rho_half(tmp_path):
    path = tmp_path / "per_sample.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sample_id", "method", "rho", "abs_err"])
        w.writerows([[1, "M1", "0.5", "0.1"], [1, "M1", "0.25", "0.9"], [1, "B1", "0.5", "0.7"], [2, "M1", "0.5", ""],
                    [3, "M1", "", "0.3"]])
    assert fe.m1_errors(str(path)) == {1: 0.1}


def test_download_checks_the_grid_and_resumes(tmp_path, monkeypatch):
    monkeypatch.setattr(fe, "RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setattr(fe.time, "sleep", lambda s: None)
    calls = []

    def fake_fetch(client, lat, lon, **kw):
        calls.append((lat, lon))
        return {"latitude": lat + 0.001, "longitude": lon, "hourly": {"time": HOURS, fe.VARIABLE: [0.0] * 48}}

    monkeypatch.setattr(fe, "fetch_cell", fake_fetch)
    fetched, est = fe.download(None, CELLS)
    assert fetched == 2 and est == pytest.approx(2 * 548 / 14)
    assert fe.download(None, CELLS)[0] == 0 and len(calls) == 2          # resumed: nothing fetched again

    monkeypatch.setattr(fe, "RAW_DIR", str(tmp_path / "raw2"))
    monkeypatch.setattr(fe, "fetch_cell", lambda client, lat, lon, **kw: {"latitude": lat + 0.05, "longitude": lon,
                                                                         "hourly": {}})
    with pytest.raises(RuntimeError, match="asked"):
        fe.download(None, CELLS)
