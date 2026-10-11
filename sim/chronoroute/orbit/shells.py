"""
shells.py
---------
Sort the real fleet into shells (DERIVED; "inferred" wherever it is shown).

A shell is a group of satellites flying at one inclination and one altitude,
like the layers of an onion. SpaceX does not publish today's shells, so we
infer them from the element sets, step by step:

  1. Layer. Direct-to-Cell satellites ("[DTC]" in the catalogue name) serve
     phones and form a separate, optional layer; all others are broadband.
  2. Inclination groups. Histogram the inclinations in 0.1 deg bins. A bin
     holding at least `min_group_size` satellites and more than its neighbours
     starts a group, centred on the median inclination of that bin. Every
     satellite within `inclination_tol_deg` of a centre joins the nearest group.
  3. Altitude modes. Altitude = a - 6378.137 km with a from the mean motion
     (elements.altitude_km). Operational shells are very sharp (the middle
     half of a shell spans well under 1 km), so within each group and layer
     we look for peaks in a 0.2 km histogram. A peak is a mode when at least
     `min_mode_core` satellites sit within +-0.5 km of it and no higher peak
     lies within `mode_separation_km`.
  4. Bands. Each satellite joins the nearest mode, if it is within `band_km`
     (10 km). Satellites outside every band are IN TRANSIT (raising, lowering
     or decaying) and are excluded from routing. Why 10 km: it is the window
     the reference measurement used (06_research_live-data.md section 4, e.g.
     465-485 km for the 70 deg / 476 km shell) and it is wider than the
     +-5 km mean-element bias. It only matters at the edges: on the
     2026-10-10 GP snapshot a 5 km band would move 12 of the 337 satellites
     of the 70 deg / 476 km shell (all at 482-487 km, changing altitude) to
     "in transit" and change every other shell of 300+ satellites by at
     most 0.5% (a test pins these counts). A
     satellite that close to a shell still sits in that shell's planes, so
     for routing it behaves like a member. The value is a parameter, recorded
     in every report.
  5. Merging. Two neighbouring modes are one shell when their satellites share
     orbital planes AND have comparable numbers (the smaller has at least
     `merge_size_ratio` of the larger). Example: at 70 deg, 474 and 477 km
     hold 180 and 136 satellites in the same planes -> one 476 km shell. A
     small mode inside the planes of a much bigger one (53.2 deg: 460 km and
     465 km next to 463 km) stays a separate sub-shell, as the plan asks, but
     is marked `shares_planes_with` so the topology code can decide.
  6. Size. A shell needs at least `min_shell_size` satellites; smaller
     groups (e.g. a launch batch at its staging altitude) count as in transit.

"Share planes" is measured, not assumed: the fraction of the smaller mode's
satellites whose node (J2-corrected RAAN at the reference instant) lies within
`share_angle_deg` of a node of the larger mode, compared with the fraction a
random node would reach by chance. `excess` = (fraction - chance)/(1 - chance)
is 0 for no relation and 1 for "every satellite is in one of their planes".

Everything here is deterministic: sorted inputs, fixed bins, explicit ties.
"""

from dataclasses import asdict, dataclass, field, replace
from types import MappingProxyType

import numpy as np

from . import elements

LAYERS = ("broadband", "dtc")


@dataclass(frozen=True)
class ShellParams:
    """Every knob of the shell inference (recorded in reports and manifests)."""

    inclination_bin_deg: float = 0.1
    min_group_size: int = 100
    inclination_tol_deg: float = 0.1
    altitude_bin_km: float = 0.2
    mode_window_km: float = 0.5
    min_mode_core: int = 20
    mode_separation_km: float = 1.5
    band_km: float = 10.0
    min_shell_size: int = 100
    share_angle_deg: float = 0.3
    share_excess_min: float = 0.5
    merge_size_ratio: float = 0.25

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Shell:
    """One inferred shell.

    altitude_km      population-weighted centre of its altitude mode(s)
    modes_km         the altitude mode(s) it was built from
    altitude_range_km (lowest, highest) member altitude
    norads           members, sorted
    shares_planes_with  id of a bigger shell whose planes these satellites
                     sit in (None when independent); see plane_sharing
    """

    shell_id: str
    layer: str
    inclination_deg: float
    altitude_km: float
    modes_km: tuple
    altitude_range_km: tuple
    norads: tuple
    shares_planes_with: str | None = None
    plane_sharing: MappingProxyType | None = None

    @property
    def count(self):
        return len(self.norads)

    def as_dict(self):
        return {
            "shell_id": self.shell_id,
            "layer": self.layer,
            "inclination_deg": round(self.inclination_deg, 4),
            "altitude_km": round(self.altitude_km, 2),
            "modes_km": [round(m, 2) for m in self.modes_km],
            "altitude_range_km": [round(a, 2) for a in self.altitude_range_km],
            "count": self.count,
            "shares_planes_with": self.shares_planes_with,
            "plane_sharing": dict(self.plane_sharing) if self.plane_sharing else None,
        }


