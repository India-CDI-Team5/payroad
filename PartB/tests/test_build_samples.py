import numpy as np

from training.build_samples import (arrival_values, assign_weeks, candidate_departures, season,
                                    stochastic_round)


def test_arrival_values_interpolates_each_point_at_its_arrival_time():
    # 2 cells x 4 hours; cell value = hour index (cell 0) or 10 x hour index (cell 1)
    precip = np.array([[0.0, 1.0, 2.0, 3.0], [0.0, 10.0, 20.0, 30.0]])
    # A point in cell 0 reached immediately, a point in cell 1 reached 30 minutes later.
    v = arrival_values(precip, cells=[0, 1], t_min=[0.0, 30.0], dep_offsets_h=np.array([1.0, 1.5]))
    assert np.allclose(v, [[1.0, 15.0], [1.5, 20.0]])


def test_weeks_never_straddle_splits_and_every_split_has_every_season():
    times = np.arange(np.datetime64("2024-06-01T00:00"), np.datetime64("2025-06-01T00:00"), np.timedelta64(1, "h"))
    split_of = assign_weeks(times, np.random.default_rng(0))
    assert set(split_of.values()) == {"train", "val", "test"}
    deps, split, seasons = candidate_departures(times, split_of, np.random.default_rng(0), max_trip_min=120)
    for s in ("train", "val", "test"):
        assert set(seasons[split == s]) == {"sw_monsoon", "ne_monsoon", "dry"}
    # Departures only in the local ride window 06:00-23:59 IST, including 06:00-06:29.
    local = times[0] + np.timedelta64(330, "m") + (deps * 60).astype("timedelta64[m]")
    hour = (local.astype("datetime64[h]") - local.astype("datetime64[D]")).astype(int)
    minute = (local - local.astype("datetime64[h]")).astype(int)
    assert hour.min() == 6 and hour.max() == 23
    assert ((hour == 6) & (minute < 30)).any()


def test_stochastic_round_is_exact_on_average():
    rng = np.random.default_rng(1)
    assert abs(np.mean([stochastic_round(rng, 1.6) for _ in range(20000)]) - 1.6) < 0.02


def test_season():
    assert [season(m) for m in (1, 6, 9, 10, 11, 12)] == ["dry", "sw_monsoon", "sw_monsoon", "ne_monsoon", "ne_monsoon", "dry"]
