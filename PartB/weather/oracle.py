"""Call oracle of ml-design v5 §1.2: what each query reveals and what it costs.

A cell query reveals every route point in that cell (Open-Meteo returns the whole cell series for one
coordinate); a point query reveals one point and costs one call even if its cell was already asked.
"""
import numpy as np


class RouteOracle:
    def __init__(self, cell, y):
        self.cell = np.asarray(cell)
        self.y = np.asarray(y, dtype=np.float64)
        _, first = np.unique(self.cell, return_index=True)
        self.order = [self.cell[i].item() for i in sorted(first)]   # cells in order of first appearance
        self.U = len(self.order)

    def points_of(self, c):
        return np.nonzero(self.cell == c)[0]

    def reveal_cells(self, cells):
        distinct = set(cells)
        idx = np.nonzero(np.isin(self.cell, list(distinct)))[0]
        return idx, self.y[idx], len(distinct)

    def reveal_points(self, idx):
        uniq = np.unique(np.asarray(idx, dtype=int))
        return uniq, self.y[uniq], len(idx)

    def duplicate_rate(self, idx):
        idx = np.asarray(idx, dtype=int)
        return 1 - len(set(self.cell[idx].tolist())) / len(idx)
