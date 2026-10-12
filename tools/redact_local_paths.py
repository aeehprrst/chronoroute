#!/usr/bin/env python3
"""Rewrite absolute local paths in committed result files as repository-relative paths.

Result records written before 12 Oct 2026 stored absolute paths of the machine the runs
were made on: the repository checkout, its virtual environment, the ns-3 build and
temporary folders. This tool rewrites them and then recomputes every value that depends on
the rewritten bytes, so that every provenance check still holds:

* ``<checkout>/x`` becomes ``x`` (relative to the repository root, where every run started)
  and a bare ``<checkout>`` becomes ``.``;
* ``<home>/x`` becomes ``~/x`` (the ns-3 build, temporary folders, tools outside the repo);
* ``config_sha256`` and ``run_id`` of every manifest whose config changed;
* the SHA-256 (and size) of every rewritten file, wherever another record cites it,
  repeated until nothing changes.

A hash that a record keeps for a file that is not in the repository (the raw run folders,
which stay on the machine that made them) still names that original file, so it is kept;
only the copy of such a manifest inside a record has its paths, config_sha256 and run_id
rewritten.

No measured value changes: before anything is written, every rewritten JSON and CSV file is
compared with its original value by value, and the only differences allowed are rewritten
paths, hashes, run ids and the sizes of rewritten files.

    venv/bin/python tools/redact_local_paths.py            # report only
    venv/bin/python tools/redact_local_paths.py --write    # rewrite the files

The rewrite is deterministic: running it on the commit before the rewrite, with the same
checkout and home paths, reproduces the rewritten files byte for byte.
"""

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "sim"))
from chronoroute.provenance import compute_run_id, config_sha256  # noqa: E402

MANIFEST_SCHEMA = "chronoroute.manifest/1"
SHA_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
RUN_ID_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{16}(?![0-9a-f])")
# A cited file size sits next to its hash (manifest outputs: sorted keys, any spacing).
SIZE_RE = re.compile(r'("sha256":\s*"([0-9a-f]{64})",\s*"size_bytes":\s*)(\d+)')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def path_rules(checkout, home):
    path_char = r"[\w.~-]"
    rules = []
    for prefix, short in ((checkout, "."), (home, "~")):
        p = re.escape(prefix.rstrip("/"))
        rules.append((re.compile(p + "/(?=" + path_char + ")"), "" if short == "." else "~/"))
        rules.append((re.compile(p + "/?(?!" + path_char + ")"), short))
    return rules


def rewrite_paths(text, rules):
    for rx, replacement in rules:
        text = rx.sub(replacement, text)
    return text


class Item:
    """One tracked file: its original bytes and, if it is text (or gzipped text), its text."""

    def __init__(self, rel):
        self.rel = rel
        self.raw = (REPO / rel).read_bytes()
        self.gz = None
        self.text = None
        data = self.raw
        if rel.endswith(".gz"):
            try:
                data = gzip.decompress(self.raw)
            except OSError:
                return
            self.gz = gz_header(self.raw)
        if b"\0" in data:
            return
        try:
            self.text = data.decode("utf-8")
        except UnicodeDecodeError:
            return

    @property
    def kind(self):
        name = self.rel[:-3] if self.gz else self.rel
        if name.endswith(".jsonl"):
            return "jsonl"
        if name.endswith(".json"):
            return "json"
        if name.endswith(".csv"):
            return "csv"
        return "text"

    def encode(self, text):
        data = text.encode("utf-8")
        if self.gz is None:
            return data
        name, mtime = self.gz
        buf = io.BytesIO()
        with gzip.GzipFile(filename=name, mode="wb", fileobj=buf, compresslevel=9,
                           mtime=mtime) as fh:
            fh.write(data)
        return buf.getvalue()


