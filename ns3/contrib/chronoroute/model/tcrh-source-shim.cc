/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#include "tcrh-source-shim.h"

#include "crh-fib.h"
#include "crh-header.h"
#include "tcrh-address-plan.h"
#include "tcrh-header.h"
#include "tcrh-process.h"

#include "ns3/abort.h"
#include "ns3/ipv6-l3-protocol.h"
#include "ns3/ipv6-route.h"
#include "ns3/log.h"
#include "ns3/simulator.h"
#include "ns3/socket.h"
#include "ns3/tcp-l4-protocol.h"
#include "ns3/udp-l4-protocol.h"
#include "ns3/uinteger.h"

namespace ns3
{

NS_LOG_COMPONENT_DEFINE("TcrhSourceShim");

NS_OBJECT_ENSURE_REGISTERED(TcrhSourceShim);

namespace
{

/// IPv6 fixed header size.
constexpr uint32_t IPV6_HEADER_BYTES = 40;

/// Destination port of a UDP or TCP packet (both keep it in bytes 2-3 of their
/// header), 0 for anything else.
uint16_t
DestinationPort(Ptr<const Packet> p, uint8_t protocol)
{
    if ((protocol != UdpL4Protocol::PROT_NUMBER && protocol != TcpL4Protocol::PROT_NUMBER) ||
        p->GetSize() < 4)
    {
        return 0;
    }
    uint8_t b[4];
    p->CopyData(b, 4);
    return static_cast<uint16_t>((b[2] << 8) | b[3]);
}

} // namespace

TypeId
TcrhSourceShim::GetTypeId()
{
    static TypeId tid =
        TypeId("ns3::TcrhSourceShim")
            .SetParent<Object>()
            .SetGroupName("Chronoroute")
            .AddConstructor<TcrhSourceShim>()
            .AddAttribute("T0GpsNs",
                          "GPS time, in integer ns since the GPS epoch, of simulation time 0. "
                          "Epoch_Base = ceil((T0GpsNs + now) / u) mod 2^32 per packet.",
                          UintegerValue(0),
                          MakeUintegerAccessor(&TcrhSourceShim::m_t0GpsNs),
                          MakeUintegerChecker<uint64_t>())
            .AddTraceSource("Ingress",
                            "A packet left (or failed to leave) this host with a routing header.",
                            MakeTraceSourceAccessor(&TcrhSourceShim::m_ingressTrace),
                            "ns3::Ipv6ExtensionTcrh::HopTracedCallback");
    return tid;
}

TcrhSourceShim::TcrhSourceShim()
    : m_t0GpsNs(0)
{
}

TcrhSourceShim::~TcrhSourceShim()
{
}

void
TcrhSourceShim::DoDispose()
{
    m_fallback = MakeNullCallback<bool, Ptr<Packet>, const Ipv6Header&, uint32_t>();
    m_udpDown = MakeNullCallback<void, Ptr<Packet>, Ipv6Address, Ipv6Address, uint8_t, Ptr<Ipv6Route>>();
    m_tcpDown = MakeNullCallback<void, Ptr<Packet>, Ipv6Address, Ipv6Address, uint8_t, Ptr<Ipv6Route>>();
    m_node = nullptr;
    Object::DoDispose();
}

void
TcrhSourceShim::Install(Ptr<Node> node)
{
    NS_LOG_FUNCTION(this << node);
    NS_ABORT_MSG_IF(m_node, "TcrhSourceShim::Install called twice");
    NS_ABORT_MSG_UNLESS(node->GetObject<Ipv6L3Protocol>(),
                        "install the IPv6 stack (InternetStackHelper) before the T-CRH shim");
    NS_ABORT_MSG_IF(node->GetObject<TcrhSourceShim>(), "node " << node->GetId() << " already has a shim");
    m_node = node;
    // The callbacks hold a plain pointer to the shim; the shim is aggregated to
    // the node below, so it lives exactly as long as the node's UDP and TCP.
    Ptr<UdpL4Protocol> udp = node->GetObject<UdpL4Protocol>();
    if (udp)
    {
        m_udpDown = udp->GetDownTarget6();
        NS_ABORT_MSG_IF(m_udpDown.IsNull(), "UDP has no IPv6 down target");
        udp->SetDownTarget6(MakeCallback(&TcrhSourceShim::SendUdp, this));
    }
    Ptr<TcpL4Protocol> tcp = node->GetObject<TcpL4Protocol>();
    if (tcp)
    {
        m_tcpDown = tcp->GetDownTarget6();
        NS_ABORT_MSG_IF(m_tcpDown.IsNull(), "TCP has no IPv6 down target");
        tcp->SetDownTarget6(MakeCallback(&TcrhSourceShim::SendTcp, this));
    }
    NS_ABORT_MSG_UNLESS(udp || tcp, "node " << node->GetId() << " has neither UDP nor TCP");
    node->AggregateObject(this);
}

void
TcrhSourceShim::StoreRoute(Ipv6Address finalDst, uint16_t port, const Route& route)
{
    NS_ABORT_MSG_IF(route.sidsFwd.empty(), "a source route needs at least one SID");
    uint32_t last = route.sidsFwd.back();
    NS_ABORT_MSG_UNLESS(tcrh::SidAddress(last) == finalDst,
                        "the last SID (" << last << ", address " << tcrh::SidAddress(last)
                                         << ") must be the transport destination " << finalDst
                                         << ": UDP/TCP checksum the final destination");
    m_routes[{finalDst, port}] = route;
}

void
TcrhSourceShim::AddRoute(Ipv6Address finalDst,
                         uint16_t dstPort,
                         const std::vector<uint16_t>& sidsFwd,
                         const std::vector<uint64_t>& cumulativeBudgetsNs,
                         uint8_t unitCode)
{
    NS_ABORT_MSG_UNLESS(sidsFwd.size() == cumulativeBudgetsNs.size(),
                        "every hop needs exactly one cumulative budget");
    NS_ABORT_MSG_UNLESS(tcrh::IsValidUnitCode(unitCode), "unit code must be 0..3");
    NS_ABORT_MSG_IF(sidsFwd.empty() ||
                        TcrhHeader::SizeForHops(sidsFwd.size()) > MAX_HEADER_BYTES,
                    "a T-CRH path through ns-3.44 has 1..78 hops (header <= "
                        << MAX_HEADER_BYTES << " bytes), got " << sidsFwd.size());
    for (size_t i = 1; i < cumulativeBudgetsNs.size(); ++i)
    {
        NS_ABORT_MSG_IF(cumulativeBudgetsNs[i] < cumulativeBudgetsNs[i - 1],
                        "cumulative budgets must not decrease (spec 5.1)");
    }
    Route r;
    r.kind = Kind::TCRH;
    r.sidsFwd = sidsFwd;
    r.cumulativeBudgetsNs = cumulativeBudgetsNs;
    r.unitCode = unitCode;
    StoreRoute(finalDst, dstPort, r);
}

void
TcrhSourceShim::AddCrh16Route(Ipv6Address finalDst, uint16_t dstPort, const std::vector<uint16_t>& sidsFwd)
{
    NS_ABORT_MSG_IF(sidsFwd.empty() ||
                        CrhHeader::SizeForSids(sidsFwd.size(), CrhHeader::ROUTING_TYPE_CRH16) >
                            MAX_HEADER_BYTES,
                    "a CRH-16 path through ns-3.44 has 1..122 SIDs, got " << sidsFwd.size());
    Route r;
    r.kind = Kind::CRH16;
    r.sidsFwd = sidsFwd;
    StoreRoute(finalDst, dstPort, r);
}

bool
TcrhSourceShim::RemoveRoute(Ipv6Address finalDst, uint16_t dstPort)
{
    return m_routes.erase({finalDst, dstPort}) > 0;
}

void
TcrhSourceShim::SetFallback(Ipv6ExtensionTcrh::FallbackCallback cb)
{
    m_fallback = cb;
}

void
TcrhSourceShim::SetT0GpsNs(uint64_t t0GpsNs)
{
    m_t0GpsNs = t0GpsNs;
}

uint64_t
TcrhSourceShim::GetT0GpsNs() const
{
    return m_t0GpsNs;
}

const TcrhCounters&
TcrhSourceShim::GetCounters() const
{
    return m_counters;
}

const TcrhSourceShim::Route*
TcrhSourceShim::FindRoute(Ipv6Address dst, uint16_t port) const
{
    auto it = m_routes.find({dst, port});
    if (it == m_routes.end())
    {
        it = m_routes.find({dst, 0});
    }
    return it == m_routes.end() ? nullptr : &it->second;
}

void
TcrhSourceShim::SendUdp(Ptr<Packet> p, Ipv6Address src, Ipv6Address dst, uint8_t protocol, Ptr<Ipv6Route> route)
{
    Send(m_udpDown, p, src, dst, protocol, route);
}

void
TcrhSourceShim::SendTcp(Ptr<Packet> p, Ipv6Address src, Ipv6Address dst, uint8_t protocol, Ptr<Ipv6Route> route)
{
    Send(m_tcpDown, p, src, dst, protocol, route);
}

void
TcrhSourceShim::Send(const IpL4Protocol::DownTargetCallback6& down,
                     Ptr<Packet> p,
                     Ipv6Address src,
                     Ipv6Address dst,
                     uint8_t protocol,
                     Ptr<Ipv6Route> route)
{
    const Route* rt = FindRoute(dst, DestinationPort(p, protocol));
    if (rt == nullptr)
    {
        down(p, src, dst, protocol, route); // no source route: ordinary IPv6
        return;
    }
    NS_LOG_FUNCTION(this << p << src << dst << +protocol);
    m_counters.processed++;
    Ptr<Ipv6L3Protocol> ipv6 = m_node->GetObject<Ipv6L3Protocol>();
    Ptr<CrhFib> fib = m_node->GetObject<CrhFib>();

    TcrhHopEvent ev;
    ev.tNs = Simulator::Now().GetNanoSeconds();
    ev.nodeId = m_node->GetId();
    if (fib)
    {
        ev.nodeSid = fib->GetLocalSid();
    }
    ev.packetUid = p->GetUid();
    ev.nextHeader = protocol;
    ev.src = src;
    ev.dstIn = dst;
    ev.numHops = static_cast<uint8_t>(rt->sidsFwd.size());
    ev.slIn = ev.numHops;
    ev.hopIndex = 0;

    std::vector<uint8_t> bytes; // the routing header as it leaves the ingress
    uint32_t firstSid = 0;
    if (rt->kind == Kind::TCRH)
    {
        ev.routingType = TcrhHeader::ROUTING_TYPE;
        // Epoch_Base stamped NOW, for this packet (spec section 4)
        const uint64_t tIngressGpsNs = tcrh::SimToGpsNs(m_t0GpsNs, Simulator::Now());
        const TcrhHeader built = TcrhHeader::Build(rt->sidsFwd,
                                                   rt->cumulativeBudgetsNs,
                                                   tIngressGpsNs,
                                                   rt->unitCode,
                                                   protocol);
        // the ingress's own steps 5-6 (no deadline check), golden-tested
        const tcrh::IngressResult ing = tcrh::IngressSend(built.ToBytes());
        NS_ABORT_MSG_UNLESS(ing.ok, "ingress step failed on a header we just built: " << ing.error);
        bytes = ing.outBytes;
        firstSid = ing.firstSid;
        ev.flagsIn = built.GetFlags();
        ev.flagsOut = built.GetFlags();
        ev.epochBase = built.GetEpochBase();
        ev.nowU = tcrh::ClockU(tIngressGpsNs, rt->unitCode);
    }
    else
    {
        ev.routingType = CrhHeader::ROUTING_TYPE_CRH16;
        CrhHeader built;
        built.SetNextHeader(protocol);
        built.SetPath(std::vector<uint32_t>(rt->sidsFwd.begin(), rt->sidsFwd.end()),
                      CrhHeader::ROUTING_TYPE_CRH16);
        // RFC 9631 Appendix A.1: the source runs segment processing itself
        const std::vector<uint8_t> fresh = built.ToBytes();
        const CrhProcessResult cr = CrhProcessAtNode(fresh.data(), static_cast<uint32_t>(fresh.size()));
        NS_ABORT_MSG_UNLESS(cr.action == "forward", "CRH ingress step failed: " << cr.action);
        bytes = *cr.outBytes;
        firstSid = *cr.nextSid;
    }
    ev.slOut = bytes[TcrhHeader::OFF_SEGMENTS_LEFT];
    ev.nextSid = firstSid;

    auto fail = [&](const char* action, const char* reason, uint64_t& counter) {
        counter++;
        ev.action = action;
        ev.reason = reason;
        m_ingressTrace(ev);
        NS_LOG_WARN("node " << m_node->GetId() << ": T-CRH ingress " << action << " (" << reason
                            << ") for a packet to " << dst);
    };

    // Step 6 at the ingress.
    const std::optional<CrhFib::Entry> entry =
        fib ? fib->Lookup(firstSid) : std::optional<CrhFib::Entry>();
    if (!entry.has_value())
    {
        fail("drop_no_fib", "sid_not_in_fib", m_counters.droppedNoFib);
        return;
    }
    NS_ABORT_MSG_UNLESS(entry->interface < ipv6->GetNInterfaces(), "CRH-FIB names a missing interface");
    if (p->GetSize() + bytes.size() + IPV6_HEADER_BYTES > ipv6->GetMtu(entry->interface))
    {
        NS_ABORT_MSG("node " << m_node->GetId() << ": a " << p->GetSize()
                             << "-byte transport packet plus a " << bytes.size()
                             << "-byte routing header exceeds the MTU "
                             << ipv6->GetMtu(entry->interface)
                             << "; ns-3.44 cannot fragment a packet whose routing header is not "
                                "Type 0 (it asserts). Make the payload or TcpSocket::SegmentSize "
                                "smaller.");
    }

    // Step 7 at the ingress: the link to s_1 is down.
    if (!ipv6->IsUp(entry->interface) || !ipv6->GetNetDevice(entry->interface)->IsLinkUp())
    {
        if (rt->kind != Kind::TCRH)
        {
            fail("drop_link_down", "link_down", m_counters.droppedLinkDown);
            return;
        }
        // Spec 6 step 7 runs BEFORE the "no fallback function -> discard" rule:
        // the ingress sets DEV (Dev Hop 0) and GREEDY and sets SL to 0. The
        // trace reports that header even when the packet is then discarded,
        // exactly like a transit node does (Ipv6ExtensionTcrh::Process), so a
        // link-down drop looks the same wherever it happens.
        const tcrh::ProcessResult ld = tcrh::LinkDownFallback(bytes); // DEV, Dev Hop 0, GREEDY, SL 0
        ev.flagsOut = (*ld.outBytes)[TcrhHeader::OFF_FLAGS];
        ev.devHop = (*ld.outBytes)[TcrhHeader::OFF_DEV_HOP];
        ev.slOut = 0;
        ev.nextSid = ld.nextSid;
        if (m_fallback.IsNull())
        {
            // "A node without a fallback function discards the packet."
            fail("drop_link_down", "link_down", m_counters.droppedLinkDown);
            return;
        }
        TcrhHeader h;
        TcrhHeader::Parse(ld.outBytes->data(), ld.outBytes->size(), true, &h, nullptr);
        p->AddHeader(h);
        // the source originates the packet: no decrement, the socket's (or the
        // default) Hop Limit
        SocketIpv6HopLimitTag tag;
        uint8_t hopLimit = 0;
        if (p->PeekPacketTag(tag))
        {
            hopLimit = tag.GetHopLimit();
        }
        else
        {
            UintegerValue ttl;
            ipv6->GetAttribute("DefaultTtl", ttl);
            hopLimit = static_cast<uint8_t>(ttl.Get());
        }
        Ipv6Header ip;
        ip.SetSource(src);
        ip.SetDestination(tcrh::SidAddress(*ld.nextSid));
        ip.SetNextHeader(Ipv6Header::IPV6_EXT_ROUTING);
        ip.SetHopLimit(hopLimit);
        ip.SetPayloadLength(p->GetSize());
        ev.dstOut = ip.GetDestination();
        ev.reason = "link_down";
        if (!m_fallback(p, ip, *ld.nextSid))
        {
            fail("drop_fallback_refused", "link_down", m_counters.droppedFallbackRefused);
            return;
        }
        m_counters.fallback++;
        ev.action = "fallback";
        m_ingressTrace(ev);
        return;
    }

    if (rt->kind == Kind::TCRH)
    {
        TcrhHeader h;
        TcrhHeader::Parse(bytes.data(), bytes.size(), true, &h, nullptr);
        p->AddHeader(h);
    }
    else
    {
        CrhHeader h;
        CrhHeader::Parse(bytes.data(), bytes.size(), true, &h, nullptr);
        p->AddHeader(h);
    }
    ev.dstOut = entry->sidAddress;
    ev.action = "ingress";
    m_counters.ingress++;
    m_ingressTrace(ev);

    Ptr<Ipv6Route> r = Create<Ipv6Route>();
    r->SetDestination(entry->sidAddress);
    r->SetSource(src);
    r->SetGateway(entry->nextHop);
    r->SetOutputDevice(ipv6->GetNetDevice(entry->interface));
    // Next Header 43: the routing header now sits between IPv6 and UDP/TCP
    down(p, src, entry->sidAddress, Ipv6Header::IPV6_EXT_ROUTING, r);
}

} // namespace ns3
