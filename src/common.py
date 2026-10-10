"""
common.py
---------
Shared setup for all five experiments, so each experiment script stays short
and they all use an identical scenario.
"""

import os
import matplotlib
matplotlib.use('Agg')        # render to file, no GUI needed inside WSL
import matplotlib.pyplot as plt

from constellation import build_constellation, propagate, ground_station_positions
from topology import build_all_graphs

RESULTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'results')

# ----- Scenario used by every experiment -----
DURATION_S = 120
STEP_S = 1

FLOWS = [
    ('GS:Chennai',  'GS:London'),
    ('GS:NewYork',  'GS:Sydney'),
    ('GS:SaoPaulo', 'GS:Tokyo'),
]

_cache = {}


def setup(duration_s=DURATION_S, step_s=STEP_S, verbose=True):
    """
    Build the constellation, propagate it, and build every graph.
    Cached, so running several experiments in one process is fast.
    """
    key = (duration_s, step_s)
    if key in _cache:
        return _cache[key]

    if verbose:
        print(f"  building constellation and propagating {duration_s}s...")
    sats = build_constellation()
    times, sat_pos = propagate(sats, duration_s=duration_s, step_s=step_s)
    gs_pos = ground_station_positions(times)
    if verbose:
        print(f"  building {len(times)} topology graphs...")
    graphs = build_all_graphs(times, sat_pos, gs_pos, verbose=False)

    _cache[key] = (times, sat_pos, gs_pos, graphs)
    return _cache[key]


def save(fig, filename):
    """Save a figure into results/ and print where it went."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.abspath(os.path.join(RESULTS_DIR, filename))
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  saved -> {path}")
    return path


def style():
    """One consistent look for every graph in the report."""
    plt.rcParams.update({
        'figure.figsize': (9, 5),
        'axes.grid': True,
        'grid.alpha': 0.3,
        'font.size': 11,
        'axes.titlesize': 13,
        'axes.titleweight': 'bold',
        'legend.frameon': True,
        'legend.framealpha': 0.9,
    })