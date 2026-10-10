"""
tle.py  (optional extension)
----------------------------
Loads REAL published Starlink orbital elements from a TLE file, instead of
generating an idealised Walker-Delta pattern.

Why bother? Because it upgrades your validation claim from

    "we modelled a constellation matching Starlink's published design"

to

    "we propagated the actual satellites currently in orbit."

That is a meaningfully stronger statement for a report.

How to get the data (do this once, manually):

    1. Open  https://celestrak.org/NORAD/elements/  in your browser
    2. Find the Starlink group and save the TLE text file as
           ~/chronoroute/data/starlink.txt
    3. Then:  python tle.py

We deliberately do NOT download inside the script. A hard-coded URL in a
student project rots the moment the site reorganises, and manually saving the
file means you can also record exactly which epoch your results came from --
which you should cite in the report.

NOTE: real TLE data is not a clean Walker-Delta. Satellites are at mixed
altitudes, some are drifting to new slots, some are decommissioned. So the
+Grid ISL pattern from topology.py does NOT apply. Use this module to
VALIDATE your synthetic constellation's statistics (altitude spread,
inclination, plane count), not to replace it.
"""

import os
import math
from collections import Counter

from sgp4.api import Satrec, jday

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
DEFAULT_FILE = os.path.join(DATA_DIR, 'starlink.txt')

EARTH_RADIUS_KM = 6371.0
MU_EARTH = 398600.4418


