"""The honesty labels (master plan section 2) come from ONE table, chronoroute/labels.py, so the
same thing carries the same label in every output (review finding: SGP4 positions were REAL in
the bundle and DERIVED in the fleet report; header bytes REAL in one place, DERIVED in another)."""

import json
from pathlib import Path

import pytest

from chronoroute import labels, provenance
from chronoroute.data import fleet_report
from chronoroute.export import bundle, ns3_crosscheck, web

REPO = Path(__file__).resolve().parents[2]
PRODUCERS = {
    "cr export bundle": bundle.LABELS,
    "cr export web": web.LABELS,
    "course milestone (ns3_crosscheck)": ns3_crosscheck.LABELS,
    "cr fleet report": fleet_report.LABELS,
}


@pytest.mark.parametrize("producer", sorted(PRODUCERS))
def test_every_producer_takes_its_labels_from_the_shared_table(producer):
    table = PRODUCERS[producer]
    assert table, producer
    for key, value in table.items():
        assert labels.TABLE[key] == value, (producer, key)


def test_the_table_follows_the_plan():
    t = labels.TABLE
    # plan section 2: row 2 "REAL physics + REAL code", row 17 "REAL code output",
    # row 5 shells/planes DERIVED, row 6 laser topology MODELLED
    assert t["satellite_positions_sgp4"] == "REAL"
    assert t["tcrh_header_bytes"] == "REAL"
    assert t["orbital_elements"] == t["city_coordinates"] == "REAL"
    assert t["shells_and_planes"] == t["routes_and_budgets"] == "DERIVED"
    assert t["isl_topology_grid4"] == t["gsl_mask_and_assignment"] == "MODELLED"
    # every value is one the provenance manifest schema accepts
    assert set(t.values()) <= set(provenance.LABELS)
    # the notes only talk about keys that exist
    assert set(labels.NOTES) <= set(t)


def test_an_unknown_key_cannot_be_used():
    with pytest.raises(KeyError):
        labels.pick("positions_sgp4")
    assert labels.pick("tcrh_header_bytes", "pcap_addresses") == {"tcrh_header_bytes": "REAL",
                                                                   "pcap_addresses": "MODELLED"}


def test_the_committed_course_results_use_the_shared_table():
    found = sorted((REPO / "results" / "course-milestone").glob("*/manifest.json"))
    assert found, "no course-milestone results"
    for path in found:
        m = json.loads(path.read_text(encoding="utf-8"))
        for key, value in m["labels"].items():
            assert labels.TABLE[key] == value, (path, key)
