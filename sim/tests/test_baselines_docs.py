"""Baseline documentation links must point to the model they describe."""

import re
from pathlib import Path


def test_olsr_limitation_links_to_flooding_idealisation():
    text = (Path(__file__).resolve().parents[2] / "docs" / "baselines.md").read_text(encoding="utf-8")
    limitation = re.search(r"^\* OLSR is modelled with OSPF-like flooding \(see §([\d.]+)\)", text, re.M)
    assert limitation is not None
    target = re.search(rf"^### {re.escape(limitation[1])} [^\n]+\n(.*?)(?=^##|\Z)",
                       text, re.M | re.S)
    assert target is not None
    assert "OLSR presets use the same OSPF-like flooding byte model" in target[1]
