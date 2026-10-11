"""
hud.py
------
Every line of text the viewer shows, built as plain strings so the content can be
tested without opening a window (sim/tests/test_viz_hud.py).

Units in the hop table (spec/tcrh-v1.md sections 4-6):
  * arrival   = the hop's arrival time minus the send time (exact, from the trace ns);
  * deadline  = the instant after which the packet counts as late at that hop,
                minus the send time. A node is late when its clock is PAST the
                deadline unit D_k, i.e. from (D_k + 1) * u on, so that is the
                instant shown;
  * margin    = D_k - now_u in units (serial arithmetic), times the unit: exactly
                the comparison the node made. Negative = late.
So "arrival > deadline" and "margin < 0" always agree.

Labels (REAL / DERIVED / MODELLED) come from the run's own labels (whose keys and
values are those of the shared table chronoroute/labels.py), never typed in here and
never assumed: a label the run does not give shows as NOT LABELLED.
"""

from ..proto import tcrh as tcrh_mod
from ..proto import timebase
from ..data import omm

KEYS_LINE = ("space next packet | m next deadline miss | d degrade link | f fail link | [ ] pick link | "
             "l link-state view | +/- speed | r replay | right-click satellite")

SOFTWARE_RENDERERS = ("llvmpipe", "softpipe", "swrast", "software rasterizer", "lavapipe")


def fmt_ms(ns, digits=3, sign=True):
    value = ns / 1e6
    return f"{value:+.{digits}f} ms" if sign else f"{value:.{digits}f} ms"


def fmt_utc(utc_ns, digits=3):
    """'2026-10-10 14:00:04.512 UTC' (truncated, never rounded up past a second)."""
    sec, rest = divmod(int(utc_ns), 1_000_000_000)
    text = omm.format_utc_ns(sec * 1_000_000_000)[:-1].replace("T", " ")
    frac = f"{rest:09d}"[:digits]
    return f"{text}.{frac} UTC" if digits else f"{text} UTC"


# ----------------------------------------------------------------------- provenance

NOT_LABELLED = "NOT LABELLED"


def label_line(labels, snapshot_id, positions_note="SGP4"):
    """'Positions REAL (snapshot ..., SGP4) | ISLs MODELLED (Grid-4) | Queues MODELLED'.

    Every label is the run's own (run.json 'labels', the shared keys of labels.py). A key
    the run does not have is never assumed: a synthetic Walker run labels its positions
    with 'synthetic_walker_constellation' (MODELLED), and anything else missing shows as
    NOT LABELLED rather than as REAL.
    """
    if "satellite_positions_sgp4" in labels:
        pos = labels["satellite_positions_sgp4"]
        where = f"snapshot {snapshot_id}, " if snapshot_id else ""
    elif "synthetic_walker_constellation" in labels:
        pos = labels["synthetic_walker_constellation"]
        where = f"synthetic Walker preset {snapshot_id}, " if snapshot_id else "synthetic Walker preset, "
    else:
        pos = NOT_LABELLED
        where = f"snapshot {snapshot_id}, " if snapshot_id else ""
    isl = labels.get("isl_topology_grid4", NOT_LABELLED)
    queues = labels.get("link_rate_and_queues", NOT_LABELLED)
    return f"Positions {pos} ({where}{positions_note}) | ISLs {isl} (Grid-4) | Queues {queues}"


def renderer_info(capabilities):
    """(renderer, version, software?) parsed from VTK's ReportCapabilities() text."""
    renderer = version = None
    for line in (capabilities or "").splitlines():
        low = line.strip().lower()
        if low.startswith("opengl renderer string:"):
            renderer = line.split(":", 1)[1].strip()
        elif low.startswith("opengl version string:"):
            version = line.split(":", 1)[1].strip()
    software = renderer is not None and any(s in renderer.lower() for s in SOFTWARE_RENDERERS)
    return renderer, version, software


def renderer_line(capabilities):
    """'renderer: D3D12 (Intel(R) Iris(R) Xe Graphics), OpenGL 4.1' or '... (software)'.

    A software fallback is always named (task P4: never hide it).
    """
    renderer, version, software = renderer_info(capabilities)
    if renderer is None:
        return "renderer: unknown (VTK did not report an OpenGL renderer)"
    gl = ""
    if version:
        gl = ", OpenGL " + version.split()[0]
    return f"renderer: {renderer}{' (software)' if software else ''}{gl}"


# ----------------------------------------------------------------------- clocks

