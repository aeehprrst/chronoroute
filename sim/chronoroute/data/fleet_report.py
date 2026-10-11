"""
fleet_report.py
---------------
`cr fleet report <snapshot-dir>`: what is in an orbit snapshot, in numbers.

Prints, and writes as JSON (fleet_report.json + planes.json + manifest.json),
plus four PNG figures (fleet_figures.py; --no-figures skips them):

  * counts: raw objects, kept, excluded by reason, 6-digit NORAD ids  (REAL)
  * epoch ages at the fetch time                                       (REAL)
  * shells and the planes in each shell, with plane quality          (DERIVED)
  * satellites in transit (excluded from routing)                    (DERIVED)
  * GP vs SupGP disagreement: both element sets propagated to the same
    instant, distance between the two predicted positions            (DERIVED)
    This is a disagreement between two sources, NOT a measured error.
  * SATCAT operational-status codes, when the folder has the SATCAT    (REAL)

The snapshot folder is either a pinned CelesTrak download
(data/pinned/<id>/) or a website snapshot (manifest.json + omm.min.json).
"""

import csv
import dataclasses
import json
import sys
from pathlib import Path

import numpy as np

from .. import __version__, labels as labels_mod, provenance
from ..orbit import planes as planes_mod, shells as shells_mod
from ..orbit.propagate import SatelliteArray
from . import omm, snapshot

REPORT_SCHEMA = "chronoroute.fleet-report/1"
REPORT_FILE = "fleet_report.json"
PLANES_FILE = "planes.json"

# The shared label table (chronoroute/labels.py), so the same thing carries the
# same label here as in bundles, results and the website: SGP4 positions are
# REAL physics + REAL code on REAL elements (master plan section 2, row 2).
LABELS = labels_mod.pick("orbital_elements", "catalogue_names_and_ids", "epoch_ages", "satcat_status",
                         "satellite_positions_sgp4", "shells_and_planes", "in_transit_flags",
                         "gp_vs_supgp_disagreement")

# The acceptance check compares shell counts with a reference measured with a
# 10 km band; the count also depends on that band, so the report always shows
# the count for this narrower band too (a sensitivity, not a second answer).
SENSITIVITY_BAND_KM = 5.0

PERCENTILES = (50, 90, 95, 99)


def _stats(values, unit_suffix):
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return None
    out = {f"p{p}_{unit_suffix}": round(float(np.percentile(values, p)), 4) for p in PERCENTILES}
    out[f"min_{unit_suffix}"] = round(float(values.min()), 4)
    out[f"max_{unit_suffix}"] = round(float(values.max()), 4)
    return out


def epoch_ages(fleet):
    ages_h = np.array([(fleet.fetched_ns - r.epoch_ns) / 3.6e12 for r in fleet.records])
    out = _stats(ages_h, "h")
    out.update(fleet.epoch_summary())
    out["older_than_1_day"] = int(np.sum(ages_h > 24))
    return out


def gp_vs_supgp(supgp, gp, at_ns, distances_out=None):
    """Distance between the GP and SupGP predictions of each satellite at one instant.

    Both fleets are propagated with SGP4 to at_ns; the difference is taken in
    TEME. along_track is its component along the SupGP velocity (most of the
    disagreement is a satellite being a little ahead or behind). If
    distances_out is a list, every distance (km) is appended to it (for the
    figure).
    """
    common = sorted(set(r.norad for r in supgp.records) & set(r.norad for r in gp.records))
    if not common:
        return None
    a = SatelliteArray(supgp.records, satrecs=supgp.satrecs).subset(common).propagate([at_ns], geodetic=False)
    b = SatelliteArray(gp.records, satrecs=gp.satrecs).subset(common).propagate([at_ns], geodetic=False)
    ok = a.ok[:, 0] & b.ok[:, 0]
    d = b.r_teme[ok, 0] - a.r_teme[ok, 0]
    dist = np.linalg.norm(d, axis=1)
    if distances_out is not None:
        distances_out.extend(dist.tolist())
    v = a.v_teme[ok, 0]
    along = np.abs(np.einsum("ij,ij->i", d, v) / np.linalg.norm(v, axis=1))
    out = {"at_utc": omm.format_utc_ns(at_ns), "pairs": int(ok.sum()),
           "failed": int((~ok).sum()), "distance": _stats(dist, "km"),
           "along_track": _stats(along, "km"),
           "label": "DERIVED: disagreement between two sources, not a measured error"}
    return out