@dataclass(frozen=True)
class ShellCatalog:
    """Result of infer_shells().

    shells           Shell tuple, broadband first, then by inclination and altitude
    shell_of         NORAD id -> shell id, for every satellite in a shell
    in_transit       NORAD id -> reason, for every other satellite:
                     "no_inclination_group", "outside_shell_bands" or "small_group"
    altitude_km      NORAD id -> mean-element altitude (km) of every satellite
    inclination_histogram  [(bin centre deg, count)] at 0.1 deg
    groups           the inclination groups found (centre, count)
    mode_pairs       every neighbouring-mode comparison made in step 5
    """

    params: ShellParams
    reference_ns: int
    shells: tuple
    shell_of: MappingProxyType
    in_transit: MappingProxyType
    altitude_km: MappingProxyType
    inclination_histogram: tuple
    groups: tuple
    mode_pairs: tuple = field(default=())

    def shell(self, shell_id):
        for shell in self.shells:
            if shell.shell_id == shell_id:
                return shell
        raise KeyError(shell_id)

    def in_transit_counts(self):
        counts = {}
        for reason in self.in_transit.values():
            counts[reason] = counts.get(reason, 0) + 1
        return dict(sorted(counts.items()))


# ------------------------------------------------------------------ helpers

def _bin_index(values, width):
    """Bin numbers on a fixed global grid (bin k holds [k*w - w/2, k*w + w/2))."""
    return np.floor(np.asarray(values, dtype=float) / width + 0.5).astype(np.int64)


def _circular_coverage(raans, half_width):
    """Fraction of the circle within half_width (deg) of any of the angles. Exact."""
    if len(raans) == 0:
        return 0.0
    r = np.sort(np.mod(np.asarray(raans, dtype=float), 360.0))
    if 2 * half_width >= 360.0:
        return 1.0
    covered = 0.0
    start, end = r[0] - half_width, r[0] + half_width
    for value in r[1:]:
        lo, hi = value - half_width, value + half_width
        if lo <= end:
            end = max(end, hi)
        else:
            covered += end - start
            start, end = lo, hi
    covered += end - start
    # The first and last interval can overlap across 0/360.
    wrap_overlap = (r[-1] + half_width) - (r[0] - half_width + 360.0)
    if wrap_overlap > 0:
        covered -= wrap_overlap
    return float(min(1.0, covered / 360.0))


def _nearest_circular_distance(values, reference):
    """For each value, the circular distance (deg) to the nearest reference angle."""
    ref = np.sort(np.mod(np.asarray(reference, dtype=float), 360.0))
    vals = np.mod(np.asarray(values, dtype=float), 360.0)
    idx = np.searchsorted(ref, vals)
    before = ref[(idx - 1) % len(ref)]
    after = ref[idx % len(ref)]
    d1 = np.abs(elements.circular_difference_deg(vals, before))
    d2 = np.abs(elements.circular_difference_deg(vals, after))
    return np.minimum(d1, d2)


def plane_sharing(raan_small, raan_large, angle_deg):
    """How strongly the satellites of one group sit in the planes of another.

    Returns {"fraction", "chance", "excess"} (see the module docstring).
    """
    if len(raan_small) == 0 or len(raan_large) == 0:
        return {"fraction": 0.0, "chance": 0.0, "excess": 0.0}
    fraction = float(np.mean(_nearest_circular_distance(raan_small, raan_large) <= angle_deg))
    chance = _circular_coverage(raan_large, angle_deg)
    excess = 0.0 if chance >= 1.0 else (fraction - chance) / (1.0 - chance)
    return {"fraction": round(fraction, 4), "chance": round(chance, 4), "excess": round(excess, 4)}


