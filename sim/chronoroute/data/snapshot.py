"""
snapshot.py
-----------
Orbit snapshots: load them, and write the website's copy.

Two folder layouts are read:

  pinned   data/pinned/<YYYYMMDDTHHMMZ>-celestrak/ as downloaded by
           pipeline/fetch.py: the raw CelesTrak files (starlink_supgp.json,
           starlink_gp.json, ...), the saved HTTP response headers
           (*_headers.txt, whose Date header is the fetch time) and SHA256SUMS.
  web      a website snapshot, snapshots/<id>/manifest.json + omm.min.json,
           in the format of web/DATA_CONTRACT.md (written by
           write_web_snapshot below, i.e. by pipeline/slim.py).

Either way you get a Fleet: the screened element sets plus where they came
from. The fetch time always comes from the HTTP Date header, never from the
clock of the machine doing the conversion, so the same input always gives the
same output (the website contract requires byte-identical reruns).
"""

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from types import MappingProxyType

import sgp4

from . import omm

WEB_SCHEMA = "chronoroute.web-snapshot/1"
WEB_MANIFEST = "manifest.json"
WEB_OMM = "omm.min.json"
LATEST = "latest.json"
SHA256SUMS = "SHA256SUMS"


@dataclass(frozen=True)
class SourceInfo:
    """One CelesTrak product and how it is stored in a pinned folder."""

    key: str              # short id used in snapshot ids: "supgp", "gp", "satcat"
    name: str             # human name for the manifest / website badge
    url: str              # the exact URL that is downloaded (FORMAT always given)
    raw_file: str         # file name inside data/pinned/<id>/
    headers_file: str     # saved HTTP response headers
    attribution: str      # shown verbatim on the website


SOURCES = MappingProxyType({
    "supgp": SourceInfo(
        key="supgp", name="CelesTrak SupGP",
        url="https://celestrak.org/NORAD/elements/supplemental/sup-gp.php?FILE=starlink&FORMAT=json",
        raw_file="starlink_supgp.json", headers_file="supgp_headers.txt",
        attribution="Orbit data courtesy of CelesTrak (celestrak.org); "
                    "SupGP elements derived from SpaceX ephemerides."),
    "gp": SourceInfo(
        key="gp", name="CelesTrak GP",
        url="https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=json",
        raw_file="starlink_gp.json", headers_file="gp_json_headers.txt",
        attribution="Orbit data courtesy of CelesTrak (celestrak.org); "
                    "GP elements from 18 SDS via CelesTrak."),
    "satcat": SourceInfo(
        key="satcat", name="CelesTrak SATCAT",
        url="https://celestrak.org/satcat/records.php?GROUP=starlink&FORMAT=csv",
        raw_file="starlink_satcat.csv", headers_file="satcat_headers.txt",
        attribution="Satellite catalogue courtesy of CelesTrak (celestrak.org)."),
})
OMM_SOURCES = ("supgp", "gp")          # the two element-set products (SupGP is primary)


# ------------------------------------------------------------- small helpers

def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def read_http_date(headers_path):
    """(raw Date header value, fetch time in UTC ns) from a saved header block."""
    text = Path(headers_path).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        name, sep, value = line.partition(":")
        if sep and name.strip().lower() == "date":
            raw = value.strip()
            moment = parsedate_to_datetime(raw)
            if moment.tzinfo is None:
                raise ValueError(f"{headers_path}: Date header {raw!r} has no time zone")
            return raw, omm.datetime_to_ns(moment)
    raise ValueError(f"{headers_path}: no Date header (the fetch time must come from it)")


def read_sha256sums(path):
    """{file name: sha256} from a coreutils SHA256SUMS file."""
    sums = {}
    for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", line)
        if not match:
            raise ValueError(f"{path}:{lineno}: not a sha256sum line")
        sums[match.group(2)] = match.group(1).lower()
    return sums


