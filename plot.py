#!/usr/bin/env python3
"""Resource landscape for breaking 256-bit ECDLP.

Three plots into render/:
  01  landscape: every result, log-log (Toffoli vs logical qubits)
  02  zoom: log-log cropped to ~10B Toffoli / ~4k qubits, this work labelled
  03  linear: linear axes to 120M Toffoli / 1500 qubits -- the low-Toffoli
      competitive region, where small separations show as true distances
      (shrunken-PZ, at ~910M projected Toffoli, is off-scale here)

Prior work is quoted as published full-ECDLP cost. The point-add circuits
(Babbush, Schrottenloher, this work) are single P += Q costs projected to a
full attack by ec_add_to_ecdlp: windowed scalar multiplication runs 2n/w - 4
windowed additions, each one point-add plus a 3*2^w table lookup, and adds a
w-bit window register. Labels carry these projected (extrapolated) costs.
"""

import math
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

N = 256


def ec_add_to_ecdlp(qubits, toffoli_per_add, w=16):
    """Project one point-add (qubits, Toffoli) to a full 256-bit ECDLP attack."""
    windows = 2 * N / w - 4
    return qubits + w, (toffoli_per_add + 3 * 2 ** w) * windows


# Prior work, as published full-ECDLP logical resources: (qubits, Toffoli).
PRIOR_WORK = {
    "Proos, Zalka '04": (1575, 8.2e9),
    "Roetteler et al. '17": (9 * N + 2 * math.ceil(math.log2(N)) + 10,
                             488 * N ** 3 * math.log2(N) + 4090 * N ** 3),
    "Häner et al. '20": (2125, 2.1e9),
    "Litinski '23": (3000, 2.16e8),
    "Gouzien et al. '23": (2069, 3.6e8),
    "Kim et al. '26": (6470, 5.0e8),
    "Chevignard et al. '26": (1193, 2 ** 38.98),
}

# Point-add operating points, projected to a full attack.
GOOGLE = {
    "low qubits": ec_add_to_ecdlp(1175, 2_700_000),
    "low gates": ec_add_to_ecdlp(1425, 2_100_000),
}
# Schrottenloher Table 1, secp256k1 rows (not the generic any-prime rows).
SCHROTTENLOHER = {
    "low qubits": ec_add_to_ecdlp(1192, 2 ** 21.19),
    "low gates": ec_add_to_ecdlp(1446, 2 ** 20.83),
}
OURS = {
    "low-qubit": ec_add_to_ecdlp(1173, 2_483_634),
    "low-tof": ec_add_to_ecdlp(1416, 2_030_340),
    "jump-lowqubit": ec_add_to_ecdlp(1169, 2_085_499),
    "jump-lowtof": ec_add_to_ecdlp(1412, 1_903_256),
    "shrunken-PZ": ec_add_to_ecdlp(1050, 32_338_076),
}


def _fmt_full(qubits, tof):
    """Label string in the plot's extrapolated full-ECDLP units."""
    mag = f"{tof / 1e9:.2g}B" if tof >= 1e9 else f"{tof / 1e6:.0f}M"
    return f"{round(qubits)}q / {mag}"


# Star labels carry the extrapolated full-ECDLP cost (matching the plotted axes).
OURS_DISPLAY = {name: f"{name}\n{_fmt_full(*vals)}" for name, vals in OURS.items()}

GREY, BLUE, GREEN, ORANGE = "#8a8a8a", "#3a6fb0", "#2e8b57", "#d4540a"

FOOTNOTE = ("This work, Babbush et al., and Schrottenloher target secp256k1; "
            "most prior-work points are general 256-bit ECDLP estimates.")

# Hand-placed offsets (points) so the spread-out prior-work labels clear.
PRIOR_LABEL = {
    "Proos, Zalka '04": (8, 5, "left"),
    "Roetteler et al. '17": (8, 5, "left"),
    "Häner et al. '20": (8, -13, "left"),
    "Litinski '23": (8, 5, "left"),
    "Gouzien et al. '23": (-8, -14, "right"),
    "Kim et al. '26": (8, 5, "left"),
    "Chevignard et al. '26": (-9, 6, "right"),
}

# Leader-line label offsets (points, ha) for this work's stars. The log-zoom
# and linear views have different layouts, so each gets its own placement.
# (dx, dy, ha, leader): leader=True draws a line from the dot to the label.
LOG_STAR_LABEL = {
    "low-tof": (10, 64, "left", True),
    "jump-lowtof": (-34, -34, "right", True),
    "low-qubit": (2, -46, "center", True),
    "jump-lowqubit": (-34, -46, "right", True),
    "shrunken-PZ": (12, 0, "left", True),
}
# Linear view labels the dots directly; only the bumped-away low-tof gets a line.
LINEAR_STAR_LABEL = {
    "low-tof": (0, 48, "center", True),
    "jump-lowtof": (-12, 2, "right", False),
    "low-qubit": (0, -22, "center", False),
    "jump-lowqubit": (0, -22, "center", False),
}


