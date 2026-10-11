# Backup plan

`tools/viva-prepare.sh` writes everything below into `~/cr-viva` (Windows path
`\\wsl.localhost\ubuntu\home\aeehprrst\cr-viva`). None of it needs the internet.

| If this fails | Show this instead |
|---|---|
| No internet (website, GitHub) | The offline site: `cd ~/chronoroute/web && npx astro preview --host 127.0.0.1 --port 4321`, then <http://localhost:4321/chronoroute/> (built by `viva-prepare.sh --site`) |
| 3D viewer: black window or crash | Add `--software` (software OpenGL), or use the 2D view: `venv/bin/cr viz map2d --trace ~/cr-viva/ns3-small-fault`; or open `~/cr-viva/backup/globe-deadline-miss.mp4` / `.png` |
| Live re-run (`d` key) is slow or fails | The viewer keeps the recorded run on screen; use the ns-3 trace (`~/cr-viva/ns3-small-fault`) and press `m` |
| ns-3 run fails | Show the committed run: `less results/course-milestone/c5-463-60s-seed1/run.log` (same `[ok]` checks and PASS), or the ns-3 screenshots in the case study |
| NetAnim does not start or WSLg has no window | The NetAnim screenshot in the case study (section 8.4); `anim.xml` is still in `~/cr-viva/netanim/` |
| Wireshark plugin not loaded | `tshark -r ~/cr-viva/wireshark/small-fault.pcap -X lua_script:tools/wireshark/tcrh.lua -Y "tcrh.flags.dev == 1" -T fields -e frame.number -e ipv6.routing.segleft -e tcrh.flags -e tcrh.dev_hop -e tcrh.margin_ms`, or `tools/wireshark/check_pcap.sh ~/cr-viva/wireshark/small-fault.pcap` |
| Laptop fails completely | The case study PDF (all screenshots), the public website on any device, the repository on GitHub |

## Files in `~/cr-viva`

| Path | Use |
|---|---|
| `fleet/` | `cr fleet report` output and figures |
| `ns3-small-fault/` | ns-3 course-milestone run converted for the viewer (bundle rebuilt and checked) |
| `live/`, `live.yaml` | A Python simulator run on the real shell for the live `d` key demo |
| `wireshark/*.pcap` | Decompressed ns-3 captures (small fault run, 60 s fault and no-fault runs) |
| `netanim/*.xml` | NetAnim animation files |
| `backup/` | Screenshots, an MP4 of the viewer, the route printout and fleet figures |
