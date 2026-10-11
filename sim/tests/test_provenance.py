"""
Tests for chronoroute.provenance (manifest writer + small schema validator).

Everything runs in pytest tmp dirs. Git behaviour is tested against throw-away
repositories created here, with the user's global git config switched off so
the tests do not depend on anyone's ~/.gitconfig.
"""

import hashlib
import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from chronoroute import __version__
from chronoroute import provenance as prov

HAVE_GIT = shutil.which("git") is not None
needs_git = pytest.mark.skipif(not HAVE_GIT, reason="git is not installed")

PINNED = prov.REPO_ROOT / "data" / "pinned" / "20261010T1358Z-celestrak"
# sha256 of that snapshot's SHA256SUMS file on 2026-10-10. The snapshot is
# permanent evidence; if this ever changes, the data was edited.
PINNED_SUMS_SHA256 = "c37e70812155c2d1d9eeb3e96681303c00c9fca91287939b21bf5313ce83aecd"


@pytest.fixture
def hermetic_git(monkeypatch, tmp_path):
    """Ignore ~/.gitconfig and /etc/gitconfig, and stop repo discovery at tmp_path."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))


def git(repo, *args):
    proc = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=ChronoRoute Test",
         "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def make_repo(path):
    """A repo with one commit containing code.py; returns its HEAD sha."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    (path / "code.py").write_text("print('hi')\n")
    git(path, "add", "code.py")
    git(path, "commit", "-q", "-m", "init")
    return git(path, "rev-parse", "HEAD")


def write(out_dir, **overrides):
    """write_manifest with sensible defaults; any argument can be overridden."""
    args = dict(tool="python-sim", tool_version="1.0.0", command=["cr", "run", "--fast"],
                config={"slack": 1.2, "preset": "dev"}, seeds=[1, 2], outputs=[],
                labels={"orbits": "REAL", "isl_topology": "MODELLED"})
    args.update(overrides)
    return prov.write_manifest(out_dir, **args)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Writing: shape, sorting, hashes
# ---------------------------------------------------------------------------

def test_write_manifest_creates_valid_sorted_pretty_json(tmp_path):
    out = tmp_path / "results" / "run"
    (tmp_path / "results").mkdir()
    out.mkdir()
    (out / "summary.csv").write_text("a,b\n1,2\n")
    path = write(out, outputs=[out / "summary.csv"])

    assert path == out / "manifest.json"
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    # keys sorted and indented -> re-dumping the same way is a no-op
    assert text == json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert data["schema"] == "chronoroute.manifest/1"
    assert data["tool"] == "python-sim"
    assert data["seeds"] == [1, 2]
    assert prov.validate_manifest(path)["run_id"] == data["run_id"]
    # nothing but the manifest and the output: the temp file was renamed away
    assert sorted(p.name for p in out.iterdir()) == ["manifest.json", "summary.csv"]


def test_out_dir_is_created(tmp_path):
    path = write(tmp_path / "new" / "deeper")
    assert path.is_file()


def test_config_sha256_is_sha_of_canonical_json(tmp_path):
    config = {"b": [1, 2.5, None], "a": {"z": True, "y": "São Paulo"}}
    data = load(write(tmp_path, config=config))
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert data["config_sha256"] == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert data["config"] == config


def test_config_normalisation():
    import numpy as np
    config = {"t": (1, 2), "p": Path("/data/x.json"), "n": np.int64(7), "f": np.float64(0.5),
              "b": np.bool_(True)}
    assert json.loads(prov.canonical_json(config)) == {
        "t": [1, 2], "p": "/data/x.json", "n": 7, "f": 0.5, "b": True}
    with pytest.raises(ValueError):
        prov.canonical_json({"x": float("nan")})
    with pytest.raises(ValueError):
        prov.canonical_json({"x": float("inf")})
    with pytest.raises(TypeError):
        prov.canonical_json({"x": {1, 2}})            # sets have no stable order
    with pytest.raises(TypeError):
        prov.canonical_json({1: "x"})                 # JSON keys are strings
    with pytest.raises(TypeError):
        prov.canonical_json({"x": object()})


def test_outputs_have_sha256_size_and_relative_sorted_paths(tmp_path):
    out = tmp_path / "run"
    (out / "figs").mkdir(parents=True)
    (out / "b.csv").write_bytes(b"x" * 1000)
    (out / "figs" / "a.png").write_bytes(b"\x89PNG fake")
    elsewhere = tmp_path / "shared.txt"
    elsewhere.write_text("outside")
    data = load(write(out, outputs=[out / "b.csv", out / "figs" / "a.png", elsewhere,
                                    out / "b.csv"]))          # duplicate is listed once
    assert [o["path"] for o in data["outputs"]] == ["../shared.txt", "b.csv", "figs/a.png"]
    b = data["outputs"][1]
    assert b["size_bytes"] == 1000
    assert b["sha256"] == hashlib.sha256(b"x" * 1000).hexdigest()


