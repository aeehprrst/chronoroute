"""
labels.py
---------
The honesty labels (master plan section 2), in ONE table that every
producer of a manifest or a data file uses. Before this table each output
picked its own key names and sometimes its own value for the same thing
(SGP4 positions were REAL in the bundle and DERIVED in the fleet report),
and the website shows these labels to readers, so they must agree.

The four labels (plan section 2):
  REAL      public or measured data, real physics, or the real output of our
            real code. SGP4 positions are "REAL physics + REAL code" on REAL
            element sets (plan section 2, row 2); the T-CRH bytes are the real
            output of the real encoder (row 17).
  DERIVED   computed by our code from REAL inputs by an inference that could
            be done differently: shells, planes, routes (plan section 2).
  MODELLED  chosen by us because the truth is not public.
  ASSUMED   a parameter from the literature. The provenance manifest schema
            only has REAL / DERIVED / MODELLED, so an ASSUMED parameter goes
            under MODELLED with a note saying so (gsl_mask_and_assignment).

Use pick() to take the labels a producer needs; a key that is not in the
table is an error, so a new key has to be added here (with its one value)
before any output can use it.
"""

from types import MappingProxyType

TABLE = MappingProxyType({
    # REAL
    "orbital_elements": "REAL",
    "catalogue_names_and_ids": "REAL",
    "epoch_ages": "REAL",
    "satcat_status": "REAL",
    "city_coordinates": "REAL",
    "satellite_positions_sgp4": "REAL",
    "tcrh_header_bytes": "REAL",
    # DERIVED
    "shells_and_planes": "DERIVED",
    "in_transit_flags": "DERIVED",
    "gp_vs_supgp_disagreement": "DERIVED",
    "routes_and_budgets": "DERIVED",
    # MODELLED
    "isl_topology_grid4": "MODELLED",
    "gsl_mask_and_assignment": "MODELLED",
    "processing_delay": "MODELLED",
    "link_rate_and_queues": "MODELLED",
    "traffic_probes": "MODELLED",
    "fault_slow_link": "MODELLED",
    "ns3_processing_delay_zero": "MODELLED",
    "pcap_addresses": "MODELLED",
    "pcap_timestamps": "MODELLED",
    "walk_link_delays": "MODELLED",
})

NOTES = MappingProxyType({
    "satellite_positions_sgp4": "REAL physics + REAL code: SGP4 (python-sgp4) on REAL CelesTrak "
                                "element sets (master plan section 2, row 2)",
    "tcrh_header_bytes": "real output of chronoroute.proto (spec/tcrh-v1.md); Starlink does not use T-CRH",
    "shells_and_planes": "inferred from the REAL element sets; SpaceX does not publish them",
    "isl_topology_grid4": "Grid-4 (+Grid) laser links; Starlink's real laser topology is not public",
    "gsl_mask_and_assignment": "25 deg mask ASSUMED (Starlink filing via Hypatia); which visible "
                               "satellites a station uses is MODELLED",
    "processing_delay": "0.5 ms per hop, the existing model's value",
    "gp_vs_supgp_disagreement": "disagreement between two sources, not a measured error",
    "pcap_addresses": "project address plan: SID s -> fd00::s",
})


def pick(*keys):
    """{key: label} for the given keys, in the given order (KeyError for an unknown key)."""
    return {k: TABLE[k] for k in keys}


def notes(*keys):
    """{key: note} for those of the keys that have a note."""
    return {k: NOTES[k] for k in keys if k in NOTES}


__all__ = ["TABLE", "NOTES", "pick", "notes"]
