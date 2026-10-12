"""
queues.py
---------
One FIFO transmit queue per DIRECTED link (MODELLED: rate, buffer and the
background traffic are our choices).

The foreground packets (the probes the engine forwards from header bytes)
go through the queue packet by packet with the Lindley recursion, written
with departure times:

    start_n = max(ready_n, end_{n-1})          (wait while the transmitter is busy)
    end_n   = start_n + size_n * 8 / C(start_n)  (serialization at the rate in force)

which is W_{n+1} = max(0, W_n + S_n - A_{n+1}) of the plan. Serialization
uses ns-3's rounding (round half up to whole ns; at 1 Gb/s exactly 8 ns per
byte), so a run without background reproduces ns-3's timing.

Buffer (drop-tail): a packet is refused if the bytes of the packets that are
still in the system (waiting or being transmitted) plus its own size would
exceed the buffer. Default buffer = 20 ms x C (2.5 MB at 1 Gb/s).

Background cross-traffic at load rho (offered rho * C on every link it is
enabled on), one of:

  "none"     no background.
  "fluid"    an EXACT solution of the fluid FIFO: background is a constant
             bit stream of rate rho * C entering the same FIFO. The backlog
             X(t) (bits, kept as integers x 1e9 so that every update is exact)
             grows at rho*C - C_eff while positive (or from 0 if the link is
             overloaded, e.g. under a rate cut f*C < rho*C), is capped by the
             buffer (excess fluid is dropped and counted), and a foreground
             packet leaves when everything ahead of it plus itself has been
             sent. Cheap (a few integer operations per packet). It captures
             overload and slow drain exactly, but a constant stream has no
             burstiness: with rho < 1 and a sparse probe it adds NO queueing.
  "poisson"  EXACT packet-level M/D/1 cross-traffic: Poisson arrivals of
             fixed-size packets (packet_bytes) into the same FIFO, with the
             same drop-tail rule. Generated lazily in fixed windows, each
             window drawn from its own keyed stream (rng component
             "background", entity (a, b, window)), so the background of a
             link is identical in a fault run and its fault-free twin (common
             random numbers). Between two foreground packets the background
             is processed in one vectorised numpy step (max-plus form of the
             recursion: end_n = (n+1) S + max(F, max_k<=n (a_k - k S))),
             falling back to a plain loop only when a drop or a rate change
             happens inside the batch. Long idle gaps are skipped exactly by
             coupling from the past: starting H before the next foreground
             packet from a FULL buffer and no drops (an upper bound on every
             possible state), the first instant that bound finds the queue
             empty is an instant where the true queue is empty too, and from
             there the true queue is simulated exactly.

Why both: the fluid model is what the plan proposed for large runs (P3a), and
it is exact for what it models; the Poisson model is the one with real
queueing jitter (the plan's J2 = "emergent queues") and is exact
packet-level, but costs about rho*C/packet_bytes arrivals per link-second
(41,667 per link-second at rho = 0.5, 1500 B, 1 Gb/s).
"""

import bisect
from collections import deque

import numpy as np

NS_PER_S = 1_000_000_000


def ser_ns(size_bytes, rate_bps):
    """Serialization time in whole ns, rounded half up (ns-3 DataRate::CalculateBytesTxTime)."""
    return (16 * NS_PER_S * size_bytes + rate_bps) // (2 * rate_bps)


class RateSchedule:
    """Link rate over time: nominal C, cut to f*C during fault intervals (piecewise constant).

    changes: sorted list of (t_ns, rate_bps) where the rate becomes rate_bps.
    """

    __slots__ = ("nominal", "times", "rates")

    def __init__(self, nominal, changes=()):
        self.nominal = int(nominal)
        ch = sorted(changes)
        self.times = [t for t, _ in ch]
        self.rates = [int(r) for _, r in ch]

    def at(self, t):
        if not self.times:
            return self.nominal
        i = bisect.bisect_right(self.times, t) - 1
        return self.nominal if i < 0 else self.rates[i]

    def next_change_after(self, t):
        """(time, rate) of the first change strictly after t, or None."""
        i = bisect.bisect_right(self.times, t)
        return (self.times[i], self.rates[i]) if i < len(self.times) else None

    @property
    def constant(self):
        return not self.times


