"""
planes.py
---------
Orbital planes inside each shell, and each satellite's slot in its plane
(DERIVED). This module is the API the topology code builds links from:

    geo = build_fleet_geometry(fleet.records, fleet.fetched_ns)
    for shell in geo.shells:                    # ShellGeometry
        for plane in shell.planes:              # Plane
            plane.norads                        # NORAD ids in slot order
    geo.satellites[44714]                       # SatelliteSlot: shell, plane, slot

How planes are found (per shell):

  1. Node at a common instant. Each element set has its own epoch, and the
     ascending node (RAAN) drifts by a few degrees per day (J2), so every
     node is carried to the same reference instant first
     (elements.raan_at_deg, J2 secular rate).
  2. RAAN clustering. Sort the nodes around the circle and cut wherever two
     neighbours are more than `gap_deg` (0.5 deg) apart. A real plane spans
     up to about 0.7 deg of RAAN (measured on the 2026-10-10 snapshot: in a
     DTC plane the node shifts by ~0.06 deg from one slot to the next, the
     same in the J2 mean elements and in the SGP4 state vectors), but its
     neighbouring nodes are only hundredths of a degree apart. On the real
     fleet the gaps between sorted nodes are almost all below 0.2 deg (inside
     a plane) or above 0.7 deg (between planes); on the 2026-10-10 SupGP
     snapshot 172 of 10,407 gaps (1.7%) fall in between.
     Exception, the 97.3 deg shell (gap_deg_by_inclination): its planes come
     as TWINS whose nodes are about 0.85 deg apart. With the 0.5 deg rule
     every twin became its own plane (61 planes of at most 24 satellites on
     the 2026-10-10 GP snapshot), so a Grid-4 "cross-plane" link would mostly
     join a satellite to its twin. A 1.0 deg gap merges each pair: 36 planes
     of 23-48 (median 43) plus 9 fragments, 45 clusters in all, against the
     planning research's "about 42 clusters of 35-48" (06_research_live-data
     section 4). Every other shell keeps 0.5 deg (1.0 deg would merge real
     planes of the 53.2 deg shell: 102 planes with one of 61 satellites).
     The 43 deg shell needs no override: 83 planes plus 21 fragments, of
     which 10 hold 9-18 satellites (below half the typical 35), i.e. about
     93 clusters of 9+ satellites, as the research counted. Plane counts are
     DERIVED and printed with this caveat by `cr fleet report`.
  3. Planes vs fragments. A cluster is a plane when it holds at least
     `min_plane_fraction` (half) of the shell's typical plane size (the plane
     size the median satellite sees). Smaller clusters are fragments: a few
     satellites moving between planes, or early satellites outside the grid.
     Their satellites stay in the shell but get no plane or slot (OFF-GRID).
  4. Slots. Inside a plane, satellites are ordered by argument of latitude u
     (angle from the ascending node along the orbit) at the reference
     instant, from the SGP4 state vector. Slot 0 is the smallest u; the ring
     is closed (the last slot is followed by slot 0). Slots are a snapshot at
     the reference instant: satellites keep their order around the ring.

Plane quality (published with every shell, because the inference can be
ambiguous, e.g. in the overlapping 53 deg sub-shells):

  score               fraction of the shell's satellites that sit in a plane
                      whose RAAN spread is at most half the distance to the
                      nearest neighbouring plane (cleanly separated). 1.0 = every
                      satellite in a clean plane; fragments count as not clean.
  separation_ratio    smallest plane-to-plane node gap / largest plane spread
  spacing_cv          spread of the plane-to-plane node spacing (0 = evenly spaced)
  slot_evenness       median over planes of (largest u gap) / (360 / n);
                      1.0 = perfectly even slots, 2.0 = one slot empty
"""

from dataclasses import asdict, dataclass
from types import MappingProxyType

import numpy as np

from . import elements
from .propagate import SatelliteArray, argument_of_latitude_deg
from .shells import ShellParams, infer_shells


@dataclass(frozen=True)
class PlaneParams:
    gap_deg: float = 0.5
    min_plane_fraction: float = 0.5
    # Per-shell override of gap_deg, keyed by the shell's inclination rounded
    # to 0.1 deg: ((inclination, gap), ...). See step 2 of the module docstring.
    gap_deg_by_inclination: tuple = ((97.3, 1.0),)

    def gap_for(self, inclination_deg):
        """The RAAN gap (deg) used to cut the planes of a shell at this inclination."""
        inc = round(float(inclination_deg), 1)
        for value, gap in self.gap_deg_by_inclination:
            if abs(inc - value) < 0.05:
                return float(gap)
        return float(self.gap_deg)

    def as_dict(self):
        out = asdict(self)
        out["gap_deg_by_inclination"] = [[float(i), float(g)] for i, g in self.gap_deg_by_inclination]
        return out