def gate_formatter(x, _):
    for val, label in [(1e12, "1T"), (1e11, "100B"), (1e10, "10B"),
                       (1e9, "1B"), (1e8, "100M"), (1e7, "10M")]:
        if x > 0 and abs(x - val) / val < 0.01:
            return label
    return ""


def render(path, title, *, logscale, xlim, ylim, label_ours, star_offsets=None,
           legend_loc="upper left"):
    fig, ax = plt.subplots(figsize=(11, 7))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    if logscale:
        ax.set_xscale("log")
        ax.set_yscale("log")
    xlo, xhi = xlim
    ylo, yhi = ylim
    ax.set_xlim(xlo, xhi)
    ax.set_ylim(ylo, yhi)
    ax.grid(True, which="both", color="#e8e8e8", linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)
    ax.set_xlabel("Toffoli gates, full 256-bit ECDLP (lower is better)", fontsize=12)
    ax.set_ylabel("Logical qubits (lower is better)", fontsize=12)
    ax.set_title(title, fontsize=13, pad=12)
    if logscale:
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(gate_formatter))
        ax.xaxis.set_major_locator(ticker.LogLocator(base=10, numticks=15))
    else:
        ax.xaxis.set_major_formatter(
            ticker.FuncFormatter(lambda x, _: f"{x / 1e6:g}M" if x > 0 else ""))
        ax.xaxis.set_major_locator(ticker.MultipleLocator(2e7))
    ax.tick_params(axis="both", which="both", labelsize=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    def in_view(t, q):
        return xlo <= t <= xhi and ylo <= q <= yhi

    # Prior work: grey circles, labelled where they fall in view.
    prior_shown = any(in_view(t, q) for q, t in PRIOR_WORK.values())
    ax.scatter([t for _, t in PRIOR_WORK.values()],
               [q for q, _ in PRIOR_WORK.values()],
               s=22, color=GREY, marker="o", zorder=5,
               label="Prior work" if prior_shown else "")
    for name, (q, t) in PRIOR_WORK.items():
        if in_view(t, q):
            dx, dy, ha = PRIOR_LABEL[name]
            ax.annotate(name, (t, q), textcoords="offset points", xytext=(dx, dy),
                        fontsize=9, color="#333333", ha=ha)

    def plot_group(group, color, marker, label, size):
        ax.scatter([t for _, t in group.values()], [q for q, _ in group.values()],
                   s=size, color=color, marker=marker, zorder=6, label=label,
                   edgecolors="white", linewidths=0.5)

    plot_group(GOOGLE, BLUE, "s", "Babbush et al. '26 (Google)", 30)
    plot_group(SCHROTTENLOHER, GREEN, "D", "Schrottenloher '26", 26)
    plot_group(OURS, ORANGE, "*", "This work", 90)

    if label_ours:
        for name, (q, t) in OURS.items():
            if not in_view(t, q):
                continue
            dx, dy, ha, lead = star_offsets[name]
            arrow = dict(arrowstyle="-", color=ORANGE, lw=0.6) if lead else None
            ax.annotate(OURS_DISPLAY[name], (t, q), textcoords="offset points",
                        xytext=(dx, dy), ha=ha, va="center", fontsize=8.5,
                        color=ORANGE, arrowprops=arrow)

    ax.legend(loc=legend_loc, fontsize=10, framealpha=0.95,
              markerscale=1.0, handletextpad=0.6)
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.text(0.5, 0.012, FOOTNOTE, ha="center", fontsize=8, color="#666666")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")


def main():
    out = Path("render")
    out.mkdir(exist_ok=True)
    base = "Logical resources to break secp256k1 ECDLP"
    render(out / "01_landscape.png", base,
           logscale=True, xlim=(2e7, 8e11), ylim=(950, 9e3), label_ours=False)
    render(out / "02_zoom.png", base + "  --  competitive region (log)",
           logscale=True, xlim=(2e7, 1e10), ylim=(950, 4e3), label_ours=True,
           star_offsets=LOG_STAR_LABEL)
    render(out / "03_linear.png", base + "  --  competitive region (linear)",
           logscale=False, xlim=(4e7, 1.2e8), ylim=(1.1e3, 1.5e3), label_ours=True,
           star_offsets=LINEAR_STAR_LABEL, legend_loc="upper right")


if __name__ == "__main__":
    main()
