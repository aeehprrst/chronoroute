"""
provenance.py
-------------
Writes (and checks) the manifest.json that sits next to every set of results.

Why this exists: a chart is only worth something if we can say exactly how it
was made -- which commit, which config, which seeds, which orbit snapshot,
which library versions, on which machine, and which files came out. The
project rule is "every number traces back to a manifest", so every experiment
ends by calling write_manifest().

Typical use:

    import sys
    from chronoroute import __version__
    from chronoroute.provenance import RunTimer, write_manifest

    with RunTimer() as timer:
        ...  # run the experiment, write summary.csv / fig.png into out_dir
    write_manifest(out_dir, tool="python-sim", tool_version=__version__,
                   command=sys.argv, config=cfg, seeds=[1000, 1001],
                   outputs=[out_dir / "summary.csv", out_dir / "fig.png"],
                   labels={"orbits": "REAL", "isl_topology": "MODELLED"},
                   timer=timer)

The manifest format is defined by spec/schemas/manifest.schema.json.
jsonschema is not a dependency, so this module carries a small validator for
the handful of JSON Schema keywords that schema uses (SUPPORTED_KEYWORDS).
Every manifest is validated before it is written, so an invalid one never
reaches disk.
"""

import hashlib
import importlib.metadata
import importlib.resources
import json
import math
import operator
import os
import platform
import re
import shlex
import subprocess
import tempfile
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path, PurePath

from . import __version__ as _chronoroute_version

SCHEMA_ID = "chronoroute.manifest/1"
MANIFEST_NAME = "manifest.json"

# The three honesty labels (plan section 2). Anything else is a typo.
LABELS = ("REAL", "DERIVED", "MODELLED")

# provenance.py lives in <repo>/sim/chronoroute/, so the repo is two levels up.
# (In a non-editable install this is site-packages' parent and not a git repo;
# git_state() then records git_sha/dirty as null, so pass repo_dir= there.)
REPO_ROOT = Path(__file__).resolve().parents[2]
# The schema ships inside the package (package data), so a normal
# `pip install .` can still write and validate manifests. The copy in
# spec/schemas/ is the documented one; a test keeps the two byte-identical.
SCHEMA_PATH = Path(str(importlib.resources.files("chronoroute") / "schemas" /
                       "manifest.schema.json"))

# Changes under these repo-relative directories do not make a run "dirty".
# results/ holds what runs PRODUCE, not what they run: without this, the
# second experiment of a session would always be marked dirty because the
# first one had just written its figures.
DIRTY_IGNORE = ("results",)

# Libraries whose versions change numbers. Read with importlib.metadata so we
# do not pay for importing matplotlib just to ask its version.
VERSION_PACKAGES = ("numpy", "networkx", "sgp4", "matplotlib")

RUN_ID_HEX_DIGITS = 16
_HASH_CHUNK = 1 << 20


class ManifestValidationError(ValueError):
    """A manifest broke the schema or one of the consistency checks."""

    def __init__(self, errors, source=None):
        self.errors = list(errors)
        where = f"{source}: " if source else ""
        super().__init__(where + "; ".join(self.errors))


class SchemaError(ValueError):
    """The schema itself uses something our small validator cannot check."""


# ---------------------------------------------------------------------------
# Canonical JSON and hashing
# ---------------------------------------------------------------------------

def _normalise(value, where):
    """Turn value into plain JSON types, refusing anything ambiguous.

    Tuples become lists and paths become POSIX strings. numpy scalars become
    Python numbers. Sets are refused because they have no stable order, and
    NaN/inf are refused because JSON cannot represent them (json.dumps would
    otherwise write the non-standard token NaN).
    """
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{where}: {value!r} cannot be stored in JSON")
        return float(value)
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{where}: keys must be strings, got {key!r}")
            out[key] = _normalise(item, f"{where}.{key}")
        return out
    if isinstance(value, (list, tuple)):
        return [_normalise(item, f"{where}[{i}]") for i, item in enumerate(value)]
    if isinstance(value, PurePath):
        return value.as_posix()
    # numpy scalars (np.int64, np.float64, np.bool_) without importing numpy.
    if type(value).__module__ == "numpy" and getattr(value, "shape", None) == ():
        return _normalise(value.item(), where)
    raise TypeError(f"{where}: {type(value).__name__} is not JSON-serialisable "
                    "(use str, int, float, bool, None, list, tuple or dict)")


