import pyarrow as pa
import pyarrow.parquet as pq

from training.data_summary import summarize


def write(path, rows):
    pq.write_table(pa.Table.from_pylist(rows), path)


def route(route_set, stratum, km, u):
    return {"route_set": route_set, "stratum": stratum, "distance_km": km, "unique_cells": u}


def sample(route_set, split, local, season, wet):
    return {"route_set": route_set, "split": split, "departure_local": local, "season": season, "wet": wet}


def test_summary_has_every_key_and_U_hist_adds_up_to_route_count(tmp_path):
    write(tmp_path / "routes.parquet", [route("main", "short", 8.0, 1), route("main", "short", 12.0, 3),
                                        route("main", "medium", 20.0, 3), route("main", "long", 45.0, 6)])
    write(tmp_path / "routes_holdout.parquet", [route("holdout", "short", 9.0, 2), route("holdout", "long", 50.0, 5)])
    times = ["2024-06-01T00:00", "2024-06-01T01:00", "2024-06-01T02:00"]
    write(tmp_path / "cells.parquet", [{"time_utc": times, "precipitation_mm": [0.0, 0.5, None]},
                                       {"time_utc": times, "precipitation_mm": [0.2, 0.0, 0.0]}])
    write(tmp_path / "samples.parquet", [
        sample("main", "train", "2024-06-03T08:00", "sw_monsoon", True),
        sample("main", "train", "2024-06-10T08:00", "dry", False),
        sample("main", "val", "2024-06-17T08:00", "dry", True),
        sample("main", "test", "2024-06-24T08:00", "sw_monsoon", False),
        sample("holdout", "test_holdout", "2024-06-24T09:00", "sw_monsoon", True),
    ])

    s = summarize(str(tmp_path))

    assert set(s) == {"routes_main", "routes_holdout", "cells", "samples", "G1"}
    for key in ("routes_main", "routes_holdout"):
        r = s[key]
        assert set(r) == {"n", "by_stratum", "U_hist", "share_U_ge_3", "distance_km"}
        assert set(r["by_stratum"]) == {"short", "medium", "long"}
        assert set(r["distance_km"]) == {"min", "median", "max"}
        assert sum(r["U_hist"].values()) == r["n"]
    assert s["routes_main"]["n"] == 4 and s["routes_holdout"]["n"] == 2
    assert s["routes_main"]["U_hist"] == {"1": 1, "3": 2, "6": 1}
    assert s["routes_main"]["share_U_ge_3"] == 0.75

    assert set(s["cells"]) == {"n", "hours", "period_utc", "wet_hour_share_gt_0.1"}
    assert s["cells"]["n"] == 2 and s["cells"]["hours"] == 3
    assert s["cells"]["period_utc"] == ["2024-06-01T00:00", "2024-06-01T02:00"]
    assert s["cells"]["wet_hour_share_gt_0.1"] == 0.4          # 0.5 and 0.2 of 5 non-missing hours

    smp = s["samples"]
    assert set(smp) == {"by_split", "wet_share_by_split", "dry_season_share", "iso_weeks_by_split"}
    for key in ("by_split", "wet_share_by_split", "iso_weeks_by_split"):
        assert set(smp[key]) == {"train", "val", "test", "test_holdout"}
    assert smp["by_split"] == {"train": 2, "val": 1, "test": 1, "test_holdout": 1}
    assert smp["iso_weeks_by_split"]["train"] == 2
    assert smp["dry_season_share"] == 0.5                       # main samples only

    assert set(s["G1"]) == {"pass", "share_U_ge_3", "wet_share"}
    assert s["G1"]["wet_share"] == 0.5 and s["G1"]["pass"] is True
