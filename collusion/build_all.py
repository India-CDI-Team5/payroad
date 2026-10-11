"""Training features for S1~S3 (card D2): python -m collusion.build_all, from the repository root.

Reads results/sim/raw/collusion/{S1,S2,S3}/ and writes results/collusion/features_train.npz with
keys, X, y, strategy and ring_share. S4 and S5 are never read here.
"""

from __future__ import annotations

import os
import time

import numpy as np

from collusion.dataset import build_dataset
from collusion.features import FEATURES

RAW = os.path.join("results", "sim", "raw", "collusion")
OUT = os.path.join("results", "collusion", "features_train.npz")
TRAIN = ("S1", "S2", "S3")


def main() -> None:
    t0 = time.perf_counter()
    keys, X, y, strategy, ring_share = build_dataset([os.path.join(RAW, s) for s in TRAIN])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    np.savez_compressed(OUT, keys=keys, X=X, y=y, strategy=strategy, ring_share=ring_share)
    runs = len(set(keys[:, 0]))
    print(f"rows={len(y)} runs={runs} features={X.shape[1]} (expected {len(FEATURES)}) "
          f"positives={int(y.sum())} share={y.mean():.4f} size_bytes={os.path.getsize(OUT)} "
          f"seconds={time.perf_counter() - t0:.1f}")
    for s in TRAIN:
        m = strategy == s
        print(f"  {s}: rows={int(m.sum())} positives={int(y[m].sum())} share={y[m].mean():.4f}")


if __name__ == "__main__":
    main()
