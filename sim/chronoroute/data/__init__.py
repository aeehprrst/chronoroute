"""Real-world input data: orbit element sets (OMM), snapshots and city lists.

    omm.py          parse and screen CelesTrak OMM JSON (GP / SupGP)
    snapshot.py     load a pinned download folder or a website snapshot; write
                    the website data contract (manifest.json + omm.min.json)
    cities.py       the curated city list in data/static/cities.csv
    fleet_report.py `cr fleet report`: counts, epoch ages, shells, planes

Everything read here is REAL (public data). Anything computed from it
(shells, planes, positions) is DERIVED and lives in chronoroute.orbit.
"""
