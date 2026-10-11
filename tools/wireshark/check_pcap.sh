#!/usr/bin/env bash
# check_pcap.sh: check every ChronoRoute T-CRH frame of a capture with tshark and
# print one line per frame.
#
#   tools/wireshark/check_pcap.sh [--timebase utc|off|offset:NS] [--quiet] <capture.pcap>
#
# Works for any link type tshark understands, e.g. the Python pcaps
# (LINKTYPE_RAW 101) and ns-3 point-to-point captures (DLT_PPP 9).
#
# A frame is INVALID when the T-CRH dissector (tcrh.lua, next to this script)
# says the header breaks spec/tcrh-v1.md section 6 step 1 (tcrh.valid == 0),
# when a Routing Type 253 header was not decoded by it at all, when Wireshark
# marks a T-CRH frame as malformed, or when the Lua dissector raised an error.
#
# A frame whose only T-CRH is QUOTED inside an ICMPv6 error message (e.g. the
# Parameter Problem a node sends back to the source) is not a T-CRH frame: the
# header is a copy of an older packet. It is listed with "quoted" in the valid
# column and counted on its own ("Q quoted in ICMPv6 errors"); it never counts
# as a T-CRH frame, as DEV, as late, or as invalid (a quoted header is often
# the malformed one that caused the error). Only a Lua error still counts.
#
# --timebase tells the dissector how to read capture timestamps for the margin
# column: utc (default; Python pcaps), off, or offset:NS where GPS time in ns =
# capture timestamp in ns + NS (e.g. an ns-3 run's t0_gps_ns).
#
# Exit status: 0 every T-CRH frame is valid, 1 some frame is invalid (they are
# listed on stderr), 2 usage error / tshark missing / tshark failed,
# 3 the capture holds no T-CRH frame at all (probably the wrong file).
# A zero UDP checksum (illegal over IPv6) is reported as a warning only.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lua="$here/tcrh.lua"
tshark_bin="${TSHARK:-tshark}"

usage() {
    # the comment block at the top of this file is the help text
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0" >&2
    exit 2
}

prefs=()
quiet=0
while [ $# -gt 0 ]; do
    case "$1" in
        --timebase)
            [ $# -ge 2 ] || usage
            case "$2" in
                utc|off) prefs+=(-o "tcrh.timebase:$2") ;;
                offset:*)
                    ns="${2#offset:}"
                    # an integer, possibly negative: GPS ns = capture ns + offset
                    [[ "$ns" =~ ^-?[0-9]+$ ]] || { echo "check_pcap: offset must be an integer number of ns, got '$ns'" >&2; exit 2; }
                    prefs+=(-o "tcrh.timebase:offset" -o "tcrh.offset_ns:$ns") ;;
                *) echo "check_pcap: --timebase must be utc, off or offset:NS" >&2; exit 2 ;;
            esac
            shift 2 ;;
        --quiet) quiet=1; shift ;;
        -h|--help) usage ;;
        --) shift; break ;;
        -*) echo "check_pcap: unknown option $1" >&2; usage ;;
        *) break ;;
    esac
done
[ $# -eq 1 ] || usage
pcap="$1"
[ -r "$pcap" ] || { echo "check_pcap: cannot read $pcap" >&2; exit 2; }
command -v "$tshark_bin" >/dev/null 2>&1 || { echo "check_pcap: tshark not found (set TSHARK=...)" >&2; exit 2; }
[ -r "$lua" ] || { echo "check_pcap: $lua is missing" >&2; exit 2; }

err="$(mktemp "${TMPDIR:-/tmp}/check_pcap.XXXXXX")"
trap 'rm -f "$err"' EXIT

# One tshark pass over every frame that has (or should have) a T-CRH.
# Columns: 1 frame, 2 ipv6.dst, 3 segleft, 4 flags, 5 current SID, 6 margin ms,
# 7 valid, 8 reason, 9 DEV, 10 late, 11 malformed, 12 Lua error,
# 13 UDP checksum status (4 = "illegal": a zero UDP checksum, forbidden over IPv6),
# 14 quoted (1 = the T-CRH is a copy inside an ICMPv6 error message).
# -E occurrence=f: the first value of each field (the outer header when a
# packet is encapsulated; a frame whose own header is T-CRH therefore reads
# quoted = 0 even if it also carries a quoted copy).
if ! rows="$("$tshark_bin" -n -r "$pcap" -X "lua_script:$lua" "${prefs[@]}" \
        -Y 'tcrh || ipv6.routing.type == 253 || _ws.lua.error' \
        -T fields -E separator=/t -E occurrence=f \
        -e frame.number -e ipv6.dst -e ipv6.routing.segleft -e tcrh.flags \
        -e tcrh.current_sid -e tcrh.margin_ms -e tcrh.valid -e tcrh.reason \
        -e tcrh.flags.dev -e tcrh.late -e _ws.malformed -e _ws.lua.error \
        -e udp.checksum.status -e tcrh.quoted 2>"$err")"; then
    echo "check_pcap: tshark failed on $pcap:" >&2
    cat "$err" >&2
    exit 2
fi

printf '%s\n' "$rows" | awk -F'\t' -v quiet="$quiet" -v pcap="$pcap" '
    function show(x) { return (x == "") ? "-" : x }
    BEGIN {
        if (!quiet) printf "%-7s %-28s %-4s %-6s %-8s %-11s %s\n",
                           "frame", "ipv6.dst", "SL", "flags", "cur_sid", "margin_ms", "valid"
    }
    NF == 0 { next }
    $14 == "1" {
        # only a quoted copy in an ICMPv6 error: listed and counted apart
        quoted++
        if ($12 != "") {
            invalid++
            badlist = badlist sprintf("  frame %s: lua_error (quoted header)\n", $1)
        }
        if (!quiet) printf "%-7s %-28s %-4s %-6s %-8s %-11s %s\n",
                           $1, show($2), show($3), show($4), show($5), "-", "quoted"
        next
    }
    {
        n++
        bad = ($7 != "1" || $11 != "" || $12 != "")
        if (bad) {
            invalid++
            why = ($8 != "") ? $8 : (($12 != "") ? "lua_error" : (($7 == "") ? "not_decoded" : "wireshark_malformed"))
            badlist = badlist sprintf("  frame %s: %s\n", $1, why)
        }
        if ($9 == "True") dev++
        if ($10 == "1") late++
        if ($13 == "4") zero_csum++
        if (!quiet) printf "%-7s %-28s %-4s %-6s %-8s %-11s %s\n",
                           $1, show($2), show($3), show($4), show($5), show($6), bad ? "NO" : "yes"
    }
    END {
        printf "check_pcap: %s: %d T-CRH frames, %d invalid, %d with DEV, %d late at capture, %d quoted in ICMPv6 errors (not counted)\n",
               pcap, n, invalid, dev, late, quoted
        # Not a T-CRH fault, so not counted as invalid, but worth saying: an
        # ns-3 run with checksums disabled writes 0, which IPv6 forbids.
        if (zero_csum > 0)
            printf "check_pcap: warning: %d frames have a zero UDP checksum (illegal over IPv6; in ns-3 set ChecksumEnabled)\n",
                   zero_csum > "/dev/stderr"
        if (invalid > 0) { printf "check_pcap: invalid frames:\n%s", badlist > "/dev/stderr"; exit 1 }
        if (n == 0) { print "check_pcap: no T-CRH frame in this capture" > "/dev/stderr"; exit 3 }
    }
'