def canonical_json(value):
    """The one byte-exact JSON form we hash: sorted keys, no spaces, UTF-8."""
    return json.dumps(_normalise(value, "value"), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def file_sha256(path):
    """sha256 of a file, read in chunks so large pcaps do not fill RAM."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def config_sha256(config):
    return sha256_hex(canonical_json(config).encode("utf-8"))


def compute_run_id(config, seeds, git_sha):
    """Deterministic run id: same config + seeds + commit -> same id."""
    key = {"config": config, "git_sha": git_sha, "seeds": list(seeds)}
    return sha256_hex(canonical_json(key).encode("utf-8"))[:RUN_ID_HEX_DIGITS]


def _normalise_seeds(seeds):
    if seeds is None:
        return []
    if isinstance(seeds, (str, bytes)):
        raise TypeError("seeds must be an int or a sequence of ints, not a string")
    if isinstance(seeds, bool):
        raise TypeError("seeds must be integers, not bool")
    if not hasattr(seeds, "__iter__"):
        seeds = [seeds]
    out = []
    for seed in seeds:
        if isinstance(seed, bool):
            raise TypeError("seeds must be integers, not bool")
        # operator.index accepts int and numpy ints but refuses 3.0 or "3".
        try:
            seed = operator.index(seed)
        except TypeError:
            raise TypeError(f"seed {seed!r} is not an integer") from None
        if seed < 0:
            raise ValueError(f"seed {seed} is negative")
        out.append(int(seed))
    return out


def _normalise_command(command):
    if isinstance(command, str):
        text = command
    elif isinstance(command, (list, tuple)) and all(isinstance(a, str) for a in command):
        text = shlex.join(command)
    else:
        raise TypeError("command must be a string or a list of strings (e.g. sys.argv)")
    if not text.strip():
        raise ValueError("command is empty")
    return text


def _normalise_labels(labels):
    if labels is None:
        return {}
    if not isinstance(labels, Mapping):
        raise TypeError("labels must be a dict like {'orbits': 'REAL'}")
    out = {}
    for name, label in labels.items():
        if not isinstance(name, str) or not name:
            raise TypeError(f"label name {name!r} must be a non-empty string")
        if label not in LABELS:
            raise ValueError(f"label {name!r} = {label!r}; allowed: {', '.join(LABELS)}")
        out[name] = label
    return out


# ---------------------------------------------------------------------------
# Git state
# ---------------------------------------------------------------------------

class _GitUnavailable(Exception):
    pass


def _git(cwd, *args):
    """Run git and return stdout; any failure (no git, not a repo) raises."""
    # GIT_OPTIONAL_LOCKS=0: `git status` must not take .git/index.lock, or a
    # git command the user runs at the same moment could fail.
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    try:
        proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                              text=True, timeout=60, check=False, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        raise _GitUnavailable(str(exc)) from None
    if proc.returncode != 0:
        raise _GitUnavailable(proc.stderr.strip())
    return proc.stdout


def git_state(repo_dir=None, *, ignore_paths=()):
    """Return {"sha": HEAD or None, "dirty": bool or None} for repo_dir.

    dirty counts modified, staged and untracked files (an untracked module can
    change results just as much as an edited one), except anything under
    DIRTY_IGNORE and the given ignore_paths (the run's own outputs). If git is
    missing, the directory is not a repo, or the repo has no commit yet, both
    values are None: we record "unknown" rather than guess.
    """
    repo_dir = Path(repo_dir) if repo_dir is not None else REPO_ROOT
    try:
        top = Path(_git(repo_dir, "rev-parse", "--show-toplevel").strip())
        sha = _git(repo_dir, "rev-parse", "--verify", "HEAD").strip()
    except _GitUnavailable:
        return {"sha": None, "dirty": None}

    excludes = [f":(exclude,literal){d}" for d in DIRTY_IGNORE]
    top_resolved = top.resolve()
    ignored = set()
    for path in ignore_paths:
        try:
            rel = Path(path).resolve().relative_to(top_resolved)
        except ValueError:
            continue                      # outside the repo: cannot be dirty
        if rel.parts:                     # never exclude the repo root itself
            ignored.add(rel.as_posix())
    try:
        status = _git(top, "status", "--porcelain", "-z", "--untracked-files=all",
                      "--", ".", *excludes)
    except _GitUnavailable:
        return {"sha": sha, "dirty": None}
    # Filter declared outputs locally: a large collection must not turn into
    # an unbounded git argument list. NUL records also preserve unusual names.
    records = iter(status.split('\0'))
    for record in records:
        if not record:
            continue
        paths = [record[3:]]
        if 'R' in record[:2] or 'C' in record[:2]:
            paths.append(next(records))
        for path in paths:
            if not any(path == prefix or path.startswith(prefix + '/') for prefix in ignored):
                return {"sha": sha, "dirty": True}
    return {"sha": sha, "dirty": False}


# ---------------------------------------------------------------------------
# Snapshot, versions, host
# ---------------------------------------------------------------------------

def snapshot_from_dir(path, *, verify=True):
    """Describe a pinned data snapshot directory (data/pinned/<id>/).

    The id is the directory name. The snapshot hash is the sha256 of its
    SHA256SUMS file, which itself lists the sha256 of every data file, so one
    hash pins all of them. With verify=True every listed file is re-hashed and
    any mismatch raises ValueError: a run must not claim a snapshot that has
    been edited.
    """
    path = Path(path)
    sums_path = path / "SHA256SUMS"
    sums_bytes = sums_path.read_bytes()
    if verify:
        bad = []
        for lineno, line in enumerate(sums_bytes.decode("utf-8").splitlines(), 1):
            if not line.strip():
                continue
            # coreutils format: "<hash> *<name>" (binary) or "<hash>  <name>" (text)
            match = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", line)
            if not match:
                raise ValueError(f"{sums_path}:{lineno}: not a sha256sum line")
            expected, name = match.group(1).lower(), match.group(2)
            target = path / name
            if PurePath(name).is_absolute() or ".." in PurePath(name).parts:
                raise ValueError(f"{sums_path}:{lineno}: {name!r} escapes the snapshot")
            if not target.is_file():
                bad.append(f"{name} (missing)")
            elif file_sha256(target) != expected:
                bad.append(f"{name} (sha256 mismatch)")
        if bad:
            raise ValueError(f"snapshot {path.name} failed verification: {', '.join(bad)}")
    return {"id": path.name, "sha256": sha256_hex(sums_bytes), "sha256_of": "SHA256SUMS"}


def _normalise_snapshot(snapshot):
    if snapshot is None:
        return None
    if isinstance(snapshot, (str, os.PathLike)):
        return snapshot_from_dir(snapshot)
    if not isinstance(snapshot, Mapping):
        raise TypeError("snapshot must be None, a dict with id and sha256, or a directory path")
    snap = _normalise(snapshot, "snapshot")
    if not isinstance(snap.get("id"), str) or not snap["id"]:
        raise ValueError("snapshot needs a non-empty 'id'")
    if not isinstance(snap.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", snap["sha256"]):
        raise ValueError("snapshot 'sha256' must be 64 lowercase hex digits")
    return snap


def package_versions():
    versions = {"python": platform.python_version(), "chronoroute": _chronoroute_version}
    for name in VERSION_PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _cpu_model():
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or None


def _ram_bytes():
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024          # value is in kB
    except (OSError, ValueError, IndexError):
        pass
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, ValueError, OSError):
        return None


def host_info():
    """CPU, cores and RAM, so a reader can judge timings. No hostname: the
    manifests are published and the machine name is nobody's business."""
    return {
        "cpu_model": _cpu_model(),
        "logical_cores": os.cpu_count(),
        "ram_bytes": _ram_bytes(),
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

def _utc_now():
    return datetime.now(timezone.utc)


def _monotonic():
    # A separate function so tests can replace the clock without touching
    # time.perf_counter for the whole interpreter.
    return time.perf_counter()


def _utc_text(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class RunTimer:
    """Records start/end UTC and wall time of a run.

        with RunTimer() as timer:
            run()
        write_manifest(..., timer=timer)

    Wall time comes from time.perf_counter() (monotonic), not from the two UTC
    stamps, so a clock adjustment during the run cannot make it wrong. If the
    manifest is written while the timer is still running, the end time is
    "now" and the wall time is the time elapsed so far.
    """

    def __init__(self):
        self.started_utc = None
        self.ended_utc = None
        self._t0 = None
        self._t1 = None

    def start(self):
        self.started_utc = _utc_now()
        self._t0 = _monotonic()
        self.ended_utc = None
        self._t1 = None
        return self

    def stop(self):
        if self._t0 is None:
            raise RuntimeError("RunTimer.stop() called before start()")
        self._t1 = _monotonic()
        self.ended_utc = _utc_now()
        return self

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, tb):
        self.stop()
        return False

    @property
    def running(self):
        return self._t0 is not None and self._t1 is None

    @property
    def wall_seconds(self):
        if self._t0 is None:
            return None
        end = self._t1 if self._t1 is not None else _monotonic()
        return end - self._t0

    def as_dict(self):
        if self._t0 is None:
            raise RuntimeError("RunTimer was never started")
        ended = self.ended_utc if self.ended_utc is not None else _utc_now()
        return {
            "started_utc": _utc_text(self.started_utc),
            "ended_utc": _utc_text(ended),
            "wall_seconds": round(max(0.0, self.wall_seconds), 6),
        }


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _describe_outputs(outputs, out_dir, manifest_path):
    entries = {}
    for item in outputs:
        path = Path(item)
        if not path.is_absolute():
            path = Path.cwd() / path
        path = path.resolve()
        if path == manifest_path:
            raise ValueError("outputs must not include the manifest itself")
        if path.is_dir():
            raise IsADirectoryError(f"output {item} is a directory; list its files")
        if not path.is_file():
            raise FileNotFoundError(f"output {item} does not exist")
        try:
            rel = os.path.relpath(path, out_dir)
        except ValueError:                       # different drive on Windows
            rel = str(path)
        rel = PurePath(rel).as_posix()
        entries[rel] = {"path": rel, "sha256": file_sha256(path),
                        "size_bytes": path.stat().st_size}
    return [entries[key] for key in sorted(entries)]


def build_manifest(out_dir, *, tool, tool_version, command, config, seeds,
                   snapshot=None, outputs=(), labels=None, extra=None,
                   timer=None, repo_dir=None):
    """Assemble the manifest dict (without writing it). See write_manifest."""
    if not isinstance(tool, str) or not tool:
        raise TypeError("tool must be a non-empty string")
    if not isinstance(tool_version, str) or not tool_version:
        raise TypeError("tool_version must be a non-empty string")
    if not isinstance(config, Mapping):
        raise TypeError("config must be a dict")
    if extra is not None and not isinstance(extra, Mapping):
        raise TypeError("extra must be a dict or None")

    out_dir = Path(out_dir).resolve()
    manifest_path = out_dir / MANIFEST_NAME
    config = _normalise(config, "config")
    seeds = _normalise_seeds(seeds)
    output_entries = _describe_outputs(outputs, out_dir, manifest_path)
    git = git_state(repo_dir, ignore_paths=[manifest_path]
                    + [out_dir / entry["path"] for entry in output_entries])
    if timer is None:
        timing = {"started_utc": None, "ended_utc": None, "wall_seconds": None}
    else:
        timing = timer.as_dict()

    return {
        "schema": SCHEMA_ID,
        "run_id": compute_run_id(config, seeds, git["sha"]),
        "tool": tool,
        "tool_version": tool_version,
        "git_sha": git["sha"],
        "dirty": git["dirty"],
        "command": _normalise_command(command),
        "config": config,
        "config_sha256": config_sha256(config),
        "seeds": seeds,
        "snapshot": _normalise_snapshot(snapshot),
        "versions": package_versions(),
        "host": host_info(),
        **timing,
        "written_utc": _utc_text(_utc_now()),
        "outputs": output_entries,
        "labels": _normalise_labels(labels),
        "extra": _normalise(extra or {}, "extra"),
    }


def write_manifest(out_dir, *, tool, tool_version, command, config, seeds,
                   snapshot=None, outputs=(), labels=None, extra=None,
                   timer=None, repo_dir=None):
    """Write out_dir/manifest.json and return its path.

    tool, tool_version : what produced the run, e.g. "python-sim", "1.0.0"
    command            : sys.argv (list) or a command-line string
    config             : dict of every setting that can change the results
    seeds              : int or list of ints (empty list if deterministic)
    snapshot           : None, {"id": ..., "sha256": ...}, or a data/pinned/<id>
                         directory (verified against its SHA256SUMS)
    outputs            : files the run produced; each is hashed (must exist)
    labels             : {"name": "REAL" | "DERIVED" | "MODELLED"}
    extra              : dict of tool-specific facts
    timer              : a RunTimer (start/end/wall time); None records nulls
    repo_dir           : repo whose commit to record (default: this checkout)

    Keys are sorted and the JSON is indented, so manifests diff cleanly. The
    file is validated against the schema first and then written atomically
    (temp file + rename), so a crash never leaves half a manifest behind.
    """
    manifest = build_manifest(out_dir, tool=tool, tool_version=tool_version,
                              command=command, config=config, seeds=seeds,
                              snapshot=snapshot, outputs=outputs, labels=labels,
                              extra=extra, timer=timer, repo_dir=repo_dir)
    errors = schema_errors(manifest, load_schema())
    if errors:
        raise ManifestValidationError(errors, "refusing to write manifest")

    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / MANIFEST_NAME
    text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False,
                      allow_nan=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=".manifest.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        # mkstemp creates the file as 0600; make the manifest readable by
        # everyone, like any other result file (web servers, other users).
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


# ---------------------------------------------------------------------------
# A small JSON Schema validator (only the keywords our schema uses)
# ---------------------------------------------------------------------------

# Keywords that only describe; they never make an instance invalid.
_ANNOTATIONS = {"$schema", "$id", "$comment", "$defs", "title", "description",
                "examples", "default"}
_CHECKED = {"type", "enum", "const", "properties", "required",
            "additionalProperties", "propertyNames", "items", "minItems",
            "maxItems", "minimum", "maximum", "minLength", "maxLength",
            "pattern", "$ref"}
SUPPORTED_KEYWORDS = frozenset(_ANNOTATIONS | _CHECKED)

_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}


def check_schema(schema, where="#"):
    """Raise SchemaError if the schema uses a keyword we do not implement.

    Without this, an unsupported keyword (say "format" or "oneOf") would be
    silently skipped and the schema would promise checks that never happen.
    """
    if isinstance(schema, bool):
        return
    if not isinstance(schema, Mapping):
        raise SchemaError(f"{where}: a schema must be an object or a boolean")
    unknown = set(schema) - SUPPORTED_KEYWORDS
    if unknown:
        raise SchemaError(f"{where}: unsupported keyword(s) {sorted(unknown)}")
    types = schema.get("type")
    if types is not None:
        for name in [types] if isinstance(types, str) else types:
            if name not in _TYPES:
                raise SchemaError(f"{where}: unknown type {name!r}")
    if "pattern" in schema:
        re.compile(schema["pattern"])
    for key in ("properties", "$defs"):
        for name, sub in schema.get(key, {}).items():
            check_schema(sub, f"{where}/{key}/{name}")
    for key in ("additionalProperties", "propertyNames", "items"):
        if key in schema:
            check_schema(schema[key], f"{where}/{key}")
    ref = schema.get("$ref")
    if ref is not None and not ref.startswith("#/"):
        raise SchemaError(f"{where}: only local $ref ('#/...') is supported, got {ref!r}")


def load_schema(path=None):
    path = Path(path) if path is not None else SCHEMA_PATH
    with open(path, encoding="utf-8") as fh:
        schema = json.load(fh)
    check_schema(schema)
    return schema


def _is_type(value, name):
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    if isinstance(value, bool):           # True is not 1 in JSON Schema
        return False
    if name == "integer":
        # JSON Schema counts 2.0 as an integer (it is the same JSON number).
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    if name == "number":
        return isinstance(value, (int, float))
    return False


def _json_equal(a, b):
    """Equality with JSON semantics: 1 == 1.0, but True != 1."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_json_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_json_equal(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def _resolve_ref(root, ref):
    node = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, Mapping) or part not in node:
            raise SchemaError(f"cannot resolve $ref {ref!r}")
        node = node[part]
    return node


def _validate(value, schema, root, where, errors):
    if schema is True:
        return
    if schema is False:
        errors.append(f"{where}: no value is allowed here")
        return

    if "$ref" in schema:
        _validate(value, _resolve_ref(root, schema["$ref"]), root, where, errors)

    if "type" in schema:
        types = [schema["type"]] if isinstance(schema["type"], str) else schema["type"]
        if not any(_is_type(value, t) for t in types):
            errors.append(f"{where}: expected {' or '.join(types)}, got {json.dumps(value)[:60]}")
            return          # the remaining checks assume the right type

    if "const" in schema and not _json_equal(value, schema["const"]):
        errors.append(f"{where}: must equal {schema['const']!r}")
    if "enum" in schema and not any(_json_equal(value, e) for e in schema["enum"]):
        errors.append(f"{where}: {value!r} is not one of {schema['enum']}")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{where}: shorter than {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{where}: longer than {schema['maxLength']} characters")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"{where}: {value!r} does not match {schema['pattern']!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{where}: {value} is below the minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{where}: {value} is above the maximum {schema['maximum']}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{where}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{where}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                _validate(item, schema["items"], root, f"{where}[{i}]", errors)

    if isinstance(value, dict):
        props = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{where}: missing required key {name!r}")
        for name, item in value.items():
            if "propertyNames" in schema:
                _validate(name, schema["propertyNames"], root, f"{where} key {name!r}", errors)
            if name in props:
                _validate(item, props[name], root, f"{where}.{name}", errors)
            elif "additionalProperties" in schema:
                extra = schema["additionalProperties"]
                if extra is False:
                    errors.append(f"{where}: unexpected key {name!r}")
                else:
                    _validate(item, extra, root, f"{where}.{name}", errors)


def schema_errors(instance, schema):
    """Return a list of human-readable problems (empty list = valid)."""
    errors = []
    _validate(instance, schema, schema, "$", errors)
    return errors


def validate_manifest(path, *, schema_path=None, check_files=True):
    """Check a manifest.json; return it as a dict, or raise ManifestValidationError.

    Beyond the schema it re-checks what the schema cannot: config_sha256 and
    run_id must match the recorded config/seeds/git_sha, and (check_files=True)
    every output must still exist with the recorded size and sha256 -- so a
    figure edited after the run is caught.
    """
    path = Path(path)
    if path.is_dir():
        path = path / MANIFEST_NAME
    with open(path, encoding="utf-8") as fh:
        manifest = json.load(fh)

    errors = schema_errors(manifest, load_schema(schema_path))
    if errors:
        raise ManifestValidationError(errors, path)

    if config_sha256(manifest["config"]) != manifest["config_sha256"]:
        errors.append("config_sha256 does not match config")
    expected_id = compute_run_id(manifest["config"], manifest["seeds"], manifest["git_sha"])
    if expected_id != manifest["run_id"]:
        errors.append(f"run_id {manifest['run_id']} does not match config/seeds/git_sha "
                      f"(expected {expected_id})")
    if check_files:
        base = path.resolve().parent
        for entry in manifest["outputs"]:
            target = base / entry["path"]
            if not target.is_file():
                errors.append(f"output {entry['path']} is missing")
            elif target.stat().st_size != entry["size_bytes"]:
                errors.append(f"output {entry['path']} size changed")
            elif file_sha256(target) != entry["sha256"]:
                errors.append(f"output {entry['path']} sha256 changed")
    if errors:
        raise ManifestValidationError(errors, path)
    return manifest