@dataclass(frozen=True)
class Plane:
    """One orbital plane: satellites sharing an ascending node, in slot order."""

    plane_id: str             # "<shell id>/P<index>", e.g. "dtc-53.2deg-360km/P07"
    index: int                # 0.. in order of node RAAN at the reference instant
    raan_deg: float           # circular mean node (J2-corrected to the reference instant)
    raan_spread_deg: float    # widest node difference inside the plane
    norads: tuple             # NORAD ids, slot 0 first (ascending u)
    u_deg: tuple              # argument of latitude of each slot at the reference instant
    slot_evenness: float      # largest u gap / (360 / n)

    @property
    def size(self):
        return len(self.norads)

    def as_dict(self):
        return {"plane_id": self.plane_id, "index": self.index,
                "raan_deg": round(self.raan_deg, 4), "raan_spread_deg": round(self.raan_spread_deg, 4),
                "size": self.size, "slot_evenness": round(self.slot_evenness, 4),
                "norads": list(self.norads), "u_deg": [round(u, 3) for u in self.u_deg]}


@dataclass(frozen=True)
class Fragment:
    """A RAAN cluster too small to be a plane (its satellites are off-grid).

    nearest_plane_id / nearest_plane_gap_deg name the plane whose node is
    closest, so the topology code can choose to attach these satellites.
    """

    raan_deg: float
    norads: tuple
    nearest_plane_id: str | None = None
    nearest_plane_gap_deg: float | None = None

    def as_dict(self):
        gap = None if self.nearest_plane_gap_deg is None else round(self.nearest_plane_gap_deg, 4)
        return {"raan_deg": round(self.raan_deg, 4), "size": len(self.norads),
                "nearest_plane_id": self.nearest_plane_id, "nearest_plane_gap_deg": gap,
                "norads": list(self.norads)}


@dataclass(frozen=True)
class ShellGeometry:
    """A shell (from shells.py) with its planes, fragments and quality."""

    shell: object             # shells.Shell
    planes: tuple             # Plane, by node RAAN
    fragments: tuple          # Fragment
    quality: MappingProxyType

    @property
    def shell_id(self):
        return self.shell.shell_id

    def plane_lists(self):
        """[[norad, ...] per plane], slot order: the plainest form for link building."""
        return [list(p.norads) for p in self.planes]

    def as_dict(self, with_members=True):
        out = {**self.shell.as_dict(), "n_planes": len(self.planes),
               "plane_sizes": [p.size for p in self.planes],
               "off_grid": sum(len(f.norads) for f in self.fragments),
               "quality": dict(self.quality)}
        if with_members:
            out["planes"] = [p.as_dict() for p in self.planes]
            out["fragments"] = [f.as_dict() for f in self.fragments]
        return out


@dataclass(frozen=True)
class SatelliteSlot:
    """Where one satellite sits. plane_id/slot are None when off-grid or in transit."""

    norad: int
    name: str
    layer: str                # "broadband" or "dtc"
    shell_id: str | None
    plane_id: str | None
    slot: int | None
    status: str               # "in_plane", "off_grid" or "in_transit"
    transit_reason: str | None
    altitude_km: float        # mean-element altitude (DERIVED)

    @property
    def routable(self):
        """Satellites in transit (outside every shell band) are excluded from routing."""
        return self.status != "in_transit"

    def as_dict(self):
        return asdict(self) | {"routable": self.routable, "altitude_km": round(self.altitude_km, 3)}


@dataclass(frozen=True)
class FleetGeometry:
    """Shells -> planes -> ordered satellites, and the reverse index per satellite."""

    reference_ns: int
    shells: tuple                     # ShellGeometry, same order as the shell catalog
    satellites: MappingProxyType      # NORAD id -> SatelliteSlot (every satellite)
    catalog: object                   # shells.ShellCatalog
    shell_params: ShellParams
    plane_params: PlaneParams

    def shell(self, shell_id):
        for shell in self.shells:
            if shell.shell_id == shell_id:
                return shell
        raise KeyError(shell_id)

    def shell_planes(self, shell_id):
        """[[norad, ...], ...]: the planes of one shell in node order, satellites in slot order."""
        return self.shell(shell_id).plane_lists()

    def routable_norads(self):
        return tuple(n for n, s in self.satellites.items() if s.routable)

    def status_counts(self):
        counts = {}
        for slot in self.satellites.values():
            counts[slot.status] = counts.get(slot.status, 0) + 1
        return dict(sorted(counts.items()))


