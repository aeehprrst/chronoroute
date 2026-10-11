"""Orbit geometry computed from the REAL element sets (everything here is DERIVED).

    elements.py   mean-element helpers: altitude from mean motion, J2 node drift
    frames.py     GMST, TEME -> ECEF, WGS84 geodetic coordinates, elevation
    propagate.py  vectorised SGP4 (SatrecArray) -> TEME, ECEF and geodetic
    shells.py     shells from inclination bins and altitude modes
    planes.py     orbital planes (RAAN clusters) and in-plane slots; the API
                  the topology code builds links from
"""
