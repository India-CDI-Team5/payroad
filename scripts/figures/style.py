"""Shared look and helpers for the paper's figures and tables (card E1).

Figure scripts only draw values read from results/**/*.csv; they compute no statistics.
"""
import csv
import hashlib
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RC = {
    "font.family": "DejaVu Sans",
    "font.size": 8,
    "axes.labelsize": 8,
    "legend.fontsize": 7,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "lines.linewidth": 1.2,
    "savefig.dpi": 600,
    "savefig.bbox": "tight",
}

SINGLE = (3.35, 2.3)        # one column, 8.5 cm
SINGLE_TALL = (3.35, 3.0)
DOUBLE = (6.9, 2.6)

METHODS = ["B0", "B1", "B1-L", "B2", "B2-L", "M1", "M2"]
# Fixed per method; line style and marker keep them apart in black-and-white print.
METHOD_STYLE = {
    "B0": {"color": "#999999", "linestyle": ":", "marker": "x"},
    "B1": {"color": "#E69F00", "linestyle": "-", "marker": "o"},
    "B1-L": {"color": "#D55E00", "linestyle": "--", "marker": "s"},
    "B2": {"color": "#56B4E9", "linestyle": "-", "marker": "^"},
    "B2-L": {"color": "#0072B2", "linestyle": "--", "marker": "v"},
    "M1": {"color": "#009E73", "linestyle": "-", "marker": "D", "linewidth": 1.8},
    "M2": {"color": "#CC79A7", "linestyle": "-", "marker": "P"},
}
CONFIGS = ["C1", "C2", "C3", "C4"]
CONFIG_COLORS = {"C1": "#000000", "C2": "#E69F00", "C3": "#56B4E9", "C4": "#CC79A7"}
# Series that are not methods or configs (collusion strategies and detectors), in a fixed order.
SERIES_STYLE = [
    {"color": "#000000", "linestyle": "-", "marker": "o"},
    {"color": "#E69F00", "linestyle": "--", "marker": "s"},
    {"color": "#56B4E9", "linestyle": ":", "marker": "^"},
    {"color": "#CC79A7", "linestyle": "-.", "marker": "D"},
]
MARKER_SIZE = 3


def apply():
    plt.rcParams.update(RC)


def read_csv(path):
    """Rows as dicts of strings. A missing file raises FileNotFoundError, which make_all reports as skipped."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(v):
    return float(v) if v not in ("", None) else None


def save(fig, path):
    """PNG without the Software stamp, so the same inputs give byte-identical files."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.savefig(path, metadata={"Software": None})
    plt.close(fig)
    return path


def errorbar(ax, x, y, lo, hi, label, style):
    """A percentile bootstrap CI can miss its point estimate when scores tie (F9_S4 at ring share 0.1);
    the bar then ends at the point instead of going negative. The CSV keeps the real interval."""
    ax.errorbar(x, y, yerr=[[max(a - b, 0.0) for a, b in zip(y, lo)], [max(b - a, 0.0) for a, b in zip(y, hi)]],
                label=label, capsize=2, markersize=MARKER_SIZE, **style)


def fmt(v, digits=3):
    """Table cell: 3 decimals, blank or missing as an en dash."""
    if v in ("", None):
        return "–"
    return f"{float(v):.{digits}f}"


def fmt_int(v):
    return "–" if v in ("", None) else str(int(float(v)))


def fmt_ci(v, lo, hi):
    return f"{fmt(v)} [{fmt(lo)}, {fmt(hi)}]"


def write_table(out_dir, table_id, header, rows, title=None, notes=()):
    """<ID>.md (markdown table) and <ID>_table.csv with the same cells."""
    os.makedirs(out_dir, exist_ok=True)
    md = [f"### {table_id}" + (f". {title}" if title else ""), "",
          "| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    md += ["| " + " | ".join(r) + " |" for r in rows]
    if notes:
        md += [""] + list(notes)
    md_path = os.path.join(out_dir, f"{table_id}.md")
    with open(md_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md) + "\n")
    csv_path = os.path.join(out_dir, f"{table_id}_table.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    return [md_path, csv_path]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()
