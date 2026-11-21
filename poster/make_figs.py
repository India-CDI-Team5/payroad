"""Poster figures (SVG) drawn at their printed size, from results/**/*.csv|json only.

Each figure is made at the exact width it takes on the 788 x 1091 mm poster, so a font size in points here is the
printed size (7 mm ~ 20 pt; the session guide asks for 7-10 mm body text). Text stays as SVG text
(svg.fonttype = none) and is set in Noto Sans KR by the browser, the same face as the poster body.

    python poster/make_figs.py        # -> poster/figs/*.svg
"""
import csv
import datetime
import glob
import gzip
import json
import os
import sys
from collections import Counter

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
RES = os.path.join(ROOT, "results")
OUT = os.path.join(HERE, "figs")
sys.path.insert(0, os.path.join(ROOT, "scripts", "figures"))
import f11_schematic as sch  # noqa: E402

MM = 1 / 25.4
W, W_HALF = 228, 112          # printed widths (mm): one poster box, half a box
INK, MUTED, GRID = "#16202a", "#4a5562", "#d5dbe1"
# Placement methods: one fixed colour each, also used in the HTML legend chips (validated: dataviz validator,
# CVD worst adjacent 6.5 -> every bar/line is also direct-labelled).
C = {"B1": "#E69F00", "M2": "#0072B2", "Mid": "#C2408F", "B2": "#56B4E9"}
SERIES = ["#16202a", "#E69F00", "#56B4E9"]       # non-method series (offer levels, detectors), fixed order

plt.rcParams.update({
    "font.family": "Noto Sans KR",
    "svg.fonttype": "none",
    "font.size": 21,
    "axes.labelsize": 22,
    "axes.labelpad": 9,
    "xtick.labelsize": 20,
    "ytick.labelsize": 20,
    "axes.edgecolor": MUTED,
    "axes.labelcolor": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "text.color": INK,
    "axes.linewidth": 1.4,
    "xtick.major.width": 1.4,
    "ytick.major.width": 1.4,
    "xtick.major.size": 6,
    "ytick.major.size": 6,
    "lines.linewidth": 3.2,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "svg.hashsalt": "payroad-poster",
})


def read_csv(*parts):
    path = os.path.join(RES, *parts)
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fig_mm(w, h):
    return plt.figure(figsize=(w * MM, h * MM))


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    fig.savefig(path, format="svg", metadata={"Date": None, "Creator": None}, transparent=True)
    plt.close(fig)
    print(path)


def ygrid(ax):
    ax.yaxis.grid(True, color=GRID, linewidth=1.2)
    ax.set_axisbelow(True)


