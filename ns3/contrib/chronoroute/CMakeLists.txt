# ChronoRoute ns-3 module: T-CRH v1 (IPv6 Routing Type 253) and CRH-16/32,
# as genuine IPv6 routing headers processed by ns-3.44's IPv6 stack.
# SPDX-License-Identifier: GPL-2.0-only
#
# Lives in the ChronoRoute repository (ns3/contrib/chronoroute) and is linked
# into ~/ns-3-dev/contrib/chronoroute by tools/ns3-sync.sh.
#
# test/golden-vectors.inc is GENERATED from spec/golden/*.json by
# tools/golden_to_inc.py (ns-3 has no JSON library); never edit it by hand.
# examples/ is picked up by ns-3's build_lib automatically (examples enabled).

build_lib(
  LIBNAME chronoroute
  SOURCE_FILES
    model/crh-fib.cc
    model/crh-header.cc
    model/ipv6-extension-tcrh.cc
    model/tcrh-address-plan.cc
    model/tcrh-header.cc
    model/tcrh-process.cc
    model/tcrh-source-shim.cc
    helper/tcrh-helper.cc
    helper/leo-bundle-helper.cc
  HEADER_FILES
    model/crh-fib.h
    model/crh-header.h
    model/ipv6-extension-tcrh.h
    model/tcrh-address-plan.h
    model/tcrh-header.h
    model/tcrh-process.h
    model/tcrh-source-shim.h
    model/tcrh-timebase.h
    helper/tcrh-helper.h
    helper/leo-bundle-helper.h
  LIBRARIES_TO_LINK
    ${libinternet}
    ${libpoint-to-point}
    ${libnetwork}
    ${libcore}
  TEST_SOURCES
    test/chronoroute-test-suite.cc
    test/tcrh-ipv6-test.cc
)