def clock_lines(player, t0_unix_ns=None):
    """Two lines: the orbit clock and the packet clock, each with its speed."""
    from .player import IDLE
    orbit = f"Orbit clock  {fmt_utc(player.orbit_utc_ns)}  "
    if player.state == IDLE:
        orbit += f"running x{player.orbit_speed:g}"
    else:
        orbit += "frozen while a packet is shown (satellites move ~7.6 m per ms)"
    walk = player.walk
    if walk is None or t0_unix_ns is None:
        packet = f"Packet clock  (no packet)  slow motion x{player.slowmo:g}"
        return [orbit, packet]
    t = walk.sim_t
    packet = f"Packet clock  t0 + {t / 1e9:.6f} s  "
    seg = walk.current
    if player.state == IDLE:
        packet += f"slow motion x{player.slowmo:g} (idle)"
    elif seg is not None and walk.is_fast_forward(seg) and not walk.done:
        what = "queue/serialization wait" if seg.kind == "wait" else "flight"
        packet += (f"FAST-FORWARD: {(seg.t_b - seg.t_a) / 1e6:,.1f} ms {what} shown in "
                   f"{walk.segment_wall_s(seg):.1f} s (x{walk.screen_factor():.3g})")
    else:
        packet += f"slow motion x{player.slowmo:g}"
    return [orbit, packet]


# ----------------------------------------------------------------------- hop table