def snapshot_stamp(ns):
    """UTC ns -> 'YYYYMMDDTHHMMZ' (minute resolution, as in snapshot ids)."""
    text = omm.format_utc_ns(ns)                    # 2026-10-10T14:02:22Z
    return f"{text[0:4]}{text[5:7]}{text[8:10]}T{text[11:13]}{text[14:16]}Z"


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------- Fleet

@dataclass(frozen=True)
class Fleet:
    """Screened element sets of one source, plus their provenance.

    records    OmmRecord tuple, sorted by NORAD id, one per id
    satrecs    NORAD id -> sgp4 Satrec (already initialised)
    excluded   counts per reason (contract order); `exclusions` has the
               individual objects when the raw file was screened here
    fetched_ns download time (UTC ns) from the HTTP Date header
    """

    source: SourceInfo
    layout: str                    # "pinned" or "web"
    folder: Path
    snapshot_id: str
    fetched_ns: int
    http_date: str
    sha256_raw: str
    count_raw: int
    records: tuple
    excluded: MappingProxyType
    exclusions: tuple = ()
    satrecs: MappingProxyType = field(default=MappingProxyType({}), repr=False, compare=False)
    screen: object = field(default=None, repr=False, compare=False)

    @property
    def fetched_utc(self):
        return omm.format_utc_ns(self.fetched_ns)

    @property
    def count(self):
        return len(self.records)

    def epoch_summary(self):
        return omm.epoch_summary(self.records)


def load_pinned(folder, source="supgp", *, verify_sha256=True,
                max_epoch_age_days=omm.MAX_EPOCH_AGE_DAYS):
    """Screen one raw OMM file of a pinned download folder.

    The raw file must match SHA256SUMS when that file exists (a snapshot that
    was edited after download must never be used silently).
    """
    folder = Path(folder)
    info = SOURCES[source]
    if source not in OMM_SOURCES:
        raise ValueError(f"{source!r} is not an element-set source")
    raw_path = folder / info.raw_file
    raw = raw_path.read_bytes()
    sha = sha256_bytes(raw)
    sums_path = folder / SHA256SUMS
    if verify_sha256 and sums_path.is_file():
        expected = read_sha256sums(sums_path).get(info.raw_file)
        if expected is None:
            raise ValueError(f"{sums_path} has no line for {info.raw_file}")
        if expected != sha:
            raise ValueError(f"sha256 mismatch for {raw_path}: SHA256SUMS {expected}, file {sha}")
    http_date, fetched_ns = read_http_date(folder / info.headers_file)
    screen = omm.screen_objects(omm.parse_omm_json(raw), fetched_ns,
                                max_epoch_age_days=max_epoch_age_days)
    return Fleet(source=info, layout="pinned", folder=folder, snapshot_id=folder.name,
                 fetched_ns=fetched_ns, http_date=http_date, sha256_raw=sha,
                 count_raw=screen.count_raw, records=screen.kept,
                 excluded=MappingProxyType(screen.excluded), exclusions=screen.exclusions,
                 satrecs=screen.satrecs, screen=screen)


