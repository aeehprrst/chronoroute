/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#include "ipv6-extension-tcrh.h"

#include "crh-header.h"
#include "tcrh-address-plan.h"
#include "tcrh-header.h"
#include "tcrh-timebase.h"

#include "ns3/abort.h"
#include "ns3/enum.h"
#include "ns3/icmpv6-header.h"
#include "ns3/icmpv6-l4-protocol.h"
#include "ns3/ipv6-route.h"
#include "ns3/ipv6-routing-protocol.h"
#include "ns3/log.h"
#include "ns3/net-device.h"
#include "ns3/node.h"
#include "ns3/packet.h"
#include "ns3/simulator.h"
#include "ns3/socket.h"
#include "ns3/uinteger.h"

#include <algorithm>
#include <iostream>
#include <sstream>
#include <vector>

namespace ns3
{

NS_LOG_COMPONENT_DEFINE("Ipv6ExtensionTcrh");

// ============================================================ hop events (CSV)

std::string
TcrhHopEventCsvHeader()
{
    return "t_ns,node,node_sid,uid,rtype,action,reason,nh,hlim_in,src,dst_in,dst_out,num_hops,"
           "sl_in,sl_out,flags_in,flags_out,dev_hop,epoch_base,hop_index,deadline_u,now_u,late,"
           "next_sid";
}

namespace
{

/// An optional number as a CSV field ("" when empty).
template <typename T>
std::string
Field(const std::optional<T>& v)
{
    if (!v.has_value())
    {
        return "";
    }
    std::ostringstream os;
    os << +*v;
    return os.str();
}

} // namespace

std::string
TcrhHopEventCsv(const TcrhHopEvent& e)
{
    std::ostringstream os;
    os << e.tNs << "," << e.nodeId << "," << Field(e.nodeSid) << "," << e.packetUid << ","
       << +e.routingType << "," << e.action << "," << (e.reason ? e.reason : "") << ","
       << +e.nextHeader << "," << +e.hopLimitIn << "," << e.src << "," << e.dstIn << ",";
    if (e.dstOut.has_value())
    {
        os << *e.dstOut;
    }
    os << "," << +e.numHops << "," << +e.slIn << "," << +e.slOut << "," << +e.flagsIn << ","
       << +e.flagsOut << "," << +e.devHop << "," << e.epochBase << "," << Field(e.hopIndex) << ","
       << Field(e.deadlineU) << "," << Field(e.nowU) << "," << (e.late ? 1 : 0) << ","
       << Field(e.nextSid);
    return os.str();
}

// ============================================================ shared helpers

namespace
{

/// Size of the fixed IPv6 header (the ICMPv6 Pointer counts it, RFC 4443 3.4).
constexpr uint32_t IPV6_HEADER_BYTES = 40;
/// ns-3.44 returns extension lengths (and keeps the running offset) as uint8_t.
constexpr uint32_t NS3_MAX_EXTENSION_OFFSET = 255;

/**
 * Copy the routing header's bytes out of the packet, never the payload: up to
 * (Hdr Ext Len + 1) * 8 bytes from @p offset, fewer if the packet ends first
 * (validation then reports "truncated"). Copying only the header keeps the
 * per-hop cost independent of the payload size.
 */
std::vector<uint8_t>
CopyRoutingHeader(Ptr<const Packet> packet, uint32_t offset)
{
    const uint32_t size = packet->GetSize();
    if (size <= offset)
    {
        return {};
    }
    const uint32_t avail = size - offset;
    uint32_t want = std::min<uint32_t>(avail, 8);
    if (want == 8)
    {
        std::vector<uint8_t> first(offset + 8);
        packet->CopyData(first.data(), first.size());
        const uint32_t total = (static_cast<uint32_t>(first[offset + 1]) + 1) * 8;
        want = std::min(avail, total);
    }
    std::vector<uint8_t> all(offset + want);
    packet->CopyData(all.data(), all.size());
    return std::vector<uint8_t>(all.begin() + offset, all.end());
}

/// A fresh event with what every routing-header event shares.
TcrhHopEvent
NewEvent(Ptr<Node> node, Ptr<const Packet> packet, const Ipv6Header& ip, uint8_t routingType)
{
    TcrhHopEvent e;
    e.tNs = Simulator::Now().GetNanoSeconds();
    e.nodeId = node->GetId();
    Ptr<CrhFib> fib = node->GetObject<CrhFib>();
    if (fib)
    {
        e.nodeSid = fib->GetLocalSid();
    }
    e.packetUid = packet->GetUid();
    e.routingType = routingType;
    e.hopLimitIn = ip.GetHopLimit();
    e.src = ip.GetSource();
    e.dstIn = ip.GetDestination();
    return e;
}

/// T-CRH fields of the bytes on arrival.
void
FillTcrhIn(TcrhHopEvent& e, const std::vector<uint8_t>& raw)
{
    if (raw.size() >= 4)
    {
        e.nextHeader = raw[TcrhHeader::OFF_NEXT_HEADER];
        e.slIn = raw[TcrhHeader::OFF_SEGMENTS_LEFT];
        e.slOut = e.slIn;
    }
    if (raw.size() >= 8)
    {
        e.flagsIn = raw[TcrhHeader::OFF_FLAGS];
        e.flagsOut = e.flagsIn;
        e.numHops = raw[TcrhHeader::OFF_NUM_HOPS];
        e.devHop = raw[TcrhHeader::OFF_DEV_HOP];
    }
    if (raw.size() >= 12)
    {
        const uint8_t* b = raw.data() + TcrhHeader::OFF_EPOCH_BASE;
        e.epochBase = (static_cast<uint32_t>(b[0]) << 24) | (static_cast<uint32_t>(b[1]) << 16) |
                      (static_cast<uint32_t>(b[2]) << 8) | static_cast<uint32_t>(b[3]);
    }
}

/// T-CRH fields of the bytes as they leave.
void
FillTcrhOut(TcrhHopEvent& e, const std::vector<uint8_t>& out)
{
    e.slOut = out[TcrhHeader::OFF_SEGMENTS_LEFT];
    e.flagsOut = out[TcrhHeader::OFF_FLAGS];
    e.devHop = out[TcrhHeader::OFF_DEV_HOP];
}

/**
 * RFC 4443 section 2.4 (e): no ICMPv6 error about a packet whose source does
 * not name one node, about a packet sent to a multicast address, or about an
 * ICMPv6 error message (type < 128) that follows the routing header.
 */
bool
MayReportError(Ptr<const Packet> packet, const Ipv6Header& ip, uint32_t offset, uint32_t rhBytes)
{
    const Ipv6Address src = ip.GetSource();
    if (src.IsAny() || src.IsMulticast() || ip.GetDestination().IsMulticast())
    {
        return false;
    }
    if (rhBytes >= 1)
    {
        uint8_t nh = 0;
        std::vector<uint8_t> b(offset + 1);
        packet->CopyData(b.data(), b.size());
        nh = b[offset];
        if (nh == Icmpv6L4Protocol::GetStaticProtocolNumber() &&
            packet->GetSize() > offset + rhBytes)
        {
            std::vector<uint8_t> all(offset + rhBytes + 1);
            packet->CopyData(all.data(), all.size());
            if (all[offset + rhBytes] < 128)
            {
                return false; // an ICMPv6 error message: never answer it with another
            }
        }
    }
    return true;
}

/// ICMPv6 Parameter Problem to the packet's source. @return true if sent.
bool
SendParameterProblem(Ptr<Node> node,
                     Ptr<const Packet> packet,
                     const Ipv6Header& ip,
                     uint32_t offset,
                     uint32_t rhBytes,
                     uint8_t code,
                     uint32_t pointer)
{
    Ptr<Icmpv6L4Protocol> icmpv6 = node->GetObject<Ipv6L3Protocol>()->GetIcmpv6();
    if (!icmpv6 || !MayReportError(packet, ip, offset, rhBytes))
    {
        return false;
    }
    // the invoking packet as it arrived, IPv6 header included (RFC 4443 3.4)
    Ptr<Packet> invoking = packet->Copy();
    invoking->AddHeader(ip);
    NS_LOG_LOGIC("node " << node->GetId() << ": ICMPv6 Parameter Problem code " << +code
                         << " pointer " << pointer << " to " << ip.GetSource());
    icmpv6->SendErrorParameterError(invoking, ip.GetSource(), code, pointer);
    return true;
}

/// ICMPv6 Time Exceeded (Hop Limit) to the packet's source. @return true if sent.
bool
SendTimeExceeded(Ptr<Node> node,
                 Ptr<const Packet> packet,
                 const Ipv6Header& ip,
                 uint32_t offset,
                 uint32_t rhBytes)
{
    Ptr<Icmpv6L4Protocol> icmpv6 = node->GetObject<Ipv6L3Protocol>()->GetIcmpv6();
    if (!icmpv6 || !MayReportError(packet, ip, offset, rhBytes))
    {
        return false;
    }
    Ptr<Packet> invoking = packet->Copy();
    invoking->AddHeader(ip);
    icmpv6->SendErrorTimeExceeded(invoking, ip.GetSource(), Icmpv6Header::ICMPV6_HOPLIMIT);
    return true;
}

/**
 * The packet to send on: a copy of @p packet (same uid, same tags) with its
 * first @p oldBytes bytes replaced by the routing header @p header. The header
 * object serializes byte for byte what it parsed (golden-tested), so only the
 * mutable fields the processing step changed differ from the input.
 */
template <typename HeaderT>
Ptr<Packet>
WithRoutingHeader(Ptr<const Packet> packet, uint32_t oldBytes, const HeaderT& header)
{
    Ptr<Packet> out = packet->Copy();
    out->RemoveAtStart(oldBytes);
    out->AddHeader(header);
    return out;
}

/// Parse bytes that a golden-tested processing step produced (cannot fail).
TcrhHeader
TcrhFromBytes(const std::vector<uint8_t>& bytes)
{
    TcrhHeader h;
    const TcrhHeader::ParseStatus s =
        TcrhHeader::Parse(bytes.data(), static_cast<uint32_t>(bytes.size()), true, &h, nullptr);
    NS_ABORT_MSG_UNLESS(s == TcrhHeader::OK, "processing produced an invalid T-CRH");
    return h;
}

/// Parse CRH bytes that a golden-tested processing step produced (cannot fail).
CrhHeader
CrhFromBytes(const std::vector<uint8_t>& bytes)
{
    CrhHeader h;
    const CrhHeader::ParseStatus s =
        CrhHeader::Parse(bytes.data(), static_cast<uint32_t>(bytes.size()), true, &h, nullptr);
    NS_ABORT_MSG_UNLESS(s == CrhHeader::OK, "processing produced an invalid CRH");
    return h;
}

/// The CRH-FIB entry's link is usable: IPv6 interface up and device link up.
bool
LinkUp(Ptr<Ipv6L3Protocol> ipv6, uint32_t interface)
{
    NS_ABORT_MSG_UNLESS(interface < ipv6->GetNInterfaces(),
                        "CRH-FIB entry names IPv6 interface " << interface << ", the node has "
                                                              << ipv6->GetNInterfaces());
    return ipv6->IsUp(interface) && ipv6->GetNetDevice(interface)->IsLinkUp();
}

} // namespace

namespace tcrh
{

void
SendSegment(Ptr<Ipv6L3Protocol> ipv6,
            Ptr<Packet> p,
            Ipv6Address src,
            Ipv6Address dst,
            uint8_t hopLimit,
            uint8_t tclass,
            uint32_t interface,
            Ipv6Address nextHop)
{
    // Ipv6L3Protocol::Send takes the Hop Limit and Traffic Class from these
    // tags (and removes them); Replace, so a stale tag can never win.
    SocketIpv6HopLimitTag hl;
    hl.SetHopLimit(hopLimit);
    p->ReplacePacketTag(hl);
    SocketIpv6TclassTag tc;
    tc.SetTclass(tclass);
    p->ReplacePacketTag(tc);

    Ptr<Ipv6Route> route = Create<Ipv6Route>();
    route->SetDestination(dst);
    route->SetSource(src);
    route->SetGateway(nextHop);
    route->SetOutputDevice(ipv6->GetNetDevice(interface));
    ipv6->Send(p, src, dst, Ipv6Header::IPV6_EXT_ROUTING, route);
}

bool
RoutingTableFallback(Ptr<Ipv6L3Protocol> ipv6,
                     Ptr<Packet> p,
                     const Ipv6Header& header,
                     uint32_t targetSid)
{
    Ptr<Ipv6RoutingProtocol> rp = ipv6->GetRoutingProtocol();
    if (!rp)
    {
        return false;
    }
    Socket::SocketErrno err;
    Ptr<Ipv6Route> route = rp->RouteOutput(p, header, nullptr, err);
    if (!route)
    {
        NS_LOG_LOGIC("routing-table fallback: no route to " << header.GetDestination()
                                                            << " (SID " << targetSid << ")");
        return false;
    }
    const int32_t interface = ipv6->GetInterfaceForDevice(route->GetOutputDevice());
    NS_ABORT_MSG_IF(interface < 0, "route through a device without IPv6");
    SendSegment(ipv6,
                p,
                header.GetSource(),
                header.GetDestination(),
                header.GetHopLimit(),
                header.GetTrafficClass(),
                static_cast<uint32_t>(interface),
                route->GetGateway());
    return true;
}

} // namespace tcrh

// ============================================================ Ipv6ExtensionTcrh

NS_OBJECT_ENSURE_REGISTERED(Ipv6ExtensionTcrh);

TypeId
Ipv6ExtensionTcrh::GetTypeId()
{
    static TypeId tid =
        TypeId("ns3::Ipv6ExtensionTcrh")
            .SetParent<Ipv6ExtensionRouting>()
            .SetGroupName("Chronoroute")
            .AddConstructor<Ipv6ExtensionTcrh>()
            .AddAttribute("T0GpsNs",
                          "GPS time, in integer ns since the GPS epoch, of simulation time 0 "
                          "(spec/tcrh-v1.md section 4: t0_gps). The node's unit clock is "
                          "floor((T0GpsNs + now) / u) mod 2^32.",
                          UintegerValue(0),
                          MakeUintegerAccessor(&Ipv6ExtensionTcrh::m_t0GpsNs),
                          MakeUintegerChecker<uint64_t>())
            .AddAttribute("Policy",
                          "Deviation policy for a packet with DEV set (spec section 6 step 4). "
                          "greedy without a fallback function behaves like continue.",
                          EnumValue(tcrh::Policy::GREEDY),
                          MakeEnumAccessor<tcrh::Policy>(&Ipv6ExtensionTcrh::m_policy),
                          MakeEnumChecker(tcrh::Policy::GREEDY,
                                          "greedy",
                                          tcrh::Policy::CONTINUE,
                                          "continue",
                                          tcrh::Policy::DROP,
                                          "drop"))
            .AddTraceSource("Hop",
                            "A T-CRH packet was processed at this node (one TcrhHopEvent).",
                            MakeTraceSourceAccessor(&Ipv6ExtensionTcrh::m_hopTrace),
                            "ns3::Ipv6ExtensionTcrh::HopTracedCallback");
    return tid;
}

Ipv6ExtensionTcrh::Ipv6ExtensionTcrh()
    : m_t0GpsNs(0),
      m_policy(tcrh::Policy::GREEDY),
      m_warnedGreedyNoFallback(false)
{
}

Ipv6ExtensionTcrh::~Ipv6ExtensionTcrh()
{
}

void
Ipv6ExtensionTcrh::DoDispose()
{
    // the fallback may hold a Ptr to this node's IPv6 layer: break the cycle
    m_fallback = MakeNullCallback<bool, Ptr<Packet>, const Ipv6Header&, uint32_t>();
    Ipv6ExtensionRouting::DoDispose();
}

uint8_t
Ipv6ExtensionTcrh::GetTypeRouting() const
{
    return TYPE_ROUTING;
}

Ipv6ExtensionRoutingHeader*
Ipv6ExtensionTcrh::GetExtensionRoutingHeaderPtr()
{
    return new TcrhHeader();
}

void
Ipv6ExtensionTcrh::SetFallback(FallbackCallback cb)
{
    m_fallback = cb;
}

bool
Ipv6ExtensionTcrh::HasFallback() const
{
    return !m_fallback.IsNull();
}

void
Ipv6ExtensionTcrh::SetPolicy(tcrh::Policy policy)
{
    m_policy = policy;
}

tcrh::Policy
Ipv6ExtensionTcrh::GetPolicy() const
{
    return m_policy;
}

std::string
Ipv6ExtensionTcrh::EffectivePolicyName() const
{
    if (m_policy == tcrh::Policy::GREEDY && m_fallback.IsNull())
    {
        return "continue (greedy set, no fallback installed)";
    }
    return tcrh::PolicyName(m_policy);
}

void
Ipv6ExtensionTcrh::SetT0GpsNs(uint64_t t0GpsNs)
{
    m_t0GpsNs = t0GpsNs;
}

uint64_t
Ipv6ExtensionTcrh::GetT0GpsNs() const
{
    return m_t0GpsNs;
}

const TcrhCounters&
Ipv6ExtensionTcrh::GetCounters() const
{
    return m_counters;
}

uint8_t
Ipv6ExtensionTcrh::Process(Ptr<Packet>& packet,
                           uint8_t offset,
                           const Ipv6Header& ipv6Header,
                           Ipv6Address dst,
                           uint8_t* nextHeader,
                           bool& stopProcessing,
                           bool& isDropped,
                           Ipv6L3Protocol::DropReason& dropReason)
{
    NS_LOG_FUNCTION(this << packet << +offset << ipv6Header << dst);
    Ptr<Node> node = GetNode();
    Ptr<Ipv6L3Protocol> ipv6 = node->GetObject<Ipv6L3Protocol>();
    m_counters.processed++;

    TcrhHopEvent ev = NewEvent(node, packet, ipv6Header, TYPE_ROUTING);
    const std::vector<uint8_t> raw = CopyRoutingHeader(packet, offset);
    FillTcrhIn(ev, raw);
    if (nextHeader != nullptr && !raw.empty())
    {
        *nextHeader = raw[TcrhHeader::OFF_NEXT_HEADER];
    }

    // Every discard ends the same way: count it, trace it, tell LocalDeliver
    // to stop and to fire its own Drop trace with an ns-3 drop reason.
    auto discard = [&](const char* action, Ipv6L3Protocol::DropReason why, uint64_t& counter) {
        counter++;
        ev.action = action;
        m_hopTrace(ev);
        isDropped = true;
        stopProcessing = true;
        dropReason = why;
        return static_cast<uint8_t>(0); // nothing after this is processed
    };

    // ns-3.44 reads the Routing Type at the start of the packet, not at the
    // header's offset (ipv6-extension.cc:887-893): a routing header behind
    // another extension header was dispatched on the wrong byte. Refuse it
    // rather than misread it.
    if (offset != 0)
    {
        ev.reason = "routing_header_not_first";
        return discard("drop_unsupported",
                       Ipv6L3Protocol::DROP_MALFORMED_HEADER,
                       m_counters.droppedUnsupported);
    }

    // The node's unit clock in the packet's own unit (spec section 4).
    const uint8_t unitCode = raw.size() >= 8 ? ((raw[TcrhHeader::OFF_FLAGS] >> 4) & 3) : 0;
    const uint32_t nowU = tcrh::NodeClockU(Simulator::Now(), m_t0GpsNs, unitCode);
    ev.nowU = nowU;

    // greedy needs somewhere to send the packet; without a fallback the node
    // keeps to the SID list (continue) and counts it
    const bool greedyWithoutFallback = m_policy == tcrh::Policy::GREEDY && m_fallback.IsNull();
    const tcrh::Policy policy = greedyWithoutFallback ? tcrh::Policy::CONTINUE : m_policy;

    // Spec section 6 steps 1-5: the golden-tested pure function.
    const tcrh::ProcessResult r = tcrh::ProcessAtNode(raw, nowU, policy);
    ev.late = r.late;
    ev.hopIndex = r.hopIndex;
    ev.deadlineU = r.deadlineU;
    ev.nextSid = r.nextSid;
    ev.reason = r.reason;
    if (r.late)
    {
        m_counters.late++;
    }
    if (r.outBytes.has_value())
    {
        FillTcrhOut(ev, *r.outBytes);
    }
    const uint32_t rhBytes = static_cast<uint32_t>(raw.size());

    // Hand a packet in fallback mode (GREEDY, SL 0) to the fallback function.
    auto handToFallback = [&](const std::vector<uint8_t>& bytes, uint32_t targetSid) {
        if (ipv6Header.GetHopLimit() <= 1)
        {
            if (SendTimeExceeded(node, packet, ipv6Header, offset, rhBytes))
            {
                m_counters.icmpSent++;
            }
            return discard("drop_hop_limit",
                           Ipv6L3Protocol::DROP_TTL_EXPIRED,
                           m_counters.droppedHopLimit);
        }
        Ptr<Packet> out = WithRoutingHeader(packet, rhBytes, TcrhFromBytes(bytes));
        Ipv6Header h = ipv6Header;
        h.SetDestination(tcrh::SidAddress(targetSid)); // spec 6 step 4: SID[0]'s address
        h.SetHopLimit(ipv6Header.GetHopLimit() - 1);
        h.SetNextHeader(Ipv6Header::IPV6_EXT_ROUTING);
        h.SetPayloadLength(out->GetSize());
        ev.dstOut = h.GetDestination();
        if (!m_fallback(out, h, targetSid))
        {
            return discard("drop_fallback_refused",
                           Ipv6L3Protocol::DROP_NO_ROUTE,
                           m_counters.droppedFallbackRefused);
        }
        m_counters.fallback++;
        ev.action = "fallback";
        m_hopTrace(ev);
        stopProcessing = true; // the fallback owns the packet now
        isDropped = false;
        return static_cast<uint8_t>(0);
    };

    switch (r.action)
    {
    case tcrh::Action::DROP_MALFORMED:
        if (r.icmpCode.has_value())
        {
            // Pointer = IPv6 header + routing header offset + field offset
            const uint32_t pointer = IPV6_HEADER_BYTES + offset + *r.icmpPointer;
            if (SendParameterProblem(node, packet, ipv6Header, offset, rhBytes, *r.icmpCode, pointer))
            {
                m_counters.icmpSent++;
            }
        }
        return discard("drop_malformed",
                       Ipv6L3Protocol::DROP_MALFORMED_HEADER,
                       m_counters.droppedMalformed);

    case tcrh::Action::DROP_LATE:
        // policy "drop": a deliberate discard; ns-3 has no closer drop reason.
        // The packet never leaves, but the trace still reports what step 2
        // decided: DEV, and Dev Hop = this node if the miss was found here.
        ev.flagsOut = ev.flagsIn | TcrhHeader::FLAG_DEV;
        if (r.late)
        {
            ev.devHop = *r.hopIndex;
        }
        return discard("drop_late", Ipv6L3Protocol::DROP_ROUTE_ERROR, m_counters.droppedLate);

    case tcrh::Action::IGNORE:
    case tcrh::Action::DELIVER: {
        // Step 3 (or RFC 8200 4.4 for a type we were wrongly handed with SL 0):
        // step over the header and let LocalDeliver process the Next Header.
        const uint32_t total =
            r.action == tcrh::Action::IGNORE ? (static_cast<uint32_t>(raw[1]) + 1) * 8 : rhBytes;
        if (total > packet->GetSize() - offset)
        {
            ev.reason = "truncated";
            return discard("drop_malformed",
                           Ipv6L3Protocol::DROP_MALFORMED_HEADER,
                           m_counters.droppedMalformed);
        }
        if (offset + total > NS3_MAX_EXTENSION_OFFSET)
        {
            // Process() returns the length as uint8_t (ns-3.44 API)
            ev.reason = "header_longer_than_ns3_offset";
            return discard("drop_unsupported",
                           Ipv6L3Protocol::DROP_MALFORMED_HEADER,
                           m_counters.droppedUnsupported);
        }
        if (r.action == tcrh::Action::DELIVER)
        {
            // keep the header as delivered (DEV / Dev Hop if this node was late)
            packet = WithRoutingHeader(packet, rhBytes, TcrhFromBytes(*r.outBytes));
            m_counters.delivered++;
            ev.action = "deliver";
        }
        else
        {
            m_counters.ignored++;
            ev.action = "ignore";
        }
        m_hopTrace(ev);
        isDropped = false; // stopProcessing stays false: on to the Next Header
        return static_cast<uint8_t>(total);
    }

    case tcrh::Action::FALLBACK:
        // policy greedy with a fallback installed (step 4)
        return handToFallback(*r.outBytes, *r.nextSid);

    case tcrh::Action::FORWARD: {
        if (greedyWithoutFallback && (ev.flagsOut & TcrhHeader::FLAG_DEV) != 0)
        {
            m_counters.greedyNoFallback++;
            ev.reason = "greedy_no_fallback";
            if (!m_warnedGreedyNoFallback)
            {
                // Once per node, always printed (not an NS_LOG that is off by
                // default): a "greedy" run without a fallback is really a
                // "continue" run, and nobody should report it as greedy.
                m_warnedGreedyNoFallback = true;
                std::clog << "WARNING: T-CRH node " << node->GetId()
                          << ": policy greedy but no fallback function installed; late packets "
                             "keep following their SID list (behaves as policy continue). "
                             "Counted in TcrhCounters::greedyNoFallback.\n";
            }
        }
        // Step 6: CRH-FIB lookup of the SID just decremented onto.
        Ptr<CrhFib> fib = node->GetObject<CrhFib>();
        const std::optional<CrhFib::Entry> entry =
            fib ? fib->Lookup(*r.nextSid) : std::optional<CrhFib::Entry>();
        if (!entry.has_value())
        {
            // RFC 9631 section 5: Parameter Problem, Code 0, pointing at the
            // current SID, i.e. entry SID[SL] after the decrement.
            const uint32_t sidOffset =
                TcrhHeader::OFF_ENTRIES + TcrhHeader::ENTRY_BYTES * ev.slOut;
            if (SendParameterProblem(node,
                                     packet,
                                     ipv6Header,
                                     offset,
                                     rhBytes,
                                     Icmpv6Header::ICMPV6_MALFORMED_HEADER,
                                     IPV6_HEADER_BYTES + offset + sidOffset))
            {
                m_counters.icmpSent++;
            }
            ev.reason = "sid_not_in_fib";
            return discard("drop_no_fib", Ipv6L3Protocol::DROP_NO_ROUTE, m_counters.droppedNoFib);
        }
        // Step 7: the entry exists but its link is down.
        if (!LinkUp(ipv6, entry->interface))
        {
            if ((ev.flagsOut & TcrhHeader::FLAG_GREEDY) != 0)
            {
                // Only a forged packet follows its SID list with GREEDY already
                // set (a fallback packet has SL 0). Step 7 is defined for packets
                // not yet in fallback mode, so just lose this one.
                ev.reason = "link_down";
                return discard("drop_link_down",
                               Ipv6L3Protocol::DROP_INTERFACE_DOWN,
                               m_counters.droppedLinkDown);
            }
            const tcrh::ProcessResult ld = tcrh::LinkDownFallback(*r.outBytes);
            FillTcrhOut(ev, *ld.outBytes);
            ev.nextSid = ld.nextSid;
            ev.reason = "link_down";
            if (m_fallback.IsNull())
            {
                // "A node without a fallback function discards the packet."
                return discard("drop_link_down",
                               Ipv6L3Protocol::DROP_INTERFACE_DOWN,
                               m_counters.droppedLinkDown);
            }
            return handToFallback(*ld.outBytes, *ld.nextSid);
        }
        // Forward: Hop Limit first (RFC 8200: discard if it would reach 0).
        if (ipv6Header.GetHopLimit() <= 1)
        {
            if (SendTimeExceeded(node, packet, ipv6Header, offset, rhBytes))
            {
                m_counters.icmpSent++;
            }
            return discard("drop_hop_limit",
                           Ipv6L3Protocol::DROP_TTL_EXPIRED,
                           m_counters.droppedHopLimit);
        }
        Ptr<Packet> out = WithRoutingHeader(packet, rhBytes, TcrhFromBytes(*r.outBytes));
        ev.dstOut = entry->sidAddress;
        ev.action = "forward";
        m_counters.forwarded++;
        m_hopTrace(ev);
        tcrh::SendSegment(ipv6,
                          out,
                          ipv6Header.GetSource(),
                          entry->sidAddress,
                          ipv6Header.GetHopLimit() - 1,
                          ipv6Header.GetTrafficClass(),
                          entry->interface,
                          entry->nextHop);
        // the packet has left: never hand its payload to UDP/TCP here
        stopProcessing = true;
        isDropped = false;
        return static_cast<uint8_t>(0);
    }
    }
    NS_ABORT_MSG("unhandled T-CRH action " << tcrh::ActionName(r.action));
    return 0;
}

// ============================================================ Ipv6ExtensionCrh

NS_OBJECT_ENSURE_REGISTERED(Ipv6ExtensionCrh);

TypeId
Ipv6ExtensionCrh::GetTypeId()
{
    static TypeId tid =
        TypeId("ns3::Ipv6ExtensionCrh")
            .SetParent<Ipv6ExtensionRouting>()
            .SetGroupName("Chronoroute")
            .AddTraceSource("Hop",
                            "A CRH packet was processed at this node (one TcrhHopEvent).",
                            MakeTraceSourceAccessor(&Ipv6ExtensionCrh::m_hopTrace),
                            "ns3::Ipv6ExtensionTcrh::HopTracedCallback");
    return tid;
}

Ipv6ExtensionCrh::Ipv6ExtensionCrh(uint8_t routingType)
    : m_routingType(routingType)
{
    NS_ABORT_MSG_UNLESS(routingType == CrhHeader::ROUTING_TYPE_CRH16 ||
                            routingType == CrhHeader::ROUTING_TYPE_CRH32,
                        "CRH routing type must be 5 or 6");
}

Ipv6ExtensionCrh::~Ipv6ExtensionCrh()
{
}

uint8_t
Ipv6ExtensionCrh::GetTypeRouting() const
{
    return m_routingType;
}

Ipv6ExtensionRoutingHeader*
Ipv6ExtensionCrh::GetExtensionRoutingHeaderPtr()
{
    auto h = new CrhHeader();
    h->SetTypeRouting(m_routingType);
    return h;
}

const TcrhCounters&
Ipv6ExtensionCrh::GetCounters() const
{
    return m_counters;
}

uint8_t
Ipv6ExtensionCrh::Process(Ptr<Packet>& packet,
                          uint8_t offset,
                          const Ipv6Header& ipv6Header,
                          Ipv6Address dst,
                          uint8_t* nextHeader,
                          bool& stopProcessing,
                          bool& isDropped,
                          Ipv6L3Protocol::DropReason& dropReason)
{
    NS_LOG_FUNCTION(this << packet << +offset << ipv6Header << dst);
    Ptr<Node> node = GetNode();
    Ptr<Ipv6L3Protocol> ipv6 = node->GetObject<Ipv6L3Protocol>();
    m_counters.processed++;

    TcrhHopEvent ev = NewEvent(node, packet, ipv6Header, m_routingType);
    const std::vector<uint8_t> raw = CopyRoutingHeader(packet, offset);
    if (raw.size() >= 4)
    {
        ev.nextHeader = raw[0];
        ev.slIn = raw[CrhHeader::OFF_SEGMENTS_LEFT];
        ev.slOut = ev.slIn;
    }
    if (nextHeader != nullptr && !raw.empty())
    {
        *nextHeader = raw[0];
    }

    auto discard = [&](const char* action, Ipv6L3Protocol::DropReason why, uint64_t& counter) {
        counter++;
        ev.action = action;
        m_hopTrace(ev);
        isDropped = true;
        stopProcessing = true;
        dropReason = why;
        return static_cast<uint8_t>(0);
    };

    if (offset != 0)
    {
        ev.reason = "routing_header_not_first";
        return discard("drop_unsupported",
                       Ipv6L3Protocol::DROP_MALFORMED_HEADER,
                       m_counters.droppedUnsupported);
    }

    // RFC 9631 section 5, golden-tested
    const CrhProcessResult r = CrhProcessAtNode(raw.data(), static_cast<uint32_t>(raw.size()));
    const uint32_t rhBytes = static_cast<uint32_t>(raw.size());
    ev.reason = r.reason;
    ev.nextSid = r.nextSid;
    if (r.outBytes.has_value())
    {
        ev.slOut = (*r.outBytes)[CrhHeader::OFF_SEGMENTS_LEFT];
    }
    if (raw.size() >= 8 && (raw[2] == CrhHeader::ROUTING_TYPE_CRH16 ||
                            raw[2] == CrhHeader::ROUTING_TYPE_CRH32))
    {
        ev.numHops = static_cast<uint8_t>(std::min<uint32_t>(
            255,
            (rhBytes - CrhHeader::FIXED_BYTES) / CrhHeader::SidBytes(raw[2])));
    }

    if (r.action == "drop_malformed")
    {
        if (r.icmpCode.has_value())
        {
            if (SendParameterProblem(node,
                                     packet,
                                     ipv6Header,
                                     offset,
                                     rhBytes,
                                     *r.icmpCode,
                                     IPV6_HEADER_BYTES + offset + *r.icmpPointer))
            {
                m_counters.icmpSent++;
            }
        }
        return discard("drop_malformed",
                       Ipv6L3Protocol::DROP_MALFORMED_HEADER,
                       m_counters.droppedMalformed);
    }
    if (r.action == "deliver" || r.action == "ignore")
    {
        const uint32_t total =
            r.action == "ignore" ? (static_cast<uint32_t>(raw[1]) + 1) * 8 : rhBytes;
        if (total > packet->GetSize() - offset)
        {
            ev.reason = "truncated";
            return discard("drop_malformed",
                           Ipv6L3Protocol::DROP_MALFORMED_HEADER,
                           m_counters.droppedMalformed);
        }
        if (offset + total > NS3_MAX_EXTENSION_OFFSET)
        {
            ev.reason = "header_longer_than_ns3_offset";
            return discard("drop_unsupported",
                           Ipv6L3Protocol::DROP_MALFORMED_HEADER,
                           m_counters.droppedUnsupported);
        }
        if (r.action == "deliver")
        {
            m_counters.delivered++;
            ev.action = "deliver";
        }
        else
        {
            m_counters.ignored++;
            ev.action = "ignore";
        }
        m_hopTrace(ev);
        isDropped = false;
        return static_cast<uint8_t>(total);
    }
    NS_ABORT_MSG_UNLESS(r.action == "forward", "unhandled CRH action " << r.action);

    Ptr<CrhFib> fib = node->GetObject<CrhFib>();
    const std::optional<CrhFib::Entry> entry =
        fib ? fib->Lookup(*r.nextSid) : std::optional<CrhFib::Entry>();
    if (!entry.has_value())
    {
        // RFC 9631 section 5: Code 0, pointing at the current SID
        const uint32_t sidOffset = CrhHeader::FIXED_BYTES + CrhHeader::SidBytes(raw[2]) * ev.slOut;
        if (SendParameterProblem(node,
                                 packet,
                                 ipv6Header,
                                 offset,
                                 rhBytes,
                                 Icmpv6Header::ICMPV6_MALFORMED_HEADER,
                                 IPV6_HEADER_BYTES + offset + sidOffset))
        {
            m_counters.icmpSent++;
        }
        ev.reason = "sid_not_in_fib";
        return discard("drop_no_fib", Ipv6L3Protocol::DROP_NO_ROUTE, m_counters.droppedNoFib);
    }
    if (!LinkUp(ipv6, entry->interface))
    {
        // CRH has no flags to record a deviation: the baseline just loses it
        ev.reason = "link_down";
        return discard("drop_link_down",
                       Ipv6L3Protocol::DROP_INTERFACE_DOWN,
                       m_counters.droppedLinkDown);
    }
    if (ipv6Header.GetHopLimit() <= 1)
    {
        if (SendTimeExceeded(node, packet, ipv6Header, offset, rhBytes))
        {
            m_counters.icmpSent++;
        }
        return discard("drop_hop_limit",
                       Ipv6L3Protocol::DROP_TTL_EXPIRED,
                       m_counters.droppedHopLimit);
    }
    Ptr<Packet> out = WithRoutingHeader(packet, rhBytes, CrhFromBytes(*r.outBytes));
    ev.dstOut = entry->sidAddress;
    ev.action = "forward";
    m_counters.forwarded++;
    m_hopTrace(ev);
    tcrh::SendSegment(ipv6,
                      out,
                      ipv6Header.GetSource(),
                      entry->sidAddress,
                      ipv6Header.GetHopLimit() - 1,
                      ipv6Header.GetTrafficClass(),
                      entry->interface,
                      entry->nextHop);
    stopProcessing = true;
    isDropped = false;
    return static_cast<uint8_t>(0);
}

NS_OBJECT_ENSURE_REGISTERED(Ipv6ExtensionCrh16);

TypeId
Ipv6ExtensionCrh16::GetTypeId()
{
    static TypeId tid = TypeId("ns3::Ipv6ExtensionCrh16")
                            .SetParent<Ipv6ExtensionCrh>()
                            .SetGroupName("Chronoroute")
                            .AddConstructor<Ipv6ExtensionCrh16>();
    return tid;
}

Ipv6ExtensionCrh16::Ipv6ExtensionCrh16()
    : Ipv6ExtensionCrh(CrhHeader::ROUTING_TYPE_CRH16)
{
}

NS_OBJECT_ENSURE_REGISTERED(Ipv6ExtensionCrh32);

TypeId
Ipv6ExtensionCrh32::GetTypeId()
{
    static TypeId tid = TypeId("ns3::Ipv6ExtensionCrh32")
                            .SetParent<Ipv6ExtensionCrh>()
                            .SetGroupName("Chronoroute")
                            .AddConstructor<Ipv6ExtensionCrh32>();
    return tid;
}

Ipv6ExtensionCrh32::Ipv6ExtensionCrh32()
    : Ipv6ExtensionCrh(CrhHeader::ROUTING_TYPE_CRH32)
{
}

} // namespace ns3