def gz_header(raw):
    """(original file name, mtime) from a gzip header, so a rewrite keeps both."""
    flags = raw[3]
    mtime = int.from_bytes(raw[4:8], "little")
    pos = 10
    if flags & 4:  # FEXTRA
        pos += 2 + int.from_bytes(raw[pos:pos + 2], "little")
    name = ""
    if flags & 8:  # FNAME
        end = raw.index(b"\0", pos)
        name = raw[pos:end].decode("latin-1")
    return name, mtime


def json_docs(item, text):
    """The JSON values in a .json or .jsonl text (empty list for other files)."""
    if item.kind == "json":
        return [json.loads(text)]
    if item.kind == "jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return []


def walk_pairs(old, new):
    """Walk two JSON values of the same shape together, yielding dict pairs."""
    if isinstance(old, dict) and isinstance(new, dict):
        yield old, new
        for key in old:
            if key in new:
                yield from walk_pairs(old[key], new[key])
    elif isinstance(old, list) and isinstance(new, list):
        for a, b in zip(old, new):
            yield from walk_pairs(a, b)


def is_manifest(d):
    return (d.get("schema") == MANIFEST_SCHEMA and isinstance(d.get("config"), dict)
            and "config_sha256" in d and "run_id" in d and "git_sha" in d)


class Redactor:
    """Finds the rewritten value of every hash, size and run id, as a fixed point.

    Each file is always rewritten from its ORIGINAL bytes with the current maps, so no
    intermediate value can leak into a file. A file is rewritten again only when a value it
    cites changed in the previous pass, so later passes touch only the files further down
    the provenance chain.
    """

    def __init__(self, items, rules, scope):
        self.rules = rules
        self.scope = scope          # paths are rewritten only in files under these folders
        self.shas = {}              # original sha256 -> rewritten sha256
        self.ids = {}               # original run_id -> rewritten run_id
        self.sizes = {}             # rewritten sha256 -> (original size, rewritten size)
        self.conflicts = []
        self.candidates = []
        for item in items:
            if item.text is None:
                continue
            item.tokens = set(SHA_RE.findall(item.text)) | set(RUN_ID_RE.findall(item.text))
            item.has_path = self.in_scope(item) and any(rx.search(item.text) for rx, _ in rules)
            item.learned = ()
            if item.has_path or item.tokens:
                self.candidates.append(item)

    def in_scope(self, item):
        return any(item.rel.startswith(s) for s in self.scope)

    def transform(self, item):
        text = item.text
        if self.in_scope(item):
            text = rewrite_paths(text, self.rules)
        if self.shas:
            text = SHA_RE.sub(lambda m: self.shas.get(m.group(0), m.group(0)), text)
        if self.ids:
            text = RUN_ID_RE.sub(lambda m: self.ids.get(m.group(0), m.group(0)), text)
        if self.sizes:
            def size(m):
                old_new = self.sizes.get(m.group(2))
                if old_new and int(m.group(3)) == old_new[0]:
                    return m.group(1) + str(old_new[1])
                return m.group(0)
            text = SIZE_RE.sub(size, text)
        return text

    def discover(self, item, text):
        """The (table, original, rewritten, sizes) values that this rewritten file changes."""
        learned = []
        # An unchanged text keeps its original bytes (recompressing a .gz would change them).
        new_raw = item.raw if text == item.text else item.encode(text)
        if new_raw != item.raw:
            learned.append(("shas", sha256(item.raw), sha256(new_raw),
                            (len(item.raw), len(new_raw))))
        if item.kind not in ("json", "jsonl") or text == item.text:
            return learned
        for old_doc, new_doc in zip(json_docs(item, item.text), json_docs(item, text)):
            for old, new in walk_pairs(old_doc, new_doc):
                if is_manifest(old) and is_manifest(new):
                    if config_sha256(old["config"]) == old["config_sha256"]:
                        learned.append(("shas", old["config_sha256"],
                                        config_sha256(new["config"]), None))
                    if compute_run_id(old["config"], old["seeds"], old["git_sha"]) == old["run_id"]:
                        learned.append(("ids", old["run_id"],
                                        compute_run_id(new["config"], new["seeds"],
                                                       new["git_sha"]), None))
        return [entry for entry in learned if entry[1] != entry[2]]

    def load(self, path):
        doc = json.loads(Path(path).read_text())
        self.shas, self.ids = doc["shas"], doc["ids"]
        self.sizes = {k: tuple(v) for k, v in doc["sizes"].items()}

    def save(self, path):
        Path(path).write_text(json.dumps({"shas": self.shas, "ids": self.ids,
                                          "sizes": self.sizes}, sort_keys=True))

    def run(self, cache=None):
        changed = None              # None: the first pass rewrites every candidate file
        for passes in range(1, 101):
            rewritten = 0
            for item in self.candidates:
                if changed is None or not item.tokens.isdisjoint(changed):
                    item.learned = self.discover(item, self.transform(item))
                    rewritten += 1
            tables, sizes, self.conflicts = {"shas": {}, "ids": {}}, {}, []
            for item in self.candidates:
                for table, old, new, size in item.learned:
                    known = tables[table].get(old)
                    if known is not None and known != new:
                        self.conflicts.append((old, known, new))
                    tables[table][old] = new
                    if size:
                        sizes[new] = size
            changed = set()
            for old_map, new_map in ((self.shas, tables["shas"]), (self.ids, tables["ids"])):
                changed |= {k for k in old_map.keys() | new_map.keys()
                            if old_map.get(k) != new_map.get(k)}
            self.shas, self.ids, self.sizes = tables["shas"], tables["ids"], sizes
            print(f"pass {passes}: {rewritten} files rewritten; {len(self.shas)} hashes and "
                  f"{len(self.ids)} run ids mapped; {len(changed)} changed", flush=True)
            if cache:
                self.save(cache)
            if self.conflicts or not changed:
                return passes
        raise SystemExit("no fixed point after 100 passes")


