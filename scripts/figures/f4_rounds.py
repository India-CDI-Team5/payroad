"""F4: negotiation length and how deals end (results/sim/E2_rounds.csv, E2_end.csv)."""
import os

import matplotlib.pyplot as plt

import style

ROUNDS_CONFIG = "C1"
ENDS = [("matched", "Matched", "#009E73", ""), ("ttl", "TTL", "#E69F00", "///"),
        ("round_limit", "Round limit", "#999999", "...")]


def make(results_dir, out_dir):
    style.apply()
    d = os.path.join(results_dir, "sim")
    rounds = style.read_csv(os.path.join(d, "E2_rounds.csv"))
    ends = style.read_csv(os.path.join(d, "E2_end.csv"))

    fig, (a, b) = plt.subplots(1, 2, figsize=style.SINGLE)
    pts = sorted((int(r["round_count"]), float(r["share"])) for r in rounds if r["config"] == ROUNDS_CONFIG)
    a.bar([p[0] for p in pts], [p[1] for p in pts], color=style.CONFIG_COLORS[ROUNDS_CONFIG], width=0.8)
    a.set_xlabel("Rounds")
    a.set_ylabel("Share of deals")
    a.set_title(f"(a) {ROUNDS_CONFIG}", fontsize=8)

    by_config = {r["config"]: r for r in ends}
    configs = [c for c in style.CONFIGS if c in by_config]
    bottom = [0.0] * len(configs)
    for col, label, color, hatch in ENDS:
        h = [float(by_config[c][col]) for c in configs]
        b.bar(configs, h, bottom=bottom, color=color, hatch=hatch, edgecolor="white", linewidth=0.3, label=label)
        bottom = [x + y for x, y in zip(bottom, h)]
    b.set_ylabel("Share of deals")
    b.set_title("(b)", fontsize=8)
    fig.tight_layout()
    fig.legend(*b.get_legend_handles_labels(), loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3, frameon=False,
               fontsize=6)
    return [style.save(fig, os.path.join(out_dir, "F4_rounds.png"))]
