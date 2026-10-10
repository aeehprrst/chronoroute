#!/usr/bin/env bash
# ns3-sync.sh -- put the ChronoRoute ns-3 code into an ns-3 source tree.
#
#   tools/ns3-sync.sh                 # symlink (default), regenerate the .inc, configure if needed
#   tools/ns3-sync.sh --copy          # copy instead of symlink (for trees that cannot see the repo)
#   tools/ns3-sync.sh --no-configure  # never run ./ns3 configure
#   NS3_DIR=~/ns-3-opt tools/ns3-sync.sh   # another ns-3 tree (default: ~/ns-3-dev)
#
# What it does, in order:
#   1. regenerates ns3/contrib/chronoroute/test/golden-vectors.inc from
#      spec/golden/*.json (tools/golden_to_inc.py; ns-3 has no JSON library);
#   2. makes $NS3_DIR/contrib/chronoroute point at the repository folder.
#      A SYMLINK is the default because ns-3.44's CMake follows it: the
#      contrib scan uses IS_DIRECTORY (true for a link to a directory) and
#      add_subdirectory(contrib/chronoroute), and the generated stub headers in
#      build/include/ns3/ #include the real header by absolute path, so edits in
#      the repository are picked up by the next ./ns3 build with no copy step.
#      (Verified 2026-10-10 on ns-3.44: configure lists "chronoroute", the
#      module builds, ./test.py -s chronoroute runs.)
#      --copy makes a plain copy instead (marked with .chronoroute-sync-copy so
#      a later sync knows it may replace it);
#   3. links (or copies) the legacy ns-3 programs that produced the v0.9
#      numbers, so the repository is their single source of truth:
#        ns3/scratch/*.cc -> $NS3_DIR/scratch/   (Assessment 6-8 programs)
#        ns3/plots/*.py   -> $NS3_DIR/           (their plot scripts)
#      A regular file already in the ns-3 tree is only replaced if it is
#      byte-identical to the repository copy, or is exactly what an earlier
#      --copy sync wrote (recorded in $NS3_DIR/.chronoroute-sync-files), so an
#      edit made in ~/ns-3-dev and never copied back is never thrown away;
#   4. runs `./ns3 configure` when needed. A tree that was never configured
#      (no cmake-cache) gets `./ns3 configure --enable-tests --enable-examples`
#      (the reference tree's settings; the build profile stays "default"), so
#      `./test.py --suite chronoroute` works. A configured tree that does not
#      know the module yet is re-configured with --enable-tests and otherwise
#      its cached settings.
#
# It never builds (that is `make ns3-test`, which runs ./ns3 build -j8; WSL has
# 7.6 GiB of RAM, so keep to 8 jobs or fewer) and never deletes a directory it
# did not create.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS3_DIR="${NS3_DIR:-$HOME/ns-3-dev}"
PYTHON="${PYTHON:-$REPO/venv/bin/python}"
SRC="$REPO/ns3/contrib/chronoroute"
DEST="$NS3_DIR/contrib/chronoroute"
MARKER=".chronoroute-sync-copy"
STATE="$NS3_DIR/.chronoroute-sync-files"    # sha256 + path of every file --copy wrote
MODE="link"
CONFIGURE=1

while [ $# -gt 0 ]; do
    case "$1" in
        --copy) MODE="copy" ;;
        --link) MODE="link" ;;
        --no-configure) CONFIGURE=0 ;;
        -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
        *) echo "ns3-sync: unknown option $1" >&2; exit 2 ;;
    esac
    shift
done

[ -d "$SRC" ] || { echo "ns3-sync: module folder not found: $SRC" >&2; exit 1; }
[ -x "$NS3_DIR/ns3" ] || { echo "ns3-sync: no ns-3 tree at NS3_DIR=$NS3_DIR" >&2; exit 1; }

# 1. golden vectors -> C++
"$PYTHON" -B "$REPO/tools/golden_to_inc.py"

# 2. link or copy the module
mkdir -p "$NS3_DIR/contrib"
if [ "$MODE" = "link" ]; then
    if [ -L "$DEST" ]; then
        if [ "$(readlink -f "$DEST")" != "$(readlink -f "$SRC")" ]; then
            ln -sfn "$SRC" "$DEST"
            echo "ns3-sync: re-pointed $DEST -> $SRC"
        else
            echo "ns3-sync: $DEST -> $SRC (already linked)"
        fi
    elif [ -e "$DEST" ]; then
        if [ -f "$DEST/$MARKER" ]; then
            rm -rf "$DEST"   # a copy this script made earlier
            ln -s "$SRC" "$DEST"
            echo "ns3-sync: replaced the earlier copy with a link $DEST -> $SRC"
        else
            echo "ns3-sync: $DEST exists and is not ours; move it away first" >&2
            exit 1
        fi
    else
        ln -s "$SRC" "$DEST"
        echo "ns3-sync: linked $DEST -> $SRC"
    fi