def satcat_status(folder, norads):
    """OPS_STATUS_CODE counts from starlink_satcat.csv for the given NORAD ids (None if absent)."""
    path = Path(folder) / snapshot.SOURCES["satcat"].raw_file
    if not path.is_file():
        return None
    wanted = set(norads)
    counts, matched = {}, 0
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                norad = int(row["NORAD_CAT_ID"])
            except (KeyError, ValueError):
                continue
            if norad in wanted:
                matched += 1
                code = row.get("OPS_STATUS_CODE", "") or "(blank)"
                counts[code] = counts.get(code, 0) + 1
    return {"file": path.name, "matched": matched, "ops_status_code": dict(sorted(counts.items()))}


def build_report(folder, source=None, distances_out=None):
    """Load a snapshot folder and compute everything. Returns (report, planes_doc, fleet, geometry).

    distances_out: optional list that receives every GP-SupGP distance (km), for the figure.
    """
    folder = Path(folder)
    layout = snapshot.detect_layout(folder)
    other = None
    if layout == "pinned":
        present = snapshot.available_sources(folder)
        if not present:
            raise ValueError(f"{folder}: no element-set file with its headers file")
        source = source or present[0]
        if source not in present:
            raise ValueError(f"{folder}: source {source!r} not present (have {present})")
        fleet = snapshot.load_pinned(folder, source)
        others = [s for s in present if s != source]
        if others:
            other = snapshot.load_pinned(folder, others[0])
    else:
        if source not in (None, "web"):
            raise ValueError("a website snapshot holds one source; do not pass --source")
        fleet = snapshot.load_web_snapshot(folder)

    geo = planes_mod.build_fleet_geometry(fleet.records, fleet.fetched_ns, satrecs=fleet.satrecs)
    # Band sensitivity: the same inference with a narrower altitude band.
    narrow_params = dataclasses.replace(geo.shell_params, band_km=SENSITIVITY_BAND_KM)
    narrow = shells_mod.infer_shells(fleet.records, fleet.fetched_ns, narrow_params)
    narrow_counts = {s.shell_id: s.count for s in narrow.shells}
    six = [r.norad for r in fleet.records if r.norad >= 100_000]
    in_transit = [geo.satellites[n] for n in geo.catalog.in_transit]
    by_norad = {r.norad: r for r in fleet.records}
    ndot = np.array([by_norad[s.norad].mean_motion_dot for s in in_transit]) if in_transit else np.array([])

    comparison = None
    if other is not None:
        sup, gp = (fleet, other) if fleet.source.key == "supgp" else (other, fleet)
        comparison = gp_vs_supgp(sup, gp, fleet.fetched_ns, distances_out)
        comparison["supgp_only"] = len(set(r.norad for r in sup.records) - set(r.norad for r in gp.records))
        comparison["gp_only"] = len(set(r.norad for r in gp.records) - set(r.norad for r in sup.records))

    report = {
        "schema": REPORT_SCHEMA,
        "labels": LABELS,
        "snapshot": {
            "folder": folder.name, "layout": layout, "snapshot_id": fleet.snapshot_id,
            "source": fleet.source.name, "source_url": fleet.source.url,
            "fetched_utc": fleet.fetched_utc, "http_date": fleet.http_date,
            "sha256_raw": fleet.sha256_raw, "attribution": fleet.source.attribution,
            "other_source": other.source.name if other is not None else None,
        },
        "reference_utc": omm.format_utc_ns(geo.reference_ns),
        "counts": {
            "raw": fleet.count_raw, "kept": fleet.count, "excluded": dict(fleet.excluded),
            "dtc": sum(r.is_dtc for r in fleet.records),
            "status": geo.status_counts(),
            "other_source": None if other is None else {
                "source": other.source.name, "raw": other.count_raw, "kept": other.count,
                "excluded": dict(other.excluded), "fetched_utc": other.fetched_utc},
        },
        "six_digit_ids": {
            "count": len(six), "min": min(six) if six else None, "max": max(six) if six else None,
            "in_shells": sum(1 for n in six if geo.satellites[n].shell_id is not None),
        },
        "epoch_age": epoch_ages(fleet),
        "inclination_histogram_0p1deg": [[deg, n] for deg, n in geo.catalog.inclination_histogram],
        "inclination_groups": list(geo.catalog.groups),
        "shells": [sg.as_dict(with_members=False) for sg in geo.shells],
        "band_sensitivity": {
            "band_km": geo.shell_params.band_km,
            "alternative_band_km": SENSITIVITY_BAND_KM,
            "counts": {sg.shell_id: {"band": sg.shell.count, "alternative": narrow_counts.get(sg.shell_id)}
                       for sg in geo.shells},
            "note": "shell membership depends on the altitude band; the reference counts were measured "
                    "with 10 km windows, the mean-element altitude has about +-5 km bias (DERIVED)",
        },
        "mode_pairs": list(geo.catalog.mode_pairs),
        "in_transit": {
            "count": len(in_transit), "by_reason": geo.catalog.in_transit_counts(),
            "mean_motion_dot_positive": int(np.sum(ndot > 0)),
            "mean_motion_dot_negative": int(np.sum(ndot < 0)),
            "note": "outside every shell band; excluded from routing",
        },
        "gp_vs_supgp": comparison,
        "satcat": satcat_status(folder, list(by_norad)) if layout == "pinned" else None,
        "parameters": {"shells": geo.shell_params.as_dict(), "planes": geo.plane_params.as_dict(),
                       "max_epoch_age_days": omm.MAX_EPOCH_AGE_DAYS},
    }
    planes_doc = {
        "schema": "chronoroute.fleet-planes/1",
        "label": "DERIVED: shells and planes inferred from REAL element sets",
        "snapshot_id": fleet.snapshot_id, "source": fleet.source.name,
        "reference_utc": omm.format_utc_ns(geo.reference_ns),
        "shells": [sg.as_dict(with_members=True) for sg in geo.shells],
        "satellites": [geo.satellites[n].as_dict() for n in sorted(geo.satellites)],
    }
    return report, planes_doc, fleet, geo