def load_web_snapshot(folder):
    """Load a website snapshot folder (manifest.json + omm.min.json).

    The rows are already screened, so any invalid row, duplicate id or SGP4
    failure here is an error rather than an exclusion.
    """
    folder = Path(folder)
    problems = check_web_snapshot(folder)
    if problems:
        raise ValueError(f"{folder}: not a valid website snapshot: " + "; ".join(problems))
    manifest = json.loads((folder / WEB_MANIFEST).read_text(encoding="utf-8"))
    table = omm.loads_keep_numbers((folder / _omm_file_name(manifest)).read_bytes())
    fields = table["fields"]
    objects = [{name: value for name, value in zip(fields, row) if value is not None}
               for row in table["rows"]]
    records = omm.records_from_objects(objects)
    # fetched_utc has the EPOCH layout plus "Z", so the exact EPOCH parser reads it.
    fetched_ns = omm.parse_epoch_ns(manifest["fetched_utc"][:-1])
    jd, fr = omm.ns_to_jd(fetched_ns)
    satrecs = {}
    for record in records:
        problem, sat = omm.sgp4_problem(record, jd, fr)
        if problem is not None:
            raise ValueError(f"{folder}: NORAD {record.norad}: {problem}")
        satrecs[record.norad] = sat
    key = next((k for k, s in SOURCES.items() if s.name == manifest["source"]), None)
    info = SOURCES[key] if key else SourceInfo(
        key="unknown", name=manifest["source"], url=manifest["source_url"],
        raw_file=manifest.get("raw_file") or "", headers_file="", attribution=manifest["attribution"])
    excluded = dict.fromkeys(omm.EXCLUSION_REASONS, 0)
    excluded.update({k: int(v) for k, v in manifest["excluded"].items() if k in excluded})
    return Fleet(source=info, layout="web", folder=folder, snapshot_id=manifest["snapshot_id"],
                 fetched_ns=fetched_ns, http_date=manifest["http_date"],
                 sha256_raw=manifest["sha256_raw"],
                 count_raw=int(manifest.get("count_raw", len(records) + sum(excluded.values()))),
                 records=records, excluded=MappingProxyType(excluded), satrecs=MappingProxyType(satrecs))


def detect_layout(folder):
    folder = Path(folder)
    if (folder / WEB_MANIFEST).is_file() and (folder / WEB_OMM).is_file():
        return "web"
    if any((folder / SOURCES[k].raw_file).is_file() for k in OMM_SOURCES):
        return "pinned"
    raise ValueError(f"{folder}: neither a pinned download folder nor a website snapshot")


def load_snapshot(folder, source="supgp"):
    """Load either layout. For a pinned folder, `source` picks SupGP (default) or GP."""
    if detect_layout(folder) == "web":
        return load_web_snapshot(folder)
    return load_pinned(folder, source)


# Sanity limits for one Starlink download (plan P2 "validate.py"). Today's
# files hold 11,103 (GP) and 11,130 (SupGP) objects.
COUNT_RANGE = (10_000, 13_000)
MAX_INVALID_FRACTION = 0.01


def validate_pinned(folder, source="supgp", *, count_range=COUNT_RANGE,
                    max_invalid_fraction=MAX_INVALID_FRACTION):
    """Check one downloaded OMM file before it is used. Returns a dict:

        ok        True when there are no problems
        problems  reasons to reject the download: unreadable or not JSON,
                  sha256 mismatch, no Date header, object count outside
                  count_range (raw or kept), more than 1% invalid objects
        warnings  things that are counted and excluded but do not reject the
                  file (stale epochs, SGP4 errors, duplicates, a few invalid)
        counts    raw / kept / excluded per reason
        fleet     the loaded Fleet (None when it could not be loaded)

    NORAD ids are unique after screening by construction (duplicates keep the
    newest EPOCH), so a duplicate in the raw file is a warning, not a problem.
    """
    problems, warnings = [], []
    try:
        fleet = load_pinned(folder, source)
    except (OSError, ValueError) as exc:          # OmmFormatError is a ValueError
        return {"ok": False, "problems": [str(exc)], "warnings": [], "counts": None, "fleet": None}
    lo, hi = count_range
    if not lo <= fleet.count_raw <= hi:
        problems.append(f"{fleet.count_raw} objects in the raw file, expected {lo}..{hi}")
    if not lo <= fleet.count <= hi:
        problems.append(f"{fleet.count} usable element sets, expected {lo}..{hi}")
    invalid = fleet.excluded["invalid"]
    if invalid > max_invalid_fraction * fleet.count_raw:
        problems.append(f"{invalid} invalid objects (more than {max_invalid_fraction:.0%})")
    for reason in omm.EXCLUSION_REASONS:
        if fleet.excluded[reason]:
            warnings.append(f"{fleet.excluded[reason]} excluded as {reason}")
    if len({r.norad for r in fleet.records}) != fleet.count:      # cannot happen; checked anyway
        problems.append("NORAD ids are not unique after screening")
    counts = {"raw": fleet.count_raw, "kept": fleet.count, "excluded": dict(fleet.excluded)}
    return {"ok": not problems, "problems": problems, "warnings": warnings, "counts": counts,
            "fleet": fleet}


