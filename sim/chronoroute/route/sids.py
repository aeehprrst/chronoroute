"""
sids.py
-------
The SID registry: which 16-bit Segment ID each node carries in a T-CRH
(spec/tcrh-v1.md section 7).

    0x0000 - 0xEFFF  satellites; for the real fleet a STABLE, APPEND-ONLY
                     registry keyed by NORAD catalogue number
    0xF000 - 0xFFFE  ground stations: ground station g -> 0xF000 + g
    0xFFFF           reserved

Why a registry instead of numbering satellites per snapshot: a satellite's
SID is what every forwarding table (CRH-FIB) is keyed by. If SIDs were
re-assigned at every orbit-data refresh, every satellite's table would have
to be re-uploaded every few hours (reviewer item 3). With a registry, a
satellite keeps its SID for life; new satellites get the next free SID, and
nothing is ever renumbered or removed. Ground stations work the same way,
keyed by city name, so "Chennai" is always the same g in every scenario.

The registry is data/static/sid_registry.json (committed). Satellite SIDs
start at 1, not 0: SID 0 would give the SID address fd00:: (ns-3 address plan
fd00::<sid>), which is the Subnet-Router anycast address of fd00::/64
(RFC 4291 section 2.6.1), an address better kept off any node.

File format (one entry per line, so `git diff` shows exactly what was appended):

    {
    "schema": "chronoroute.sid-registry/1",
    ...
    "satellites": [
    [1,44713],                <- [sid, NORAD id], sid = 1, 2, 3, ... in order
    ...
    ],
    "ground_stations": [
    [0,"Addis Ababa"],        <- [g, city name], g = 0, 1, 2, ... in order
    ...
    ]
    }
"""

import json
import os
import tempfile
from pathlib import Path

from ..proto import tcrh

SCHEMA = "chronoroute.sid-registry/1"
DEFAULT_PATH = Path(__file__).resolve().parents[3] / "data" / "static" / "sid_registry.json"
FIRST_SATELLITE_SID = 1
MAX_SATELLITE_SID = tcrh.SID_SATELLITE_MAX             # 0xEFFF
GROUND_BASE = tcrh.SID_GROUND_BASE                      # 0xF000
MAX_GROUND_G = tcrh.SID_GROUND_MAX - tcrh.SID_GROUND_BASE   # 0xFFE

DESCRIPTION = ("Stable, append-only T-CRH SID registry (spec/tcrh-v1.md section 7). "
               "satellites: [sid, NORAD_CAT_ID], sid 1..61439 in allocation order. "
               "ground_stations: [g, city name], SID = 0xF000 + g. "
               "Entries are never changed or removed; new ones are appended.")


class RegistryError(ValueError):
    """The registry file is malformed or would break the append-only rule."""