def format_report(report):
    """The human-readable printout."""
    snap, counts = report["snapshot"], report["counts"]
    lines = []
    add = lines.append
    add(f"ChronoRoute fleet report  (snapshot {snap['folder']}, {snap['layout']})")
    add(f"  source       {snap['source']}  [REAL]  fetched {snap['fetched_utc']} (HTTP Date)")
    add(f"  attribution  {snap['attribution']}")
    ex = counts["excluded"]
    add(f"  objects      {counts['raw']:,} raw -> {counts['kept']:,} kept;"
        f" excluded: stale_epoch {ex['stale_epoch']}, sgp4_error {ex['sgp4_error']},"
        f" invalid {ex['invalid']}, duplicate {ex['duplicate']}")
    six = report["six_digit_ids"]
    add(f"  6-digit ids  {six['count']} (NORAD {six['min']}..{six['max']}), {six['in_shells']} of them in shells")
    add(f"  DTC          {counts['dtc']} satellites named [DTC]")
    age = report["epoch_age"]
    add(f"  epoch age    min {age['min_h']:.1f} h, median {age['p50_h']:.1f} h, p90 {age['p90_h']:.1f} h,"
        f" max {age['max_h']:.1f} h  ({age['older_than_1_day']} older than 1 day)")
    add(f"               epochs {age['epoch_min']} .. {age['epoch_max']} (median {age['epoch_median']})")
    other = counts["other_source"]
    if other:
        oex = other["excluded"]
        add(f"  also         {other['source']}: {other['raw']:,} raw -> {other['kept']:,} kept"
            f" (stale_epoch {oex['stale_epoch']}, sgp4_error {oex['sgp4_error']},"
            f" invalid {oex['invalid']}, duplicate {oex['duplicate']}), fetched {other['fetched_utc']}")
    add("")
    band = report["band_sensitivity"]
    alt_band = band["alternative_band_km"]
    add(f"Shells and planes [DERIVED, inferred]  at {report['reference_utc']}")
    add(f"  {'shell':22s} {'layer':9s} {'inc':>7s} {'alt km':>7s} {'sats':>5s} {f'+-{alt_band:g}km':>7s}"
        f" {'planes':>6s} {'sats/plane':>12s} {'off-grid':>8s} {'quality':>7s}  notes")
    for s in report["shells"]:
        q = s["quality"]
        sizes = (f"{q['plane_size_min']}/{q['plane_size_median']:g}/{q['plane_size_max']}"
                 if q["n_planes"] else "-")
        note = f"shares planes with {s['shares_planes_with']}" if s["shares_planes_with"] else ""
        if len(s["modes_km"]) > 1:
            note = (note + "; " if note else "") + "merged modes " + "+".join(f"{m:g}" for m in s["modes_km"])
        narrow = band["counts"].get(s["shell_id"], {}).get("alternative")
        narrow_txt = "-" if narrow is None else str(narrow)
        add(f"  {s['shell_id']:22s} {s['layer']:9s} {s['inclination_deg']:7.2f} {s['altitude_km']:7.1f}"
            f" {s['count']:5d} {narrow_txt:>7s} {q['n_planes']:6d} {sizes:>12s} {q['off_grid']:8d}"
            f" {q['score']:7.3f}  {note}")
    add("  (sats/plane = min/median/max; quality = share of satellites in cleanly separated planes)")
    add(f"  altitude band +-{band['band_km']:g} km (parameter band_km, the window the reference counts used);"
        f" the +-{alt_band:g}km column is the same")
    add("  inference with a narrower band, to show how much a count depends on it (mean-element altitudes"
        " carry ~+-5 km bias)")
    planes_par = report["parameters"]["planes"]
    overrides = ", ".join(f"{i:g} deg: {g:g} deg" for i, g in planes_par["gap_deg_by_inclination"])
    add(f"  planes: RAAN gap {planes_par['gap_deg']:g} deg ({overrides}: twin planes merged); clusters"
        f" smaller than {planes_par['min_plane_fraction']:g} x the typical plane are off-grid fragments."
        " Plane counts are inferred, not published.")
    tr = report["in_transit"]
    add(f"  in transit   {tr['count']} satellites, excluded from routing: "
        + ", ".join(f"{k} {v}" for k, v in tr["by_reason"].items())
        + f"  (n-dot > 0: {tr['mean_motion_dot_positive']}, < 0: {tr['mean_motion_dot_negative']})")
    add(f"  status       " + ", ".join(f"{k} {v}" for k, v in counts["status"].items()))
    cmp_ = report["gp_vs_supgp"]
    add("")
    if cmp_:
        d, a = cmp_["distance"], cmp_["along_track"]
        add(f"GP vs SupGP disagreement [DERIVED; not an error measurement]  at {cmp_['at_utc']}")
        add(f"  {cmp_['pairs']:,} satellites in both: median {d['p50_km']:.2f} km, p90 {d['p90_km']:.2f} km,"
            f" p95 {d['p95_km']:.2f} km, p99 {d['p99_km']:.1f} km, max {d['max_km']:.1f} km")
        add(f"  along-track part: median {a['p50_km']:.2f} km;  SupGP only {cmp_['supgp_only']}, GP only {cmp_['gp_only']}")
    else:
        add("GP vs SupGP disagreement: not available (the snapshot has one source)")
    sat = report["satcat"]
    if sat:
        add(f"SATCAT OPS_STATUS_CODE [REAL] for the {sat['matched']:,} kept objects found in the SATCAT: "
            + ", ".join(f"{k} {v}" for k, v in sat["ops_status_code"].items()))
    return "\n".join(lines)