def test_relative_output_paths_resolve_from_cwd(tmp_path, monkeypatch):
    out = tmp_path / "run"
    out.mkdir()
    (out / "f.csv").write_text("1\n")
    monkeypatch.chdir(tmp_path)
    data = load(write(out, outputs=["run/f.csv"]))
    assert data["outputs"][0]["path"] == "f.csv"


def test_bad_outputs_are_refused(tmp_path):
    with pytest.raises(FileNotFoundError):
        write(tmp_path, outputs=[tmp_path / "missing.csv"])
    with pytest.raises(IsADirectoryError):
        write(tmp_path, outputs=[tmp_path])
    (tmp_path / "manifest.json").write_text("{}")
    with pytest.raises(ValueError):
        write(tmp_path, outputs=[tmp_path / "manifest.json"])


def test_command_list_is_shell_quoted(tmp_path):
    data = load(write(tmp_path, command=["python", "run all.py", "--out", "a b"]))
    assert data["command"] == "python 'run all.py' --out 'a b'"
    data = load(write(tmp_path, command="make legacy-dev"))
    assert data["command"] == "make legacy-dev"
    with pytest.raises(ValueError):
        write(tmp_path, command=[])
    with pytest.raises(TypeError):
        write(tmp_path, command=["ok", 3])


def test_seeds_forms(tmp_path):
    assert load(write(tmp_path, seeds=7))["seeds"] == [7]
    assert load(write(tmp_path, seeds=range(3)))["seeds"] == [0, 1, 2]
    assert load(write(tmp_path, seeds=[]))["seeds"] == []
    assert load(write(tmp_path, seeds=None))["seeds"] == []
    for bad, exc in [([1.0], TypeError), ([True], TypeError), ("12", TypeError),
                     ([-1], ValueError)]:
        with pytest.raises(exc):
            write(tmp_path, seeds=bad)


def test_labels_must_be_real_derived_or_modelled(tmp_path):
    assert load(write(tmp_path, labels=None))["labels"] == {}
    data = load(write(tmp_path, labels={"orbits": "REAL", "shells": "DERIVED",
                                        "traffic": "MODELLED"}))
    assert data["labels"]["shells"] == "DERIVED"
    with pytest.raises(ValueError):
        write(tmp_path, labels={"orbits": "real"})
    with pytest.raises(ValueError):
        write(tmp_path, labels={"queues": "ASSUMED"})


def test_extra_and_versions_and_host(tmp_path):
    data = load(write(tmp_path, extra={"skipped_sgp4": 57, "ns3_base": "6314c8a"}))
    assert data["extra"] == {"skipped_sgp4": 57, "ns3_base": "6314c8a"}
    v = data["versions"]
    assert v["python"] == platform.python_version()
    assert v["chronoroute"] == __version__
    assert set(v) >= {"numpy", "networkx", "sgp4", "matplotlib"}
    import numpy
    assert v["numpy"] == numpy.__version__
    host = data["host"]
    assert host["logical_cores"] == os.cpu_count()
    if Path("/proc/meminfo").exists():
        assert host["ram_bytes"] > 0
    assert "hostname" not in host            # manifests are public


def test_invalid_manifest_is_never_written(tmp_path, monkeypatch):
    monkeypatch.setattr(prov, "package_versions", lambda: {"python": 3})
    with pytest.raises(prov.ManifestValidationError):
        write(tmp_path)
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# run_id
# ---------------------------------------------------------------------------

def test_run_id_is_deterministic(tmp_path):
    a = load(write(tmp_path / "a", config={"x": 1, "y": 2}, seeds=[5]))
    b = load(write(tmp_path / "b", config={"y": 2, "x": 1}, seeds=[5],
                   tool_version="other", command="something else"))
    assert a["run_id"] == b["run_id"]
    assert len(a["run_id"]) == 16
    assert a["run_id"] == prov.compute_run_id({"x": 1, "y": 2}, [5], a["git_sha"])


def test_run_id_changes_with_config_seeds_and_commit():
    base = prov.compute_run_id({"x": 1}, [5], "a" * 40)
    assert prov.compute_run_id({"x": 2}, [5], "a" * 40) != base
    assert prov.compute_run_id({"x": 1}, [6], "a" * 40) != base
    assert prov.compute_run_id({"x": 1}, [5], "b" * 40) != base
    assert prov.compute_run_id({"x": 1}, [5], None) != base


