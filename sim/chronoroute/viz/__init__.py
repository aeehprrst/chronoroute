"""
The in-tool viewer (plan phase P4): real satellites over a textured Earth, the
MODELLED laser links, and one packet hopping along its T-CRH path in slow
motion, with the deadline check visible at every hop.

    sources.py  what the viewer reads: chronoroute.trace/1 run folders, pinned
                snapshots (SGP4) and scenario-bundle positions; no graphics
    player.py   the two clocks and the slow-motion packet walk; no graphics
    hud.py      every line of text the viewer shows (testable without a window)
    globe.py    the PyVista 3D scene and its keys (`cr viz globe`)
    map2d.py    the matplotlib 2D fallback (`cr viz map2d`)
    record.py   off-screen MP4 recording with imageio-ffmpeg
    command.py  the `cr viz ...` and `cr trace from-ns3` commands

PyVista / VTK are imported only by globe.py and record.py, so `cr` stays fast
and the trace tools work on machines without a GPU stack.
"""
