import datetime

import numpy as np

from training import temporal_check as tc


def test_candidates_are_ist_hours_of_every_day():
    first = datetime.datetime(2025, 12, 1, 0, 0)
    offsets, stamps = tc.candidate_offsets(first)
    days = (tc.END - tc.START).days + 1
    assert len(offsets) == days * len(tc.LOCAL_HOURS)
    assert offsets[0] == 0.5                                    # 06:00 IST = 00:30 UTC
    assert stamps[0] == datetime.datetime(2025, 12, 1, 0, 30)
    assert stamps[-1] == datetime.datetime(2026, 10, 14, 17, 30)  # 23:00 IST on the last day


def routes_and_rain():
    route = {"cell": np.array([0, 0, 1, 1, 2]), "t_min": np.zeros(5), "unique_cells": 3}
    short = {"cell": np.array([0, 1]), "t_min": np.zeros(2), "unique_cells": 2}
    precip = np.zeros((3, 40))
    precip[1, [3, 4, 10, 20, 30, 31]] = 1.0                    # wet hours in cell 1
    precip[2, 15] = np.nan                                     # one missing hour
    return {("main", 0): route, ("main", 1): short}, precip


def test_draw_takes_wet_complete_departures_only_and_is_repeatable():
    routes, precip = routes_and_rain()
    offsets = np.arange(36, dtype=float)
    stamps = list(range(36))
    a, skipped = tc.draw_samples(routes, precip, offsets, stamps, np.random.default_rng(tc.SEED))
    b, _ = tc.draw_samples(routes, precip, offsets, stamps, np.random.default_rng(tc.SEED))
    assert [s["departure_utc"] for s in a] == [s["departure_utc"] for s in b]
    assert len(a) == tc.PER_ROUTE and all(s["route_id"] == 0 for s in a)     # U = 2 route never sampled
    assert all(np.max(s["gt_mm"]) > 0.1 and not np.isnan(s["gt_mm"]).any() for s in a)
    assert skipped >= 1


def test_supported_needs_holm_and_the_right_sign():
    rows = []
    for i in range(60):
        week = f"2026-W{i % 6:02d}"
        for method, err in (("B1", 0.3 + 0.01 * i), ("M2", 0.2 + 0.01 * i), ("H-P", 0.25 + 0.01 * i)):
            rows.append({"sample_id": i, "iso_week": week, "rho": tc.TEST_RHO, "method": method, "abs_err": err})
    t = {r["test"]: r for r in tc.tests_table(rows)}
    assert t["T-2"]["supported"]                  # B1 - M2 > 0
    assert not t["T-1"]["supported"]              # M2 - H-P < 0: significant but the wrong way
