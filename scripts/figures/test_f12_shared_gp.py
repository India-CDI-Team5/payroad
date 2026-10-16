import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import f12_shared_gp  # noqa: E402


def test_draws_from_summary(tmp_path):
    runs = {f"N{n}_f0.5": {m: {"mae": 0.01 * (i + 1)} for i, m in enumerate("GNP")} for n in f12_shared_gp.RATES}
    src = tmp_path / "summary.json"
    src.write_text(json.dumps({"runs": runs}), encoding="utf-8")
    out = f12_shared_gp.make(str(src), str(tmp_path / "f.png"))
    assert os.path.getsize(out) > 0
    assert f12_shared_gp.series(runs, "G") == [0.01] * 4
