#!/usr/bin/env bash
# Prepare every file the viva demo needs, plus offline backups, in one folder.
#
#     tools/viva-prepare.sh [OUT]          # default OUT: ~/cr-viva
#     tools/viva-prepare.sh [OUT] --site   # also build the website for offline use (web/dist)
#
# Run it inside WSL from the repository root the day before the viva, and again on the
# morning if you like (it starts from a clean OUT each time). Nothing here downloads
# anything: it uses the pinned snapshot and the committed course-milestone results.
# The steps and what each file is for are in docs/viva/README.md.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

OUT="${HOME}/cr-viva"
SITE=0
for arg in "$@"; do
    case "$arg" in
        --site) SITE=1 ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
        -*) echo "unknown option: $arg" >&2; exit 2 ;;
        *) OUT="$arg" ;;
    esac
done

CR="$REPO/venv/bin/cr"
SNAPSHOT="data/pinned/20261010T1358Z-celestrak"
SMALL="results/course-milestone/c5-463-10s-small-seed1"
FULL="results/course-milestone/c5-463-60s-seed1"
export MPLBACKEND=Agg PYTHONDONTWRITEBYTECODE=1
# The Intel GPU through WSLg; the viewer falls back to software rendering on its own if needed.
export GALLIUM_DRIVER="${GALLIUM_DRIVER:-d3d12}"

[[ -x "$CR" ]] || { echo "venv/bin/cr not found: create the venv first (see README.md)" >&2; exit 1; }
case "$OUT" in
    /|"$HOME"|"$REPO"|"$REPO"/*) echo "refusing to use $OUT as the output folder" >&2; exit 2 ;;
esac
rm -rf -- "$OUT"
mkdir -p "$OUT"/{wireshark,netanim,backup,bundles}

step() { printf '\n== %s\n' "$*"; }

step "1/7 fleet report from the pinned CelesTrak snapshot"
"$CR" fleet report "$SNAPSHOT" --out "$OUT/fleet" | tail -n 4

step "2/7 ns-3 course-milestone run -> viewer trace (rebuilds its scenario bundle, byte-identical)"
"$CR" trace from-ns3 "$SMALL" --out "$OUT/ns3-small-fault" \
    --rebuild-bundle "$OUT/bundles/c5-463-10s-small" | tail -n 4

step "3/7 Wireshark captures (decompressed) + automatic dissector check"
zcat "$SMALL/fault/capture.pcap.gz" > "$OUT/wireshark/small-fault.pcap"
zcat "$FULL/fault/capture.pcap.gz"  > "$OUT/wireshark/60s-fault.pcap"
zcat "$FULL/nofault/capture.pcap.gz" > "$OUT/wireshark/60s-nofault.pcap"
for f in "$OUT"/wireshark/*.pcap; do
    tools/wireshark/check_pcap.sh --quiet "$f"
done

step "4/7 NetAnim animation files"
cp "$FULL/anim/anim.xml" "$OUT/netanim/anim-60s.xml"
cp "$SMALL/anim/anim.xml" "$OUT/netanim/anim-10s-small.xml"
ls -l "$OUT/netanim"

step "5/7 a fresh Python simulator run for the live slowed-link demo (real 463 km shell, 20 s)"
cat > "$OUT/live.yaml" <<'EOF'
# Live demo: two flows on the real 463 km shell, no fault recorded; press d in the
# viewer to slow one laser link from that moment on (the simulator re-runs in seconds).
scenario: {kind: real, duration_s: 20}
traffic: {flows: [{src: Chennai, dst: London}, {src: London, dst: Chennai}], rate_pps: 100}
forwarding: {policy: continue}
EOF
"$CR" run --config "$OUT/live.yaml" --seed 1 --out "$OUT/live" | tail -n 3

step "6/7 offline backup pictures and a video (off-screen rendering)"
"$CR" viz globe --trace "$OUT/ns3-small-fault" --screenshot "$OUT/backup/globe-deadline-miss.png" --at 10.3
"$CR" viz map2d --trace "$OUT/ns3-small-fault" --out "$OUT/backup/map2d-deadline-miss.png" --at 10.3
"$CR" viz globe --trace "$OUT/ns3-small-fault" --record "$OUT/backup/globe-deadline-miss.mp4" --seconds 20
"$CR" viz globe --snapshot "$SNAPSHOT" --shell 53.2deg-463km --screenshot "$OUT/backup/fleet-463km-shell.png" --at 1
"$CR" route --from Chennai --to London > "$OUT/backup/route-chennai-london.txt"
cp "$OUT"/fleet/*.png "$OUT/backup/" 2>/dev/null || true

step "7/7 website"
if [[ "$SITE" == 1 ]]; then
    export PATH="$HOME/.local/opt/node/bin:$PATH"
    (cd web && { [[ -f public/data/latest.json ]] || npm run data; } && npm run build >/dev/null)
    echo "built web/dist; serve it offline with:  cd web && npx astro preview --host 127.0.0.1 --port 4321"
else
    echo "skipped (add --site to build web/dist for offline use)"
fi

WIN="\\\\wsl.localhost\\ubuntu${OUT//\//\\}"
cat <<EOF

Done. Everything is in $OUT
  From Windows (Wireshark, File > Open):  $WIN\\wireshark\\small-fault.pcap
  Viewer (ns-3 deadline miss):            venv/bin/cr viz globe --trace $OUT/ns3-small-fault
  Viewer (live slowed-link demo):         venv/bin/cr viz globe --trace $OUT/live
  NetAnim:                                QT_QPA_PLATFORM=xcb ~/netanim/build/netanim  then File > Open $OUT/netanim/anim-60s.xml
  Offline backups:                        $OUT/backup  ($WIN\\backup)
EOF
