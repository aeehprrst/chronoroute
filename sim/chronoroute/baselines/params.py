"""
params.py
---------
Settings of the comparison schemes, their defaults and their checks.

A scheme is chosen with a small mapping (the `scheme:` block of a run file,
see docs/baselines.md), for example

    scheme:
      name: ls_h
      ls: {preset: ospf, bfd: true}

Every key must be known (a typo is an error, never silently ignored) and
every value is checked, exactly like the engine's own config (fwd/config.py).

Where a number comes from (docs/baselines.md has the full table):

  OLSR   HELLO_INTERVAL 2 s, NEIGHB_HOLD_TIME = 3 x REFRESH_INTERVAL = 6 s
         (RFC 3626 sections 18.2, 18.3). A TC message after a link failure
         "SHOULD be transmitted after an interval shorter than TC_INTERVAL"
         (section 9.3): modelled as sent at once (no MinLSInterval).
  OLSR-LEO  hello 1 s / hold 3 s: the same 1:3 ratio, tuned for LEO
         (the plan's "best LEO setting", fairness rule 1; not from an RFC).
  OSPF   HelloInterval 10 s ("Sample value for a local area network"),
         RouterDeadInterval "some multiple of the HelloInterval (say 4)"
         = 40 s (RFC 2328 appendix C.3); MinLSInterval 5 s (appendix B).
  BFD    detection time = Detect Mult x agreed transmit interval
         (RFC 5880 section 6.8.4); 3 x 100 ms is a typical choice, not a
         default of the RFC.
  SPF    INITIAL_SPF_DELAY 50 ms (RFC 8405 section 6 default); the back-off
         to 200 ms / 5 s under churn is NOT modelled (this favours LS).
  RFC 7471 delay: default measurement interval 30 s, values are averages
         (sections 3, 7); inter-update throttle default 120 s, at most one
         announcement per second, accelerated announcement when a value
         changes by more than a configured threshold (sections 5, 7).
  FB1    50 ms one-way report delay, penalty x{2, 10, inf}, hold {10, 60} s
         (experiment E8).
  CRH state  CRH-FIB (+ station table) and, with a fallback, element sets
         re-uploaded to every satellite every 4 h: the SupGP refresh cadence of
         the planner's data; a MODELLED choice, swept by
         setting crh_state.*_s.
  Failure visibility  forwarding.carrier_detect_ms (engine config) for every
         scheme; LS fault_detection "carrier" uses it (docs/baselines.md 2.3).
"""

import copy
from fractions import Fraction

from ..fwd.config import ConfigError, exact_fraction

SCHEMES = ("chronoroute", "crh16", "e2e", "lq", "o_t", "o_q", "snap", "ls_h", "ls_d")

# which data plane a scheme uses (engine.py):
#   "crh"    the engine's own byte path: SIDs in a T-CRH, the ground's planned path
#   "oracle" a source route chosen at send time by an oracle on the TRUE network
#   "table"  hop-by-hop next-hop tables (no routing header)
DATA_PLANE = {"chronoroute": "crh", "crh16": "crh", "e2e": "crh", "lq": "crh",
              "o_t": "oracle", "o_q": "oracle", "snap": "table", "ls_h": "table", "ls_d": "table"}

# routing header carried by each scheme (for the wire size and the header-byte metric)
HEADER = {"chronoroute": "tcrh", "crh16": "crh16", "e2e": "e2e", "lq": "crh16",
          "o_t": "crh16", "o_q": "crh16", "snap": "none", "ls_h": "none", "ls_d": "none"}

LS_PRESETS = {
    # name: hello_s, dead_s, min_ls_interval_s, source
    "olsr_leo": ("1", "3", "0", "LEO-tuned 1/3 s with the RFC 3626 1:3 hello:hold ratio (MODELLED choice)"),
    "olsr": ("2", "6", "0", "RFC 3626 sections 18.2-18.3: HELLO_INTERVAL 2 s, NEIGHB_HOLD_TIME 6 s"),
    "ospf": ("10", "40", "5", "RFC 2328 appendix C.3 (HelloInterval 10 s, dead 4 x hello), "
                              "appendix B (MinLSInterval 5 s)"),
}

