"""Routing on the time-varying topology (results are DERIVED from REAL positions
and MODELLED links).

    sids.py        the stable, append-only SID registry (data/static/sid_registry.json)
    dijkstra.py    hand-written Dijkstra: binary heap, integer ns, lowest-id tie-break
    scheduler.py   path -> per-hop predicted delays -> slack budgets -> T-CRH bytes
    command.py     `cr route --from A --to B`
"""