# --------------------------------------------------------------- clustering

def cluster_raans(raan_deg, gap_deg):
    """Split angles on a circle wherever neighbours are more than gap_deg apart.

    Returns a list of index arrays (into raan_deg), each sorted by angle,
    starting with the cluster that contains the smallest angle after the
    first cut. If there is no gap anywhere, everything is one cluster.
    """
    raan = np.mod(np.asarray(raan_deg, dtype=float), 360.0)
    n = len(raan)
    if n == 0:
        return []
    order = np.argsort(raan, kind="stable")
    sorted_r = raan[order]
    gaps = np.diff(np.concatenate([sorted_r, [sorted_r[0] + 360.0]]))   # gap after each element
    cuts = np.where(gaps > gap_deg)[0]
    if n == 1 or len(cuts) == 0:
        return [order]
    clusters = []
    for a, b in zip(cuts, np.roll(cuts, -1)):
        start = (a + 1) % n
        length = (b - a) % n or n
        clusters.append(order[(start + np.arange(length)) % n])
    return clusters


def _circular_spread(angles):
    """Width of the smallest arc containing all the angles (deg)."""
    a = np.sort(np.mod(np.asarray(angles, dtype=float), 360.0))
    if len(a) < 2:
        return 0.0
    gaps = np.diff(np.concatenate([a, [a[0] + 360.0]]))
    return float(360.0 - gaps.max())


def _slot_evenness(u_sorted):
    n = len(u_sorted)
    if n < 2:
        return float("nan")
    gaps = np.diff(np.concatenate([u_sorted, [u_sorted[0] + 360.0]]))
    return float(gaps.max() / (360.0 / n))