# ---------------------------------------------------------------------------
# Independent value-by-value check
# ---------------------------------------------------------------------------

def is_token(value):
    return isinstance(value, str) and (SHA_RE.fullmatch(value) or RUN_ID_RE.fullmatch(value))


def compare_values(old, new, rules, where, problems, key=None, sizes_ok=False):
    if isinstance(old, dict) and isinstance(new, dict):
        # Keys may be paths too (e.g. a table of library files and their hashes).
        keys = [rewrite_paths(k, rules) for k in old]
        if keys != list(new):
            problems.append(f"{where}: keys differ")
            return
        changed_hash = is_token(old.get("sha256")) and old.get("sha256") != new.get("sha256")
        for k, k2 in zip(old, keys):
            compare_values(old[k], new[k2], rules, f"{where}.{k2}", problems, k2,
                           sizes_ok=changed_hash)
    elif isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            problems.append(f"{where}: list length differs")
            return
        for i, (a, b) in enumerate(zip(old, new)):
            compare_values(a, b, rules, f"{where}[{i}]", problems)
    elif isinstance(old, str) and isinstance(new, str):
        if rewrite_paths(old, rules) == new:
            return
        if tokens_only_differ(rewrite_paths(old, rules), new):
            return
        problems.append(f"{where}: string changed beyond paths and hashes")
    elif type(old) is type(new) and old == new:
        return
    elif key == "size_bytes" and sizes_ok and isinstance(old, int) and isinstance(new, int):
        return
    else:
        problems.append(f"{where}: value changed ({old!r} -> {new!r})")


def tokens_only_differ(a, b):
    mask = lambda s: RUN_ID_RE.sub("<id>", SHA_RE.sub("<sha>", s))  # noqa: E731
    return mask(a) == mask(b)