def load_tle_file(path=DEFAULT_FILE, limit=None):
    """
    Parse a Celestrak-style 3-line-per-satellite TLE file.

    Format is:
        line 0: satellite name
        line 1: TLE line 1 (starts with '1 ')
        line 2: TLE line 2 (starts with '2 ')

    Returns: list of dicts with name and a Satrec object.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No TLE file at {path}\n"
            f"Save the Starlink TLE set from celestrak.org to that path first."
        )

    with open(path) as f:
        lines = [ln.rstrip() for ln in f if ln.strip()]

    sats = []
    i = 0
    while i < len(lines) - 2:
        # tolerate files with or without the name line
        if lines[i].startswith('1 ') and lines[i + 1].startswith('2 '):
            name, l1, l2 = f"SAT-{len(sats)}", lines[i], lines[i + 1]
            i += 2
        elif lines[i + 1].startswith('1 ') and lines[i + 2].startswith('2 '):
            name, l1, l2 = lines[i], lines[i + 1], lines[i + 2]
            i += 3
        else:
            i += 1
            continue

        try:
            satrec = Satrec.twoline2rv(l1, l2)
        except Exception:
            continue

        sats.append({'name': name, 'satrec': satrec})
        if limit and len(sats) >= limit:
            break

    return sats


def orbital_elements(sat):
    """
    Pull the human-readable orbital elements back out of a Satrec.

    sgp4 stores mean motion in radians/minute as `no_kozai`, inclination and
    RAAN in radians.
    """
    s = sat['satrec']
    n_rad_per_min = s.no_kozai
    n_rad_per_sec = n_rad_per_min / 60.0
    a = (MU_EARTH / (n_rad_per_sec ** 2)) ** (1.0 / 3.0)

    return {
        'name': sat['name'],
        'altitude_km': a - EARTH_RADIUS_KM,
        'inclination_deg': math.degrees(s.inclo),
        'raan_deg': math.degrees(s.nodeo) % 360.0,
        'eccentricity': s.ecco,
        'period_min': 2 * math.pi / n_rad_per_min,
    }


def compare_with_synthetic(path=DEFAULT_FILE, shell_alt=550.0, tol_km=40.0):
    """
    Compare the real fleet against our synthetic Starlink shell.

    Prints the statistics you should quote in the report's validation section.
    """
    import scale

    sats = load_tle_file(path)
    els = [orbital_elements(s) for s in sats]

    print(f"Loaded {len(els)} real satellites from {os.path.basename(path)}")

    # isolate the 550 km / 53 deg shell we modelled
    shell = [e for e in els
             if abs(e['altitude_km'] - shell_alt) < tol_km
             and 52.0 < e['inclination_deg'] < 54.0]

    print(f"\nSatellites in the {shell_alt:.0f} km / 53 deg shell "
          f"(+/- {tol_km:.0f} km): {len(shell)}")

    if not shell:
        print("  none matched -- check shell_alt and tol_km")
        return

    alts = [e['altitude_km'] for e in shell]
    incs = [e['inclination_deg'] for e in shell]
    pers = [e['period_min'] for e in shell]
    eccs = [e['eccentricity'] for e in shell]

    def stats(v):
        return min(v), sum(v) / len(v), max(v)

    print(f"\n  {'quantity':<20} {'min':>10} {'mean':>10} {'max':>10}")
    for label, v, fmt in [('altitude (km)', alts, '10.1f'),
                          ('inclination (deg)', incs, '10.2f'),
                          ('period (min)', pers, '10.2f'),
                          ('eccentricity', eccs, '10.5f')]:
        lo, mid, hi = stats(v)
        print(f"  {label:<20} {lo:{fmt}} {mid:{fmt}} {hi:{fmt}}")

    # estimate the number of distinct orbital planes by clustering RAAN
    raans = sorted(e['raan_deg'] for e in shell)
    plane_width = 360.0 / 72          # Starlink Shell 1 has 72 planes
    buckets = Counter(int(r / plane_width) for r in raans)
    print(f"\n  distinct RAAN buckets (at 360/72 = {plane_width:.1f} deg "
          f"width): {len(buckets)}")
    print(f"  satellites per plane: min {min(buckets.values())}, "
          f"mean {sum(buckets.values()) / len(buckets):.1f}, "
          f"max {max(buckets.values())}")

    print(f"\n  our synthetic model: "
          f"{scale.describe('starlink')}")
    print("\n  Quote the mean altitude, inclination and plane count above as")
    print("  evidence that the synthetic shell matches the real fleet.")


# ---------------------------------------------------------------- self-test

# One real published Starlink TLE, embedded so the parser can be tested
# without any network access or downloaded file.
SAMPLE_TLE = """STARLINK-1007
1 44713U 19074A   24145.52916667  .00002182  00000+0  16716-3 0  9993
2 44713  53.0544 191.4638 0001373  84.5623 275.5533 15.06391968246031"""


def _self_test():
    print("=== TLE parser self-test (no download needed) ===\n")

    lines = SAMPLE_TLE.strip().split('\n')
    satrec = Satrec.twoline2rv(lines[1], lines[2])
    sat = {'name': lines[0], 'satrec': satrec}
    el = orbital_elements(sat)

    print(f"  parsed        : {el['name']}")
    print(f"  altitude      : {el['altitude_km']:.1f} km")
    print(f"  inclination   : {el['inclination_deg']:.4f} deg")
    print(f"  RAAN          : {el['raan_deg']:.4f} deg")
    print(f"  eccentricity  : {el['eccentricity']:.7f}")
    print(f"  period        : {el['period_min']:.2f} min")

    # propagate it and confirm the position is sane
    jd, fr = jday(2024, 5, 25, 0, 0, 0)
    err, r, v = satrec.sgp4(jd, fr)
    radius = math.sqrt(sum(c * c for c in r))
    speed = math.sqrt(sum(c * c for c in v))
    print(f"\n  propagated    : error code {err}")
    print(f"  altitude      : {radius - EARTH_RADIUS_KM:.1f} km")
    print(f"  speed         : {speed:.2f} km/s")

    assert err == 0, "propagation failed"
    assert 52.0 < el['inclination_deg'] < 54.0, "inclination off"
    assert 400 < el['altitude_km'] < 700, "altitude off"
    assert 7.0 < speed < 8.0, "speed off"
    print("\n  PASS -- real Starlink elements match our synthetic shell:")
    print(f"          53 deg inclination, ~550 km, ~7.6 km/s")


if __name__ == '__main__':
    _self_test()

    print("\n" + "=" * 60)
    if os.path.exists(DEFAULT_FILE):
        print()
        compare_with_synthetic()
    else:
        print(f"\nNo TLE file found at:\n  {os.path.abspath(DEFAULT_FILE)}")
        print("\nTo run the full real-fleet comparison:")
        print("  mkdir -p ~/chronoroute/data")
        print("  # save the Starlink TLE set from celestrak.org to")
        print("  #   ~/chronoroute/data/starlink.txt")
        print("  python tle.py")