def _find_modes(alt, params):
    """Altitude modes (centres, km) of one group/layer, lowest first."""
    width = params.altitude_bin_km
    bins = np.floor(alt / width).astype(np.int64)
    lo, hi = int(bins.min()), int(bins.max())
    counts = np.bincount(bins - lo, minlength=hi - lo + 1)
    # Window sum over 2w+1 bins: with 0.2 km bins and a 0.5 km window that is
    # 5 bins = 1.0 km, i.e. the satellites within about +-0.5 km of each bin.
    w = int(params.mode_window_km / width + 1e-9)
    padded = np.concatenate([np.zeros(w, dtype=np.int64), counts, np.zeros(w, dtype=np.int64)])
    csum = np.concatenate([[0], np.cumsum(padded)])
    window = csum[2 * w + 1:] - csum[:-(2 * w + 1)]
    reach = int(round(params.mode_separation_km / width))
    centres = []
    for k in range(len(window)):
        if window[k] < params.min_mode_core:
            continue
        left = window[max(0, k - reach):k]
        right = window[k + 1:k + 1 + reach]
        # Highest within reach; on a tie the lowest altitude wins (left strict, right not).
        if (left.size and window[k] <= left.max()) or (right.size and window[k] < right.max()):
            continue
        centre_km = (k + lo + 0.5) * width
        near = alt[np.abs(alt - centre_km) <= params.mode_window_km]
        centres.append(float(np.median(near)))
    return sorted(centres)


def _shell_label(layer, inclination, altitude):
    prefix = "dtc-" if layer == "dtc" else ""
    return f"{prefix}{inclination:.1f}deg-{altitude:.0f}km"


# --------------------------------------------------------------- main entry

