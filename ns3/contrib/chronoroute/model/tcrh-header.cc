/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#include "tcrh-header.h"

#include "tcrh-timebase.h"

#include "ns3/abort.h"
#include "ns3/log.h"

#include <algorithm>
#include <iomanip>
#include <sstream>

namespace ns3
{

NS_LOG_COMPONENT_DEFINE("TcrhHeader");

NS_OBJECT_ENSURE_REGISTERED(TcrhHeader);

// ---------------------------------------------------------------- statics

const char*
TcrhHeader::ParseStatusName(ParseStatus status)
{
    switch (status)
    {
    case OK:
        return "ok";
    case TRUNCATED:
        return "truncated";
    case WRONG_TYPE:
        return "wrong_type";
    case SL_GT_NUMHOPS:
        return "sl_gt_numhops";
    case LENGTH_MISMATCH:
        return "length_mismatch";
    case TRAILING_BYTES:
        return "trailing_bytes";
    case NUMHOPS_ZERO:
        return "numhops_zero";
    }
    return "unknown";
}

int
TcrhHeader::ParseStatusIcmpPointer(ParseStatus status)
{
    // Spec section 6 step 1 (and the golden vectors' expect_icmp_pointer):
    // point at the field that is wrong; a header that just stops has no such
    // field. These are offsets inside the routing header.
    switch (status)
    {
    case WRONG_TYPE:
        return OFF_ROUTING_TYPE;
    case NUMHOPS_ZERO:
        return OFF_NUM_HOPS;
    case SL_GT_NUMHOPS:
        return OFF_SEGMENTS_LEFT;
    case LENGTH_MISMATCH:
        return OFF_HDR_EXT_LEN;
    default:
        return -1;
    }
}

uint32_t
TcrhHeader::SizeForHops(uint32_t numHops)
{
    // pad8(12 + 3h): the header must end on a 64-bit boundary (RFC 8200 4.4)
    return ((FIXED_BYTES + ENTRY_BYTES * numHops + 7) / 8) * 8;
}

std::vector<uint8_t>
TcrhHeader::EncodeDeltas(const std::vector<uint64_t>& cumulativeBudgetsNs,
                         uint8_t unitCode,
                         bool* sat)
{
    const uint64_t u = tcrh::UnitNs(unitCode);
    std::vector<uint8_t> deltas;
    deltas.reserve(cumulativeBudgetsNs.size());
    bool saturated = false;
    uint64_t encoded = 0; // E: the encoded cumulative sum, in units
    for (uint64_t b : cumulativeBudgetsNs)
    {
        const uint64_t target = b / u + (b % u != 0 ? 1 : 0); // exact ceil(B_k / u)
        // d_k = target - E, but never negative (cannot happen when B is
        // non-decreasing; unsigned arithmetic must not wrap if it does)
        uint64_t d = target > encoded ? target - encoded : 0;
        if (d > 255)
        {
            d = 255;
            saturated = true;
        }
        encoded += d;
        deltas.push_back(static_cast<uint8_t>(d));
    }
    if (sat != nullptr)
    {
        *sat = saturated;
    }
    return deltas;
}

TcrhHeader
TcrhHeader::Build(const std::vector<uint16_t>& sidsFwd,
                  const std::vector<uint64_t>& cumulativeBudgetsNs,
                  uint64_t tIngressGpsNs,
                  uint8_t unitCode,
                  uint8_t nextHeader)
{
    NS_ABORT_MSG_UNLESS(sidsFwd.size() == cumulativeBudgetsNs.size(),
                        "every hop needs exactly one cumulative budget");
    bool sat = false;
    std::vector<uint8_t> deltas = EncodeDeltas(cumulativeBudgetsNs, unitCode, &sat);
    // Epoch_Base is stamped per packet at ingress, rounded UP (section 4)
    uint32_t epoch = tcrh::EpochBaseAtIngress(tIngressGpsNs, unitCode);
    TcrhHeader h;
    h.SetNextHeader(nextHeader);
    h.SetPath(sidsFwd, deltas, epoch, unitCode, sat ? FLAG_SAT : 0);
    return h;
}

TcrhHeader::ParseStatus
TcrhHeader::Parse(const uint8_t* data,
                  uint32_t len,
                  bool exact,
                  TcrhHeader* out,
                  uint32_t* headerBytes)
{
    // The order of these checks is part of the contract (spec/golden/README.md).
    if (data == nullptr || len < 8)
    {
        return TRUNCATED;
    }
    const uint8_t hel = data[OFF_HDR_EXT_LEN];
    const uint8_t sl = data[OFF_SEGMENTS_LEFT];
    const uint8_t numHops = data[OFF_NUM_HOPS];
    if (data[OFF_ROUTING_TYPE] != ROUTING_TYPE)
    {
        return WRONG_TYPE;
    }
    if (numHops == 0)
    {
        return NUMHOPS_ZERO; // spec section 2: Num Hops is 1..255
    }
    if (sl > numHops)
    {
        return SL_GT_NUMHOPS;
    }
    const uint32_t total = (static_cast<uint32_t>(hel) + 1) * 8;
    if (total < SizeForHops(numHops))
    {
        return LENGTH_MISMATCH;
    }
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
        TcrhHeader h;
        // the four shared bytes go into the base class (see the class comment)
        h.SetNextHeader(data[OFF_NEXT_HEADER]);
        h.m_length = hel; // the base's Hdr Ext Len, kept exactly as received
        h.SetTypeRouting(ROUTING_TYPE);
        h.m_flags = data[OFF_FLAGS];
        h.m_devHop = data[OFF_DEV_HOP];
        h.m_reserved = data[OFF_RESERVED];
        h.m_epochBase = (static_cast<uint32_t>(data[OFF_EPOCH_BASE]) << 24) |
                        (static_cast<uint32_t>(data[OFF_EPOCH_BASE + 1]) << 16) |
                        (static_cast<uint32_t>(data[OFF_EPOCH_BASE + 2]) << 8) |
                        static_cast<uint32_t>(data[OFF_EPOCH_BASE + 3]);
        // Num Hops lets us read exactly the real entries and stop before the
        // padding (the ambiguity a CRH-16 deserializer has to live with).
        h.m_sids.clear();
        h.m_deltas.clear();
        uint32_t off = OFF_ENTRIES;
        for (uint32_t i = 0; i < numHops; ++i)
        {
            h.m_sids.push_back(static_cast<uint16_t>((data[off] << 8) | data[off + 1]));
            h.m_deltas.push_back(data[off + 2]);
            off += ENTRY_BYTES;
        }
        // keep whatever follows the entries (padding, normally zero) byte for byte
        h.m_tail.assign(data + off, data + total);
        h.SetSegmentsLeft(sl); // after the entries: the check needs Num Hops
        h.m_status = OK;
        *out = h;
    }
    if (headerBytes != nullptr)
    {
        *headerBytes = total;
    }
    return OK;
}

