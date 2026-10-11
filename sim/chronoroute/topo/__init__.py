"""Network topology built on the REAL fleet (links are MODELLED, see each module).

    geometry.py    line-of-sight height above WGS84, light-time in integer ns
    isl_grid4.py   Grid-4 laser links (MODELLED): 2 intra-plane + 2 cross-plane
    gsl.py         ground links (MODELLED policy): city ground stations, 25 deg mask
    graph.py       one compact time-varying graph (numpy arrays + CSR per step)
    invariants.py  physical sanity checks every scenario must pass

Labels used everywhere these surface: satellite positions REAL (SGP4 on REAL
element sets), shells and planes DERIVED, laser links MODELLED (Grid-4, the
2018-filing-style "+Grid" pattern; Starlink's real laser topology is not
public), ground-link mask ASSUMED and assignment policy MODELLED.
"""
