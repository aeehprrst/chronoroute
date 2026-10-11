/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#ifndef TCRH_IPV6_TEST_H
#define TCRH_IPV6_TEST_H

#include "ns3/test.h"

#include <vector>

/**
 * @file
 * @ingroup chronoroute-test
 *
 * The phase P5a test cases (T-CRH as a real IPv6 routing header, in a real
 * ns-3 network). They live in tcrh-ipv6-test.cc and are added to the ONE
 * "chronoroute" test suite by chronoroute-test-suite.cc (TestCase::AddTestCase
 * is protected, so the suite's constructor adds them).
 *
 * @return new test cases; the suite takes ownership
 */
std::vector<ns3::TestCase*> MakeTcrhIpv6TestCases();

#endif /* TCRH_IPV6_TEST_H */
