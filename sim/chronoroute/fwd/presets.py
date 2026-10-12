"""
presets.py
----------
Ready-made constellations and city pairs for `cr run`.

Synthetic Walker presets (MODELLED constellations):

    C1   dev shell        24 planes x 20 satellites, 550 km, 53 deg, F = 1
    C2   Starlink S1      72 x 22, 550 km, 53 deg, F = 39  (Hypatia "D:550:53:1584/72/39")
    C2b  S1 lowered       72 x 22, 480 km, 53 deg, F = 39  (the 2026 lowering, plan 5.1)

They are generated as OMM-like element sets (the same JSON fields CelesTrak
publishes) and then pushed through the SAME pipeline as the real fleet:
omm.screen_objects -> SGP4 -> shells/planes inference -> Grid-4 -> ground
links. So a synthetic run and a real-fleet run differ only in where the
element sets come from, never in the code that turns them into links.

Walker-Delta i : T / P / F (T satellites in P planes, phasing F): plane p
(0..P-1) has RAAN 360 p / P; slot s (0..S-1, S = T / P) has mean anomaly
360 s / S + 360 F p / T. Orbits are circular (e = 0, so the argument of
latitude equals the mean anomaly), with argument of perigee 0 and no drag
(BSTAR = 0). The mean motion comes from Kepler's third law for
a = 6378.137 km + altitude, with the same mu as orbit/elements.py, so the
shell inference reads the altitude back exactly (e.g. "53.0deg-550km").
SGP4 treats that mean motion as a Kozai mean motion, so the real geometric
altitude differs by a few km (the same known bias as for the real fleet).

Catalogue numbers of synthetic satellites are 9,000,000 + 1000 p + s:
outside every real NORAD range, and never written to the SID registry
(synthetic runs use an in-memory registry).

The 20 fixed science pairs are city pairs fixed before any results. data/static/cities.csv spells Sao Paulo without the
accent; that is the only name mapping.
"""

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from ..data import omm, snapshot
from ..orbit import elements

REPO = Path(__file__).resolve().parents[3]
DEFAULT_SNAPSHOT_DIR = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"
DEFAULT_SOURCE = "supgp"
DEFAULT_REAL_SHELL = "53.2deg-463km"
SYNTHETIC_NORAD_BASE = 9_000_000


@dataclass(frozen=True)
class WalkerPreset:
    name: str
    planes: int
    per_plane: int
    altitude_km: float
    inclination_deg: float
    phasing: int
    note: str = ""

    @property
    def total(self):
        return self.planes * self.per_plane

    def as_dict(self):
        return {"name": self.name, "planes": self.planes, "per_plane": self.per_plane,
                "total": self.total, "altitude_km": self.altitude_km,
                "inclination_deg": self.inclination_deg, "phasing_f": self.phasing,
                "notation": f"{self.inclination_deg}:{self.total}/{self.planes}/{self.phasing}",
                "note": self.note}


WALKER_PRESETS = MappingProxyType({
    "C1": WalkerPreset("C1", 24, 20, 550.0, 53.0, 1, "dev shell (legacy Tier 1, 480/24/1)"),
    "C2": WalkerPreset("C2", 72, 22, 550.0, 53.0, 39, "Starlink S1 as in Hypatia (D:550:53:1584/72/39)"),
    "C2b": WalkerPreset("C2b", 72, 22, 480.0, 53.0, 39, "S1 geometry at 480 km (2026 lowering)"),
})

# Fixed before any results: short, medium, long.
SCIENCE_PAIRS_PLAN = (
    ("Mumbai", "Dubai"), ("Cairo", "Moscow"), ("Reykjavik", "Toronto"),
    ("London", "New York"), ("Singapore", "Sydney"), ("Nairobi", "Frankfurt"),
    ("Lagos", "São Paulo"), ("Honolulu", "Tokyo"), ("Anchorage", "Oslo"), ("Delhi", "Paris"),
    ("Seoul", "Vancouver"), ("Chennai", "London"), ("Perth", "Johannesburg"),
    ("Tokyo", "Los Angeles"), ("Johannesburg", "London"), ("Mexico City", "Paris"),
    ("Lima", "Madrid"), ("Santiago", "Auckland"), ("New York", "Sydney"), ("São Paulo", "Tokyo"),
)
# Plan spelling -> data/static/cities.csv spelling.
CITY_NAME_MAP = MappingProxyType({"São Paulo": "Sao Paulo"})


