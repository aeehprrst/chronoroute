/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#ifndef TCRH_ADDRESS_PLAN_H
#define TCRH_ADDRESS_PLAN_H

#include "ns3/ipv6-address.h"

#include <cstdint>

/**
 * @file
 * @ingroup chronoroute
 *
 * The ns-3 address plan for ChronoRoute, version 1 (spec/tcrh-v1.md section 7:
 * "each node's SID address is derived from its SID inside the unique-local
 * prefix fd00::/8; the exact mapping is defined by each simulator's address
 * plan"). Everything is computed from numbers, so no address allocator (and
 * none of ns-3's O(n^2) Ipv6AddressGenerator bookkeeping) is involved.
 *
 *  - SID address of SID s:   fd00::s/128, i.e. fd00:0:0:0:0:0:HHHH:LLLL where
 *    HHHH:LLLL is s as a 32-bit number (16-bit T-CRH/CRH-16 SIDs leave HHHH 0).
 *    Examples: SID 2 -> fd00::2, ground station 1 (0xF001) -> fd00::f001.
 *    It sits on the node's loopback interface; the node accepts it on every
 *    interface because the helper turns the strong end-system model off.
 *    T-CRH packets always carry a SID address as IPv6 Destination Address.
 *  - Link address of end e (1 or 2) of point-to-point link L (32-bit id):
 *    fd01:0:HHHH:LLLL::e/64. These give every interface a global address,
 *    which ns-3 needs as the source of packets the node itself sends on that
 *    interface (ICMPv6 errors, for example), and the on-link next hop that
 *    the CRH-FIB and the static routes point at.
 *
 * fd00::/8 and not 2001:db8::/32: ns-3.44 silently drops the documentation
 * prefix when forwarding (ipv6-l3-protocol.cc:1310-1316).
 */

namespace ns3
{
namespace tcrh
{

/// Prefix length of a SID address (one address per SID).
static constexpr uint8_t SID_PREFIX_LENGTH = 128;
/// Prefix length of a point-to-point link.
static constexpr uint8_t LINK_PREFIX_LENGTH = 64;

/**
 * @param sid a SID (16 bits for T-CRH and CRH-16, up to 32 bits for CRH-32)
 * @return its SID address, fd00::sid
 */
Ipv6Address SidAddress(uint32_t sid);

/**
 * Inverse of SidAddress().
 * @param address an IPv6 address
 * @param sid out: the SID (may be nullptr)
 * @return true if @p address is inside fd00::/96 (a SID address)
 */
bool SidFromAddress(Ipv6Address address, uint32_t* sid);

/**
 * @param linkId the link's number
 * @return the link's /64 prefix, fd01:0:HHHH:LLLL::
 */
Ipv6Address LinkPrefix(uint32_t linkId);

/**
 * @param linkId the link's number
 * @param end 1 or 2 (aborts otherwise)
 * @return fd01:0:HHHH:LLLL::end
 */
Ipv6Address LinkAddress(uint32_t linkId, uint8_t end);

} // namespace tcrh
} // namespace ns3

#endif /* TCRH_ADDRESS_PLAN_H */