// ---------------------------------------------------------------- object

TcrhHeader::TcrhHeader()
    : m_flags(0),
      m_devHop(0),
      m_reserved(0),
      m_epochBase(0),
      m_tail(SizeForHops(0) - FIXED_BYTES, 0),
      m_status(OK)
{
    // the shared routing-header fields live in the base class
    SetNextHeader(DEFAULT_NEXT_HEADER);
    m_length = static_cast<uint8_t>(SizeForHops(0) / 8 - 1);
    SetTypeRouting(ROUTING_TYPE);
    Ipv6ExtensionRoutingHeader::SetSegmentsLeft(0);
}

TypeId
TcrhHeader::GetTypeId()
{
    static TypeId tid = TypeId("ns3::TcrhHeader")
                            .SetParent<Ipv6ExtensionRoutingHeader>()
                            .SetGroupName("Chronoroute")
                            .AddConstructor<TcrhHeader>();
    return tid;
}

TypeId
TcrhHeader::GetInstanceTypeId() const
{
    return GetTypeId();
}

void
TcrhHeader::SetPath(const std::vector<uint16_t>& sidsFwd,
                    const std::vector<uint8_t>& deltasFwd,
                    uint32_t epochBase,
                    uint8_t unitCode,
                    uint8_t extraFlags)
{
    NS_ABORT_MSG_UNLESS(sidsFwd.size() == deltasFwd.size(),
                        "every hop needs exactly one delta (sidsFwd and deltasFwd differ in length)");
    NS_ABORT_MSG_UNLESS(!sidsFwd.empty() && sidsFwd.size() <= MAX_HOPS,
                        "a T-CRH carries 1.." << MAX_HOPS << " hops, got " << sidsFwd.size());
    for (uint16_t sid : sidsFwd)
    {
        // 0xFFFF is reserved (spec section 7): never put it in a new path
        NS_ABORT_MSG_IF(sid == SID_RESERVED, "SID 0xFFFF is reserved");
    }
    NS_ABORT_MSG_UNLESS(tcrh::IsValidUnitCode(unitCode),
                        "T-CRH unit code must be 0..3, got " << +unitCode);
    NS_ABORT_MSG_IF((extraFlags & ~FLAG_STATE_MASK) != 0,
                    "extraFlags may only contain DEV/GREEDY/SAT; the unit goes in unitCode");

    const uint32_t h = sidsFwd.size();
    m_sids.assign(sidsFwd.rbegin(), sidsFwd.rend());
    m_deltas.assign(deltasFwd.rbegin(), deltasFwd.rend());
    SetSegmentsLeft(static_cast<uint8_t>(h));
    SetTypeRouting(ROUTING_TYPE);
    m_flags = static_cast<uint8_t>((unitCode << FLAG_UNIT_SHIFT) | extraFlags);
    m_devHop = 0;
    m_reserved = 0;
    m_epochBase = epochBase;
    const uint32_t size = SizeForHops(h);
    m_length = static_cast<uint8_t>(size / 8 - 1); // the base's Hdr Ext Len
    m_tail.assign(size - FIXED_BYTES - ENTRY_BYTES * h, 0); // zero padding
    m_status = OK;
}

