/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#include "crh-header.h"

#include "ns3/abort.h"
#include "ns3/log.h"

#include <algorithm>
#include <iomanip>
#include <sstream>

namespace ns3
{

NS_LOG_COMPONENT_DEFINE("CrhHeader");

NS_OBJECT_ENSURE_REGISTERED(CrhHeader);

// largest header Hdr Ext Len can describe: (255 + 1) * 8 bytes
static constexpr uint32_t CRH_MAX_HEADER_BYTES = 2048;

const char*
CrhHeader::ParseStatusName(ParseStatus status)
{
    switch (status)
    {
    case OK:
        return "ok";
    case TRUNCATED:
        return "truncated";
    case WRONG_TYPE:
        return "wrong_type";
    case TRAILING_BYTES:
        return "trailing_bytes";
    }
    return "unknown";
}

uint32_t
CrhHeader::SidBytes(uint8_t routingType)
{
    NS_ABORT_MSG_UNLESS(routingType == ROUTING_TYPE_CRH16 || routingType == ROUTING_TYPE_CRH32,
                        "CRH routing type must be 5 (CRH-16) or 6 (CRH-32), got " << +routingType);
    return routingType == ROUTING_TYPE_CRH16 ? 2 : 4;
}

uint32_t
CrhHeader::SizeForSids(uint32_t numSids, uint8_t routingType)
{
    // RFC 9631: "the CRH MUST end on a 64-bit boundary", so zero-pad to 8 bytes
    return ((FIXED_BYTES + SidBytes(routingType) * numSids + 7) / 8) * 8;
}

uint8_t
CrhHeader::MinHdrExtLen(uint8_t segmentsLeft, uint8_t routingType)
{
    // The first 8 octets hold the 4 fixed bytes plus 2 CRH-16 SIDs or 1 CRH-32
    // SID; every further 8 octets hold 4 or 2 more.
    const uint32_t firstWord = routingType == ROUTING_TYPE_CRH16 ? 2 : 1;
    const uint32_t perWord = SidBytes(routingType) == 2 ? 4 : 2;
    if (segmentsLeft <= firstWord)
    {
        return 0;
    }
    return static_cast<uint8_t>((segmentsLeft - firstWord + perWord - 1) / perWord);
}

CrhHeader::ParseStatus
CrhHeader::Parse(const uint8_t* data, uint32_t len, bool exact, CrhHeader* out, uint32_t* headerBytes)
{
    if (data == nullptr || len < 8)
    {
        return TRUNCATED;
    }
    const uint8_t rtype = data[OFF_ROUTING_TYPE];
    if (rtype != ROUTING_TYPE_CRH16 && rtype != ROUTING_TYPE_CRH32)
    {
        return WRONG_TYPE;
    }
    const uint32_t total = (static_cast<uint32_t>(data[OFF_HDR_EXT_LEN]) + 1) * 8;
    if (len < total)
    {
        return TRUNCATED;
    }
    if (exact && len != total)
    {
        return TRAILING_BYTES;
    }
    if (out != nullptr)
    {
        CrhHeader h;
        h.SetTypeRouting(rtype);
        h.SetNextHeader(data[0]);
        h.SetSegmentsLeft(data[OFF_SEGMENTS_LEFT]);
        const uint32_t size = SidBytes(rtype);
        // every SID-sized slot, padding included (no count field; see class doc)
        h.m_sids.clear();
        for (uint32_t off = FIXED_BYTES; off + size <= total; off += size)
        {
            uint32_t sid = 0;
            for (uint32_t b = 0; b < size; ++b)
            {
                sid = (sid << 8) | data[off + b];
            }
            h.m_sids.push_back(sid);
        }
        h.SyncLength();
        h.m_status = OK;
        *out = h;
    }
    if (headerBytes != nullptr)
    {
        *headerBytes = total;
    }
    return OK;
}

CrhHeader::CrhHeader()
    : m_status(OK)
{
    // the shared routing-header fields live in the base class
    SetTypeRouting(ROUTING_TYPE_CRH16);
    SetNextHeader(DEFAULT_NEXT_HEADER);
    SetSegmentsLeft(0);
    SyncLength();
}

void
CrhHeader::SyncLength()
{
    m_length = static_cast<uint8_t>(GetSerializedSize() / 8 - 1);
}

TypeId
CrhHeader::GetTypeId()
{
    static TypeId tid = TypeId("ns3::CrhHeader")
                            .SetParent<Ipv6ExtensionRoutingHeader>()
                            .SetGroupName("Chronoroute")
                            .AddConstructor<CrhHeader>();
    return tid;
}

TypeId
CrhHeader::GetInstanceTypeId() const
{
    return GetTypeId();
}

void
CrhHeader::SetPath(const std::vector<uint32_t>& sidsFwd, uint8_t routingType)
{
    const uint32_t sidBytes = SidBytes(routingType);
    NS_ABORT_MSG_UNLESS(!sidsFwd.empty() && sidsFwd.size() <= 255,
                        "a CRH path has 1..255 SIDs (Segments Left is one byte), got "
                            << sidsFwd.size());
    for (uint32_t sid : sidsFwd)
    {
        NS_ABORT_MSG_IF(sidBytes == 2 && sid > 0xFFFF, "SID " << sid << " does not fit CRH-16");
    }
    NS_ABORT_MSG_IF(SizeForSids(sidsFwd.size(), routingType) > CRH_MAX_HEADER_BYTES,
                    "path too long for one CRH");
    SetTypeRouting(routingType);
    m_sids.assign(sidsFwd.rbegin(), sidsFwd.rend());
    SetSegmentsLeft(static_cast<uint8_t>(m_sids.size()));
    SyncLength();
    m_status = OK;
}

uint8_t
CrhHeader::GetHdrExtLen() const
{
    return static_cast<uint8_t>(GetSerializedSize() / 8 - 1);
}

uint8_t
CrhHeader::GetMinimumLength() const
{
    return MinHdrExtLen(GetSegmentsLeft(), GetTypeRouting());
}

uint32_t
CrhHeader::GetNumSids() const
{
    return m_sids.size();
}

uint32_t
CrhHeader::GetSid(uint32_t i) const
{
    NS_ABORT_MSG_UNLESS(i < m_sids.size(), "SID index " << i << " out of range");
    return m_sids[i];
}

const std::vector<uint32_t>&
CrhHeader::GetSidsReversed() const
{
    return m_sids;
}

uint32_t
CrhHeader::GetCurrentSid() const
{
    NS_ABORT_MSG_UNLESS(GetSegmentsLeft() < m_sids.size(),
                        "Segments Left out of range for the SID list");
    return m_sids[GetSegmentsLeft()];
}

std::vector<uint8_t>
CrhHeader::ToBytes() const
{
    Buffer buf;
    buf.AddAtStart(GetSerializedSize());
    Serialize(buf.Begin());
    std::vector<uint8_t> out(GetSerializedSize());
    buf.CopyData(out.data(), out.size());
    return out;
}

std::string
CrhHeader::ToHex() const
{
    std::ostringstream os;
    for (uint8_t b : ToBytes())
    {
        os << std::hex << std::setw(2) << std::setfill('0') << +b;
    }
    return os.str();
}

CrhHeader::ParseStatus
CrhHeader::GetParseStatus() const
{
    return m_status;
}

uint32_t
CrhHeader::GetSerializedSize() const
{
    return SizeForSids(m_sids.size(), GetTypeRouting());
}

void
CrhHeader::Serialize(Buffer::Iterator start) const
{
    const uint32_t total = GetSerializedSize();
    start.WriteU8(GetNextHeader());
    start.WriteU8(static_cast<uint8_t>(total / 8 - 1)); // Hdr Ext Len
    start.WriteU8(GetTypeRouting());
    start.WriteU8(GetSegmentsLeft());
    for (uint32_t sid : m_sids)
    {
        if (GetTypeRouting() == ROUTING_TYPE_CRH16)
        {
            start.WriteHtonU16(static_cast<uint16_t>(sid));
        }
        else
        {
            start.WriteHtonU32(sid);
        }
    }
    // zero padding to the 64-bit boundary
    for (uint32_t i = FIXED_BYTES + SidBytes(GetTypeRouting()) * m_sids.size(); i < total; ++i)
    {
        start.WriteU8(0);
    }
}

uint32_t
CrhHeader::Deserialize(Buffer::Iterator start)
{
    const uint32_t avail = start.GetRemainingSize();
    std::vector<uint8_t> bytes(std::min<uint32_t>(avail, 8));
    start.Read(bytes.data(), bytes.size());
    if (bytes.size() == 8)
    {
        const uint32_t total = (static_cast<uint32_t>(bytes[OFF_HDR_EXT_LEN]) + 1) * 8;
        const uint32_t want = std::min(avail, total);
        bytes.resize(want);
        start.Read(bytes.data() + 8, want - 8);
    }
    CrhHeader parsed;
    uint32_t total = 0;
    ParseStatus status = Parse(bytes.data(), bytes.size(), false, &parsed, &total);
    if (status != OK)
    {
        NS_LOG_LOGIC("malformed CRH: " << ParseStatusName(status));
        *this = CrhHeader();
        m_status = status;
        return 0; // consumed nothing: the caller must discard the packet
    }
    *this = parsed;
    return total;
}

void
CrhHeader::Print(std::ostream& os) const
{
    os << (GetTypeRouting() == ROUTING_TYPE_CRH16 ? "CRH-16" : "CRH-32") << "(type="
       << +GetTypeRouting() << " segsLeft=" << +GetSegmentsLeft() << " sids=[";
    for (size_t i = 0; i < m_sids.size(); ++i)
    {
        os << (i ? " " : "") << m_sids[i];
    }
    os << "] " << GetSerializedSize() << "B)";
}

CrhProcessResult
CrhProcessAtNode(const uint8_t* raw, uint32_t len)
{
    CrhProcessResult r;
    CrhHeader hdr;
    CrhHeader::ParseStatus status = CrhHeader::Parse(raw, len, false, &hdr, nullptr);
    if (status == CrhHeader::WRONG_TYPE && raw[CrhHeader::OFF_SEGMENTS_LEFT] == 0)
    {
        // RFC 8200 section 4.4: an unrecognised routing header with Segments
        // Left 0 is ignored and the Next Header processed; only SL > 0 is a
        // Parameter Problem. (WRONG_TYPE implies at least 8 bytes.)
        r.action = "ignore";
        r.reason = CrhHeader::ParseStatusName(status);
        r.outBytes = std::vector<uint8_t>(raw, raw + len);
        return r;
    }
    if (status != CrhHeader::OK)
    {
        r.action = "drop_malformed";
        r.reason = CrhHeader::ParseStatusName(status);
        if (status == CrhHeader::WRONG_TYPE)
        {
            r.icmpCode = CrhHeader::ICMP_CODE_ERRONEOUS_FIELD;
            r.icmpPointer = CrhHeader::OFF_ROUTING_TYPE;
        }
        return r;
    }
    std::vector<uint8_t> out(raw, raw + len);
    // 0. Segments Left == 0: the packet is for me (RFC 8200 4.4)
    if (hdr.GetSegmentsLeft() == 0)
    {
        r.action = "deliver";
        r.outBytes = std::move(out);
        return r;
    }
    // 1. minimum-length check (RFC 9631 5.1): stops a forged Segments Left from
    //    indexing past the end of the SID list
    if (hdr.GetMinimumLength() > hdr.GetHdrExtLen())
    {
        r.action = "drop_malformed";
        r.reason = "min_length";
        r.icmpCode = CrhHeader::ICMP_CODE_MIN_LENGTH;
        r.icmpPointer = CrhHeader::OFF_SEGMENTS_LEFT;
        return r;
    }
    // 2-3. decrement THEN index
    const uint8_t sl = hdr.GetSegmentsLeft() - 1;
    hdr.SetSegmentsLeft(sl);
    NS_ASSERT_MSG(sl < hdr.GetNumSids(), "minimum-length check let SL index past the SIDs");
    r.action = "forward";
    r.nextSid = hdr.GetCurrentSid();
    out[CrhHeader::OFF_SEGMENTS_LEFT] = sl;
    r.outBytes = std::move(out);
    return r;
}

} // namespace ns3