def available_sources(folder):
    """Element-set sources present in a pinned folder, primary first."""
    folder = Path(folder)
    return [k for k in OMM_SOURCES if (folder / SOURCES[k].raw_file).is_file()
            and (folder / SOURCES[k].headers_file).is_file()]


# ------------------------------------------------- website snapshot writer

def default_web_snapshot_id(fleet):
    """'<YYYYMMDDTHHMMZ of fetched_utc>-<source>', the production naming rule."""
    return f"{snapshot_stamp(fleet.fetched_ns)}-{fleet.source.key}"


def _json_text(value):
    """A JSON string exactly as JavaScript's JSON.stringify writes it (UTF-8, not ASCII-escaped)."""
    return json.dumps(value, ensure_ascii=False)


def omm_min_bytes(records):
    """omm.min.json bytes: {"fields": [...], "rows": [[...], ...]} plus a newline.

    Every number is the exact text CelesTrak wrote (record.tokens), so the
    website gets the source values verbatim; strings are JSON-escaped;
    a field the source object did not have becomes null.
    """
    parts = ['{"fields":[', ",".join(_json_text(f) for f in omm.OMM_FIELDS), '],"rows":[']
    rows = []
    for record in sorted(records, key=lambda r: r.norad):
        cells = []
        for name in omm.OMM_FIELDS:
            if name in record.tokens:
                cells.append(record.tokens[name])
            elif name in record.values:
                cells.append(_json_text(record.values[name]))
            else:
                cells.append("null")
        rows.append("[" + ",".join(cells) + "]")
    parts.append(",".join(rows))
    parts.append("]}\n")
    return "".join(parts).encode("utf-8")


def pipeline_identifier(repo_dir=None):
    """'chronoroute-pipeline <commit>' (+ ' dirty' when the tree has local changes)."""
    from .. import provenance
    state = provenance.git_state(repo_dir)
    if state["sha"] is None:
        return "chronoroute-pipeline (commit unknown)"
    return f"chronoroute-pipeline {state['sha']}" + (" dirty" if state["dirty"] else "")


def web_manifest(fleet, snapshot_id, pipeline):
    """The manifest dict, keys in the order of web/DATA_CONTRACT.md (no time stamp of its own)."""
    if fleet.layout != "pinned":
        raise ValueError("a website snapshot is written from a pinned raw download")
    epochs = fleet.epoch_summary()
    max_age = fleet.screen.max_epoch_age_days
    max_age = int(max_age) if float(max_age).is_integer() else float(max_age)
    return {
        "schema": WEB_SCHEMA,
        "snapshot_id": snapshot_id,
        "source": fleet.source.name,
        "source_url": fleet.source.url,
        "fetched_utc": fleet.fetched_utc,
        "http_date": fleet.http_date,
        "count": fleet.count,
        "count_raw": fleet.count_raw,
        "epoch_min": epochs["epoch_min"],
        "epoch_median": epochs["epoch_median"],
        "epoch_max": epochs["epoch_max"],
        "max_epoch_age_days": max_age,
        "raw_file": fleet.source.raw_file,
        "sha256_raw": fleet.sha256_raw,
        "excluded": {
            "stale_epoch": fleet.excluded["stale_epoch"],
            "sgp4_error": fleet.excluded["sgp4_error"],
            "invalid": fleet.excluded["invalid"],
            "duplicate": fleet.excluded["duplicate"],
        },
        "sgp4_check": {"library": "python-sgp4", "version": sgp4.__version__,
                       "at_utc": fleet.fetched_utc},
        "attribution": fleet.source.attribution,
        "pipeline": pipeline,
        "files": {"omm": WEB_OMM},
    }


