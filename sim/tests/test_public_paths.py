"""The repository is public: committed files and new manifests hold no local home-folder paths."""

import gzip
import json
import re
import subprocess
from pathlib import Path

import pytest

from chronoroute import provenance

REPO = Path(__file__).resolve().parents[2]

# An absolute path inside somebody's home folder (Linux, macOS or Windows). The names "x" and
# "user" are placeholders that tests and documents use on purpose.
HOME_PATH = re.compile(rb"/home/(?!(?:x|user)/)[a-z_][a-z0-9_.-]*/"
                       rb"|/Users/[A-Za-z][^/\s\"]*/"
                       rb"|[A-Za-z]:\\{1,2}Users\\{1,2}[A-Za-z]")


def _tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, check=True,
                         capture_output=True).stdout.decode()
    return [REPO / rel for rel in out.split("\0") if rel]


def _text(path):
    data = path.read_bytes()
    if path.suffix == ".gz":
        try:
            data = gzip.decompress(data)
        except OSError:
            return None
    return None if b"\0" in data else data


def test_no_committed_file_holds_a_home_folder_path():
    if not (REPO / ".git").exists():
        pytest.skip("not a git checkout")
    found = []
    for path in _tracked_files():
        if not path.is_file():
            continue
        data = _text(path)
        if data is not None and HOME_PATH.search(data):
            found.append(str(path.relative_to(REPO)))
    assert not found, ("local home-folder paths in committed files (rewrite them with "
                       f"tools/redact_local_paths.py --write): {found[:10]}")


def test_public_paths_rewrites_checkout_and_home_paths():
    repo, home = "/srv/me/chronoroute", "/srv/me"
    value = {
        "command": f"{repo}/venv/bin/python -B {repo}/experiments/E01/confirm.py --out results/E01/x",
        "cwd": repo,
        "trailing": f"{repo}/",
        "ns3": [f"-I{home}/ns-3-dev/build/include", f"{home}/tmpab12/bundle"],
        "pair": (f"{repo}/results/a/raw:{repo}/results/b/raw",),
        "other": "/opt/tools/bin/node /srv/me2/file /srv/me/chronoroute2/x",
        "number": 3,
    }
    out = provenance.public_paths(value, repo_dir=repo, home=home)
    assert out == {
        "command": "venv/bin/python -B experiments/E01/confirm.py --out results/E01/x",
        "cwd": ".",
        "trailing": ".",
        "ns3": ["-I~/ns-3-dev/build/include", "~/tmpab12/bundle"],
        "pair": ("results/a/raw:results/b/raw",),
        "other": "/opt/tools/bin/node /srv/me2/file ~/chronoroute2/x",
        "number": 3,
    }


def test_public_paths_leaves_shallow_prefixes_alone():
    assert provenance.public_paths("/data/x", repo_dir="/", home="/data") == "/data/x"


def test_new_manifests_record_repository_relative_paths(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "ns-3-dev").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    out = provenance.REPO_ROOT / "results" / "does-not-exist"
    manifest = provenance.build_manifest(
        tmp_path / "run", tool="t", tool_version="1",
        command=[str(provenance.REPO_ROOT / "venv/bin/python"), "-B", "x.py", "--out", str(out)],
        config={"ns3": str(home / "ns-3-dev"), "out": str(out)},
        seeds=[1], extra={"raw_cache": str(out)})
    text = json.dumps(manifest)
    assert str(provenance.REPO_ROOT) not in text and str(home) not in text
    assert manifest["command"] == "venv/bin/python -B x.py --out results/does-not-exist"
    assert manifest["config"] == {"ns3": "~/ns-3-dev", "out": "results/does-not-exist"}
    assert manifest["config_sha256"] == provenance.config_sha256(manifest["config"])