class LinkQueue:
    """FIFO + drop-tail for one directed link; see the module docstring.

    enqueue(t, size) -> (start_ns, end_ns), or None when the buffer refuses
    the packet. Calls must come in non-decreasing t (the engine guarantees it:
    a link's packets are handed over in event-time order).
    """

    def __init__(self, rate, buffer_bytes, *, background="none", rho=None, bg_packet_bytes=1500,
                 bg_window_ns=10_000_000, rng=None, key=None, cftp_lookback_ns=None):
        self.rate = rate if isinstance(rate, RateSchedule) else RateSchedule(rate)
        self.buffer = int(buffer_bytes)
        self.mode = background
        self.free_at = 0
        self.inq = deque()               # (end_ns, size) of accepted foreground packets in the system
        self.inq_bytes = 0
        self.fg_sent = 0
        self.fg_dropped = 0
        self.max_wait_ns = 0
        self._ser = {}                   # size -> serialization ns at the nominal rate (constant-rate links)
        self._const = self.rate.constant
        if background == "none":
            # hot path: no background, so enqueue is the plain recursion itself
            self.enqueue = self._enqueue_plain
            return
        if rho is None:
            raise ValueError("background needs rho")
        # offered background rate in bit/s, exact integer (rho is a Fraction)
        self.bg_bps = int(rho * self.rate.nominal)
        if background == "fluid":
            self.x = 0                    # backlog, bits * 1e9 (exact integer)
            self.t_x = 0
            self.cap = self.buffer * 8 * NS_PER_S
            self.fluid_lost = 0           # bits * 1e9 of background fluid dropped at the buffer
        elif background == "poisson":
            if rng is None or key is None:
                raise ValueError("poisson background needs rng and key")
            self.rng = rng
            self.key = tuple(key)
            self.bg_size = int(bg_packet_bytes)
            self.win = int(bg_window_ns)
            self.lam = self.bg_bps / (8.0 * self.bg_size)        # packets per second
            self.t_done = 0                                       # background processed up to here
            self.q_end = np.zeros(0, dtype=np.int64)              # in-system packets, both kinds
            self.q_size = np.zeros(0, dtype=np.int64)
            self.bg_arrived = 0
            self.bg_dropped = 0
            self.cftp_skips = 0
            self.cftp_fallbacks = 0
            self._wcache = {}
            if cftp_lookback_ns is None:
                drain = ser_ns(self.buffer, self.rate.nominal)
                cftp_lookback_ns = max(20_000_000, int(3 * drain / max(1e-9, 1.0 - float(rho))))
            self.lookback = int(cftp_lookback_ns)
        else:
            raise ValueError(f"unknown background model {background!r}")

    # ------------------------------------------------------------- no background
    def _enqueue_plain(self, t, size):
        inq = self.inq
        while inq and inq[0][0] <= t:
            self.inq_bytes -= inq.popleft()[1]
        if self.inq_bytes + size > self.buffer:
            self.fg_dropped += 1
            return None
        start = t if t > self.free_at else self.free_at
        s = self._ser.get(size) if self._const else None
        if s is None:
            s = ser_ns(size, self.rate.at(start))
            if self._const:
                self._ser[size] = s
        end = start + s
        self.free_at = end
        inq.append((end, size))
        self.inq_bytes += size
        self.fg_sent += 1
        if start - t > self.max_wait_ns:
            self.max_wait_ns = start - t
        return start, end

    # ------------------------------------------------------------- fluid
    def _fluid_advance(self, t):
        """Evolve the fluid backlog from t_x to t (rates may change in between)."""
        while self.t_x < t:
            r = self.rate.at(self.t_x)
            nxt = self.rate.next_change_after(self.t_x)
            seg_end = t if nxt is None or nxt[0] >= t else nxt[0]
            dt = seg_end - self.t_x
            net = (self.bg_bps - r) * dt
            x = self.x + net
            if x < 0:
                x = 0
            if x > self.cap:
                self.fluid_lost += x - self.cap
                x = self.cap
            self.x = x
            self.t_x = seg_end

    def _fluid_drain_time(self, t, bits_e9):
        """When the transmitter, busy from t, has sent bits_e9 (bits x 1e9) more."""
        rem = bits_e9
        tt = t
        while True:
            r = self.rate.at(tt)
            nxt = self.rate.next_change_after(tt)
            if nxt is None or rem <= r * (nxt[0] - tt):
                # round half up to whole ns, like ser_ns
                return tt + (2 * rem + r) // (2 * r)
            rem -= r * (nxt[0] - tt)
            tt = nxt[0]

    def _enqueue_fluid(self, t, size):
        self._fluid_advance(t)
        bits = size * 8 * NS_PER_S
        if self.x + bits > self.cap:
            self.fg_dropped += 1
            return None
        end = self._fluid_drain_time(t, self.x + bits)
        start = max(t, end - ser_ns(size, self.rate.at(t)))
        self.x += bits
        return start, end

    # ------------------------------------------------------------- poisson
    def _window(self, w):
        arr = self._wcache.get(w)
        if arr is None:
            g = self.rng.generator("background", self.key + (w,))
            n = int(g.poisson(self.lam * self.win / NS_PER_S))
            arr = np.sort(w * self.win + np.floor(g.random(n) * self.win).astype(np.int64))
            if len(self._wcache) > 4:
                self._wcache.pop(min(self._wcache))
            self._wcache[w] = arr
        return arr

    def _arrivals(self, lo, hi):
        """Background arrival times a with lo < a <= hi (sorted)."""
        parts = []
        for w in range(lo // self.win, hi // self.win + 1):
            a = self._window(w)
            if a.size:
                parts.append(a[(a > lo) & (a <= hi)])
        if not parts:
            return np.zeros(0, dtype=np.int64)
        return np.concatenate(parts)

    def _occupancy(self, t):
        """Bytes of packets still in the system at t (end > t); prunes finished ones."""
        i = int(np.searchsorted(self.q_end, t, side="right"))
        if i:
            self.q_end = self.q_end[i:]
            self.q_size = self.q_size[i:]
        return int(self.q_size.sum())

    def _batch_loop(self, a, F):
        """Exact scalar recursion with drops for background arrivals a (sorted). Returns new F."""
        S_cache = {}
        ends, sizes = list(self.q_end.tolist()), list(self.q_size.tolist())
        head = 0
        occ = sum(sizes)
        P = self.bg_size
        for t in a.tolist():
            while head < len(ends) and ends[head] <= t:
                occ -= sizes[head]
                head += 1
            self.bg_arrived += 1
            if occ + P > self.buffer:
                self.bg_dropped += 1
                continue
            start = t if t > F else F
            r = self.rate.at(start)
            S = S_cache.get(r)
            if S is None:
                S = S_cache[r] = ser_ns(P, r)
            F = start + S
            ends.append(F)
            sizes.append(P)
            occ += P
        self.q_end = np.asarray(ends[head:], dtype=np.int64)
        self.q_size = np.asarray(sizes[head:], dtype=np.int64)
        return F

    def _batch(self, a, F):
        """Process background arrivals a (sorted) starting with transmitter free at F."""
        if a.size == 0:
            return F
        P = self.bg_size
        r = self.rate.at(int(a[0]) if a[0] > F else F)
        if not self.rate.constant:
            nxt = self.rate.next_change_after(min(int(a[0]), F))
            if nxt is not None and nxt[0] <= int(a[-1]) + ser_ns(self.buffer, min(self.rate.rates + [self.rate.nominal])):
                return self._batch_loop(a, F)          # a rate change may fall inside: exact loop
        S = ser_ns(P, r)
        k = np.arange(a.size, dtype=np.int64)
        base = np.maximum.accumulate(a - k * S)
        ends = (k + 1) * S + np.maximum(base, F)
        # drop-tail check for every arrival assuming no drops
        idx = np.searchsorted(ends, a, side="right")            # batch packets finished by a_n
        in_batch = (k - idx) * P
        old = np.searchsorted(self.q_end, a, side="right")
        old_cum = np.concatenate([[0], np.cumsum(self.q_size)])
        old_bytes = old_cum[-1] - old_cum[old]
        if np.any(old_bytes + in_batch + P > self.buffer):
            return self._batch_loop(a, F)
        self.bg_arrived += int(a.size)
        self.q_end = np.concatenate([self.q_end, ends])
        self.q_size = np.concatenate([self.q_size, np.full(a.size, P, dtype=np.int64)])
        return int(ends[-1])

    def _advance_poisson(self, t):
        """Process every background arrival up to and including t."""
        if t <= self.t_done:
            return
        lo = self.t_done
        if t - lo > self.lookback and self.rate.constant:
            s = t - self.lookback
            a = self._arrivals(s, t)
            F_up = s + ser_ns(self.buffer, self.rate.nominal)      # full buffer at s: an upper bound
            S = ser_ns(self.bg_size, self.rate.nominal)
            if a.size:
                k = np.arange(a.size, dtype=np.int64)
                ends = (k + 1) * S + np.maximum(np.maximum.accumulate(a - k * S), F_up)
                prev_end = np.concatenate([[F_up], ends[:-1]])
                empty = np.flatnonzero(prev_end <= a)
                if empty.size:
                    n0 = int(empty[0])
                    # the true queue is empty just before a[n0]: forget the past exactly
                    self.cftp_skips += 1
                    self.q_end = np.zeros(0, dtype=np.int64)
                    self.q_size = np.zeros(0, dtype=np.int64)
                    self.free_at = self._batch(a[n0:], int(a[n0]))
                    self.t_done = t
                    return
            elif F_up <= t:
                self.cftp_skips += 1
                self.q_end = np.zeros(0, dtype=np.int64)
                self.q_size = np.zeros(0, dtype=np.int64)
                # the true transmitter is free by F_up <= t (domination), so by t
                self.free_at = min(self.free_at, t)
                self.t_done = t
                return
            self.cftp_fallbacks += 1
        self.free_at = self._batch(self._arrivals(lo, t), self.free_at)
        self.t_done = t

    def _enqueue_poisson(self, t, size):
        self._advance_poisson(t)
        occ = self._occupancy(t)
        if occ + size > self.buffer:
            self.fg_dropped += 1
            return None
        start = t if t > self.free_at else self.free_at
        end = start + ser_ns(size, self.rate.at(start))
        self.free_at = end
        self.q_end = np.append(self.q_end, end)
        self.q_size = np.append(self.q_size, size)
        return start, end

    # ------------------------------------------------------------- public
    def enqueue(self, t, size):
        """(start_ns, end_ns) of the packet, or None if the buffer drops it (see the class docstring)."""
        if self.mode == "fluid":
            res = self._enqueue_fluid(t, size)
        else:
            res = self._enqueue_poisson(t, size)
        if res is not None:
            self.fg_sent += 1
            w = res[0] - t
            if w > self.max_wait_ns:
                self.max_wait_ns = w
        return res

    def queue_delay_estimate(self, t):
        """Local view of the egress queue at t: how long a new packet would wait (ns).

        This is what the satellite itself can see (its own transmit queue);
        the +Grid detour fallback may use it to call a link 'slow'.
        """
        if self.mode == "fluid":
            self._fluid_advance(t)
            r = self.rate.at(t)
            return (self.x + r - 1) // r if self.x else 0
        if self.mode == "poisson":
            self._advance_poisson(t)
        return max(0, self.free_at - t)

    def stats(self):
        out = {"fg_sent": self.fg_sent, "fg_dropped": self.fg_dropped, "max_wait_ns": self.max_wait_ns}
        if self.mode == "fluid":
            out["fluid_lost_bits"] = self.fluid_lost // NS_PER_S
        elif self.mode == "poisson":
            out.update(bg_arrived=self.bg_arrived, bg_dropped=self.bg_dropped,
                       cftp_skips=self.cftp_skips, cftp_fallbacks=self.cftp_fallbacks)
        return out


__all__ = ["ser_ns", "RateSchedule", "LinkQueue"]