DEFAULTS = {
    "name": "chronoroute",
    # ChronoRoute feedback (FB0 none / FB1 report to the ground)
    "feedback": {"mode": "fb0", "delay_ms": 50, "penalty": 10, "hold_s": 10, "report_bytes": 64,
                 "min_interval_ms": 0},
    # E2E: one end-to-end deadline, checked at the destination, reported to the ground
    "e2e": {"report_delay_ms": 50, "localize": "path", "penalty": 10, "hold_s": 10, "report_bytes": 64,
            "deadline_bytes": 8, "feedback": True, "window_s": 1},
    # LQ: the upstream node watches its own egress queue and ARQ retransmissions
    "lq": {"q_th_ms": 1, "action": "flag", "arq_window_ms": 100},
    # SNAP: Hypatia-style precomputed forwarding tables
    "snap": {"update_s": 1, "telemetry_s": 10, "upload_latency_ms": 0, "at_dead_next_hop": "drop",
             "entry_bytes": 6, "upload_header_bytes": 56, "telemetry_bytes": 64, "count_uploads": True},
    # link-state family (LS-H and LS-D). fault_detection "carrier" (default): a failed link is
    # noticed by loss of carrier after forwarding.carrier_detect_ms, exactly when every other
    # scheme's node notices it (one failure-visibility model, docs/baselines.md 2.3);
    # carrier_detect_ms None = the engine's value (another value is refused). "hello": a SILENT
    # failure noticed only by missing hellos / BFD (sensitivity analysis; NOT like-for-like,
    # since the other schemes still see the carrier loss; run.json says so).
    "ls": {"preset": "olsr_leo", "hello_s": None, "dead_s": None, "min_ls_interval_s": None,
           "bfd": False, "bfd_interval_ms": 100, "bfd_mult": 3, "spf_delay_ms": 50, "lsa_hop_ns": None,
           "carrier_detect_ms": None, "adjacency_ms": 0, "fault_detection": "carrier"},
    # what a ChronoRoute-family satellite (crh data plane) must be sent, besides the schedule
    # rows that go to the ingress gateway: its CRH-FIB with the ground
    # station table, and (with a fallback function) the element sets of itself and its laser
    # neighbours. Both re-uploaded every period, each satellite at its own keyed phase. The 4 h
    # default is the SupGP refresh cadence of the data the planner uses
    # ("CelesTrak: SupGP (every 4 h)"); sizes as SNAP's upload (56 B header) and state_report.
    "crh_state": {"count": True, "fib_refresh_s": 14400, "ephemeris_upload_s": 14400,
                  "upload_header_bytes": 56, "fib_entry_bytes": 4, "tle_bytes": 140, "gs_coord_bytes": 12},
    # LS-D extra: RFC 7471-style delay measurement and advertisement
    "ls_d": {"window_s": 30, "threshold": 0.2, "variant": "avg", "inter_update_s": 120,
             "min_interval_s": 1, "probe_ms": 100},
    # outputs of the scheme runner
    "outputs": {"stretch_oracle": True},
}

PENALTIES = (2, 10, "inf")


def _merge(defaults, user, where):
    if user is None:
        return copy.deepcopy(defaults)
    if not isinstance(user, dict):
        raise ConfigError(f"{where} must be a mapping")
    out = copy.deepcopy(defaults)
    for key, value in user.items():
        if key not in defaults:
            raise ConfigError(f"unknown setting {where}.{key} (known: {', '.join(sorted(defaults))})")
        if isinstance(defaults[key], dict):
            out[key] = _merge(defaults[key], value, f"{where}.{key}")
        else:
            out[key] = copy.deepcopy(value)
    return out


def _pos_num(value, where, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"{where} must be a number, got {value!r}")
    f = exact_fraction(value, where)
    if f < 0 or (f == 0 and not allow_zero):
        raise ConfigError(f"{where} must be {'>= 0' if allow_zero else '> 0'}, got {value!r}")
    return f