def _typical_plane_size(sizes):
    """The plane size the median satellite sees (satellite-weighted median)."""
    per_satellite = np.sort(np.repeat(sizes, sizes))
    return float(per_satellite[(len(per_satellite) - 1) // 2])


def planes_for_shell(shell, raan_by_norad, u_by_norad, params):
    """Planes, fragments and quality for one shell (see the module docstring)."""
    norads = np.array(shell.norads, dtype=np.int64)
    raan = np.array([raan_by_norad[int(n)] for n in norads])
    u = np.array([u_by_norad[int(n)] for n in norads])
    clusters = cluster_raans(raan, params.gap_for(shell.inclination_deg))
    sizes = np.array([len(c) for c in clusters])
    typical = _typical_plane_size(sizes)
    threshold = params.min_plane_fraction * typical

    plane_data, fragments = [], []
    for c in clusters:
        mean = elements.circular_mean_deg(raan[c])
        if len(c) >= threshold:
            plane_data.append((mean, c))
        else:
            fragments.append(Fragment(raan_deg=mean, norads=tuple(sorted(int(x) for x in norads[c]))))
    plane_data.sort(key=lambda item: item[0])
    fragments.sort(key=lambda f: f.raan_deg)

    planes = []
    for index, (mean, c) in enumerate(plane_data):
        # Slot order: ascending u; equal u (never in practice) falls back to NORAD id.
        order = sorted(c, key=lambda i: (u[i], norads[i]))
        u_sorted = np.array([u[i] for i in order])
        planes.append(Plane(
            plane_id=f"{shell.shell_id}/P{index:02d}", index=index, raan_deg=mean,
            raan_spread_deg=_circular_spread(raan[c]),
            norads=tuple(int(norads[i]) for i in order),
            u_deg=tuple(float(x) for x in u_sorted),
            slot_evenness=_slot_evenness(u_sorted)))
    if planes:
        centres = np.array([p.raan_deg for p in planes])
        linked = []
        for fragment in fragments:
            gaps = np.abs(elements.circular_difference_deg(fragment.raan_deg, centres))
            k = int(np.argmin(gaps))                     # ties -> lower plane index
            linked.append(Fragment(fragment.raan_deg, fragment.norads,
                                   planes[k].plane_id, float(gaps[k])))
        fragments = linked
    return tuple(planes), tuple(fragments), MappingProxyType(_quality(shell, planes, fragments))


def _quality(shell, planes, fragments):
    n_total = shell.count
    if not planes:
        return {"score": 0.0, "n_planes": 0, "n_fragments": len(fragments),
                "off_grid": n_total, "separation_ratio": None, "spacing_cv": None,
                "slot_evenness_median": None, "plane_size_min": None,
                "plane_size_median": None, "plane_size_max": None}
    centres = np.array([p.raan_deg for p in planes])
    spreads = np.array([p.raan_spread_deg for p in planes])
    sizes = np.array([p.size for p in planes])
    clean = 0
    if len(planes) == 1:
        clean = sizes[0]
        spacing = np.array([360.0])
        min_gap = None
    else:
        spacing = np.diff(np.concatenate([centres, [centres[0] + 360.0]]))   # centre to next centre
        nearest = np.minimum(spacing, np.roll(spacing, 1))                   # to either neighbour
        clean = int(sizes[spreads <= 0.5 * nearest].sum())
        # Edge-to-edge gap between neighbouring planes (centre spacing minus half spreads).
        edge_gaps = spacing - 0.5 * (spreads + np.roll(spreads, -1))
        min_gap = float(edge_gaps.min())
    max_spread = float(spreads.max())
    if min_gap is None:
        separation = None
    elif max_spread > 0:
        separation = round(min_gap / max_spread, 3)
    else:
        separation = None
    evenness = [p.slot_evenness for p in planes if np.isfinite(p.slot_evenness)]
    return {
        "score": round(clean / n_total, 4) if n_total else 0.0,
        "n_planes": len(planes),
        "n_fragments": len(fragments),
        "off_grid": int(sum(len(f.norads) for f in fragments)),
        "separation_ratio": separation,
        "spacing_cv": round(float(spacing.std() / spacing.mean()), 4),
        "slot_evenness_median": round(float(np.median(evenness)), 4) if evenness else None,
        "plane_size_min": int(sizes.min()),
        "plane_size_median": float(np.median(sizes)),
        "plane_size_max": int(sizes.max()),
    }


# --------------------------------------------------------------- main entry

def build_fleet_geometry(records, reference_ns, *, satrecs=None, shell_params=None,
                         plane_params=None):
    """Shells, planes and slots for a fleet at one reference instant.

    records       OmmRecord sequence (e.g. Fleet.records), one per NORAD id
    reference_ns  the common instant (UTC ns); normally the snapshot fetch time
    satrecs       optional NORAD -> Satrec (Fleet.satrecs) to skip re-initialising
    """
    shell_params = shell_params or ShellParams()
    plane_params = plane_params or PlaneParams()
    records = tuple(sorted(records, key=lambda r: r.norad))
    catalog = infer_shells(records, reference_ns, shell_params)
    by_norad = {r.norad: r for r in records}

    members = [n for shell in catalog.shells for n in shell.norads]
    raan_by_norad, u_by_norad = {}, {}
    if members:
        recs = [by_norad[n] for n in members]
        raan = elements.raan_at_deg([r.raan for r in recs], [r.epoch_ns for r in recs], reference_ns,
                                    [r.mean_motion for r in recs], [r.eccentricity for r in recs],
                                    [r.inclination for r in recs])
        state = SatelliteArray(recs, satrecs=satrecs).propagate([reference_ns], geodetic=False)
        if not state.ok.all():
            bad = [int(n) for n, ok in zip(state.norad, state.ok[:, 0]) if not ok]
            raise ValueError(f"SGP4 failed at the reference instant for NORAD {bad[:10]}")
        u = argument_of_latitude_deg(state.r_teme[:, 0], state.v_teme[:, 0])
        raan_by_norad = dict(zip(members, raan.tolist()))
        u_by_norad = dict(zip(members, u.tolist()))

    shells_out = []
    slots = {}
    for shell in catalog.shells:
        planes, fragments, quality = planes_for_shell(shell, raan_by_norad, u_by_norad, plane_params)
        shells_out.append(ShellGeometry(shell=shell, planes=planes, fragments=fragments, quality=quality))
        for plane in planes:
            for slot, n in enumerate(plane.norads):
                slots[n] = (shell, plane.plane_id, slot, "in_plane")
        for fragment in fragments:
            for n in fragment.norads:
                slots[n] = (shell, None, None, "off_grid")

    satellites = {}
    for r in records:
        layer = "dtc" if r.is_dtc else "broadband"
        alt = catalog.altitude_km[r.norad]
        if r.norad in slots:
            shell, plane_id, slot, status = slots[r.norad]
            satellites[r.norad] = SatelliteSlot(r.norad, r.name, layer, shell.shell_id, plane_id,
                                                slot, status, None, alt)
        else:
            satellites[r.norad] = SatelliteSlot(r.norad, r.name, layer, None, None, None,
                                                "in_transit", catalog.in_transit[r.norad], alt)
    return FleetGeometry(reference_ns=int(reference_ns), shells=tuple(shells_out),
                         satellites=MappingProxyType(satellites), catalog=catalog,
                         shell_params=shell_params, plane_params=plane_params)