def write_web_snapshot(fleet, out_root, *, snapshot_id=None, pipeline=None, update_latest=True):
    """Write <out_root>/snapshots/<id>/{manifest.json, omm.min.json} (+ latest.json).

    out_root is the website's data directory (public/data/). Returns a dict
    with the written paths and the manifest. Files are written atomically.
    """
    out_root = Path(out_root)
    snapshot_id = snapshot_id or default_web_snapshot_id(fleet)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", snapshot_id):
        raise ValueError(f"snapshot id {snapshot_id!r} may only use A-Z a-z 0-9 . _ -")
    pipeline = pipeline or pipeline_identifier()
    manifest = web_manifest(fleet, snapshot_id, pipeline)
    snap_dir = out_root / "snapshots" / snapshot_id
    omm_path = snap_dir / WEB_OMM
    manifest_path = snap_dir / WEB_MANIFEST
    atomic_write(omm_path, omm_min_bytes(fleet.records))
    atomic_write(manifest_path, (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    written = {"snapshot_dir": snap_dir, "omm": omm_path, "manifest": manifest_path,
               "manifest_dict": manifest}
    if update_latest:
        latest = {"snapshot_id": snapshot_id, "path": f"snapshots/{snapshot_id}/"}
        latest_path = out_root / LATEST
        atomic_write(latest_path, (json.dumps(latest, indent=2) + "\n").encode("utf-8"))
        written["latest"] = latest_path
    return written


# --------------------------------------------- website contract validator

_ISO_UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z")
_REQUIRED_MANIFEST = ("snapshot_id", "source", "source_url", "fetched_utc", "http_date", "count",
                      "epoch_min", "epoch_median", "epoch_max", "sha256_raw", "attribution",
                      "pipeline")


def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _omm_file_name(manifest):
    """files.omm from the manifest (default omm.min.json); never a path outside the folder."""
    files = manifest.get("files") if isinstance(manifest, dict) else None
    name = files.get("omm", WEB_OMM) if isinstance(files, dict) else WEB_OMM
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", name) or name in (".", ".."):
        raise ValueError(f"files.omm {name!r} must be a plain file name")
    return name


def check_manifest_dict(manifest):
    """Problems with a website manifest, following parseManifest() in web/src/lib/data.ts."""
    problems = []
    if not isinstance(manifest, dict):
        return ["manifest is not a JSON object"]
    if "schema" in manifest and manifest["schema"] != WEB_SCHEMA:
        problems.append(f"schema must be {WEB_SCHEMA!r}")
    for key in _REQUIRED_MANIFEST:
        if key == "count":
            if not _is_count(manifest.get(key)):
                problems.append("count must be a non-negative integer")
        elif not isinstance(manifest.get(key), str) or manifest.get(key) == "":
            problems.append(f"{key} must be a non-empty string")
    for key in ("fetched_utc", "epoch_min", "epoch_median", "epoch_max"):
        if isinstance(manifest.get(key), str) and not _ISO_UTC.fullmatch(manifest[key]):
            problems.append(f"{key} must be ISO 8601 UTC ending in Z")
    if isinstance(manifest.get("sha256_raw"), str) and not re.fullmatch(r"[0-9a-f]{64}", manifest["sha256_raw"]):
        problems.append("sha256_raw must be 64 lowercase hex digits")
    excluded = manifest.get("excluded")
    total = 0
    if not isinstance(excluded, dict):
        problems.append("excluded must be an object")
    else:
        for key in ("stale_epoch", "sgp4_error"):
            if not _is_count(excluded.get(key)):
                problems.append(f"excluded.{key} must be a non-negative integer")
        for key in ("invalid", "duplicate"):
            if key in excluded and not _is_count(excluded[key]):
                problems.append(f"excluded.{key} must be a non-negative integer")
        total = sum(v for v in excluded.values() if _is_count(v))
    if "max_epoch_age_days" in manifest:
        age = manifest["max_epoch_age_days"]
        if isinstance(age, bool) or not isinstance(age, (int, float)) or not age > 0:
            problems.append("max_epoch_age_days must be a positive number")
    if "count_raw" in manifest:
        if not _is_count(manifest["count_raw"]):
            problems.append("count_raw must be a non-negative integer")
        elif _is_count(manifest.get("count")) and manifest["count"] + total != manifest["count_raw"]:
            problems.append("count + excluded must equal count_raw")
    for key in ("sgp4_check", "files"):
        if key in manifest and not isinstance(manifest[key], dict):
            problems.append(f"{key} must be an object")
    if isinstance(manifest.get("sgp4_check"), dict):
        check = manifest["sgp4_check"]
        for key in ("library", "version", "at_utc"):
            if not isinstance(check.get(key), str) or not check.get(key):
                problems.append(f"sgp4_check.{key} must be a non-empty string")
        if isinstance(check.get("at_utc"), str) and not _ISO_UTC.fullmatch(check["at_utc"]):
            problems.append("sgp4_check.at_utc must be ISO 8601 UTC ending in Z")
    if all(isinstance(manifest.get(k), str) for k in ("epoch_min", "epoch_median", "epoch_max")):
        if not manifest["epoch_min"] <= manifest["epoch_median"] <= manifest["epoch_max"]:
            problems.append("epochs must satisfy epoch_min <= epoch_median <= epoch_max")
    return problems


def check_web_snapshot(folder, *, latest_path=None):
    """Every problem with a website snapshot folder (empty list = valid).

    Checks the manifest (as the website does), then omm.min.json: exact field
    list and order, row width, NORAD ids sorted and unique, required values
    present and valid, row count == manifest count. With latest_path, also
    checks that latest.json points at this snapshot.
    """
    folder = Path(folder)
    problems = []
    try:
        manifest = json.loads((folder / WEB_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"cannot read {WEB_MANIFEST}: {exc}"]
    problems += check_manifest_dict(manifest)
    omm_name = WEB_OMM
    try:
        omm_name = _omm_file_name(manifest)
        table = omm.loads_keep_numbers((folder / omm_name).read_bytes())
    except (OSError, ValueError) as exc:
        return problems + [f"cannot read {omm_name}: {exc}"]
    if not isinstance(table, dict) or not isinstance(table.get("fields"), list) \
            or not isinstance(table.get("rows"), list):
        return problems + [f"{omm_name} must be an object with 'fields' and 'rows'"]
    fields = table["fields"]
    if tuple(fields) != omm.OMM_FIELDS:
        problems.append(f"{omm_name}: fields must be exactly {list(omm.OMM_FIELDS)}")
    previous = None
    for index, row in enumerate(table["rows"]):
        if not isinstance(row, list) or len(row) != len(fields):
            problems.append(f"{omm_name}: row {index} must have {len(fields)} values")
            break
        obj = {name: value for name, value in zip(fields, row) if value is not None}
        problem = omm.object_problem(obj)
        if problem:
            problems.append(f"{omm_name}: row {index}: {problem}")
            break
        norad = int(obj["NORAD_CAT_ID"].value)
        if previous is not None and norad <= previous:
            problems.append(f"{omm_name}: rows must be sorted by NORAD_CAT_ID without duplicates "
                            f"(row {index}: {norad} after {previous})")
            break
        previous = norad
    if _is_count(manifest.get("count")) and len(table["rows"]) != manifest["count"]:
        problems.append(f"{omm_name} has {len(table['rows'])} rows but the manifest says {manifest['count']}")
    if latest_path is not None:
        try:
            latest = json.loads(Path(latest_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"cannot read latest.json: {exc}")
        else:
            if latest.get("snapshot_id") != manifest.get("snapshot_id"):
                problems.append("latest.json and manifest.json name different snapshots")
            if latest.get("path") != f"snapshots/{manifest.get('snapshot_id')}/":
                problems.append("latest.json path must be snapshots/<id>/")
    return problems
