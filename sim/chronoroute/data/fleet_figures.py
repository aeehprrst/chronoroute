"""
fleet_figures.py
----------------
The figures of `cr fleet report` (master plan P2-H): what the report's numbers
look like. Four PNG files, each labelled REAL / DERIVED in its title:

  fig_shells.png        inclination histogram (0.1 deg bins, REAL elements) and
                        the mean-element altitude of every satellite, shell
                        members versus satellites in transit (DERIVED shells)
  fig_planes.png        one panel per broadband shell: satellites per plane
                        against the plane's node (RAAN) (DERIVED planes)
  fig_six_digit_ids.png satellites with a 6-digit NORAD id per shell (REAL ids)
  fig_gp_vs_supgp.png   distance between the GP and SupGP predictions of each
                        satellite at one instant, as a cumulative curve
                        (DERIVED: a disagreement between sources, not an error)

Everything is drawn from the report's JSON documents (plus the GP-SupGP
distances), so the figures show exactly the numbers the JSON holds. The PNGs
are deterministic: fixed size and DPI, no time stamp or software tag in the
file (same input, same bytes, for the same matplotlib version).

Style: one data colour (blue) plus a neutral grey for "in transit", thin
marks, light grid, the counts named in the titles; no legend for a single
series.
"""

from pathlib import Path

import numpy as np

BLUE = "#2a78d6"          # categorical slot 1 (dataviz reference palette, light surface)
GREY = "#9a9893"          # neutral: satellites outside every shell
INK = "#0b0b0b"
INK_2 = "#52514e"
SURFACE = "#fcfcfb"
DPI = 110
FILES = ("fig_shells.png", "fig_planes.png", "fig_six_digit_ids.png", "fig_gp_vs_supgp.png")


def _plt():
    import matplotlib
    matplotlib.use("Agg")                 # files only, never a window
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": INK_2, "axes.labelcolor": INK, "xtick.color": INK_2, "ytick.color": INK_2,
        "text.color": INK, "axes.grid": True, "grid.color": "#e4e3df", "grid.linewidth": 0.6,
        "axes.spines.top": False, "axes.spines.right": False, "font.size": 9,
        "svg.hashsalt": "chronoroute",
    })
    return plt


def _save(fig, path):
    # no "Software" tag and no date: byte-identical output for identical input
    fig.savefig(path, dpi=DPI, metadata={"Software": None})


