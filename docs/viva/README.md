# Viva kit

Everything needed to show ChronoRoute live in about nine minutes, with a backup for every
step, and the questions an examiner is likely to ask.

| File | What it is |
|---|---|
| [`demo-script.md`](demo-script.md) | The 9-minute demo, minute by minute: what to run, what to point at, what to say |
| [`questions.md`](questions.md) | Likely questions with short answers, each tied to a file in this repository |
| [`backup-plan.md`](backup-plan.md) | What to show if something fails (no internet, no GPU, a tool will not start) |
| [`../../tools/viva-prepare.sh`](../../tools/viva-prepare.sh) | One command that builds every demo file and the offline backups in `~/cr-viva` |

## The day before (about 15 minutes)

1. In WSL, from `~/chronoroute`:

   ```bash
   git pull
   make check                    # all Python tests + golden vectors (about 11 minutes)
   tools/viva-prepare.sh --site  # demo files, pictures, a video and the offline website
   ```

   The script prints where everything is. It uses only the pinned snapshot and the committed
   results, so it needs no internet.

2. Install the Wireshark dissector and profile on Windows once (PowerShell):

   ```powershell
   $src = "\\wsl.localhost\ubuntu\home\aeehprrst\chronoroute\tools\wireshark"
   New-Item -ItemType Directory -Force "$env:APPDATA\Wireshark\plugins", "$env:APPDATA\Wireshark\profiles\ChronoRoute" | Out-Null
   Copy-Item "$src\tcrh.lua" "$env:APPDATA\Wireshark\plugins\"
   Copy-Item "$src\profiles\ChronoRoute\*" "$env:APPDATA\Wireshark\profiles\ChronoRoute\"
   ```

3. Open each tool once to check it starts (section "Setup" of `demo-script.md`).

## On the day

* Laptop charged and plugged in, notifications off, screen scaling unchanged.
* Open in advance: one WSL terminal in `~/chronoroute`, Wireshark (profile **ChronoRoute**),
  the browser on <https://aeehprrst.github.io/chronoroute/>, the case study PDF.
* Keep `~/cr-viva/backup/` open in Explorer (`\\wsl.localhost\ubuntu\home\aeehprrst\cr-viva\backup`).

## Three sentences to remember

1. ChronoRoute adds a time stamp and one deadline byte per hop to a compact IPv6 Routing Header
   (type 253), so every satellite can tell from the packet itself whether the network is
   keeping its predicted schedule.
2. It is built four times from one specification (Python, ns-3, Wireshark, website), and all
   four agree byte for byte on the real Starlink geometry.
3. It catches strong slow-downs and dead links in-band with no extra control traffic, but at a
   1% false-alarm limit small delays hide inside the slack, and a local queue monitor is more
   sensitive; we report that honestly.
