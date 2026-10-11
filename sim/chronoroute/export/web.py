"""
web.py
------
Two extra files for the website, written into a website snapshot folder next
to the data owner's manifest.json + omm.min.json (web/DATA_CONTRACT.md):

    snapshots/<id>/shells.json      shells and planes (DERIVED)
    snapshots/<id>/isl_grid4.json   Grid-4 laser-link pairs per shell (MODELLED)

Same rules as the contract: plain JSON, UTF-8, a "schema" string, no
"generated at" time stamp (same input -> byte-identical output), NORAD ids as
numbers (they can have six digits), satellites identified only by NORAD id.

Both files describe the snapshot's reference instant = its fetched_utc
(the plane slots and the Grid-4 pairs are chosen then). The pairs do not
change during a visit; the website decides per frame whether each pair is
drawn as up, with the same rules as the Python model (written into
isl_grid4.json under "rules"): cross-plane pairs are off while either end is
above |lat| 70 deg, and any pair whose straight line dips below 80 km above
WGS84 is off.

A provenance manifest (provenance.write_manifest) is written to
snapshots/<id>/provenance-topo/manifest.json, because the folder's own
manifest.json is the website contract's file and must not be replaced.
"""

import json
from pathlib import Path

from .. import __version__, labels as labels_mod, provenance
from ..data import omm, snapshot
from ..orbit import planes as planes_mod
from ..topo import isl_grid4

SHELLS_FILE = "shells.json"
ISL_FILE = "isl_grid4.json"
SHELLS_SCHEMA = "chronoroute.web-shells/1"
ISL_SCHEMA = "chronoroute.web-isl-grid4/1"
PROVENANCE_DIR = "provenance-topo"

LABELS = labels_mod.pick("orbital_elements", "shells_and_planes", "isl_topology_grid4")


def _compact(doc):
    """Compact JSON + newline (the files are fetched by browsers; size matters)."""
    return (json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def shells_doc(fleet, geo):
    shells = []
    for sg in geo.shells:
        s = sg.shell
        shells.append({
            "shell_id": s.shell_id,
            "layer": s.layer,
            "inclination_deg": round(s.inclination_deg, 4),
            "altitude_km": round(s.altitude_km, 2),
            "count": s.count,
            "n_planes": len(sg.planes),
            "off_grid": sum(len(f.norads) for f in sg.fragments),
            "quality": round(float(sg.quality["score"]), 4),
            "shares_planes_with": s.shares_planes_with,
            "planes": [list(p.norads) for p in sg.planes],
            "off_grid_norads": sorted(n for f in sg.fragments for n in f.norads),
        })
    return {
        "schema": SHELLS_SCHEMA,
        "snapshot_id": fleet.snapshot_id,
        "reference_utc": omm.format_utc_ns(geo.reference_ns),
        "label": "DERIVED",
        "note": "Shells and orbital planes inferred from the REAL element sets; SpaceX does not "
                "publish them. planes: NORAD ids in slot order (ascending argument of latitude "
                "at reference_utc). off_grid_norads: in the shell but in no plane.",
        "parameters": {"shells": geo.shell_params.as_dict(), "planes": geo.plane_params.as_dict()},
        "shells": shells,
        "in_transit": sorted(geo.catalog.in_transit),
    }


def isl_doc(fleet, geo, params=None):
    params = params or isl_grid4.Grid4Params()
    shells = []
    for sg in geo.shells:
        pairs = isl_grid4.grid4_pairs(sg, geo.reference_ns, params)
        intra = [[int(a), int(b)] for a, b, k in zip(pairs.a, pairs.b, pairs.kind) if k == isl_grid4.INTRA]
        cross = [[int(a), int(b)] for a, b, k in zip(pairs.a, pairs.b, pairs.kind) if k == isl_grid4.CROSS]
        shells.append({"shell_id": sg.shell_id, "layer": sg.shell.layer,
                       "max_cross_du_deg": round(pairs.max_cross_du_deg, 6),
                       "intra": intra, "cross": cross})
    return {
        "schema": ISL_SCHEMA,
        "snapshot_id": fleet.snapshot_id,
        "reference_utc": omm.format_utc_ns(geo.reference_ns),
        "label": "MODELLED",
        "note": "Grid-4 laser links: 2 intra-plane (ring by argument of latitude) + 2 cross-plane "
                "(one-to-one nearest-u matching with each adjacent plane, |du| <= max_cross_du_deg), "
                "degree <= 4, no links between shells. Starlink's real laser topology is not public.",
        "model": {"name": isl_grid4.MODEL_NAME, **params.as_dict(), "max_degree": isl_grid4.MAX_DEGREE,
                  "inter_shell_links": False},
        "rules": {
            "pairs": "fixed for the snapshot (chosen at reference_utc); [a, b] NORAD ids, a < b",
            "cross_polar_cutoff": "a cross pair is down while |geodetic latitude| of either end > polar_cutoff_deg",
            "grazing": "any pair is down while the straight line between the two satellites comes "
                       "closer than min_grazing_alt_km to the WGS84 ellipsoid",
            "range": "when max_range_km is not null, any pair is down while the two satellites are "
                     "more than max_range_km apart (null: no limit besides grazing)",
        },
        "shells": shells,
    }


def export_web(fleet, snapshot_dir, *, command, grid_params=None):
    """Write shells.json, isl_grid4.json and their provenance into snapshot_dir."""
    snapshot_dir = Path(snapshot_dir)
    grid_params = grid_params or isl_grid4.Grid4Params()
    with provenance.RunTimer() as timer:
        geo = planes_mod.build_fleet_geometry(fleet.records, fleet.fetched_ns, satrecs=fleet.satrecs)
        shells_path = snapshot_dir / SHELLS_FILE
        isl_path = snapshot_dir / ISL_FILE
        snapshot.atomic_write(shells_path, _compact(shells_doc(fleet, geo)))
        snapshot.atomic_write(isl_path, _compact(isl_doc(fleet, geo, grid_params)))
    if fleet.layout == "pinned":
        snap = provenance.snapshot_from_dir(fleet.folder)
    else:
        omm_path = Path(fleet.folder) / snapshot.WEB_OMM
        snap = {"id": fleet.snapshot_id, "sha256": snapshot.sha256_bytes(omm_path.read_bytes()),
                "sha256_of": snapshot.WEB_OMM}
    config = {"snapshot_id": fleet.snapshot_id, "source": fleet.source.name,
              "reference_utc": omm.format_utc_ns(geo.reference_ns),
              "shell_params": geo.shell_params.as_dict(), "plane_params": geo.plane_params.as_dict(),
              "isl_model": grid_params.as_dict()}
    manifest = provenance.write_manifest(
        snapshot_dir / PROVENANCE_DIR, tool="cr export web", tool_version=__version__, command=command,
        config=config, seeds=[], snapshot=snap, outputs=[shells_path, isl_path], labels=LABELS,
        extra={"files": {"shells": SHELLS_FILE, "isl_grid4": ISL_FILE}}, timer=timer)
    return {"shells": shells_path, "isl_grid4": isl_path, "manifest": manifest, "geometry": geo}


__all__ = ["SHELLS_FILE", "ISL_FILE", "SHELLS_SCHEMA", "ISL_SCHEMA", "PROVENANCE_DIR", "LABELS",
           "shells_doc", "isl_doc", "export_web"]