def write_figures(out_dir, report, planes_doc, gp_distances_km=None):
    """Write the four PNGs into out_dir; returns their paths (fig_gp_vs_supgp only with distances)."""
    plt = _plt()
    out_dir = Path(out_dir)
    paths = []
    snap = report["snapshot"]["snapshot_id"]
    when = report["reference_utc"]

    # ---- shells: inclination histogram + altitude of every satellite
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 3.8))
    hist = np.array(report["inclination_histogram_0p1deg"], dtype=float).reshape(-1, 2)
    # 0.1 deg bins on a 60 deg axis are thinner than a pixel: draw each bin as a 2 px stem
    a1.vlines(hist[:, 0], 0.8, hist[:, 1], color=BLUE, linewidth=2)
    a1.set_yscale("log")
    a1.set_ylim(0.8, None)
    for inc, n in sorted(map(tuple, hist), key=lambda r: -r[1])[:5]:
        a1.annotate(f"{inc:g} deg", (inc, n), textcoords="offset points", xytext=(4, -2), fontsize=7.5,
                    color=INK_2)
    a1.set_xlabel("inclination (deg, 0.1 deg bins)")
    a1.set_ylabel("satellites (log scale)")
    a1.set_title(f"Inclinations [REAL elements], {report['counts']['kept']:,} satellites", fontsize=9)
    sats = planes_doc["satellites"]
    alt_in = np.array([s["altitude_km"] for s in sats if s["shell_id"] is not None])
    alt_out = np.array([s["altitude_km"] for s in sats if s["shell_id"] is None])
    bins = np.arange(250, 651, 2)
    a2.hist([alt_in, alt_out], bins=bins, stacked=True, color=[BLUE, GREY],
            label=[f"in a shell ({alt_in.size:,})", f"in transit ({alt_out.size:,})"])
    a2.set_yscale("log")
    a2.set_xlabel("mean-element altitude (km, 2 km bins; about +-5 km bias)")
    a2.set_ylabel("satellites (log scale)")
    a2.set_title(f"Altitudes; {len(report['shells'])} shells [DERIVED, inferred]", fontsize=9)
    a2.legend(frameon=False, fontsize=8)
    fig.suptitle(f"ChronoRoute fleet report: snapshot {snap} at {when}", fontsize=10)
    fig.tight_layout()
    paths.append(out_dir / FILES[0])
    _save(fig, paths[-1])
    plt.close(fig)

    # ---- planes: satellites per plane against the plane's node, per broadband shell
    shells = [s for s in planes_doc["shells"] if s["layer"] == "broadband" and s["planes"]]
    shells.sort(key=lambda s: -s["count"])
    shells = shells[:6]
    fig, axes = plt.subplots(2, 3, figsize=(11, 5.8), squeeze=False)
    for ax, s in zip(axes.flat, shells):
        raan = [p["raan_deg"] for p in s["planes"]]
        size = [p["size"] for p in s["planes"]]
        ax.bar(raan, size, width=2.0, color=BLUE)
        ax.set_xlim(0, 360)
        ax.set_xticks([0, 90, 180, 270, 360])
        ax.set_title(f"{s['shell_id']}: {len(size)} planes, {sum(size):,} sats "
                     f"({s['off_grid']} off-grid)", fontsize=8.5)
        ax.set_xlabel("plane node, RAAN (deg)")
        ax.set_ylabel("satellites in plane")
    for ax in list(axes.flat)[len(shells):]:
        ax.set_visible(False)
    fig.suptitle(f"Orbital planes [DERIVED, inferred from REAL elements]: {snap}", fontsize=10)
    fig.tight_layout()
    paths.append(out_dir / FILES[1])
    _save(fig, paths[-1])
    plt.close(fig)

    # ---- six-digit NORAD ids per shell
    counts = {}
    for s in sats:
        if s["norad"] >= 100_000:
            key = s["shell_id"] or "in transit"
            counts[key] = counts.get(key, 0) + 1
    names = sorted(counts, key=lambda k: (k == "in transit", -counts[k], k))
    fig, ax = plt.subplots(figsize=(7, 0.35 * max(3, len(names)) + 1.2))
    y = np.arange(len(names))
    ax.barh(y, [counts[n] for n in names], color=[GREY if n == "in transit" else BLUE for n in names],
            height=0.6)
    ax.set_yticks(y, names)
    ax.invert_yaxis()
    for yi, n in zip(y, names):
        ax.text(counts[n], yi, f" {counts[n]}", va="center", fontsize=8, color=INK_2)
    six = report["six_digit_ids"]
    ax.set_xlabel("satellites with a 6-digit NORAD id")
    ax.set_title(f"6-digit NORAD ids [REAL]: {six['count']} ({six['min']}..{six['max']}), "
                 f"{six['in_shells']} in shells", fontsize=9)
    fig.tight_layout()
    paths.append(out_dir / FILES[2])
    _save(fig, paths[-1])
    plt.close(fig)

    # ---- GP vs SupGP disagreement
    if gp_distances_km is not None and len(gp_distances_km):
        d = np.sort(np.asarray(gp_distances_km, dtype=float))
        frac = np.arange(1, d.size + 1) / d.size
        fig, ax = plt.subplots(figsize=(7, 3.8))
        ax.plot(d, frac, color=BLUE, linewidth=2)
        ax.set_xscale("log")
        ax.set_xlabel("distance between the GP and SupGP positions (km, log scale)")
        ax.set_ylabel("share of satellites")
        for q in (0.5, 0.9, 0.99):
            v = float(np.quantile(d, q, method="lower"))
            ax.plot([v], [q], marker="o", markersize=6, color=BLUE, markeredgecolor=SURFACE)
            ax.annotate(f"p{int(q * 100)} {v:.1f} km", (v, q), textcoords="offset points",
                        xytext=(8, -10), fontsize=8, color=INK_2)
        cmp_ = report["gp_vs_supgp"]
        ax.set_title(f"GP vs SupGP at {cmp_['at_utc']}, {cmp_['pairs']:,} satellites\n"
                     "[DERIVED: disagreement between two sources, not an error]", fontsize=8.5)
        fig.tight_layout()
        paths.append(out_dir / FILES[3])
        _save(fig, paths[-1])
        plt.close(fig)
    return paths


__all__ = ["FILES", "write_figures"]
