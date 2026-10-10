# ChronoRoute ns-3 module: T-CRH v1 (IPv6 Routing Type 253) and CRH-16/32.
# SPDX-License-Identifier: GPL-2.0-only
#
# Lives in the ChronoRoute repository (ns3/contrib/chronoroute) and is linked
# into ~/ns-3-dev/contrib/chronoroute by tools/ns3-sync.sh.
#
# test/golden-vectors.inc is GENERATED from spec/golden/*.json by
# tools/golden_to_inc.py (ns-3 has no JSON library); never edit it by hand.

build_lib(
  LIBNAME chronoroute
  SOURCE_FILES
    model/crh-header.cc
    model/tcrh-header.cc
    model/tcrh-process.cc
  HEADER_FILES
    model/crh-header.h
    model/tcrh-header.h
    model/tcrh-process.h
    model/tcrh-timebase.h
  LIBRARIES_TO_LINK ${libnetwork} ${libcore}
  TEST_SOURCES test/chronoroute-test-suite.cc
)
