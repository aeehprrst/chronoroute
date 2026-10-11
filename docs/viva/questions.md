# Likely questions and short answers

Every number below comes from a committed result file; the file is named in brackets.

## The idea

**1. What problem does ChronoRoute solve?**
A pre-computed route in a satellite network cannot see a link that is still up but has become
slow (lower rate, retransmissions, queueing). Hello-based link-state routing only reacts when a
link goes down. ChronoRoute lets every packet carry the time it should reach each hop, so the
first node after a slow link can see the problem from the packet itself.

**2. Which OSI/TCP-IP layer is this?**
The Network layer (Layer 3). We add an IPv6 extension header (a Routing Header, type 253) and a
per-node forwarding rule. UDP, the link layer and applications are unchanged.

**3. Why satellites, and why can routes be planned in advance there?**
LEO satellites move fast, so links change every few seconds, but orbits are predictable: from
public orbital elements (CelesTrak) and the SGP4 model we can compute every position and every
link delay ahead of time. That makes source routing from a ground station attractive, and it
also makes it possible to predict when a packet should arrive.

**4. What existed before?**
Hop-by-hop link-state routing (OSPF, IS-IS) with hellos/BFD; source routing with SRv6 (RFC 8754,
16 bytes per hop) and the Compact Routing Header (RFC 9631, 2 or 4 bytes per hop). None of them
carries timing. The closest drafts (CRH-20, SRTSN) carry per-hop timing to *schedule* packets;
we use deadlines to *detect* that the plan has broken.

## The header

**5. Describe the T-CRH header.**
8 bytes like every routing header (Next Header, Hdr Ext Len, Routing Type 253, Segments Left)
plus Flags, Num Hops, Dev Hop, Reserved; then a 4-byte Epoch_Base; then one 3-byte entry per hop
(16-bit SID + 8-bit Delta budget), stored in reverse order, padded to a multiple of 8 bytes.
Size = pad8(12 + 3h). (`spec/tcrh-v1.md`)

**6. Why Routing Type 253?**
RFC 4727 reserves 253 and 254 for experiments. A real deployment would need an IANA assignment.

**7. How is a deadline computed?**
D_k = Epoch_Base + d_1 + ... + d_k (mod 2^32), in units of 0.1 ms. Epoch_Base is the ingress
time (GPS time, rounded up); each d_i is that hop's budget = S x (light time + 0.5 ms processing)
with S = 1.5, encoded with the ceil-cumulative rule so deadlines are never early and rounding
does not accumulate.

**8. When is a packet "late", and what happens then?**
When serial_diff(node clock, D_k) > 0. The node sets the DEV flag and writes its hop number into
Dev Hop. Then its deviation policy decides: continue on the planned path, drop, or switch to
greedy fallback forwarding (GREEDY flag) towards the destination.

**9. Why serial-number arithmetic?**
Clocks and deadlines are 32-bit counters that wrap (every 4.97 days at 0.1 ms). Comparing them
as signed differences modulo 2^32 keeps the comparison correct across the wrap.

**10. Why GPS time and not UTC?**
GPS time has no leap seconds, so it never jumps. Satellites already carry GNSS receivers, so
synchronised clocks are realistic there.

**11. Which fields change in flight?**
Only Segments Left, Flags and Dev Hop. Everything else is fixed at the ingress. (This differs
from RFC 9631, where only Segments Left changes; it matters for IPsec AH.)

**12. How does the header get into the packet if RFC 8200 forbids inserting headers in transit?**
Either the sending host builds it (source insertion), or a gateway encapsulates the packet in a
new IPv6 header plus T-CRH (+40 bytes) and the egress removes it, like SRv6 encapsulation.

**13. How big is the overhead?**
At 10 hops: T-CRH 48 B (3.43% of a 1400 B packet), CRH-16 24 B, CRH-32 48 B, SRv6 168 B (12%).
Every ns-3 probe was exactly 290 B on the wire, as the formula predicts.
(`results/E02/20261011T214624Z-confirmatory/summary.csv`)

## Implementation

**14. What did you build?**
One specification and golden test vectors, then four implementations: a Python reference and
discrete-event simulator, an ns-3.44 module (a real IPv6 extension handler for type 253), a
Wireshark Lua dissector, and the website's TypeScript engine. Plus a PyVista 3D viewer, a 2D
map, NetAnim output and a public website.