def _json_bytes(doc, indent=1):
    """JSON as UTF-8 bytes. NaN is refused (allow_nan=False): JSON cannot hold it."""
    separators = None if indent is not None else (",", ":")
    return (json.dumps(doc, indent=indent, separators=separators, ensure_ascii=False,
                       allow_nan=False) + "\n").encode("utf-8")


def write_report(folder, out_dir, *, source=None, command=None, stream=None, figures=True):
    """Compute the report, print it, write the JSON files (and figures) with their provenance manifest."""
    stream = stream if stream is not None else sys.stdout
    with provenance.RunTimer() as timer:
        distances = []
        report, planes_doc, fleet, _ = build_report(folder, source, distances_out=distances)
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        report_path, planes_path = out_dir / REPORT_FILE, out_dir / PLANES_FILE
        snapshot.atomic_write(report_path, _json_bytes(report))
        snapshot.atomic_write(planes_path, _json_bytes(planes_doc, indent=None))   # large: compact
        figure_paths = []
        if figures:
            from . import fleet_figures            # matplotlib only when figures are wanted
            figure_paths = fleet_figures.write_figures(out_dir, report, planes_doc, distances)
    print(format_report(report), file=stream)
    if fleet.layout == "pinned":
        snap = provenance.snapshot_from_dir(folder)
    else:
        omm_path = Path(folder) / snapshot.WEB_OMM
        snap = {"id": fleet.snapshot_id, "sha256": snapshot.sha256_bytes(omm_path.read_bytes()),
                "sha256_of": snapshot.WEB_OMM}
    config = {"snapshot_dir": Path(folder).name, "source": report["snapshot"]["source"],
              "parameters": report["parameters"]}
    manifest = provenance.write_manifest(
        out_dir, tool="cr fleet report", tool_version=__version__,
        command=command or ["cr", "fleet", "report", str(folder)], config=config, seeds=[],
        snapshot=snap, outputs=[report_path, planes_path, *figure_paths], labels=LABELS,
        extra={"report_schema": REPORT_SCHEMA, "figures": [p.name for p in figure_paths]}, timer=timer)
    print(f"\nwrote {report_path}, {planes_path} and {manifest}", file=stream)
    if figure_paths:
        print("figures: " + ", ".join(p.name for p in figure_paths), file=stream)
    return report


# ------------------------------------------------------------------ CLI hook

def _run(args):
    folder = Path(args.snapshot_dir)
    out = Path(args.out) if args.out else Path("fleet-report") / f"{folder.resolve().name}-{args.source or 'auto'}"
    write_report(folder, out, source=args.source, command=["cr", *args.argv], figures=not args.no_figures)
    return 0


def register(registry):
    """Add `cr fleet report` (see chronoroute.cli)."""
    parser = registry.command(
        "fleet", "report", help="counts, epoch ages, shells, planes and GP-vs-SupGP for a snapshot",
        func=_run, group_help="the real fleet: reports on orbit snapshots")
    parser.add_argument("snapshot_dir", help="data/pinned/<id>/ or a website snapshot folder")
    parser.add_argument("--source", choices=["supgp", "gp"], default=None,
                        help="pinned folders only: which element sets to analyse (default: SupGP if present)")
    parser.add_argument("--out", default=None,
                        help="output folder (default: ./fleet-report/<snapshot>-<source>/)")
    parser.add_argument("--no-figures", action="store_true",
                        help="JSON only: skip the PNG figures (shells, planes, 6-digit ids, GP vs SupGP)")
