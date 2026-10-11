"""
rerun.py
--------
Re-run a finished python-sim run with ONE extra fault on one link (the viewer's
live mode: key `d` degrades the selected link, key `f` fails it; master plan P4).

    out = rerun_with_fault(run_dir, flow=0, link=(a, b), start_ns=2_000_000_000, kind="down")

What it does, and why it is a fair "what if":

  * It reads the run's own normalised config and seed from run.json
    (engine.config, written by `cr run` and `cr eval scheme`), appends one fault
    and runs the SAME scenario again: same seed, same traffic, same scheme.
  * Every random draw of the engine is keyed (rng.py) and renewal faults are
    keyed by their identity, not their list position (faults.py), so the new
    run uses exactly the same random numbers: a packet that never meets the
    new fault behaves identically, byte for byte (test_fwd_rerun checks it).
    Only packets that cross the link after start_ns can change.
  * It is a full run of every flow (common random numbers need the same
    traffic), so it takes as long as the original run. `flow` only names the
    flow the viewer follows; it is recorded in run.json "rerun".

Fault kinds (all MODELLED, docs/sim-config.md section 6):

  "rate"  rate_cut: the link rate drops to factor x C (default 0.0002, i.e.
          200 kb/s at 1 Gb/s: the course milestone's fault); queues build by
          themselves. The physical "up but slow" choice, so it is `d`.
  "slow"  slow_processing on the link: +delta_ns per packet (default 10 ms;
          the MODELLED per-packet extra link latency, see faults.py).
  "down"  link_down: the link is down in both directions.

The fault holds from start_ns to stop_ns (default: the end of the sending
window). The output folder (default: next to the run, named after the fault)
gets a full trace/1 run with its manifest.

Re-runs CHAIN: re-running a re-run keeps the faults added before (it starts
from that run's config). run.json "rerun" therefore records the whole list,
"live_faults" (oldest first, each {"kind", "fault"}), and "original" (the
recorded run the chain started from), so the viewer names every fault that is
active in the run on screen, not only the newest.
"""

import json
from fractions import Fraction
from pathlib import Path

from . import config as config_mod

KINDS = {"rate": "rate_cut", "slow": "slow_processing", "down": "link_down"}


def _seconds_text(ns):
    """Integer ns as an exact seconds value the config reads back exactly ("2" or "2001/1000")."""
    f = Fraction(int(ns), 1_000_000_000)
    return str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"


def fault_for(kind, link, start_ns, stop_ns, *, factor="0.0002", delta_ns=10_000_000):
    """The config entry of the extra fault (docs/sim-config.md section 6)."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}, got {kind!r}")
    a, b = (int(x) for x in link)
    f = {"kind": KINDS[kind], "link": [a, b], "start_s": _seconds_text(start_ns), "stop_s": _seconds_text(stop_ns)}
    if kind == "rate":
        f["factor"] = str(factor)
    elif kind == "slow":
        f["delta_ns"] = int(delta_ns)
    return f


def _live_faults_of(run):
    """Faults earlier live re-runs added to `run` (oldest first): [{"kind", "fault"}].

    Re-runs chain: a re-run of a re-run keeps every fault added before (the viewer re-runs
    the run on screen), so run.json "rerun" carries the whole list ("live_faults") and a
    viewer can name every one of them, not only the newest. A re-run written before the list
    existed has only its own "fault"."""
    r = run.get("rerun")
    if not isinstance(r, dict):
        return []
    if isinstance(r.get("live_faults"), list):
        return [dict(x) for x in r["live_faults"]]
    return [{"kind": r.get("kind"), "fault": r.get("fault")}] if r.get("fault") else []


def _original_of(run_dir, run):
    """The recorded run the chain of live re-runs started from."""
    r = run.get("rerun")
    if isinstance(r, dict):
        return r.get("original") or r.get("of") or str(run_dir)
    return str(run_dir)


def rerun_with_fault(run_dir, *, flow, link, start_ns, kind="rate", stop_ns=None, factor="0.0002",
                     delta_ns=10_000_000, out_dir=None):
    """Re-run run_dir with one more fault on `link` (module docstring). Returns the new folder."""
    run_dir = Path(run_dir)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if run.get("tool") != "python-sim":
        raise ValueError(f"only python-sim runs can be re-run (this trace was written by {run.get('tool')!r})")
    eng = run.get("engine") or {}
    cfg = eng.get("config")
    if not isinstance(cfg, dict):
        raise ValueError("run.json has no engine.config (written by cr run / cr eval scheme since 2026-10-11): "
                         "re-run the original once with this version")
    cfg = config_mod.normalise(cfg)                   # re-checked, exactly as the original was
    duration = int(eng["duration_ns"])
    start_ns = int(start_ns)
    stop_ns = duration if stop_ns is None else int(stop_ns)
    if not 0 <= start_ns < stop_ns:
        raise ValueError(f"the fault must start in [0, {stop_ns}) ns, got start {start_ns} ns")
    fault = fault_for(kind, link, start_ns, stop_ns, factor=factor, delta_ns=delta_ns)
    cfg["faults"] = list(cfg["faults"]) + [fault]
    cfg = config_mod.normalise(cfg)
    a, b = fault["link"]
    if out_dir is None:
        out_dir = run_dir.parent / f"{run_dir.name}--rerun-{kind}-{a}-{b}-t{start_ns}"
    out_dir = Path(out_dir)
    extra = {"rerun": {"of": str(run_dir), "flow": int(flow), "kind": kind, "fault": fault,
                       "original": _original_of(run_dir, run),
                       "live_faults": _live_faults_of(run) + [{"kind": kind, "fault": fault}]}}
    argv = ["rerun_with_fault", str(run_dir), f"--flow={int(flow)}", f"--link={a},{b}",
            f"--start-ns={start_ns}", f"--kind={kind}"]
    scheme = run.get("scheme")
    if isinstance(scheme, dict) and isinstance(scheme.get("settings"), dict):
        from ..baselines import params as bparams, run as brun
        brun.run_scheme(cfg, bparams.normalise_scheme(scheme["settings"]), out_dir, argv=argv, run_extra=extra)
    else:
        from .command import run_config
        run_config(cfg, out_dir, argv=argv, run_extra=extra)
    return out_dir


__all__ = ["KINDS", "fault_for", "rerun_with_fault"]