**15. How do you know the implementations are correct?**
E0 compares them: 34 checks, 17.26 million comparisons (orbits vs satellite.js, header bytes in
Python vs ns-3 vs the browser vs Wireshark, link physics), 0 violations
(`results/E00/20261011T214507Z`). E16 compares the Python simulator with ns-3: 355,200 packets,
0 mismatches (`results/E16/20261011T194240Z-confirmatory`).

**16. What is REAL and what is MODELLED?**
REAL: the Starlink orbital elements (CelesTrak SupGP), SGP4 positions, city coordinates, the
header bytes our code produces. MODELLED: the Grid-4 laser-link layout, link rates (1 Gb/s),
queues, traffic and faults. UNKNOWN: Starlink's real routing. Starlink does not use T-CRH.

**17. How does ns-3 handle a moving topology?**
Each link is a stock point-to-point channel; its propagation delay and up/down state are updated
every 100 ms from the scenario bundle that the Python pipeline exports from the real orbits.

## Results

**18. Does it work?**
In ns-3 on the real 463 km shell, a laser link slowed from 1 Gb/s to 200 kb/s (still up) was
flagged by 3,645 of 3,648 probes that crossed it (99.92%), and by 0 of the same probes without
the fault. At 250 kb/s and faster nothing was flagged. (`results/course-milestone/c5-463-60s-seed1`)

**19. So why does E1 say "mostly not supported"?**
At the operating point chosen on pilot data (S = 1.5, false-positive rate 0.59% on clean
packets), a strong rate cut is detected in 36/36 runs, but the registered nominal rate cut (to
30%) and added delays of 0.25 to 4 ms are almost never detected: each hop has several
milliseconds of slack and a small extra delay fits inside it. Looser rules catch them but flag
more than 1% of clean packets. (`results/E01/20261011T154940Z-confirmatory-resumed`)

**20. Is anything better than ChronoRoute at detection?**
Yes: a local queue monitor (LQ) in the satellite in front of the link sees its own queue
directly and detects queue-forming faults more often. Deadlines see the problem one hop later
and only once it exceeds the slack. Their advantage is that they need no extra control
traffic and also see delay that does not show up as a local queue.

**21. What about the LS-D comparator?**
Our pre-registered delay-aware link-state comparator turned out to be flawed: it read the
injected delay without measurement noise and re-advertised any change, so its results say
nothing about real slow-link detection. We kept the registered numbers and disclosed the flaw
instead of quietly changing the design after seeing results.

**22. How did you avoid fooling yourselves?**
Pre-registration (`experiments/PREREG.md`) before the main runs; the operating point chosen on
pilot seeds only; 36 seeds per cell; counterfactual twins (same random numbers, no fault) so a
null fault scores exactly 0; t intervals and bootstraps over whole runs, Holm correction; a
manifest with git commit, clean tree and SHA-256 of every output for every result; an
independent review that re-computed every number.

**23. What happens after a satellite or link fails completely?**
The node before a dead link sets DEV and GREEDY and uses the fallback. On the real shell during
satellite outages, delivery rose from 0.968 (no fallback) to 0.997 with greedy-with-visited, but
hello-based link-state routing with BFD still delivered 0.999. Remembering visited nodes cuts
stuck packets compared with pure greedy. (`results/E04/...collected`, `results/E05/...`)

## Limits and next steps

**24. What are the main limitations?**
Synchronised clocks are required; the deadline plan must be good; the slack trades sensitivity
against false alarms; the header is not authenticated, so it must stay inside one operator's
network; the laser-link layout and traffic are modelled; the fallback can loop.

**25. Security: could someone abuse it?**
A forged or replayed header could make packets look late or steer them. Routing Type 0 was
deprecated for exactly this kind of abuse (RFC 5095), so T-CRH is meant for a closed, trusted
domain, like SRv6, with filtering at the domain edge.

**26. What would you do next?**
Per-hop slack learned from measured jitter (to catch smaller delays without more false alarms),
a fair delay-aware link-state baseline with realistic noise and update intervals, authentication
of the mutable fields, and longer runs on all Starlink shells.

**27. What did you learn about Computer Networks?**
How extension headers chain in IPv6 and who processes a routing header; the difference between
hop-by-hop and source routing; how the four delay components behave; why hello-based failure
detection misses gray failures; and that the control plane / data plane split is a design choice
(here, a little state moves into every packet).