else
    if [ -L "$DEST" ]; then
        rm "$DEST"       # only the link, never its target
    elif [ -e "$DEST" ] && [ ! -f "$DEST/$MARKER" ]; then
        echo "ns3-sync: $DEST exists and is not ours; move it away first" >&2
        exit 1
    fi
    mkdir -p "$DEST"
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --delete --exclude "$MARKER" "$SRC/" "$DEST/"
    else
        find "$DEST" -mindepth 1 -maxdepth 1 ! -name "$MARKER" -exec rm -rf {} +
        cp -a "$SRC/." "$DEST/"
    fi
    echo "copied from $SRC by tools/ns3-sync.sh; re-run it after editing the repository" > "$DEST/$MARKER"
    echo "ns3-sync: copied $SRC -> $DEST"
fi

# 3. the legacy scratch programs and plot scripts, one file at a time
recorded_sha() {   # the sha256 an earlier --copy sync wrote for this path, if any
    [ -f "$STATE" ] && awk -v p="$1" '$2 == p { print $1 }' "$STATE" | tail -n 1
}
record_sha() {
    local rel="$1" sha
    sha="$(sha256sum "$NS3_DIR/$rel" | cut -d' ' -f1)"
    { [ -f "$STATE" ] && awk -v p="$rel" '$2 != p' "$STATE"; echo "$sha $rel"; } > "$STATE.tmp"
    mv "$STATE.tmp" "$STATE"
}
sync_file() {      # sync_file <repo file> <path relative to NS3_DIR>
    local src="$1" rel="$2" dest="$NS3_DIR/$2"
    if [ -L "$dest" ]; then
        if [ "$MODE" = "link" ] && [ "$(readlink -f "$dest")" = "$(readlink -f "$src")" ]; then
            echo "ns3-sync: $rel -> repository (already linked)"
            return
        fi
        rm "$dest"   # only the link
    elif [ -e "$dest" ]; then
        if cmp -s "$src" "$dest"; then
            :        # same bytes: nothing can be lost
        elif [ "$(sha256sum "$dest" | cut -d' ' -f1)" = "$(recorded_sha "$rel")" ]; then
            :        # exactly what an earlier --copy sync wrote
        else
            echo "ns3-sync: $dest differs from $src and was not written by this script." >&2
            echo "          Copy your edits into the repository (or move the file away), then re-run." >&2
            exit 1
        fi
        rm "$dest"
    fi
    if [ "$MODE" = "link" ]; then
        ln -s "$src" "$dest"
        echo "ns3-sync: linked $rel -> $src"
    else
        cp -p "$src" "$dest"
        record_sha "$rel"
        echo "ns3-sync: copied $src -> $rel"
    fi
}
mkdir -p "$NS3_DIR/scratch"
for f in "$REPO"/ns3/scratch/*.cc; do
    [ -e "$f" ] && sync_file "$f" "scratch/$(basename "$f")"
done
for f in "$REPO"/ns3/plots/*.py; do
    [ -e "$f" ] && sync_file "$f" "$(basename "$f")"
done

# 4. configure, if needed
if [ ! -d "$NS3_DIR/cmake-cache" ]; then
    if [ "$CONFIGURE" -eq 1 ]; then
        echo "ns3-sync: fresh ns-3 tree: ./ns3 configure --enable-tests --enable-examples (profile 'default')"
        (cd "$NS3_DIR" && ./ns3 configure --enable-tests --enable-examples)
    else
        echo "ns3-sync: run './ns3 configure --enable-tests --enable-examples' in $NS3_DIR"
    fi
elif grep -qs "ns3-chronoroute" "$NS3_DIR"/.lock-ns3_*; then
    echo "ns3-sync: ns-3 already knows the chronoroute module"
    if ! grep -qs "^ENABLE_TESTS = True" "$NS3_DIR"/.lock-ns3_*; then
        echo "ns3-sync: WARNING: tests are disabled in $NS3_DIR; run './ns3 configure --enable-tests'" >&2
    fi
elif [ "$CONFIGURE" -eq 1 ]; then
    echo "ns3-sync: running ./ns3 configure --enable-tests (otherwise the cached settings)"
    (cd "$NS3_DIR" && ./ns3 configure --enable-tests)
else
    echo "ns3-sync: run './ns3 configure --enable-tests' in $NS3_DIR so CMake sees the new module"
fi
