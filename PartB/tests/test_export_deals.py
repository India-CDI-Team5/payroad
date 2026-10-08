import csv

import pytest

from training import export_deals as ed
from weather.metrics import beta as metrics_beta

FROZEN = {"baseFee": 0, "perKm": 18, "betaCoef": 0.15, "betaCap": 0.5, "uncertaintyWeight": 0.5}


@pytest.mark.parametrize("r,s", [(0.0, 0.0), (1.0, 0.0), (4 / 3, 0.0), (10.0, 0.0), (2.0, 1.0), (0.5, 3.0)])
def test_beta_matches_the_metrics_formula_at_the_frozen_constants(r, s):
    assert ed.beta(r, s, FROZEN) == pytest.approx(metrics_beta(r, s))


def test_write_uses_four_decimals_and_fixed_columns(tmp_path):
    row = {"deal_id": "S7", "sample_id": 7, "distance_km": 12.345678, "origin_lat": 12.97, "origin_lng": 77.5946,
           "base_dry": 222.222204, "m_true": 0.0, "beta": 1.0, "base_price": 222.22, "wet": 0}
    path = tmp_path / "deals.csv"
    ed.write([row], str(path))
    lines = path.read_bytes().decode("utf-8").split("\n")
    assert lines[0] == ",".join(ed.COLUMNS)
    assert lines[1] == "S7,7,12.3457,12.9700,77.5946,222.2222,0.0000,1.0000,222.2200,0"
    assert lines[2] == ""                                   # LF only, one trailing newline


def test_written_file_matches_the_spec():
    try:
        with open(ed.OUT_PATH, encoding="utf-8", newline="") as f:
            got = list(csv.DictReader(f))
    except FileNotFoundError:
        pytest.skip("data/experiment/deals.csv not written yet")
    ids = [int(r["sample_id"]) for r in got]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    for r in got:
        assert r["deal_id"] == f"S{r['sample_id']}"
        base_dry, b, price = float(r["base_dry"]), float(r["beta"]), float(r["base_price"])
        assert 1.0 <= b <= 1.5
        # base_price comes from the unrounded beta; the file's beta is rounded to 4 decimals (±5e-5).
        assert abs(price - base_dry * b) <= 0.005 + base_dry * 5e-5 + 1e-9
        assert (float(r["m_true"]) > 0) or r["wet"] == "0"
