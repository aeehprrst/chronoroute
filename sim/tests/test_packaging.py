"""
Packaging and repository hygiene (P1 review, end-to-end findings):

  * the manifest schema ships INSIDE the chronoroute package, so a normal
    (non-editable) `pip install .` can still write and validate manifests;
    spec/schemas/manifest.schema.json stays as the documented copy and must
    be byte-identical;
  * pyproject.toml needs setuptools >= 77 for the PEP 639 licence string,
    declares the LICENSE file and the schema as package data;
  * .gitattributes keeps hashed / byte-compared files exactly as committed
    (a CRLF checkout broke the pinned-snapshot check);
  * the ns-3 .inc is checked by `make golden` (so CI checks it too).
"""

import importlib.resources
import subprocess
import tomllib
from pathlib import Path

from chronoroute import provenance as prov

REPO = Path(__file__).resolve().parents[2]


def test_manifest_schema_is_package_data():
    packaged = importlib.resources.files("chronoroute") / "schemas" / "manifest.schema.json"
    assert packaged.is_file()
    # provenance reads the packaged copy, not a path into the source checkout
    assert Path(str(prov.SCHEMA_PATH)).resolve() == Path(str(packaged)).resolve()
    assert "spec" not in Path(str(prov.SCHEMA_PATH)).relative_to(REPO / "sim").parts
    # the documented copy in spec/ is the same file, byte for byte
    assert packaged.read_bytes() == (REPO / "spec" / "schemas" / "manifest.schema.json").read_bytes()
    assert prov.load_schema()["properties"]["schema"]["const"] == prov.SCHEMA_ID


def test_pyproject_build_requirements_and_package_data():
    meta = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    requires = meta["build-system"]["requires"]
    assert any(r.replace(" ", "").startswith("setuptools>=") and
               tuple(int(x) for x in r.split(">=")[1].split(".")[:1]) >= (77,) for r in requires)
    assert meta["project"]["license"] == "MIT"
    assert meta["project"]["license-files"] == ["LICENSE"]
    assert "schemas/*.json" in meta["tool"]["setuptools"]["package-data"]["chronoroute"]
    licence = (REPO / "LICENSE").read_text(encoding="utf-8")
    assert licence.startswith("MIT License") and "Arshpreet Gaba" in licence


def test_gitattributes_protects_hashed_files():
    attrs = (REPO / ".gitattributes").read_text(encoding="utf-8")
    lines = {ln.split("#")[0].strip() for ln in attrs.splitlines()}
    for rule in ("data/** -text", "spec/golden/** -text", "results/** -text"):
        assert rule in lines, rule
    # and git really applies them (no line-ending conversion for these paths)
    out = subprocess.run(
        ["git", "-C", str(REPO), "check-attr", "text", "--",
         "data/pinned/20261010T1358Z-celestrak/SHA256SUMS", "spec/golden/tcrh_vectors.json",
         "results/legacy-v0.9/dev/exp1_slack_sweep/exp1_slack_sweep.csv"],
        capture_output=True, text=True, check=True).stdout
    assert out.count("text: unset") == 3, out


def test_make_golden_checks_the_ns3_inc():
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    golden = makefile.split("\ngolden:", 1)[1].split("\n\n", 1)[0]
    assert "tools/golden_to_inc.py --check" in golden
