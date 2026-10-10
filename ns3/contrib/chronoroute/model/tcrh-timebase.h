/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#ifndef TCRH_TIMEBASE_H
#define TCRH_TIMEBASE_H

/**
 * @file
 * @ingroup chronoroute
 *
 * The T-CRH v1 time base (spec/tcrh-v1.md section 4). C++ twin of the Python
 * module chronoroute/proto/timebase.py; both are checked against the same
 * golden vectors (spec/golden/tcrh_vectors.json).
 *
 * Every time quantity that goes on the wire (Epoch_Base and every Delta) is a
 * count of the deadline unit u, chosen by the two UNIT bits of the Flags byte.
 * Everything here is INTEGER arithmetic on nanoseconds of GPS time, because
 * the spec requires the ceil/floor that produce wire values to be exact
 * (section 5.1): a budget of exactly 3.0 units must encode to 3, never 4.
 * A double such as 3.0000000001 would ceil to 4, so there is no double in
 * any function below.
 *
 * All 32-bit comparisons use serial-number arithmetic, so a deadline just
 * after the 2^32 wrap still compares correctly with a clock just before it.
 */

#include "ns3/abort.h"
#include "ns3/nstime.h"

#include <cstdint>

namespace ns3
{
namespace tcrh
{

/// Number of deadline unit codes (two UNIT bits).
static constexpr uint8_t UNIT_CODE_COUNT = 4;
/// Provisional v1 default unit code: 0.1 ms (spec section 3; experiment E13 decides).
static constexpr uint8_t DEFAULT_UNIT_CODE = 1;
/// GPS = UTC + 18 s for every date in this project (no leap second since 2017-01-01).
static constexpr int64_t GPS_UTC_OFFSET_S = 18;
/// Nanoseconds per second.
static constexpr uint64_t NS_PER_S = 1000000000ULL;
/// Nanoseconds per millisecond.
static constexpr uint64_t NS_PER_MS = 1000000ULL;

/**
 * @return true if @p unitCode is one of the four defined unit codes (0..3).
 * @param unitCode the UNIT field value, (flags >> 4) & 3
 */
inline bool
IsValidUnitCode(uint8_t unitCode)
{
    return unitCode < UNIT_CODE_COUNT;
}

/**
 * Length of deadline unit @p unitCode in nanoseconds (spec section 3):
 * 0 -> 1 ms (v0-compatible), 1 -> 0.1 ms, 2 -> 0.25 ms, 3 -> 0.125 ms.
 * Aborts on an invalid code (a caller bug, never a property of received bytes:
 * the UNIT field is two bits, so a decoded value is always valid).
 *
 * @param unitCode 0..3
 * @return the unit length in ns
 */
inline uint64_t
UnitNs(uint8_t unitCode)
{
    NS_ABORT_MSG_UNLESS(IsValidUnitCode(unitCode),
                        "T-CRH unit code must be 0..3, got " << +unitCode);
    static constexpr uint64_t table[UNIT_CODE_COUNT] = {1000000ULL, 100000ULL, 250000ULL, 125000ULL};
    return table[unitCode];
}

/**
 * Signed 32-bit serial difference a - b, in [-2^31, 2^31) (spec section 4):
 * serial_diff(a, b) = ((a - b + 2^31) mod 2^32) - 2^31.
 *
 * Clocks and deadlines wrap at 2^32 (49.7 days at 1 ms, 4.97 days at 0.1 ms).
 * A path lasts far less than a second, so the true difference is always tiny
 * and the wrapped difference recovers it exactly. Written without relying on
 * the implementation-defined uint32 -> int32 conversion of older C++.
 *
 * @param a first 32-bit value
 * @param b second 32-bit value
 * @return the serial difference
 */
inline int32_t
SerialDiff(uint32_t a, uint32_t b)
{
    const uint32_t d = a - b; // unsigned arithmetic wraps mod 2^32 by definition
    if (d >= 0x80000000U)
    {
        // d - 2^31 is in [0, 2^31), so the result fits in int32 exactly
        return static_cast<int32_t>(d - 0x80000000U) - INT32_C(2147483647) - 1;
    }
    return static_cast<int32_t>(d);
}

/**
 * True when the clock has moved PAST the deadline unit (spec section 6):
 * a packet arriving anywhere inside unit @p deadlineU is on time; it is late
 * only from unit deadlineU + 1 on. serial_diff = -2^31 counts as not late.
 *
 * @param nowU the node's unit clock
 * @param deadlineU the cumulative arrival deadline D_k
 * @return true if late
 */
inline bool
IsLate(uint32_t nowU, uint32_t deadlineU)
{
    return SerialDiff(nowU, deadlineU) > 0;
}

/**
 * A node's unit clock: floor(t_gps / u) mod 2^32 (spec section 4).
 * floor, because a node is "in" unit n for the whole interval [n u, (n+1) u).
 *
 * @param tGpsNs GPS time in integer nanoseconds since the GPS epoch
 * @param unitCode 0..3
 * @return the unit clock
 */
inline uint32_t
ClockU(uint64_t tGpsNs, uint8_t unitCode)
{
    return static_cast<uint32_t>(tGpsNs / UnitNs(unitCode)); // cast = mod 2^32
}

/**
 * Epoch_Base stamped per packet at ingress: ceil(T_ingress / u) mod 2^32
 * (spec section 4). ceil, not floor: rounding the anchor UP can only add slack
 * to every deadline, never remove it.
 *
 * @param tGpsNs ingress GPS time in integer nanoseconds
 * @param unitCode 0..3
 * @return Epoch_Base in units
 */
inline uint32_t
EpochBaseAtIngress(uint64_t tGpsNs, uint8_t unitCode)
{
    const uint64_t u = UnitNs(unitCode);
    const uint64_t q = tGpsNs / u + (tGpsNs % u != 0 ? 1 : 0); // exact integer ceil
    return static_cast<uint32_t>(q);                             // mod 2^32
}

/**
 * GPS time (ns) of simulation time @p simTime, for a simulator whose time 0 is
 * the GPS instant @p t0GpsNs (spec section 4: simulators on a relative clock
 * add their configured t0_gps to simulation time). ns-3 keeps Time as an
 * integer count of its resolution unit (ns by default), so this is exact.
 *
 * @param t0GpsNs GPS time of simulation time 0, in ns
 * @param simTime a non-negative simulation time
 * @return GPS time in ns
 */
inline uint64_t
SimToGpsNs(uint64_t t0GpsNs, Time simTime)
{
    const int64_t ns = simTime.GetNanoSeconds();
    NS_ABORT_MSG_IF(ns < 0, "T-CRH time base: negative simulation time " << simTime);
    return t0GpsNs + static_cast<uint64_t>(ns);
}

/**
 * The unit clock of a node at simulation time @p simTime (convenience for
 * SimToGpsNs followed by ClockU).
 *
 * @param simTime current simulation time (for example Simulator::Now())
 * @param t0GpsNs GPS time of simulation time 0, in ns
 * @param unitCode 0..3
 * @return the unit clock
 */
inline uint32_t
NodeClockU(Time simTime, uint64_t t0GpsNs, uint8_t unitCode)
{
    return ClockU(SimToGpsNs(t0GpsNs, simTime), unitCode);
}

} // namespace tcrh
} // namespace ns3

#endif /* TCRH_TIMEBASE_H */