# ---------------------------------------------------------------------------
# Git state
# ---------------------------------------------------------------------------

@needs_git
def test_git_clean_repo(tmp_path, hermetic_git):
    repo = tmp_path / "repo"
    sha = make_repo(repo)
    assert prov.git_state(repo) == {"sha": sha, "dirty": False}
    data = load(write(tmp_path / "out", repo_dir=repo))
    assert data["git_sha"] == sha and data["dirty"] is False


@needs_git
def test_git_state_bounds_arguments_for_large_collections(tmp_path, hermetic_git, monkeypatch):
    repo = tmp_path / "repo"
    sha = make_repo(repo)
    original = prov._git
    def bounded(cwd, *args):
        if sum(len(str(a)) for a in args) > 4096:
            raise prov._GitUnavailable('argument list too long')
        return original(cwd, *args)
    monkeypatch.setattr(prov, '_git', bounded)
    paths = [repo / 'results' / 'run' / f'packet-{i}.csv' for i in range(10000)]
    assert prov.git_state(repo, ignore_paths=paths) == {'sha': sha, 'dirty': False}
    (repo / 'code.py').write_text('changed\n')
    assert prov.git_state(repo, ignore_paths=paths)['dirty'] is True


@needs_git
def test_git_output_filter_handles_renames_and_unusual_names(tmp_path, hermetic_git):
    repo = tmp_path / 'repo'
    make_repo(repo)
    output = repo / 'output\nwith space.txt'
    output.write_text('data')
    assert prov.git_state(repo, ignore_paths=[output])['dirty'] is False
    git(repo, 'mv', 'code.py', 'renamed.py')
    assert prov.git_state(repo, ignore_paths=[output, repo / 'renamed.py'])['dirty'] is True
    assert prov.git_state(repo, ignore_paths=[output, repo / 'renamed.py', repo / 'code.py'])['dirty'] is False


@needs_git
@pytest.mark.parametrize("change", ["modify", "untracked", "staged"])
def test_git_dirty_repo(tmp_path, hermetic_git, change):
    repo = tmp_path / "repo"
    make_repo(repo)
    if change == "modify":
        (repo / "code.py").write_text("print('changed')\n")
    elif change == "untracked":
        (repo / "new_module.py").write_text("x = 1\n")
    else:
        (repo / "staged.py").write_text("x = 1\n")
        git(repo, "add", "staged.py")
    assert prov.git_state(repo)["dirty"] is True


@needs_git
def test_results_and_declared_outputs_do_not_make_a_run_dirty(tmp_path, hermetic_git):
    repo = tmp_path / "repo"
    make_repo(repo)
    # an earlier run left figures in results/, this run writes into docs/figs
    (repo / "results" / "old").mkdir(parents=True)
    (repo / "results" / "old" / "fig.png").write_bytes(b"png")
    out = repo / "docs" / "figs"
    out.mkdir(parents=True)
    (out / "fig.svg").write_text("<svg/>")
    data = load(write(out, outputs=[out / "fig.svg"], repo_dir=repo))
    assert data["dirty"] is False
    # but an undeclared file next to them does count
    (out / "stray.txt").write_text("?")
    data = load(write(out, outputs=[out / "fig.svg"], repo_dir=repo))
    assert data["dirty"] is True


@needs_git
def test_not_a_repo_gives_nulls(tmp_path, hermetic_git):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert prov.git_state(plain) == {"sha": None, "dirty": None}
    data = load(write(tmp_path / "out", repo_dir=plain))
    assert data["git_sha"] is None and data["dirty"] is None
    assert prov.validate_manifest(tmp_path / "out" / "manifest.json")


@needs_git
def test_repo_without_commits_gives_nulls(tmp_path, hermetic_git):
    repo = tmp_path / "empty"
    repo.mkdir()
    git(repo, "init", "-q")
    assert prov.git_state(repo) == {"sha": None, "dirty": None}


def test_git_missing_gives_nulls(tmp_path, monkeypatch):
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")
    monkeypatch.setattr(prov.subprocess, "run", no_git)
    assert prov.git_state(tmp_path) == {"sha": None, "dirty": None}