def check_item(item, new_text, rules, in_scope):
    """Problems found when comparing a rewritten file with its original."""
    old_text = item.text
    problems = []
    if item.kind in ("json", "jsonl"):
        old_docs, new_docs = json_docs(item, old_text), json_docs(item, new_text)
        if len(old_docs) != len(new_docs):
            return [f"{item.rel}: number of JSON documents differs"]
        for i, (a, b) in enumerate(zip(old_docs, new_docs)):
            compare_values(a, b, rules if in_scope else [], f"{item.rel}#{i}", problems)
    elif item.kind == "csv":
        old_rows = list(csv.reader(io.StringIO(old_text)))
        new_rows = list(csv.reader(io.StringIO(new_text)))
        if len(old_rows) != len(new_rows):
            return [f"{item.rel}: number of rows differs"]
        for r, (a, b) in enumerate(zip(old_rows, new_rows)):
            if len(a) != len(b):
                problems.append(f"{item.rel} row {r}: number of cells differs")
                continue
            for c, (x, y) in enumerate(zip(a, b)):
                x2 = rewrite_paths(x, rules) if in_scope else x
                if x2 != y and not tokens_only_differ(x2, y):
                    problems.append(f"{item.rel} row {r} cell {c}: value changed")
    else:
        old_lines, new_lines = old_text.splitlines(), new_text.splitlines()
        if len(old_lines) != len(new_lines):
            return [f"{item.rel}: number of lines differs"]
        for n, (x, y) in enumerate(zip(old_lines, new_lines)):
            x2 = rewrite_paths(x, rules) if in_scope else x
            if x2 != y and not tokens_only_differ(x2, y):
                problems.append(f"{item.rel} line {n + 1}: changed beyond paths and hashes")
    return problems[:5]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--checkout", default=str(REPO),
                    help="absolute checkout path recorded in the files (default: this checkout)")
    ap.add_argument("--home", default=str(Path.home()),
                    help="absolute home folder recorded in the files (default: yours)")
    ap.add_argument("--scope", nargs="+", default=["results/"],
                    help="folders whose files get their paths rewritten (default: results/)")
    ap.add_argument("--cache", help="JSON file that keeps the maps between runs (optional)")
    ap.add_argument("--write", action="store_true", help="rewrite the files")
    args = ap.parse_args(argv)

    rules = path_rules(args.checkout, args.home)
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, check=True,
                            capture_output=True).stdout.decode().split("\0")
    items = [Item(rel) for rel in listed if rel and (REPO / rel).is_file()]
    needle = args.home.rstrip("/").encode()
    binary = [i.rel for i in items if i.text is None and needle in i.raw]

    red = Redactor(items, rules, tuple(args.scope))
    if args.cache and Path(args.cache).exists():
        red.load(args.cache)
    passes = red.run(args.cache)
    if red.conflicts:
        for old, a, b in red.conflicts[:10]:
            print(f"conflict: {old} -> {a} and {b}", file=sys.stderr)
        return 1

    changes, problems = [], []
    for item in items:
        if item.text is None:
            continue
        text = red.transform(item)
        if text != item.text:
            changes.append((item, text))
            problems += check_item(item, text, rules, red.in_scope(item))
    left = [item.rel for item, text in changes
            if red.in_scope(item) and args.home.rstrip("/") in text]
    # A rewritten hash or run id must not be part of a file name: names are not rewritten.
    named = [rel for rel in listed if rel and any(
        token in red.shas or token in red.ids
        for token in SHA_RE.findall(rel) + RUN_ID_RE.findall(rel))]
    for rel in named[:10]:
        print(f"PROBLEM a rewritten hash or run id is part of the file name {rel}")
    problems += [f"file name {rel}" for rel in named]

    print(f"{len(changes)} files change after {passes} passes; "
          f"{len(red.shas)} hashes, {len(red.ids)} run ids")
    for rel in binary:
        print(f"binary file still holding a local path (not rewritten): {rel}")
    for rel in left:
        print(f"still holding a local path: {rel}")
    for p in problems[:40]:
        print(f"PROBLEM {p}")
    if problems or left:
        print("not written: fix the problems above first", file=sys.stderr)
        return 1
    if args.write:
        for item, text in changes:
            (REPO / item.rel).write_bytes(item.encode(text))
        print(f"wrote {len(changes)} files")
    else:
        print("report only; add --write to rewrite the files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