def infer_shells(records, reference_ns, params=None):
    """Infer shells from OMM records (see the module docstring for the method).

    records       OmmRecord sequence (one per NORAD id)
    reference_ns  common instant (UTC ns) for the node positions used in the
                  plane-sharing test; normally the snapshot's fetch time
    """
    params = params or ShellParams()
    records = sorted(records, key=lambda r: r.norad)
    if not records:
        raise ValueError("no satellites")
    norad = np.array([r.norad for r in records], dtype=np.int64)
    inc = np.array([r.inclination for r in records])
    alt = elements.altitude_km([r.mean_motion for r in records])
    layer = np.array(["dtc" if r.is_dtc else "broadband" for r in records])
    raan = elements.raan_at_deg([r.raan for r in records], [r.epoch_ns for r in records],
                                reference_ns, [r.mean_motion for r in records],
                                [r.eccentricity for r in records], inc)

    # Step 2: inclination groups from 0.1 deg bins.
    ibin = _bin_index(inc, params.inclination_bin_deg)
    keys, counts = np.unique(ibin, return_counts=True)
    count_of = dict(zip(keys.tolist(), counts.tolist()))
    histogram = tuple((round(k * params.inclination_bin_deg, 1), int(c)) for k, c in zip(keys, counts))
    centres = []
    for k, c in zip(keys.tolist(), counts.tolist()):
        if c >= params.min_group_size and c > count_of.get(k - 1, 0) and c >= count_of.get(k + 1, 0):
            centres.append(float(np.median(inc[ibin == k])))
    centres = np.array(sorted(centres))
    group = np.full(len(records), -1)
    if len(centres):
        dist = np.abs(inc[:, None] - centres[None, :])
        nearest = np.argmin(dist, axis=1)                  # ties -> lower inclination
        ok = dist[np.arange(len(records)), nearest] <= params.inclination_tol_deg
        group[ok] = nearest[ok]
    groups = tuple({"inclination_deg": round(float(c), 4), "count": int(np.sum(group == g))}
                   for g, c in enumerate(centres))

    in_transit = {}
    for i in np.where(group < 0)[0]:
        in_transit[int(norad[i])] = "no_inclination_group"

    shells = []
    shell_members = {}
    pair_log = []
    for g, centre in enumerate(centres):
        for lay in LAYERS:
            idx = np.where((group == g) & (layer == lay))[0]
            if len(idx) == 0:
                continue
            modes = _find_modes(alt[idx], params) if len(idx) >= params.min_mode_core else []
            if not modes:
                for i in idx:
                    in_transit[int(norad[i])] = "outside_shell_bands"
                continue
            # Step 4: nearest mode within the band (ties -> lower mode).
            mode_arr = np.array(modes)
            d = np.abs(alt[idx][:, None] - mode_arr[None, :])
            nearest = np.argmin(d, axis=1)
            inside = d[np.arange(len(idx)), nearest] <= params.band_km
            members = [idx[inside & (nearest == m)] for m in range(len(modes))]
            for i in idx[~inside]:
                in_transit[int(norad[i])] = "outside_shell_bands"

            # Step 5: compare neighbouring modes (on the original modes, so the
            # result does not depend on the order of merging).
            parent = list(range(len(modes)))

            def find(a):
                while parent[a] != a:
                    parent[a] = parent[parent[a]]
                    a = parent[a]
                return a

            sharing_links = []
            for m in range(len(modes) - 1):
                a, b = members[m], members[m + 1]
                if len(a) == 0 or len(b) == 0:
                    continue
                small, large = (a, b) if len(a) <= len(b) else (b, a)
                share = plane_sharing(raan[small], raan[large], params.share_angle_deg)
                ratio = len(small) / len(large)
                coplanar = share["excess"] >= params.share_excess_min
                merge = coplanar and ratio >= params.merge_size_ratio
                pair_log.append({
                    "inclination_deg": round(float(centre), 4), "layer": lay,
                    "modes_km": [round(modes[m], 2), round(modes[m + 1], 2)],
                    "counts": [int(len(a)), int(len(b))],
                    "size_ratio": round(ratio, 4), **share,
                    "coplanar": bool(coplanar), "merged": bool(merge),
                })
                if merge:
                    parent[find(m + 1)] = find(m)
                elif coplanar:
                    sharing_links.append((m if len(a) <= len(b) else m + 1,
                                          m + 1 if len(a) <= len(b) else m, share))

            components = {}
            for m in range(len(modes)):
                components.setdefault(find(m), []).append(m)
            built = {}
            for root, mode_list in sorted(components.items()):
                idx_all = np.sort(np.concatenate([members[m] for m in mode_list]))
                if len(idx_all) == 0:
                    continue
                weights = [len(members[m]) for m in mode_list]
                centre_alt = float(np.average([modes[m] for m in mode_list], weights=weights)) \
                    if sum(weights) else float(np.mean([modes[m] for m in mode_list]))
                if len(idx_all) < params.min_shell_size:
                    for i in idx_all:
                        in_transit[int(norad[i])] = "small_group"
                    continue
                built[root] = {"idx": idx_all, "modes": [modes[m] for m in mode_list],
                               "altitude": centre_alt}
            for root, info in built.items():
                shell_id = _shell_label(lay, float(np.round(centre, 1)), info["altitude"])
                info["id"] = shell_id
            for small_mode, large_mode, share in sharing_links:
                s_root, l_root = find(small_mode), find(large_mode)
                if s_root in built and l_root in built and s_root != l_root:
                    built[s_root]["shares"] = (built[l_root]["id"], share)
            for root in sorted(built, key=lambda r: built[r]["altitude"]):
                info = built[root]
                ids = norad[info["idx"]]
                shares = info.get("shares")
                shells.append(Shell(
                    shell_id=info["id"], layer=lay, inclination_deg=float(centre),
                    altitude_km=info["altitude"], modes_km=tuple(info["modes"]),
                    altitude_range_km=(float(alt[info["idx"]].min()), float(alt[info["idx"]].max())),
                    norads=tuple(int(n) for n in np.sort(ids)),
                    shares_planes_with=shares[0] if shares else None,
                    plane_sharing=MappingProxyType(dict(shares[1])) if shares else None,
                ))
                for n in ids:
                    shell_members[int(n)] = info["id"]

    # Shell ids must be unique; two shells rounding to the same label get a suffix.
    seen = {}
    unique = []
    for shell in sorted(shells, key=lambda s: (LAYERS.index(s.layer), s.inclination_deg, s.altitude_km)):
        n = seen.get(shell.shell_id, 0)
        seen[shell.shell_id] = n + 1
        if n:
            new_id = f"{shell.shell_id}-{chr(ord('a') + n)}"
            for member in shell.norads:
                shell_members[member] = new_id
            shell = replace(shell, shell_id=new_id)
        unique.append(shell)

    altitude_map = {int(n): float(a) for n, a in zip(norad, alt)}
    return ShellCatalog(
        params=params, reference_ns=int(reference_ns), shells=tuple(unique),
        shell_of=MappingProxyType(dict(sorted(shell_members.items()))),
        in_transit=MappingProxyType(dict(sorted(in_transit.items()))),
        altitude_km=MappingProxyType(altitude_map),
        inclination_histogram=histogram, groups=groups, mode_pairs=tuple(pair_log),
    )