class SidRegistry:
    """In-memory registry; load(), ensure_*() (append), save()."""

    def __init__(self, satellites=(), ground_stations=(), path=None):
        self.path = Path(path) if path is not None else None
        self._sat = {}            # norad -> sid, in allocation order
        self._gs = {}             # name -> g, in allocation order
        self.added_satellites = []
        self.added_ground_stations = []
        for expect, (sid, norad) in enumerate(satellites, FIRST_SATELLITE_SID):
            if not isinstance(sid, int) or not isinstance(norad, int) or isinstance(norad, bool):
                raise RegistryError(f"satellite entry {[sid, norad]!r} must be two integers")
            if sid != expect:
                raise RegistryError(f"satellite SIDs must be {FIRST_SATELLITE_SID}, 2, 3, ... in order; "
                                    f"found {sid} where {expect} was expected")
            if sid > MAX_SATELLITE_SID:
                raise RegistryError(f"satellite SID {sid} is above 0x{MAX_SATELLITE_SID:04X}")
            if norad <= 0 or norad in self._sat:
                raise RegistryError(f"NORAD id {norad} is not positive or appears twice")
            self._sat[norad] = sid
        for expect, (g, name) in enumerate(ground_stations):
            if g != expect:
                raise RegistryError(f"ground stations must be numbered 0, 1, 2, ...; found {g} for {name!r}")
            if not isinstance(name, str) or not name or name in self._gs:
                raise RegistryError(f"ground station name {name!r} is empty or appears twice")
            if g > MAX_GROUND_G:
                raise RegistryError(f"ground station number {g} is above {MAX_GROUND_G}")
            self._gs[name] = g

    # ----- reading -----

    @classmethod
    def load(cls, path=None):
        path = Path(path) if path is not None else DEFAULT_PATH
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("schema") != SCHEMA:
            raise RegistryError(f"{path}: schema must be {SCHEMA!r}")
        return cls(satellites=[tuple(e) for e in doc["satellites"]],
                   ground_stations=[tuple(e) for e in doc["ground_stations"]], path=path)

    @classmethod
    def load_or_empty(cls, path=None):
        path = Path(path) if path is not None else DEFAULT_PATH
        if path.is_file():
            return cls.load(path)
        return cls(path=path)

    def __contains__(self, norad):
        return int(norad) in self._sat

    @property
    def n_satellites(self):
        return len(self._sat)

    @property
    def n_ground_stations(self):
        return len(self._gs)

    @property
    def changed(self):
        return bool(self.added_satellites or self.added_ground_stations)

    def satellite_sid(self, norad):
        """SID of a satellite (KeyError if it was never registered: call ensure_satellites)."""
        return self._sat[int(norad)]

    def ground_station_number(self, name):
        return self._gs[name]

    def ground_station_sid(self, name):
        return tcrh.ground_station_sid(self._gs[name])

    def satellites(self):
        """[(sid, norad), ...] in SID order."""
        return [(sid, norad) for norad, sid in self._sat.items()]

    def ground_stations(self):
        return [(g, name) for name, g in self._gs.items()]

    # ----- appending -----

    def ensure_satellites(self, norads):
        """Register every NORAD id not yet known; new ones get the next SIDs in NORAD order.

        Returns the newly added NORAD ids (sorted). Existing entries never change.
        """
        new = sorted({int(n) for n in norads} - set(self._sat))
        if new and FIRST_SATELLITE_SID + len(self._sat) + len(new) - 1 > MAX_SATELLITE_SID:
            raise RegistryError("the satellite SID space 0x0001-0xEFFF is full")
        for norad in new:
            if norad <= 0:
                raise RegistryError(f"NORAD id {norad} must be positive")
            self._sat[norad] = FIRST_SATELLITE_SID + len(self._sat)
        self.added_satellites.extend(new)
        return new

    def ensure_ground_stations(self, names):
        """Register city names not yet known (new ones numbered in name order)."""
        new = sorted(set(names) - set(self._gs))
        for name in new:
            if not isinstance(name, str) or not name:
                raise RegistryError(f"ground station name {name!r} must be a non-empty string")
            if len(self._gs) > MAX_GROUND_G:
                raise RegistryError("the ground-station SID space 0xF000-0xFFFE is full")
            self._gs[name] = len(self._gs)
        self.added_ground_stations.extend(new)
        return new

    # ----- writing -----

    def to_bytes(self):
        lines = ["{",
                 f'"schema": {json.dumps(SCHEMA)},',
                 f'"description": {json.dumps(DESCRIPTION)},',
                 f'"satellite_sid_first": {FIRST_SATELLITE_SID},',
                 f'"satellite_sid_max": {MAX_SATELLITE_SID},',
                 f'"ground_station_sid_base": {GROUND_BASE},',
                 '"satellites": [']
        sats = [f"[{sid},{norad}]" for sid, norad in self.satellites()]
        lines += [s + ("," if i < len(sats) - 1 else "") for i, s in enumerate(sats)]
        lines.append("],")
        lines.append('"ground_stations": [')
        gss = [f"[{g},{json.dumps(name, ensure_ascii=False)}]" for g, name in self.ground_stations()]
        lines += [s + ("," if i < len(gss) - 1 else "") for i, s in enumerate(gss)]
        lines.append("]")
        lines.append("}")
        return ("\n".join(lines) + "\n").encode("utf-8")

    def save(self, path=None):
        """Write atomically. Refuses to drop or change any entry already on disk."""
        path = Path(path) if path is not None else (self.path or DEFAULT_PATH)
        if path.is_file():
            old = SidRegistry.load(path)
            mine_sat, mine_gs = self.satellites(), self.ground_stations()
            if mine_sat[:old.n_satellites] != old.satellites() or \
                    mine_gs[:old.n_ground_stations] != old.ground_stations():
                raise RegistryError(f"{path}: refusing to write: the registry is append-only and "
                                    "this copy does not start with every entry already on disk")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(self.to_bytes())
            os.chmod(tmp, 0o644)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self.path = path
        self.added_satellites = []
        self.added_ground_stations = []
        return path


__all__ = ["SCHEMA", "DEFAULT_PATH", "FIRST_SATELLITE_SID", "MAX_SATELLITE_SID", "GROUND_BASE",
           "RegistryError", "SidRegistry"]