# ---------------------------------------------------------------- problem: points vs cells (made-up route, a drawing)
def concept():
    import numpy as np
    route = np.array([(2, 60), (24, 52), (40, 36), (58, 30), (70, 16), (86, 6)], float)
    seg = np.r_[0, np.cumsum(np.hypot(*np.diff(route, axis=0).T))]
    t = np.linspace(0, seg[-1], 2000)
    d = np.c_[np.interp(t, seg, route[:, 0]), np.interp(t, seg, route[:, 1])]
    cs, cols, rows_ = 22, 4, 3

    def cell(p):
        return int(p[0] // cs), int(p[1] // cs)

    crossed = []
    for p in d:
        if cell(p) not in crossed:
            crossed.append(cell(p))
    pts = [d[i] for i in np.linspace(0, len(d) - 1, 7).astype(int)]

    fig = fig_mm(W, 112)
    for j, title in enumerate(("이전 방식: 균등 간격 지점", "셀 단위 조회: 지나는 셀마다 1회")):
        ax = fig.add_axes([0.02 + j * 0.5, 0.01, 0.46, 0.72])
        ax.set_xlim(-1, cols * cs + 1)
        ax.set_ylim(rows_ * cs + 1, -1)
        ax.set_aspect("equal")
        ax.axis("off")
        for cx in range(cols):
            for cy in range(rows_):
                hit = (cx, cy) in crossed
                face = "#f3f5f7"
                if j == 1 and hit:
                    face = "#cfe3f1"
                if j == 0 and hit and (cx, cy) not in {cell(p) for p in pts}:
                    face = "#fbe3d6"
                ax.add_patch(Rectangle((cx * cs, cy * cs), cs, cs, facecolor=face, edgecolor="#b8c1ca", lw=1.4))
        ax.plot(d[:, 0], d[:, 1], color=INK, lw=3.4, solid_capstyle="round", zorder=2)
        if j == 0:
            seen = set()
            for p in pts:
                dup = cell(p) in seen
                seen.add(cell(p))
                ax.plot(*p, marker="X" if dup else "o", ms=17, color="#B33A00" if dup else C["B1"],
                        markeredgecolor="white", mew=1.6, zorder=3)
            missed = [c for c in crossed if c not in {cell(p) for p in pts}]
            for cx, cy in missed:
                ax.text(cx * cs + cs / 2, cy * cs + 3.2, "놓침", ha="center", va="top", fontsize=19, color="#B33A00",
                        fontweight="bold")
            note = f"호출 {len(pts)}회 · 중복 {len(pts) - len(set(cell(p) for p in pts))} · 놓친 셀 {len(missed)}"
        else:
            for cx, cy in crossed:
                p = min(d, key=lambda q: abs(q[0] - (cx + 0.5) * cs) + abs(q[1] - (cy + 0.5) * cs)
                        if cell(q) == (cx, cy) else 1e9)
                ax.plot(*p, marker="o", ms=17, color=C["M2"], markeredgecolor="white", mew=1.6, zorder=3)
            note = f"호출 {len(crossed)}회 · 빠진 셀 없음"
        fig.text(0.02 + j * 0.5, 0.985, title, fontsize=20, fontweight="bold", va="top")
        fig.text(0.02 + j * 0.5, 0.88, note, fontsize=20, color=MUTED, va="top")
    save(fig, "concept.svg")


# ---------------------------------------------------------------- RQ1-2: error vs budget (paper Fig. 3)
def curve():
    rows = [r for r in read_csv("model_a", "F1_curve.csv") if r["subset"] == "MAIN"]
    fig = fig_mm(W, 182)
    ax = fig.add_axes([0.15, 0.2, 0.62, 0.74])
    end = {}
    for m, mk in (("B1", "o"), ("B2", "^"), ("M2", "s")):
        pts = sorted((float(r["rho"]), float(r["mae"]), float(r["ci_lo"]), float(r["ci_hi"]))
                     for r in rows if r["method"] == m)
        x = [p[0] for p in pts]
        y = [p[1] for p in pts]
        ax.errorbar(x, y, yerr=[[p[1] - p[2] for p in pts], [p[3] - p[1] for p in pts]], color=C[m], marker=mk,
                    markersize=11, capsize=5, elinewidth=1.8, linewidth=4 if m == "M2" else 2.6,
                    markeredgecolor="white", markeredgewidth=1.5, zorder=4 if m == "M2" else 3)
        end[m] = dict(zip(x, y))
    # direct labels at the right edge, nudged apart (all three meet at 0 for k/U = 1)
    for m, ly in (("B1", 0.112), ("B2", 0.085), ("M2", 0.040)):
        ax.annotate(m, xy=(0.75, end[m][0.75]), xytext=(1.08, ly), textcoords="data", color=INK, fontsize=21,
                    fontweight="bold", va="center", annotation_clip=False,
                    arrowprops=dict(arrowstyle="-", color=C[m], lw=2))
    b, m2 = end["B1"][0.5], end["M2"][0.5]
    ax.annotate("", xy=(0.5, m2 + 0.004), xytext=(0.5, b - 0.004),
                arrowprops=dict(arrowstyle="-|>", color=INK, lw=2.2, mutation_scale=22))
    ax.text(0.462, (b + m2) / 2, f"−{(1 - m2 / b) * 100:.0f}%", fontsize=24, fontweight="bold", va="center",
            ha="right")
    ax.set_xlim(0.2, 1.04)
    ax.set_ylim(0, 0.215)
    ax.set_xticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticks([0, 0.05, 0.10, 0.15, 0.20])
    ax.set_xlabel("조회 예산 비율 k/U")
    ax.set_ylabel("경로 평균 강수 MAE (mm/h)")
    ygrid(ax)
    save(fig, "curve.svg")


# ---------------------------------------------------------------- RQ3: which cells each rule picks (paper Fig. 4)
def schematic():
    cp, k = sch.CELL_POINTS, sch.K
    cells = sch.cell_of_points(cp)
    P = len(cells)
    starts = [sum(cp[:c]) for c in range(len(cp))]
    pts = sch.b1_points(P, k)
    rows = [("B1 (균등 지점)", "B1", None), ("B2 · M2", "M2", sch.end_anchored(cp, k)),
            ("Mid (구간 중앙)", "Mid", sch.segment_centre(cp, k))]
    fig = fig_mm(W, 92)
    ax = fig.add_axes([0.27, 0.2, 0.71, 0.62])
    n = len(rows)
    for c, (s0, w) in enumerate(zip(starts, cp)):
        ax.add_patch(Rectangle((s0, -0.5), w, n, facecolor="#e3e7eb" if c % 2 == 0 else "#f3f5f7", lw=0, zorder=0))
        ax.text(s0 + w / 2, n - 0.25, str(w), ha="center", va="bottom", fontsize=20, color=MUTED)
    ax.text(-0.6, n - 0.25, "셀당 지점", ha="right", va="bottom", fontsize=20, color=MUTED)
    for i, (label, key, chosen) in enumerate(rows):
        y = n - 1 - i
        if chosen is None:
            seen = set()
            for p in pts:
                dup = cells[p] in seen
                seen.add(cells[p])
                ax.plot(p + 0.5, y, marker="X" if dup else "o", color="#B33A00" if dup else C[key], markersize=17,
                        markeredgecolor="white", markeredgewidth=1.5, ls="none", zorder=3)
        else:
            for c in chosen:
                ax.add_patch(Rectangle((starts[c] + 0.15, y - 0.3), cp[c] - 0.3, 0.6, facecolor=C[key], lw=0,
                                       zorder=3))
    ax.set_yticks(range(n))
    ax.set_yticklabels([r[0] for r in reversed(rows)], fontsize=21, color=INK)
    ax.set_xlim(0, P)
    ax.set_ylim(-0.55, n + 0.25)
    ax.set_xticks([0, P])
    ax.set_xticklabels(["출발", "도착"], fontsize=20)
    for lab, ha in zip(ax.get_xticklabels(), ("left", "right")):
        lab.set_ha(ha)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    save(fig, "schematic.svg")


# ---------------------------------------------------------------- realtime: what was collected
def realtime_timeline():
    start = datetime.datetime(2026, 10, 18, tzinfo=datetime.timezone.utc)
    end = datetime.datetime(2026, 11, 18, tzinfo=datetime.timezone.utc)
    ist = datetime.timedelta(hours=5, minutes=30)
    snaps = Counter()
    for path in sorted(glob.glob(os.path.join(ROOT, "PartB", "data", "realtime", "*.json"))):
        with open(path, encoding="utf-8") as f:
            t = datetime.datetime.strptime(json.load(f)["fetched_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=datetime.timezone.utc)
        if start <= t < end and 6 <= (t + ist).hour <= 23:       # the pre-registered window (realtime_check.py)
            snaps[(t + ist).date()] += 1
    wet = Counter(r["iso_week"] for r in read_csv("realtime_check", "per_sample.csv.gz")
                  if r["method"] == "B1" and r["rho"] == "0.5")
    days = [(start + ist).date() + datetime.timedelta(days=i) for i in range(31)]
    s = [snaps.get(d, 0) for d in days]
    w = [wet.get(d.isoformat(), 0) for d in days]
    print(f"timeline: {sum(s)} snapshots, {sum(w)} wet samples on {sum(1 for v in w if v)} days")

    fig = fig_mm(W, 130)
    a1 = fig.add_axes([0.11, 0.6, 0.86, 0.24])
    a2 = fig.add_axes([0.11, 0.15, 0.86, 0.3], sharex=a1)
    x = range(len(days))
    a1.bar(x, s, width=0.78, color="#9aa5b1", lw=0)
    a2.bar(x, w, width=0.78, color=C["Mid"], lw=0)
    a1.set_ylim(0, 19)
    a1.set_yticks([0, 18])
    a2.set_ylim(0, 60)
    a2.set_yticks([0, 30, 60])
    a1.set_title(f"수집 스냅숏 / 일  (합계 {sum(s)}, IST 06~24시)", loc="left", fontsize=21, color=INK, pad=12)
    a2.set_title(f"우천 표본 / 일  (합계 {sum(w)}, {sum(1 for v in w if v)}일)", loc="left", fontsize=21, color=INK,
                 pad=12)
    plt.setp(a1.get_xticklabels(), visible=False)
    ticks = [i for i, d in enumerate(days) if d.day in (18, 25, 1, 8, 15)]
    a2.set_xticks(ticks)
    a2.set_xticklabels([f"{d.month}/{d.day}" for d in (days[i] for i in ticks)])
    a2.set_xlim(-0.7, len(days) - 0.3)
    for a in (a1, a2):
        ygrid(a)
    save(fig, "realtime_timeline.svg")


# ---------------------------------------------------------------- same pre-registered comparison in three data sets
def three_conditions():
    sets = [("과거 분석 자료\n(새 기간, n = 1,512)", ("temporal", "mae.csv")),
            ("1일 전 예보\n(n = 1,512)", ("forecast_check", "mae.csv")),
            ("실시간 예보 ★\n(전향적, n = 584)", ("realtime_check", "mae.csv"))]
    methods = [("B1", "B1"), ("M2", "M2"), ("Mid", "H-P")]
    fig = fig_mm(W, 178)
    ax = fig.add_axes([0.13, 0.25, 0.85, 0.68])
    bw = 0.26
    for g, (label, parts) in enumerate(sets):
        rows = {r["method"]: r for r in read_csv(*parts) if r["rho"] == "0.5"}
        b1 = float(rows["B1"]["mae"])
        for i, (name, key) in enumerate(methods):
            r = rows[key]
            v, lo, hi = float(r["mae"]), float(r["ci_lo"]), float(r["ci_hi"])
            xx = g + (i - 1) * (bw + 0.02)
            ax.bar(xx, v, width=bw, color=C[name], lw=0, zorder=2)
            ax.errorbar(xx, v, yerr=[[v - lo], [hi - v]], color=INK, capsize=4, elinewidth=1.6, zorder=3)
            ax.text(xx, hi + 0.002, f"{v:.3f}".lstrip("0"), ha="center", va="bottom", fontsize=19, color=INK)
            ax.text(xx, 0.003, name, ha="center", va="bottom", fontsize=19, color="white", fontweight="bold")
        mid = float(rows["H-P"]["mae"])
        top = float(rows["H-P"]["ci_hi"]) + 0.0115   # stop the dashed leader just above the Mid value label
        ax.annotate(f"B1 대비\n−{(1 - mid / b1) * 100:.0f}%", xy=(g + 0.28, top), xytext=(g + 0.28, 0.105),
                    ha="center", va="bottom", fontsize=21, fontweight="bold", color=C["Mid"],
                    arrowprops=dict(arrowstyle="-", color=C["Mid"], lw=1.6, ls=(0, (3, 2))))
    ax.set_xticks(range(len(sets)))
    ax.set_xticklabels([s[0] for s in sets], fontsize=19, color=INK)
    ax.tick_params(axis="x", length=0)
    ax.set_ylim(0, 0.135)
    ax.set_yticks([0, 0.05, 0.10])
    ax.set_xlim(-0.5, len(sets) - 0.5)
    ax.set_ylabel("MAE (mm/h), k/U = 0.5")
    ygrid(ax)
    save(fig, "three_conditions.svg")


# ---------------------------------------------------------------- RQ4: shared GP
def shared_gp():
    with open(os.path.join(RES, "shared_gp_city", "summary.json"), encoding="utf-8") as f:
        runs = json.load(f)["runs"]
    rates = [5, 10, 20, 50]
    fig = fig_mm(W, 108)
    ax = fig.add_axes([0.14, 0.24, 0.66, 0.68])
    x = list(range(len(rates)))
    ax.axvspan(1.6, 2.4, color="#eef1f4", zorder=0)
    ax.text(2, 0.004, "검정 조건", ha="center", va="bottom", fontsize=20, color=MUTED)
    labels = {"G": "G 공유 GP", "N": "N 이웃 규칙", "P": "P 고정 예산"}
    nudge = {"G": -0.007, "N": 0.005, "P": 0}            # N and G end 0.006 apart; keep their labels from touching
    for key, color, mk, lw in (("P", C["B1"], "s", 2.6), ("N", C["B2"], "^", 2.6), ("G", INK, "o", 4.2)):
        y = [runs[f"N{n}_f0.5"][key]["mae"] for n in rates]
        ax.plot(x, y, color=color, marker=mk, markersize=12, lw=lw, markeredgecolor="white", markeredgewidth=1.5,
                zorder=3)
        ax.text(3.15, y[-1] + nudge[key], labels[key], va="center", fontsize=20, color=INK, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels([str(n) for n in rates])
    ax.set_xlim(-0.25, 3.05)
    ax.set_ylim(0, 0.11)
    ax.set_yticks([0, 0.05, 0.10])
    ax.set_xlabel("10분당 요청 수 (같은 호출 수로 맞춤)")
    ax.set_ylabel("MAE (mm/h)")
    ygrid(ax)
    save(fig, "shared_gp.svg")


def stream_calls():
    with open(os.path.join(RES, "shared_gp_city", "stream_calls.json"), encoding="utf-8") as f:
        d = json.load(f)
    items = [("이전 방식 (지점)", d["previous"], "#9aa5b1"), ("셀마다 1회", d["cell"], "#7d8894"),
             ("셀 + 캐시", d["F"], "#5d6874"), ("공유 GP", d["G"], INK)]
    fig = fig_mm(W, 74)
    ax = fig.add_axes([0.25, 0.05, 0.73, 0.9])
    for i, (name, v, color) in enumerate(items):
        y = len(items) - 1 - i
        ax.barh(y, v["calls"], height=0.62, color=color, lw=0)
        ax.text(v["calls"] + 0.15, y, f"{v['calls']:.2f}회 (MAE {v['mae']:.3f})", va="center", fontsize=20,
                color=INK, fontweight="bold" if name == "공유 GP" else "normal")
    ax.set_yticks(range(len(items)))
    ax.set_yticklabels([it[0] for it in reversed(items)], fontsize=20, color=INK)
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, 11.2)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_visible(False)
    save(fig, "stream_calls.svg")


# ---------------------------------------------------------------- mechanism and collusion
def markup():
    levels = [("0.80", ("sim",)), ("0.90", ("posthoc", "sim", "ob090")), ("1.00", ("posthoc", "sim", "ob100"))]
    fig = fig_mm(W_HALF, 120)
    ax = fig.add_axes([0.3, 0.2, 0.47, 0.43])
    for i, (lv, parts) in enumerate(levels):
        pts = sorted((int(r["n"]), float(r["markup_median"])) for r in read_csv(*parts, "E1_summary.csv")
                     if r["config"] == "C1")
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=SERIES[i], lw=3, marker="o", markersize=8,
                markeredgecolor="white", markeredgewidth=1.2)
        ax.text(10.6, pts[-1][1], lv, va="center", fontsize=20, color=INK, fontweight="bold")
    ax.text(10.6, 1.085, "첫 오퍼", fontsize=20, color=MUTED, va="center")
    ax.set_xticks([1, 4, 7, 10])
    ax.set_ylim(0.7, 1.05)
    ax.set_yticks([0.7, 0.8, 0.9, 1.0])
    ax.set_xlabel("호가 기사 수")
    ax.set_ylabel("마크업 중앙값", labelpad=22)
    ygrid(ax)
    save(fig, "markup.svg")


def collusion():
    rows = read_csv("collusion", "F9_S4.csv")
    fig = fig_mm(W_HALF, 120)
    ax = fig.add_axes([0.24, 0.2, 0.72, 0.43])
    names = {"model": "학습 모델", "B-rule": "단일 규칙", "B-price": "가격 기준"}
    for i, key in enumerate(("model", "B-price", "B-rule")):
        pts = sorted((float(r["ring_share"]), float(r["pr_auc"])) for r in rows if r["method"] == key)
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=SERIES[i], lw=3.4 if key == "model" else 2.6,
                ls="-" if key == "model" else (0, (4, 2)), marker="o", markersize=8, markeredgecolor="white",
                markeredgewidth=1.2, label=names[key])
    ax.legend(loc="lower left", bbox_to_anchor=(-0.05, 1.03), frameon=False, fontsize=20, handlelength=1.8,
              borderaxespad=0, labelspacing=0.25)
    ax.set_xticks([0.1, 0.5, 0.9])
    ax.set_ylim(0, 1.05)
    ax.set_yticks([0, 0.5, 1.0])
    ax.set_xlabel("담합 기사 비율")
    ax.set_ylabel("PR-AUC (S4)", labelpad=10)
    ygrid(ax)
    save(fig, "collusion.svg")


if __name__ == "__main__":
    import logging
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)   # VF file: weight lookup only
    concept()
    curve()
    schematic()
    realtime_timeline()
    three_conditions()
    shared_gp()
    stream_calls()
    markup()
    collusion()