def _int(value, where, lo=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < lo:
        raise ConfigError(f"{where} must be an integer >= {lo}, got {value!r}")
    return value


def _choice(value, choices, where):
    if value not in choices:
        raise ConfigError(f"{where} must be one of {choices}, got {value!r}")
    return value


def ns(value_fraction, unit_ns):
    """An exact Fraction of some unit -> integer ns (refuses values that are not whole ns)."""
    v = Fraction(value_fraction) * unit_ns
    if v.denominator != 1:
        raise ConfigError(f"{value_fraction} x {unit_ns} ns is not a whole number of ns")
    return int(v)


def to_ns(value, unit_ns, where="value"):
    """A setting read exactly from its decimal text (1.5, "0.1", 50) in some unit -> integer ns."""
    return ns(exact_fraction(value, where), unit_ns)


MS = 1_000_000
S = 1_000_000_000


def normalise_scheme(doc):
    """Merge a scheme mapping (or a bare scheme name) onto DEFAULTS and check it."""
    if isinstance(doc, str):
        doc = {"name": doc}
    if not isinstance(doc, dict):
        raise ConfigError("scheme must be a name or a mapping with a name")
    s = _merge(DEFAULTS, doc, "scheme")
    _choice(s["name"], SCHEMES, "scheme.name")

    fb = s["feedback"]
    _choice(fb["mode"], ("fb0", "fb1"), "scheme.feedback.mode")
    _pos_num(fb["delay_ms"], "scheme.feedback.delay_ms", allow_zero=True)
    _choice(fb["penalty"], PENALTIES, "scheme.feedback.penalty")
    _pos_num(fb["hold_s"], "scheme.feedback.hold_s")
    _int(fb["report_bytes"], "scheme.feedback.report_bytes", 1)
    _pos_num(fb["min_interval_ms"], "scheme.feedback.min_interval_ms", allow_zero=True)
    if fb["mode"] == "fb1" and s["name"] != "chronoroute":
        raise ConfigError("scheme.feedback.mode fb1 applies to the chronoroute scheme only")

    e = s["e2e"]
    _pos_num(e["report_delay_ms"], "scheme.e2e.report_delay_ms", allow_zero=True)
    _choice(e["localize"], ("path", "intersect"), "scheme.e2e.localize")
    _choice(e["penalty"], PENALTIES, "scheme.e2e.penalty")
    _pos_num(e["hold_s"], "scheme.e2e.hold_s")
    _int(e["report_bytes"], "scheme.e2e.report_bytes", 1)
    _int(e["deadline_bytes"], "scheme.e2e.deadline_bytes", 0)
    if not isinstance(e["feedback"], bool):
        raise ConfigError("scheme.e2e.feedback must be true or false")
    _pos_num(e["window_s"], "scheme.e2e.window_s")

    lq = s["lq"]
    _pos_num(lq["q_th_ms"], "scheme.lq.q_th_ms")
    _choice(lq["action"], ("flag", "detour"), "scheme.lq.action")
    _pos_num(lq["arq_window_ms"], "scheme.lq.arq_window_ms")

    sn = s["snap"]
    _pos_num(sn["update_s"], "scheme.snap.update_s")
    _pos_num(sn["telemetry_s"], "scheme.snap.telemetry_s", allow_zero=True)
    _pos_num(sn["upload_latency_ms"], "scheme.snap.upload_latency_ms", allow_zero=True)
    _choice(sn["at_dead_next_hop"], ("drop", "detour"), "scheme.snap.at_dead_next_hop")
    for k in ("entry_bytes", "upload_header_bytes", "telemetry_bytes"):
        _int(sn[k], f"scheme.snap.{k}", 0)
    if not isinstance(sn["count_uploads"], bool):
        raise ConfigError("scheme.snap.count_uploads must be true or false")

    ls = s["ls"]
    _choice(ls["preset"], tuple(LS_PRESETS), "scheme.ls.preset")
    hello, dead, minls, _src = LS_PRESETS[ls["preset"]]
    ls["hello_s"] = str(_pos_num(hello if ls["hello_s"] is None else ls["hello_s"], "scheme.ls.hello_s"))
    ls["dead_s"] = str(_pos_num(dead if ls["dead_s"] is None else ls["dead_s"], "scheme.ls.dead_s"))
    ls["min_ls_interval_s"] = str(_pos_num(minls if ls["min_ls_interval_s"] is None
                                           else ls["min_ls_interval_s"], "scheme.ls.min_ls_interval_s",
                                           allow_zero=True))
    if Fraction(ls["dead_s"]) < Fraction(ls["hello_s"]):
        raise ConfigError("scheme.ls.dead_s must be >= hello_s (a neighbour is declared dead only "
                          "after at least one missed hello)")
    if not isinstance(ls["bfd"], bool):
        raise ConfigError("scheme.ls.bfd must be true or false")
    _pos_num(ls["bfd_interval_ms"], "scheme.ls.bfd_interval_ms")
    _int(ls["bfd_mult"], "scheme.ls.bfd_mult", 1)
    _pos_num(ls["spf_delay_ms"], "scheme.ls.spf_delay_ms", allow_zero=True)
    if ls["lsa_hop_ns"] is not None:
        _int(ls["lsa_hop_ns"], "scheme.ls.lsa_hop_ns", 0)
    if ls["carrier_detect_ms"] is not None:
        _pos_num(ls["carrier_detect_ms"], "scheme.ls.carrier_detect_ms", allow_zero=True)
    _pos_num(ls["adjacency_ms"], "scheme.ls.adjacency_ms", allow_zero=True)
    _choice(ls["fault_detection"], ("carrier", "hello"), "scheme.ls.fault_detection")

    cs = s["crh_state"]
    if not isinstance(cs["count"], bool):
        raise ConfigError("scheme.crh_state.count must be true or false")
    _pos_num(cs["fib_refresh_s"], "scheme.crh_state.fib_refresh_s")
    _pos_num(cs["ephemeris_upload_s"], "scheme.crh_state.ephemeris_upload_s")
    for k in ("upload_header_bytes", "fib_entry_bytes", "tle_bytes", "gs_coord_bytes"):
        _int(cs[k], f"scheme.crh_state.{k}", 0)

    d = s["ls_d"]
    _pos_num(d["window_s"], "scheme.ls_d.window_s")
    th = _pos_num(d["threshold"], "scheme.ls_d.threshold")
    if th >= 10:
        raise ConfigError("scheme.ls_d.threshold is a fraction (0.2 = 20 %), got a value >= 10")
    _choice(d["variant"], ("avg", "min"), "scheme.ls_d.variant")
    _pos_num(d["inter_update_s"], "scheme.ls_d.inter_update_s")
    _pos_num(d["min_interval_s"], "scheme.ls_d.min_interval_s", allow_zero=True)
    _pos_num(d["probe_ms"], "scheme.ls_d.probe_ms")
    if Fraction(str(d["probe_ms"])) * 1_000_000 > Fraction(str(d["window_s"])) * 1_000_000_000:
        raise ConfigError("scheme.ls_d.probe_ms must not exceed the measurement window")

    if not isinstance(s["outputs"]["stretch_oracle"], bool):
        raise ConfigError("scheme.outputs.stretch_oracle must be true or false")
    return s


def scheme_label(s):
    """A short human name for result tables, e.g. 'ls_h[ospf+bfd]' or 'chronoroute[fb1 x10 10s]'."""
    n = s["name"]
    if n == "chronoroute":
        fb = s["feedback"]
        return n if fb["mode"] == "fb0" else f"{n}[fb1 x{fb['penalty']} {fb['hold_s']}s]"
    if n in ("ls_h", "ls_d"):
        tag = s["ls"]["preset"] + ("+bfd" if s["ls"]["bfd"] else "")
        if s["ls"]["fault_detection"] == "hello":
            tag += " silent"                 # failures noticed by hellos only (not like-for-like)
        if n == "ls_d":
            d = s["ls_d"]
            tag += f" M{d['window_s']}s th{d['threshold']} {d['variant']}"
        return f"{n}[{tag}]"
    if n == "snap":
        sn = s["snap"]
        return f"snap[up {sn['update_s']}s tel {sn['telemetry_s']}s {sn['at_dead_next_hop']}]"
    if n == "lq":
        return f"lq[{s['lq']['q_th_ms']}ms {s['lq']['action']}]"
    if n == "e2e":
        return f"e2e[{s['e2e']['localize']}]"
    return n


__all__ = ["SCHEMES", "DATA_PLANE", "HEADER", "LS_PRESETS", "DEFAULTS", "PENALTIES", "MS", "S", "ns",
           "to_ns", "normalise_scheme", "scheme_label"]
