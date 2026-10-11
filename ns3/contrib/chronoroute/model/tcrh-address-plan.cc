/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#include "tcrh-address-plan.h"

#include "ns3/abort.h"

namespace ns3
{
namespace tcrh
{

namespace
{

/// Write @p value big-endian into bytes[at..at+3].
void
PutU32(uint8_t* bytes, uint32_t at, uint32_t value)
{
    bytes[at] = static_cast<uint8_t>(value >> 24);
    bytes[at + 1] = static_cast<uint8_t>(value >> 16);
    bytes[at + 2] = static_cast<uint8_t>(value >> 8);
    bytes[at + 3] = static_cast<uint8_t>(value);
}

} // namespace

Ipv6Address
SidAddress(uint32_t sid)
{
    // fd00:0000:0000:0000:0000:0000:HHHH:LLLL
    uint8_t bytes[16] = {0xfd, 0x00};
    PutU32(bytes, 12, sid);
    return Ipv6Address(bytes);
}

bool
SidFromAddress(Ipv6Address address, uint32_t* sid)
{
    uint8_t bytes[16];
    address.GetBytes(bytes);
    if (bytes[0] != 0xfd || bytes[1] != 0x00)
    {
        return false;
    }
    for (int i = 2; i < 12; ++i)
    {
        if (bytes[i] != 0)
        {
            return false; // inside fd00::/8 but not fd00::/96: a link or other address
        }
    }
    if (sid != nullptr)
    {
        *sid = (static_cast<uint32_t>(bytes[12]) << 24) | (static_cast<uint32_t>(bytes[13]) << 16) |
               (static_cast<uint32_t>(bytes[14]) << 8) | static_cast<uint32_t>(bytes[15]);
    }
    return true;
}

Ipv6Address
LinkPrefix(uint32_t linkId)
{
    // fd01:0000:HHHH:LLLL::/64
    uint8_t bytes[16] = {0xfd, 0x01};
    PutU32(bytes, 4, linkId);
    return Ipv6Address(bytes);
}

Ipv6Address
LinkAddress(uint32_t linkId, uint8_t end)
{
    NS_ABORT_MSG_UNLESS(end == 1 || end == 2, "a point-to-point link has ends 1 and 2, got " << +end);
    uint8_t bytes[16] = {0xfd, 0x01};
    PutU32(bytes, 4, linkId);
    bytes[15] = end;
    return Ipv6Address(bytes);
}

} // namespace tcrh
} // namespace ns3