def epoch_units(trace, send_t):
    """Epoch_Base the ingress stamps for a packet sent at trace time send_t (not wrapped)."""
    u = timebase.unit_ns(trace.unit_code)
    return -(-(trace.t0_gps_ns + int(send_t)) // u)


def deadline_rel_ns(trace, send_t, deadline_u):
    """Instant after which the packet is late at that hop, minus the send time (module docstring)."""
    u = timebase.unit_ns(trace.unit_code)
    e_abs = epoch_units(trace, send_t)
    d_units = timebase.serial_diff(int(deadline_u), e_abs % timebase.MOD32)
    return (e_abs + d_units + 1) * u - (trace.t0_gps_ns + int(send_t))


def margin_units(event):
    if event.deadline_u is None or event.now_u is None:
        return None
    return timebase.serial_diff(event.deadline_u, event.now_u)


HOP_HEADER = f"{'hop':>3}  {'SID':>5}  {'node':<16} {'deadline':>11} {'arrival':>11} {'margin':>10}"


def hop_rows(trace, track, reached=None):
    """The hop table as (text, status) rows; status in ok / late / fallback / send / end."""
    events = track.events if reached is None else reached
    send = track.send
    unit_ms = timebase.unit_ns(trace.unit_code) / 1e6
    rows = [(HOP_HEADER, "header")]
    if send is not None and (reached is None or len(reached) > 0):
        n = trace.nodes[send.node]
        rows.append((f"{0:>3}  {n.sid:>5}  {n.name[:16]:<16} {'(ingress)':>11} {fmt_ms(0):>11} "
                     f"{'':>10}", "send"))
    late_nodes = {(e.node, e.t) for e in events if e.ev == "late"}
    fb_nodes = {(e.node, e.t) for e in events if e.ev == "fallback"}
    k = 0
    for e in events:
        if e.ev != "hop":
            continue
        k += 1
        n = trace.nodes[e.node]
        dl = (fmt_ms(deadline_rel_ns(trace, send.t, e.deadline_u), 1)
              if send is not None and e.deadline_u is not None else "-")
        arr = fmt_ms(e.t - send.t) if send is not None else "-"
        m = margin_units(e)
        mtxt = f"{m * unit_ms:+.1f} ms" if m is not None else "-"
        status = "ok"
        tag = ""
        if (e.node, e.t) in late_nodes:
            status, tag = "late", "  LATE: DEV set"
        elif m is not None and m < 0:
            status, tag = "late", "  late (DEV already set)"
        if (e.node, e.t) in fb_nodes:
            status, tag = "fallback", tag + "  FALLBACK"
        rows.append((f"{k:>3}  {n.sid:>5}  {n.name[:16]:<16} {dl:>11} {arr:>11} {mtxt:>10}{tag}", status))
    total_hops = len(track.arrivals)
    if reached is not None and k < total_hops:
        rows.append((f"     ... {total_hops - k} more hop{'s' if total_hops - k != 1 else ''}", "pending"))
    return rows


# ----------------------------------------------------------------------- header bytes

def flags_text(flags):
    return (f"Flags=0x{flags:02x}: DEV={1 if flags & tcrh_mod.FLAG_DEV else 0} "
            f"GREEDY={1 if flags & tcrh_mod.FLAG_GREEDY else 0} "
            f"SAT={1 if flags & tcrh_mod.FLAG_SAT else 0} "
            f"unit={(flags & tcrh_mod.FLAG_UNIT_MASK) >> tcrh_mod.FLAG_UNIT_SHIFT}")


def header_hex_parts(hexstr, per_line=24):
    """Split T-CRH bytes for display with Segments Left (byte 3) and Flags (byte 4) highlighted.

    Returns (line1_parts, more_lines): line1_parts = [(text, role)] for the 12 fixed
    bytes, role in plain / sl / flags; more_lines = the entries, per_line bytes a line.
    """
    raw = bytes.fromhex(hexstr)
    b = [f"{x:02x}" for x in raw]
    fixed = b[:tcrh_mod.OFF_ENTRIES]
    parts = [(" ".join(fixed[:3]) + " ", "plain"), (fixed[3], "sl"), (" ", "plain"),
             (fixed[4], "flags"), (" " + " ".join(fixed[5:8]) + " | " + " ".join(fixed[8:12]), "plain")]
    rest = b[tcrh_mod.OFF_ENTRIES:]
    more = [" ".join(rest[i:i + per_line]) for i in range(0, len(rest), per_line)]
    return parts, more


HEADER_WHEN = {"send": "leaving the source", "hop": "as it arrived", "deliver": "as delivered",
               "drop": "when dropped", "late": "after the deadline check", "fallback": "at the fallback"}


def header_lines(event, late=None):
    """Plain-text header block for an event: hex (with [SL] and [Flags] marked) + decoded fields.

    The bytes are the trace's own (spec/trace-v1.md: a hop event carries the header
    as it ARRIVED). `late`: a later 'late' event at the same node, whose SL/Flags
    (DEV just set) are added after the decoded line, since it carries no bytes.
    """
    if event is None:
        return ["T-CRH: -"]
    when = HEADER_WHEN.get(event.ev, event.ev)
    if not event.hex:
        sl = "-" if event.sl is None else str(event.sl)
        fl = "-" if event.flags is None else flags_text(event.flags)
        return [f"T-CRH bytes not sampled for this packet in the trace; {when}: SL={sl}  {fl}"]
    parts, more = header_hex_parts(event.hex)
    line1 = "".join(f"[{t}]" if role in ("sl", "flags") else t for t, role in parts)
    hdr, _n = tcrh_mod.TcrhHeader.decode_prefix(bytes.fromhex(event.hex))
    decoded = (f"{when}: SL={hdr.segments_left} (byte 3)  {flags_text(hdr.flags)} (byte 4)  "
               f"NumHops={hdr.num_hops}  DevHop={hdr.dev_hop}  Epoch_Base={hdr.epoch_base}")
    if late is not None and late.flags is not None:
        decoded += f"  ->  this node set DEV: leaves with Flags=0x{late.flags:02x}"
    return [f"T-CRH  {line1}", *[f"       {m}" for m in more], decoded]


def header_context(reached):
    """(event whose bytes to show, late event after it or None) for the reached events."""
    ev = latest_header_event(reached)
    late = None
    if ev is not None:
        after = reached[reached.index(ev) + 1:] if ev in reached else []
        late = next((e for e in after if e.ev == "late" and e.node == ev.node), None)
    return ev, late


def latest_header_event(reached):
    """The header to show: the most recent reached event WITH bytes when the packet has any,
    else the most recent one that at least has SL / Flags. A 'late' event is never chosen
    (it carries the bytes after processing, spec/trace-v1.md 3): the arrival bytes are shown
    with the late event's 'this node set DEV' note instead (header_context), which tells
    what the node saw AND what it did."""
    with_hex = [e for e in reached if e.hex and e.ev != "late"]
    if with_hex:
        return with_hex[-1]
    for e in reversed(reached):
        if e.sl is not None:
            return e
    return None


# ----------------------------------------------------------------------- messages

def event_message(trace, track, event):
    """The headline for an event that matters (late, fallback, end), or None."""
    n = trace.nodes[event.node]
    unit_ms = timebase.unit_ns(trace.unit_code) / 1e6
    if event.ev == "late":
        by = -margin_units(event) if margin_units(event) is not None else None
        hop = [e.node for e in track.arrivals].index(event.node) + 1 if any(
            e.node == event.node for e in track.arrivals) else "?"
        by_txt = f"{by * unit_ms:.1f} ms (now_u - D = {by} units)" if by is not None else "?"
        return f"MISS by {by_txt} at {n.name} (SID {n.sid}, hop {hop}): DEV set"
    if event.ev == "fallback":
        return f"FALLBACK at {n.name} (SID {n.sid}): leaves the source route ({event.reason or 'policy'})"
    if event.ev == "deliver":
        lat = track.latency_ns
        dev = event.flags is not None and event.flags & tcrh_mod.FLAG_DEV
        tail = ""
        if dev:
            late = track.late_events
            where = trace.nodes[late[0].node].name if late else "?"
            tail = f", DEV=1 (late at {where})"
        return f"delivered to {n.name} in {lat / 1e6:.3f} ms{tail}" if lat is not None else \
            f"delivered to {n.name}{tail}"
    if event.ev == "drop":
        return f"DROPPED at {n.name} (SID {n.sid}): {event.reason or 'no reason given'}"
    return None


def packet_title(trace, track):
    return (f"packet {track.pkt}  flow {track.flow} ({trace.flow_label(track.flow)})  "
            f"sent t0 + {track.t_start / 1e9:.6f} s  {len(track.arrivals)} hops")


# ----------------------------------------------------------------------- links, picking, modes

def fault_text(trace, fault):
    """One line about a ground-truth fault, whichever producer wrote it (python-sim writes
    'factor' etc. as in spec/trace-v1.md 1.3; cr trace from-ns3 adds the rates in b/s)."""
    p = fault.params
    if fault.link:
        where = " - ".join(trace.nodes[x].name for x in fault.link)
    elif fault.node is not None:
        where = trace.nodes[fault.node].name
    else:
        where = "?"
    what = []
    if "rate_bps" in p:
        nominal = p.get("nominal_rate_bps")
        what.append(f"rate {_bps(nominal)} -> {_bps(p['rate_bps'])}" if nominal
                    else f"rate {_bps(p['rate_bps'])}")
    elif "factor" in p:
        what.append(f"rate x {p['factor']}")
    if p.get("delta_ns"):
        what.append(f"+{p['delta_ns'] / 1e6:g} ms processing")
    if p.get("extra_delay_ns"):
        what.append(f"+{p['extra_delay_ns'] / 1e6:g} ms")
    if "loss" in p:
        what.append(f"loss {p['loss']}")
    state = {"link_down": "link DOWN", "node_down": "node DOWN"}.get(fault.kind, "link stays UP")
    # "t0 + 1.51864 s to 4 s", not "1.51864-4 s" (which reads like 1.51864e-4)
    parts = [where, *what, f"t0 + {fault.start_ns / 1e9:g} s to {fault.stop_ns / 1e9:g} s", state]
    label = trace.labels.get("fault_slow_link") or trace.labels.get("fault_models") or NOT_LABELLED
    return f"fault {fault.kind} ({label}, ground truth): " + ", ".join(parts)


def _bps(v):
    if v is None:
        return "?"
    for unit, div in (("Gb/s", 1e9), ("Mb/s", 1e6), ("kb/s", 1e3)):
        if v >= div:
            return f"{v / div:g} {unit}"
    return f"{v} b/s"


def link_line(trace, link, hop_index=None):
    if link is None:
        return "selected link: none"
    a, b = link
    hop = f" (hop {hop_index})" if hop_index is not None else ""
    return f"selected link: {trace.nodes[a].name} - {trace.nodes[b].name}{hop}"


def overlay_line(on, slowed_up=None):
    if not on:
        return None
    text = "LINK-STATE VIEW (l): green = up, red = down (what link-state routing sees)"
    if slowed_up:
        text += "; the slowed link is still UP (green)"
    return text


LIVE_WHAT = {"rate": "degraded (rate cut)", "slow": "slowed", "down": "failed"}


def live_faults(trace):
    """Faults added by live re-runs that are active in this trace, oldest first: [(kind, fault)].

    A live key re-runs the run ON SCREEN, so faults accumulate; fwd/rerun.py writes the whole
    list to run.json "rerun" "live_faults" (an older re-run has only its own "fault")."""
    r = (trace.run or {}).get("rerun") if trace is not None else None
    if not isinstance(r, dict):
        return []
    lst = r.get("live_faults")
    if isinstance(lst, list):
        return [(x.get("kind"), x.get("fault") or {}) for x in lst if isinstance(x, dict)]
    return [(r.get("kind"), r.get("fault") or {})] if r.get("fault") else []


def _live_parts(trace, kind, fault):
    """('A - B', 'failed from t0 + 2.000 s') for one live fault."""
    from fractions import Fraction
    a, b = fault.get("link") or (None, None)
    name = (lambda n: trace.nodes[n].name if n in trace.nodes else str(n))
    start = fault.get("start_s")
    when = f" from t0 + {float(Fraction(str(start))):.3f} s" if start is not None else ""
    return f"{name(a)} - {name(b)}", f"{LIVE_WHAT.get(kind, kind)}{when}"


def live_fault_phrase(trace, kind, fault):
    """'A - B failed from t0 + 2.000 s' for one live fault."""
    return " ".join(_live_parts(trace, kind, fault))


def live_faults_lines(trace, max_listed=4):
    """The globe's HUD block for a live re-run: a header, then two short lines per live fault
    (the link; what and from when), oldest first. With more than max_listed faults the oldest
    ones are summarised in one line that says how many (the 2D map's side panel, the message
    and run.json list every one). [] for a recorded run."""
    lf = live_faults(trace)
    if not lf:
        return []
    out = [f"LIVE FAULTS ({len(lf)}, all active; d/f add one)"]
    first = max(0, len(lf) - max_listed)
    if first:
        out.append(f"  ... {first} older one{'' if first == 1 else 's'} not listed here")
    for i, (kind, fault) in enumerate(lf[first:], first + 1):
        link, what = _live_parts(trace, kind, fault)
        out += [f"{i}. {link}", f"   {what}"]
    return out


def live_faults_text(trace):
    """'N live faults in this run (all active): ...' or None when the trace is not a live re-run.

    Shown for as long as the re-run is on screen (globe: its own HUD text on the right; 2D
    map: the side panel), because the event messages below it change with every packet."""
    lf = live_faults(trace)
    if not lf:
        return None
    parts = "; ".join(live_fault_phrase(trace, k, f) for k, f in lf)
    return (f"{len(lf)} live fault{'' if len(lf) == 1 else 's'} in this run (all active; d / f add "
            f"one more): {parts}")


def mode_line(engine_available, reason=None):
    """Live (the engine re-runs) or replay-only, and why."""
    if engine_available:
        return ("live: d re-runs the engine with the selected link degraded (rate cut), f with it "
                "failed; same seed and random numbers")
    return (f"replay-only: {reason or 'engine API not available'}, so d / f show the recorded fault "
            "instead of a new run")


def positions_note(positions):
    """How the satellite positions on screen were computed RIGHT NOW (for label_line).

    A bundle trace (ns-3) is drawn from the bundle's positions.csv: SGP4 samples every
    1 s joined by a cubic Hermite curve, which is not the same as evaluating SGP4 at the
    drawn instant; outside the bundle's window the viewer falls back to SGP4 itself.
    Both cases are named, so the HUD never shows interpolated samples as direct SGP4.
    """
    from .sources import BundlePositions
    src = getattr(positions, "last_source", None) or getattr(positions, "primary", None)
    primary = getattr(positions, "primary", None)
    if isinstance(src, BundlePositions):
        step = src.step_ms / 1000.0
        note = f"SGP4 samples at {step:g} s from the bundle, interpolated"
        if src.clamped:
            note += ", HELD outside the bundle window"
        return note
    if isinstance(primary, BundlePositions):
        return "SGP4 evaluated directly (outside the bundle's sample window)"
    return "SGP4"


def pick_lines(name, norad, sid, elements, orbit_utc_ns, lat=None, lon=None, alt_km=None):
    """The right-click panel: the REAL element set and its epoch age at the orbit clock."""
    out = [f"{name}  NORAD {norad}" + (f"  SID {sid}" if sid is not None else "")]
    if elements is None:
        out.append("elements: snapshot not loaded")
    else:
        age_h = (orbit_utc_ns - elements.epoch_ns) / 3.6e12
        out.append(f"epoch {elements.epoch} ({elements.source}), age {age_h:+.2f} h at the orbit clock")
        out.append(f"i {elements.inclination_deg:.4f} deg  RAAN {elements.raan_deg:.4f} deg  "
                   f"e {elements.eccentricity:.7f}  n {elements.mean_motion_rev_day:.8f} rev/day")
    if lat is not None:
        out.append(f"now: lat {lat:+.3f}  lon {lon:+.3f}  alt {alt_km:.1f} km (SGP4, WGS84)")
    return out


__all__ = ["KEYS_LINE", "label_line", "renderer_info", "renderer_line", "clock_lines",
           "hop_rows", "header_hex_parts", "header_lines", "latest_header_event", "event_message",
           "packet_title", "fault_text", "link_line", "overlay_line", "mode_line", "live_faults",
           "live_fault_phrase", "live_faults_lines", "live_faults_text", "positions_note", "pick_lines",
           "deadline_rel_ns", "margin_units", "fmt_utc", "fmt_ms", "flags_text"]