@needs_git
def test_this_checkout_sha_matches_git():
    proc = subprocess.run(["git", "-C", str(prov.REPO_ROOT), "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip("source tree is not a git checkout")
    state = prov.git_state()
    assert state["sha"] == proc.stdout.strip()
    assert isinstance(state["dirty"], bool)


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

def test_run_timer_records_times(tmp_path, monkeypatch):
    clock = iter([100.0, 102.5])
    monkeypatch.setattr(prov, "_monotonic", lambda: next(clock))
    with prov.RunTimer() as timer:
        assert timer.running
    assert not timer.running
    assert timer.wall_seconds == 2.5
    data = load(write(tmp_path, timer=timer))
    assert data["wall_seconds"] == 2.5
    start = datetime.strptime(data["started_utc"], "%Y-%m-%dT%H:%M:%S.%fZ")
    end = datetime.strptime(data["ended_utc"], "%Y-%m-%dT%H:%M:%S.%fZ")
    assert timedelta(0) <= end - start < timedelta(seconds=60)
    written = datetime.strptime(data["written_utc"], "%Y-%m-%dT%H:%M:%S.%fZ")
    assert abs(written.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)) < timedelta(minutes=5)


def test_running_timer_uses_elapsed_so_far(tmp_path, monkeypatch):
    clock = iter([10.0, 11.25, 99.0])
    monkeypatch.setattr(prov, "_monotonic", lambda: next(clock))
    timer = prov.RunTimer().start()
    data = load(write(tmp_path, timer=timer))      # written inside the run
    assert data["wall_seconds"] == 1.25
    assert data["ended_utc"] is not None


def test_no_timer_records_nulls(tmp_path):
    data = load(write(tmp_path))
    assert data["started_utc"] is None and data["ended_utc"] is None
    assert data["wall_seconds"] is None
    assert data["written_utc"].endswith("Z")


def test_timer_misuse():
    with pytest.raises(RuntimeError):
        prov.RunTimer().stop()
    with pytest.raises(RuntimeError):
        prov.RunTimer().as_dict()


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

def make_snapshot(path, files, mode="*"):
    path.mkdir(parents=True)
    lines = []
    for name, content in files.items():
        (path / name).write_bytes(content)
        lines.append(f"{hashlib.sha256(content).hexdigest()} {mode}{name}")
    (path / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    return path


@pytest.mark.parametrize("mode", ["*", " "])          # binary and text sha256sum formats
def test_snapshot_from_dir(tmp_path, mode):
    snap = make_snapshot(tmp_path / "20261010T0000Z-test", {"a.json": b"[1]", "b.csv": b"x"}, mode)
    info = prov.snapshot_from_dir(snap)
    assert info == {"id": "20261010T0000Z-test", "sha256_of": "SHA256SUMS",
                    "sha256": hashlib.sha256((snap / "SHA256SUMS").read_bytes()).hexdigest()}
    data = load(write(tmp_path / "out", snapshot=snap))
    assert data["snapshot"] == info


def test_snapshot_tampering_is_detected(tmp_path):
    snap = make_snapshot(tmp_path / "snap", {"a.json": b"[1]"})
    (snap / "a.json").write_bytes(b"[2]")
    with pytest.raises(ValueError, match="a.json"):
        prov.snapshot_from_dir(snap)
    (snap / "a.json").unlink()
    with pytest.raises(ValueError, match="missing"):
        prov.snapshot_from_dir(snap)


def test_snapshot_dict_and_none(tmp_path):
    assert load(write(tmp_path))["snapshot"] is None
    snap = {"id": "20261010T1400Z-supgp", "sha256": "ab" * 32, "source": "CelesTrak SupGP"}
    assert load(write(tmp_path, snapshot=snap))["snapshot"] == snap
    with pytest.raises(ValueError):
        write(tmp_path, snapshot={"id": "x", "sha256": "not-a-hash"})
    with pytest.raises(ValueError):
        write(tmp_path, snapshot={"sha256": "ab" * 32})


@pytest.mark.skipif(not PINNED.is_dir(), reason="pinned snapshot not present")
def test_pinned_celestrak_snapshot_is_intact():
    info = prov.snapshot_from_dir(PINNED)
    assert info["id"] == "20261010T1358Z-celestrak"
    assert info["sha256"] == PINNED_SUMS_SHA256


# ---------------------------------------------------------------------------
# validate_manifest
# ---------------------------------------------------------------------------

def test_validate_detects_edited_output(tmp_path):
    (tmp_path / "f.csv").write_text("1\n")
    path = write(tmp_path, outputs=[tmp_path / "f.csv"])
    prov.validate_manifest(path)
    prov.validate_manifest(tmp_path)               # a directory means its manifest.json
    (tmp_path / "f.csv").write_text("2\n")          # same size, different bytes
    with pytest.raises(prov.ManifestValidationError, match="sha256 changed"):
        prov.validate_manifest(path)
    prov.validate_manifest(path, check_files=False)
    (tmp_path / "f.csv").unlink()
    with pytest.raises(prov.ManifestValidationError, match="missing"):
        prov.validate_manifest(path)


def test_validate_detects_inconsistent_hashes(tmp_path):
    path = write(tmp_path)
    data = load(path)
    data["config"]["slack"] = 9.9
    path.write_text(json.dumps(data))
    with pytest.raises(prov.ManifestValidationError, match="config_sha256"):
        prov.validate_manifest(path)

    data = load(write(tmp_path))
    data["run_id"] = "0" * 16
    path.write_text(json.dumps(data))
    with pytest.raises(prov.ManifestValidationError, match="run_id"):
        prov.validate_manifest(path)


@pytest.mark.parametrize("mutate, message", [
    (lambda m: m.pop("seeds"), "missing required key 'seeds'"),
    (lambda m: m.update(dirty="no"), "$.dirty: expected boolean or null"),
    (lambda m: m.update(schema="chronoroute.manifest/2"), "$.schema: must equal"),
    (lambda m: m.update(surprise=1), "unexpected key 'surprise'"),
    (lambda m: m.update(seeds=[-1]), "below the minimum"),
    (lambda m: m.update(seeds=[True]), "expected integer"),
    (lambda m: m["labels"].update(x="ASSUMED"), "not one of"),
    (lambda m: m.update(config_sha256="XYZ"), "does not match"),
    (lambda m: m.update(git_sha="abc123"), "$.git_sha"),
    (lambda m: m["host"].pop("ram_bytes"), "missing required key 'ram_bytes'"),
    (lambda m: m.update(started_utc="2026-10-10 14:00"), "$.started_utc"),
])
def test_schema_rejects_bad_manifests(tmp_path, mutate, message):
    data = load(write(tmp_path))
    mutate(data)
    errors = prov.schema_errors(data, prov.load_schema())
    assert errors and any(message in e for e in errors), errors


def test_schema_accepts_written_manifest_and_json_integers(tmp_path):
    data = load(write(tmp_path, seeds=[3]))
    assert prov.schema_errors(data, prov.load_schema()) == []
    data["seeds"] = [3.0]          # the same JSON number as 3
    assert prov.schema_errors(data, prov.load_schema()) == []


def test_schema_file_uses_only_supported_keywords():
    schema = prov.load_schema()          # runs check_schema over the whole tree
    assert schema["properties"]["schema"]["const"] == prov.SCHEMA_ID
    assert schema["properties"]["labels"]["additionalProperties"]["enum"] == list(prov.LABELS)


def test_check_schema_refuses_unknown_keywords():
    with pytest.raises(prov.SchemaError, match="format"):
        prov.check_schema({"type": "object", "properties": {"t": {"type": "string",
                                                                  "format": "date-time"}}})
    with pytest.raises(prov.SchemaError):
        prov.check_schema({"oneOf": [{"type": "string"}]})
    with pytest.raises(prov.SchemaError):
        prov.check_schema({"$ref": "other.json#/x"})
    with pytest.raises(prov.SchemaError):
        prov.check_schema({"type": "float"})


def test_small_validator_semantics():
    schema = {"$defs": {"hex": {"type": "string", "pattern": "^[0-9a-f]+$"}},
              "type": "object", "required": ["h"],
              "properties": {"h": {"$ref": "#/$defs/hex"},
                             "n": {"type": ["integer", "null"], "minimum": 1, "maximum": 3},
                             "e": {"enum": [1, "a"]},
                             "l": {"type": "array", "items": {"type": "number"},
                                   "minItems": 1, "maxItems": 2}},
              "additionalProperties": False}
    prov.check_schema(schema)
    ok = {"h": "ff", "n": None, "e": 1.0, "l": [1, 2.5]}
    assert prov.schema_errors(ok, schema) == []
    assert prov.schema_errors({"h": "FF"}, schema)                   # pattern
    assert prov.schema_errors({"h": "f", "n": 4}, schema)            # maximum
    assert prov.schema_errors({"h": "f", "e": True}, schema)         # True is not 1
    assert prov.schema_errors({"h": "f", "l": []}, schema)           # minItems
    assert prov.schema_errors({"h": "f", "l": ["x"]}, schema)        # items type
    assert prov.schema_errors({"h": "f", "zz": 1}, schema)           # additionalProperties
    assert prov.schema_errors([], schema)                            # wrong root type