void
TcrhHeader::SetSegmentsLeft(uint8_t segmentsLeft)
{
    NS_ABORT_MSG_IF(segmentsLeft > m_sids.size(),
                    "Segments Left " << +segmentsLeft << " > Num Hops " << m_sids.size());
    Ipv6ExtensionRoutingHeader::SetSegmentsLeft(segmentsLeft);
}

uint8_t
TcrhHeader::GetHdrExtLen() const
{
    return m_length;
}

uint8_t
TcrhHeader::GetFlags() const
{
    return m_flags;
}

void
TcrhHeader::SetFlags(uint8_t flags)
{
    m_flags = flags;
}

uint8_t
TcrhHeader::GetUnitCode() const
{
    return (m_flags >> FLAG_UNIT_SHIFT) & 3;
}

uint64_t
TcrhHeader::GetUnitNs() const
{
    return tcrh::UnitNs(GetUnitCode());
}

bool
TcrhHeader::IsDev() const
{
    return (m_flags & FLAG_DEV) != 0;
}

bool
TcrhHeader::IsGreedy() const
{
    return (m_flags & FLAG_GREEDY) != 0;
}

bool
TcrhHeader::IsSat() const
{
    return (m_flags & FLAG_SAT) != 0;
}

uint8_t
TcrhHeader::GetNumHops() const
{
    return static_cast<uint8_t>(m_sids.size());
}

uint8_t
TcrhHeader::GetDevHop() const
{
    return m_devHop;
}

void
TcrhHeader::SetDevHop(uint8_t devHop)
{
    m_devHop = devHop;
}

uint8_t
TcrhHeader::GetReserved() const
{
    return m_reserved;
}

uint32_t
TcrhHeader::GetEpochBase() const
{
    return m_epochBase;
}

uint16_t
TcrhHeader::GetSid(uint8_t i) const
{
    NS_ABORT_MSG_UNLESS(i < m_sids.size(), "SID index " << +i << " out of range");
    return m_sids[i];
}

uint8_t
TcrhHeader::GetDelta(uint8_t i) const
{
    NS_ABORT_MSG_UNLESS(i < m_deltas.size(), "Delta index " << +i << " out of range");
    return m_deltas[i];
}

std::vector<uint16_t>
TcrhHeader::GetSidsForward() const
{
    return std::vector<uint16_t>(m_sids.rbegin(), m_sids.rend());
}

std::vector<uint8_t>
TcrhHeader::GetDeltasForward() const
{
    return std::vector<uint8_t>(m_deltas.rbegin(), m_deltas.rend());
}