def science_pairs(available_names):
    """(pairs that exist in the city list, report) for the 20 plan pairs.

    available_names: the names in data/static/cities.csv. report lists the
    spelling mappings applied and every pair left out because a city is
    missing (none with the committed cities.csv).
    """
    names = set(available_names)
    pairs, missing, mapped = [], [], {}
    for src, dst in SCIENCE_PAIRS_PLAN:
        s, d = CITY_NAME_MAP.get(src, src), CITY_NAME_MAP.get(dst, dst)
        for plan_name, csv_name in ((src, s), (dst, d)):
            if plan_name != csv_name:
                mapped[plan_name] = csv_name
        if s in names and d in names:
            pairs.append((s, d))
        else:
            missing.append({"pair": [src, dst], "missing": sorted({s, d} - names)})
    return tuple(pairs), {"plan_pairs": len(SCIENCE_PAIRS_PLAN), "used": len(pairs),
                          "missing": missing, "name_mapping": mapped}


def walker_mean_motion_rev_day(altitude_km):
    """Mean motion (rev/day) of a circular orbit at a = R_E + altitude (orbit/elements.py constants)."""
    a = elements.EARTH_RADIUS_KM + float(altitude_km)
    n = math.sqrt(elements.MU_KM3_S2 / a ** 3)                    # rad/s
    return n * elements.SECONDS_PER_DAY / (2.0 * math.pi)


def walker_objects(preset, epoch_ns):
    """OMM-like JSON objects (plain Python values) for every satellite of a preset."""
    if preset.planes < 1 or preset.per_plane < 1:
        raise ValueError("a Walker preset needs at least one plane and one satellite per plane")
    if not 0 <= preset.phasing < preset.planes:
        raise ValueError("Walker phasing F must be in 0 .. planes-1")
    epoch = omm.format_utc_ns(epoch_ns)[:-1]
    if "." not in epoch:
        epoch += ".000000"
    mm = walker_mean_motion_rev_day(preset.altitude_km)
    total = preset.total
    out = []
    for p in range(preset.planes):
        raan = 360.0 * p / preset.planes
        for s in range(preset.per_plane):
            m = (360.0 * s / preset.per_plane + 360.0 * preset.phasing * p / total) % 360.0
            norad = SYNTHETIC_NORAD_BASE + 1000 * p + s
            out.append({
                "OBJECT_NAME": f"WALKER-{preset.name}-P{p:02d}-S{s:02d}",
                "OBJECT_ID": f"SYNTH-{preset.name}-{p:02d}{s:02d}",
                "EPOCH": epoch,
                "MEAN_MOTION": mm,
                "ECCENTRICITY": 0.0,
                "INCLINATION": float(preset.inclination_deg),
                "RA_OF_ASC_NODE": raan,
                "ARG_OF_PERICENTER": 0.0,
                "MEAN_ANOMALY": m,
                "EPHEMERIS_TYPE": 0,
                "CLASSIFICATION_TYPE": "U",
                "NORAD_CAT_ID": norad,
                "ELEMENT_SET_NO": 999,
                "REV_AT_EPOCH": 0,
                "BSTAR": 0.0,
                "MEAN_MOTION_DOT": 0.0,
                "MEAN_MOTION_DDOT": 0.0,
            })
    return out


def walker_omm_bytes(preset, epoch_ns):
    """The preset as an OMM JSON array (bytes, deterministic): written next to a run's trace."""
    return (json.dumps(walker_objects(preset, epoch_ns), indent=0) + "\n").encode("utf-8")


def walker_fleet(preset, epoch_ns):
    """A data.snapshot.Fleet for a Walker preset, screened by the real fleet's screening code."""
    raw = walker_omm_bytes(preset, epoch_ns)
    screen = omm.screen_objects(omm.parse_omm_json(raw), epoch_ns)
    if len(screen.kept) != preset.total:
        raise ValueError(f"preset {preset.name}: {preset.total - len(screen.kept)} element sets "
                         f"were excluded by screening: {screen.exclusions[:3]}")
    info = snapshot.SourceInfo(key="synthetic", name=f"Synthetic Walker {preset.name}",
                               url="", raw_file="synthetic_omm.json", headers_file="",
                               attribution="Synthetic Walker-Delta constellation (MODELLED)")
    return snapshot.Fleet(source=info, layout="synthetic", folder=Path("."),
                          snapshot_id=f"synthetic-walker-{preset.name}", fetched_ns=epoch_ns,
                          http_date="", sha256_raw=hashlib.sha256(raw).hexdigest(),
                          count_raw=screen.count_raw, records=screen.kept,
                          excluded=MappingProxyType(screen.excluded), exclusions=screen.exclusions,
                          satrecs=screen.satrecs, screen=screen)


__all__ = ["DEFAULT_SNAPSHOT_DIR", "DEFAULT_SOURCE", "DEFAULT_REAL_SHELL", "SYNTHETIC_NORAD_BASE",
           "WalkerPreset", "WALKER_PRESETS", "SCIENCE_PAIRS_PLAN", "CITY_NAME_MAP", "science_pairs",
           "walker_mean_motion_rev_day", "walker_objects", "walker_omm_bytes", "walker_fleet"]