uint32_t
TcrhHeader::GetDeadline(uint8_t k) const
{
    const uint32_t h = m_sids.size();
    NS_ABORT_MSG_UNLESS(k >= 1 && k <= h, "hop index k must be 1.." << h << ", got " << +k);
    // uint32_t arithmetic wraps mod 2^32, exactly as the spec's "(...) mod 2^32"
    uint32_t sum = m_epochBase;
    for (uint32_t i = h - k; i < h; ++i)
    {
        sum += m_deltas[i];
    }
    return sum;
}

std::vector<uint32_t>
TcrhHeader::GetDeadlines() const
{
    std::vector<uint32_t> out;
    uint32_t running = m_epochBase;
    for (auto it = m_deltas.rbegin(); it != m_deltas.rend(); ++it)
    {
        running += *it;
        out.push_back(running);
    }
    return out;
}

uint8_t
TcrhHeader::GetCurrentHopIndex() const
{
    return static_cast<uint8_t>(m_sids.size() - GetSegmentsLeft());
}

TcrhHeader::ParseStatus
TcrhHeader::GetParseStatus() const
{
    return m_status;
}

std::vector<uint8_t>
TcrhHeader::ToBytes() const
{
    Buffer buf;
    buf.AddAtStart(GetSerializedSize());
    Serialize(buf.Begin());
    std::vector<uint8_t> out(GetSerializedSize());
    buf.CopyData(out.data(), out.size());
    return out;
}

std::string
TcrhHeader::ToHex() const
{
    std::ostringstream os;
    for (uint8_t b : ToBytes())
    {
        os << std::hex << std::setw(2) << std::setfill('0') << +b;
    }
    return os.str();
}

// ---------------------------------------------------------------- Header

uint32_t
TcrhHeader::GetSerializedSize() const
{
    return (static_cast<uint32_t>(m_length) + 1) * 8;
}

void
TcrhHeader::Serialize(Buffer::Iterator start) const
{
    // invariant: entries + tail fill exactly (HdrExtLen + 1) * 8 bytes
    NS_ASSERT(FIXED_BYTES + ENTRY_BYTES * m_sids.size() + m_tail.size() == GetSerializedSize());
    start.WriteU8(GetNextHeader());
    start.WriteU8(m_length);
    start.WriteU8(ROUTING_TYPE);
    start.WriteU8(GetSegmentsLeft());
    start.WriteU8(m_flags);
    start.WriteU8(static_cast<uint8_t>(m_sids.size()));
    start.WriteU8(m_devHop);
    start.WriteU8(m_reserved);
    start.WriteHtonU32(m_epochBase);
    for (size_t i = 0; i < m_sids.size(); ++i)
    {
        start.WriteHtonU16(m_sids[i]);
        start.WriteU8(m_deltas[i]);
    }
    for (uint8_t b : m_tail)
    {
        start.WriteU8(b);
    }
}

uint32_t
TcrhHeader::Deserialize(Buffer::Iterator start)
{
    // Read only what is there: a short or forged packet must be rejected, not
    // read past its end.
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
    TcrhHeader parsed;
    uint32_t total = 0;
    ParseStatus status = Parse(bytes.data(), bytes.size(), false, &parsed, &total);
    if (status != OK)
    {
        NS_LOG_LOGIC("malformed T-CRH: " << ParseStatusName(status));
        *this = TcrhHeader();
        m_status = status;
        return 0; // consumed nothing: the caller must discard the packet
    }
    *this = parsed;
    return total;
}

void
TcrhHeader::Print(std::ostream& os) const
{
    static const char* unitText[4] = {"1ms", "0.1ms", "0.25ms", "0.125ms"};
    os << "T-CRH(nh=" << +GetNextHeader() << " sl=" << +GetSegmentsLeft() << " flags=0x" << std::hex
       << std::setw(2) << std::setfill('0') << +m_flags << std::dec << std::setfill(' ');
    if (IsDev())
    {
        os << " DEV";
    }
    if (IsGreedy())
    {
        os << " GREEDY";
    }
    if (IsSat())
    {
        os << " SAT";
    }
    os << " unit=" << unitText[GetUnitCode()] << " hops=" << m_sids.size()
       << " devHop=" << +m_devHop << " epoch=" << m_epochBase << " path=[";
    for (size_t i = m_sids.size(); i-- > 0;)
    {
        os << m_sids[i] << "/" << +m_deltas[i] << (i ? " " : "");
    }
    os << "] " << GetSerializedSize() << "B)";
}

} // namespace ns3
