/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

/**
 * @file
 * @ingroup chronoroute-test
 *
 * Phase P5a: T-CRH as a GENUINE IPv6 Routing Header (Type 253) inside ns-3.44's
 * IPv6 stack, tested in a real simulated network. Everything here runs real
 * ns-3 packets through real point-to-point links; nothing is called directly
 * except to inject deliberately broken packets.
 *
 * The test network (10 Mb/s, 2 ms point-to-point links, MODELLED):
 *
 *     S (0xF000) -- T1 (1) -- T2 (2) -- T3 (3) -- D (0xF001)
 *                    |
 *                    X (0x63)   plain ns-3 IPv6, NO T-CRH support
 *
 * S sends UDP probes (200-byte payload) from its SID address; its source shim
 * inserts the routing header. Link numbers: 0 S-T1, 1 T1-T2, 2 T2-T3, 3 T3-D,
 * 4 T1-X. With no queueing a 272-byte IPv6 packet (40 + 24 T-CRH + 8 UDP + 200)
 * is 274 bytes with PPP framing, 219.2 us on the wire, so each hop takes
 * exactly 2219.2 us. The budgets are 2.5 ms per hop at unit code 1 (0.1 ms),
 * which lets the tests predict every clock reading to the unit.
 */

#include "golden-vectors.h"
#include "tcrh-ipv6-test.h"

#include "ns3/boolean.h"
#include "ns3/crh-fib.h"
#include "ns3/crh-header.h"
#include "ns3/data-rate.h"
#include "ns3/global-value.h"
#include "ns3/inet6-socket-address.h"
#include "ns3/internet-stack-helper.h"
#include "ns3/ipv6-extension-tcrh.h"
#include "ns3/ipv6-extension.h"
#include "ns3/ipv6-header.h"
#include "ns3/ipv6-l3-protocol.h"
#include "ns3/node-container.h"
#include "ns3/packet.h"
#include "ns3/point-to-point-helper.h"
#include "ns3/point-to-point-net-device.h"
#include "ns3/queue-disc.h"
#include "ns3/simulator.h"
#include "ns3/socket.h"
#include "ns3/string.h"
#include "ns3/tcp-socket-factory.h"
#include "ns3/tcrh-address-plan.h"
#include "ns3/tcrh-header.h"
#include "ns3/tcrh-helper.h"
#include "ns3/tcrh-process.h"
#include "ns3/tcrh-source-shim.h"
#include "ns3/tcrh-timebase.h"
#include "ns3/test.h"
#include "ns3/traffic-control-layer.h"
#include "ns3/udp-socket-factory.h"

#include <algorithm>
#include <map>
#include <string>
#include <utility>
#include <vector>

using namespace ns3;

namespace
{

// ---------------------------------------------------------------- constants

constexpr uint32_t SID_S = 0xF000;  // ground station 0 (spec section 7)
constexpr uint32_t SID_T1 = 1;
constexpr uint32_t SID_T2 = 2;
constexpr uint32_t SID_T3 = 3;
constexpr uint32_t SID_D = 0xF001;  // ground station 1
constexpr uint32_t SID_X = 0x63;    // the node without T-CRH support

constexpr uint16_t PORT_A = 9000;   // T-CRH S -> T1 -> T2 -> T3 -> D
constexpr uint16_t PORT_B = 9001;   // T-CRH S -> T1 -> X -> T2 -> T3 -> D (X cannot)
constexpr uint16_t PORT_C = 9002;   // T-CRH S -> T1 -> X, X is the final endpoint
constexpr uint16_t PORT_CRH = 9200; // CRH-16 S -> T1 -> T2 -> T3 -> D
constexpr uint16_t PORT_TCP = 9100; // TCP over T-CRH, S -> D

constexpr uint32_t PAYLOAD_BYTES = 200;
/// 2026-10-10T13:58:00 UTC as GPS ns (GPS = UTC + 18 s), the pinned snapshot time
constexpr uint64_t T0_GPS_NS = 1475675898000000000ULL;
/// unit code 1: u = 0.1 ms
constexpr uint8_t UC = 1;
constexpr uint64_t U_NS = 100000;
/// ns-3's default IPv6 Hop Limit
constexpr uint8_t DEFAULT_HOP_LIMIT = 64;

// ---------------------------------------------------------------- small helpers

std::vector<uint8_t>
FromHex(const std::string& hex)
{
    std::vector<uint8_t> out;
    for (size_t i = 0; i + 1 < hex.size(); i += 2)
    {
        out.push_back(static_cast<uint8_t>(std::stoul(hex.substr(i, 2), nullptr, 16)));
    }
    return out;
}

std::string
Hex(const std::vector<uint8_t>& bytes)
{
    static const char* digits = "0123456789abcdef";
    std::string s;
    for (uint8_t b : bytes)
    {
        s += digits[b >> 4];
        s += digits[b & 15];
    }
    return s;
}

std::vector<uint8_t>
Bytes(Ptr<const Packet> p)
{
    std::vector<uint8_t> out(p->GetSize());
    p->CopyData(out.data(), out.size());
    return out;
}

/// The spec's Epoch_Base, written out: ceil(t / u) mod 2^32 (exact integers).
uint32_t
SpecEpoch(uint64_t tGpsNs)
{
    return static_cast<uint32_t>((tGpsNs + U_NS - 1) / U_NS);
}

/// The spec's unit clock, written out: floor(t / u) mod 2^32.
uint32_t
SpecClock(uint64_t tGpsNs)
{
    return static_cast<uint32_t>(tGpsNs / U_NS);
}

/// Turn checksums on for a network test (UDP over IPv6 must carry one) and
/// back off afterwards, so other suites in the same process are unaffected.
class ChecksumScope
{
  public:
    ChecksumScope()
    {
        GlobalValue::Bind("ChecksumEnabled", BooleanValue(true));
    }

    ~ChecksumScope()
    {
        GlobalValue::Bind("ChecksumEnabled", BooleanValue(false));
    }
};

// ---------------------------------------------------------------- the test network

/// One UDP datagram received by a socket.
struct UdpRx
{
    uint32_t seq;
    int64_t tNs;
};

/// One packet with Next Header 43 seen by a node's IPv6 Rx trace.
struct Rx43
{
    uint64_t uid;
    uint8_t hopLimit;
    Ipv6Address dst;
    uint8_t routingType;
    uint8_t segmentsLeft;
    uint8_t flags;
};

/// One ICMPv6 message delivered to S.
struct IcmpRx
{
    uint8_t type;
    uint8_t code;
    uint32_t pointer;
    std::vector<uint8_t> invoking; // the invoking packet (IPv6 header first)
};

/// One call of a recording fallback function.
struct FallbackCall
{
    uint32_t nodeId;
    Ipv6Header ip;
    std::vector<uint8_t> bytes; // routing header + payload
    uint32_t targetSid;
};

class TestNet
{
  public:
    struct Options
    {
        uint64_t t0GpsNs{T0_GPS_NS};
        tcrh::Policy policy{tcrh::Policy::CONTINUE};
        bool routingTableFallback{false}; // tcrh::RoutingTableFallback on every T-CRH node
        bool recordingFallback{false};    // RecordFallback on every T-CRH node and the shim
    };

    explicit TestNet(const Options& o);

    Ptr<Node> s, t1, t2, t3, d, x;
    NodeContainer all;
    TcrhHelper helper;
    std::vector<TcrhHelper::Link> links;
    Ptr<TcrhSourceShim> shim;
    Ptr<Socket> sender;

    std::vector<TcrhHopEvent> events;
    std::map<std::pair<uint32_t, uint16_t>, std::vector<UdpRx>> udpRx;
    std::map<uint32_t, std::vector<std::pair<uint8_t, uint32_t>>> l4; // node -> (nh, size)
    std::map<uint32_t, std::vector<Rx43>> rx43;
    std::map<uint32_t, std::vector<Ipv6L3Protocol::DropReason>> drops;
    std::vector<IcmpRx> icmpAtS;
    std::vector<FallbackCall> fallbacks;
    std::map<uint64_t, uint32_t> seqOfUid;
    std::map<uint32_t, int64_t> sendNsOfSeq;

    uint64_t tcpToSend{0};
    uint64_t tcpSent{0};
    uint64_t tcpReceived{0};
    Ptr<Socket> tcpSender;
    std::vector<Ptr<Socket>> tcpAccepted;

    /// Send one probe to D (or X for PORT_C) now.
    void SendProbe(uint16_t port, uint32_t seq);
    /// Schedule @p n probes, the first at @p start.
    void ScheduleProbes(uint16_t port, Time start, Time interval, uint32_t n);
    /// Inject raw IPv6 payload bytes from S to T1 (Next Header 43).
    void InjectToT1(std::vector<uint8_t> bytes, uint8_t hopLimit);
    /// Start a TCP transfer of @p bytes from S to D at @p when.
    void StartTcp(Time when, uint64_t bytes);

    /// Events at one node (optionally only one action), in order.
    std::vector<TcrhHopEvent> At(Ptr<Node> n, const std::string& action = "") const;
    /// Datagrams received by node @p n on @p port.
    std::vector<UdpRx> Udp(Ptr<Node> n, uint16_t port) const;
    /// LocalDeliver count of Next Header @p nh at node @p n.
    uint32_t L4Count(Ptr<Node> n, uint8_t nh) const;
    /// The probe sequence number of a packet uid (or UINT32_MAX).
    uint32_t Seq(uint64_t uid) const;

    // trace sinks
    static void OnHop(TestNet* net, const TcrhHopEvent& e);
    static void OnRx(TestNet* net, uint32_t node, Ptr<const Packet> p, Ptr<Ipv6> ipv6, uint32_t i);
    static void OnLocalDeliver(TestNet* net, uint32_t node, const Ipv6Header& h, Ptr<const Packet> p, uint32_t i);
    static void OnDrop(TestNet* net,
                       uint32_t node,
                       const Ipv6Header& h,
                       Ptr<const Packet> p,
                       Ipv6L3Protocol::DropReason r,
                       Ptr<Ipv6> ipv6,
                       uint32_t i);
    static void OnRecv(TestNet* net, uint32_t node, uint16_t port, Ptr<Socket> socket);
    static bool RecordFallback(TestNet* net, uint32_t node, Ptr<Packet> p, const Ipv6Header& h, uint32_t sid);
    static void OnTcpConnected(TestNet* net, Ptr<Socket> s);
    static void OnTcpFailed(TestNet* net, Ptr<Socket> s);
    static void OnTcpSendable(TestNet* net, Ptr<Socket> s, uint32_t available);
    static void OnTcpAccept(TestNet* net, Ptr<Socket> s, const Address& from);
    static void OnTcpRecv(TestNet* net, Ptr<Socket> s);
    void TcpPump();
};

TestNet::TestNet(const Options& o)
{
    all.Create(6);
    s = all.Get(0);
    t1 = all.Get(1);
    t2 = all.Get(2);
    t3 = all.Get(3);
    d = all.Get(4);
    x = all.Get(5);

    InternetStackHelper stack;
    stack.SetIpv4StackInstall(false);
    stack.Install(all);

    helper.SetT0GpsNs(o.t0GpsNs);
    helper.SetPolicy(o.policy);
    helper.Install(s, SID_S);
    helper.Install(t1, SID_T1);
    helper.Install(t2, SID_T2);
    helper.Install(t3, SID_T3);
    helper.Install(d, SID_D);
    helper.InstallPlain(x, SID_X);

    PointToPointHelper p2p;
    p2p.SetDeviceAttribute("DataRate", StringValue("10Mbps"));
    p2p.SetChannelAttribute("Delay", StringValue("2ms"));
    links.push_back(helper.Connect(s, t1, p2p));
    links.push_back(helper.Connect(t1, t2, p2p));
    links.push_back(helper.Connect(t2, t3, p2p));
    links.push_back(helper.Connect(t3, d, p2p));
    links.push_back(helper.Connect(t1, x, p2p));
    helper.PopulateStaticRoutes();

    shim = helper.InstallSourceShim(s);
    const std::vector<uint64_t> b4 = {2500000, 5000000, 7500000, 10000000};
    const std::vector<uint64_t> b5 = {2500000, 5000000, 7500000, 10000000, 12500000};
    shim->AddRoute(tcrh::SidAddress(SID_D), PORT_A, {SID_T1, SID_T2, SID_T3, SID_D}, b4, UC);
    shim->AddRoute(tcrh::SidAddress(SID_D), PORT_B, {SID_T1, SID_X, SID_T2, SID_T3, SID_D}, b5, UC);
    shim->AddRoute(tcrh::SidAddress(SID_X), PORT_C, {SID_T1, SID_X}, {2500000, 5000000}, UC);
    shim->AddRoute(tcrh::SidAddress(SID_D), PORT_TCP, {SID_T1, SID_T2, SID_T3, SID_D}, b4, UC);
    shim->AddCrh16Route(tcrh::SidAddress(SID_D), PORT_CRH, {SID_T1, SID_T2, SID_T3, SID_D});
    shim->TraceConnectWithoutContext("Ingress", MakeBoundCallback(&TestNet::OnHop, this));

    for (uint32_t i = 0; i < all.GetN(); ++i)
    {
        Ptr<Node> n = all.Get(i);
        const uint32_t id = n->GetId();
        Ptr<Ipv6L3Protocol> ipv6 = n->GetObject<Ipv6L3Protocol>();
        ipv6->TraceConnectWithoutContext("Rx", MakeBoundCallback(&TestNet::OnRx, this, id));
        ipv6->TraceConnectWithoutContext("LocalDeliver",
                                         MakeBoundCallback(&TestNet::OnLocalDeliver, this, id));
        ipv6->TraceConnectWithoutContext("Drop", MakeBoundCallback(&TestNet::OnDrop, this, id));
        Ptr<Ipv6ExtensionTcrh> ext = TcrhHelper::GetTcrhExtension(n);
        if (ext)
        {
            ext->TraceConnectWithoutContext("Hop", MakeBoundCallback(&TestNet::OnHop, this));
            TcrhHelper::GetCrh16Extension(n)->TraceConnectWithoutContext(
                "Hop",
                MakeBoundCallback(&TestNet::OnHop, this));
            if (o.routingTableFallback)
            {
                ext->SetFallback(MakeBoundCallback(&tcrh::RoutingTableFallback, ipv6));
            }
            if (o.recordingFallback)
            {
                ext->SetFallback(MakeBoundCallback(&TestNet::RecordFallback, this, id));
            }
        }
        // a UDP socket on every probe port of every node: a transit node must
        // never deliver a T-CRH packet's payload to it
        for (uint16_t port : {PORT_A, PORT_B, PORT_C, PORT_CRH})
        {
            Ptr<Socket> sock = Socket::CreateSocket(n, UdpSocketFactory::GetTypeId());
            sock->Bind(Inet6SocketAddress(Ipv6Address::GetAny(), port));
            sock->SetRecvCallback(MakeBoundCallback(&TestNet::OnRecv, this, id, port));
        }
    }
    if (o.recordingFallback)
    {
        shim->SetFallback(MakeBoundCallback(&TestNet::RecordFallback, this, s->GetId()));
    }

    // S sends from its SID address, so the source address is fd00::f000
    sender = Socket::CreateSocket(s, UdpSocketFactory::GetTypeId());
    sender->Bind(Inet6SocketAddress(tcrh::SidAddress(SID_S), 50000));
}

void
TestNet::SendProbe(uint16_t port, uint32_t seq)
{
    std::vector<uint8_t> payload(PAYLOAD_BYTES, 0);
    payload[0] = static_cast<uint8_t>(seq >> 24);
    payload[1] = static_cast<uint8_t>(seq >> 16);
    payload[2] = static_cast<uint8_t>(seq >> 8);
    payload[3] = static_cast<uint8_t>(seq);
    Ptr<Packet> p = Create<Packet>(payload.data(), payload.size());
    seqOfUid[p->GetUid()] = seq;
    sendNsOfSeq[seq] = Simulator::Now().GetNanoSeconds();
    const uint32_t dstSid = port == PORT_C ? SID_X : SID_D;
    sender->SendTo(p, 0, Inet6SocketAddress(tcrh::SidAddress(dstSid), port));
}

void
TestNet::ScheduleProbes(uint16_t port, Time start, Time interval, uint32_t n)
{
    for (uint32_t i = 0; i < n; ++i)
    {
        Simulator::Schedule(start + interval * i, &TestNet::SendProbe, this, port, i);
    }
}

void
TestNet::InjectToT1(std::vector<uint8_t> bytes, uint8_t hopLimit)
{
    Ptr<Packet> p = Create<Packet>(bytes.data(), bytes.size());
    tcrh::SendSegment(s->GetObject<Ipv6L3Protocol>(),
                      p,
                      tcrh::SidAddress(SID_S),
                      tcrh::SidAddress(SID_T1),
                      hopLimit,
                      0,
                      links[0].ifA,
                      tcrh::LinkAddress(links[0].id, 2));
}

std::vector<TcrhHopEvent>
TestNet::At(Ptr<Node> n, const std::string& action) const
{
    std::vector<TcrhHopEvent> out;
    for (const TcrhHopEvent& e : events)
    {
        if (e.nodeId == n->GetId() && (action.empty() || action == e.action))
        {
            out.push_back(e);
        }
    }
    return out;
}

std::vector<UdpRx>
TestNet::Udp(Ptr<Node> n, uint16_t port) const
{
    auto it = udpRx.find({n->GetId(), port});
    return it == udpRx.end() ? std::vector<UdpRx>() : it->second;
}

uint32_t
TestNet::L4Count(Ptr<Node> n, uint8_t nh) const
{
    auto it = l4.find(n->GetId());
    if (it == l4.end())
    {
        return 0;
    }
    return static_cast<uint32_t>(std::count_if(it->second.begin(), it->second.end(), [nh](const auto& e) {
        return e.first == nh;
    }));
}

uint32_t
TestNet::Seq(uint64_t uid) const
{
    auto it = seqOfUid.find(uid);
    return it == seqOfUid.end() ? UINT32_MAX : it->second;
}

void
TestNet::OnHop(TestNet* net, const TcrhHopEvent& e)
{
    net->events.push_back(e);
}

void
TestNet::OnRx(TestNet* net, uint32_t node, Ptr<const Packet> p, Ptr<Ipv6>, uint32_t)
{
    Ptr<Packet> c = p->Copy();
    Ipv6Header ip;
    c->RemoveHeader(ip);
    if (ip.GetNextHeader() != Ipv6Header::IPV6_EXT_ROUTING || c->GetSize() < 8)
    {
        return;
    }
    uint8_t b[8];
    c->CopyData(b, 8);
    net->rx43[node].push_back(Rx43{p->GetUid(), ip.GetHopLimit(), ip.GetDestination(), b[2], b[3], b[4]});
}

void
TestNet::OnLocalDeliver(TestNet* net, uint32_t node, const Ipv6Header& h, Ptr<const Packet> p, uint32_t)
{
    net->l4[node].emplace_back(h.GetNextHeader(), p->GetSize());
    if (node == net->s->GetId() && h.GetNextHeader() == 58 && p->GetSize() >= 8)
    {
        std::vector<uint8_t> b = Bytes(p);
        IcmpRx m;
        m.type = b[0];
        m.code = b[1];
        m.pointer = (static_cast<uint32_t>(b[4]) << 24) | (static_cast<uint32_t>(b[5]) << 16) |
                    (static_cast<uint32_t>(b[6]) << 8) | b[7];
        m.invoking.assign(b.begin() + 8, b.end());
        net->icmpAtS.push_back(m);
    }
}

void
TestNet::OnDrop(TestNet* net,
                uint32_t node,
                const Ipv6Header&,
                Ptr<const Packet>,
                Ipv6L3Protocol::DropReason r,
                Ptr<Ipv6>,
                uint32_t)
{
    net->drops[node].push_back(r);
}

void
TestNet::OnRecv(TestNet* net, uint32_t node, uint16_t port, Ptr<Socket> socket)
{
    Address from;
    while (Ptr<Packet> p = socket->RecvFrom(from))
    {
        uint8_t b[4] = {0, 0, 0, 0};
        p->CopyData(b, 4);
        const uint32_t seq = (static_cast<uint32_t>(b[0]) << 24) | (static_cast<uint32_t>(b[1]) << 16) |
                             (static_cast<uint32_t>(b[2]) << 8) | b[3];
        net->udpRx[{node, port}].push_back(UdpRx{seq, Simulator::Now().GetNanoSeconds()});
    }
}

bool
TestNet::RecordFallback(TestNet* net, uint32_t node, Ptr<Packet> p, const Ipv6Header& h, uint32_t sid)
{
    net->fallbacks.push_back(FallbackCall{node, h, Bytes(p), sid});
    return true; // taken (and dropped here: the test only checks what it was given)
}

void
TestNet::StartTcp(Time when, uint64_t bytes)
{
    tcpToSend = bytes;
    Ptr<Socket> listener = Socket::CreateSocket(d, TcpSocketFactory::GetTypeId());
    listener->Bind(Inet6SocketAddress(Ipv6Address::GetAny(), PORT_TCP));
    listener->Listen();
    listener->SetAcceptCallback(MakeNullCallback<bool, Ptr<Socket>, const Address&>(),
                                MakeBoundCallback(&TestNet::OnTcpAccept, this));
    tcpSender = Socket::CreateSocket(s, TcpSocketFactory::GetTypeId());
    tcpSender->Bind(Inet6SocketAddress(tcrh::SidAddress(SID_S), 0));
    tcpSender->SetConnectCallback(MakeBoundCallback(&TestNet::OnTcpConnected, this),
                                  MakeBoundCallback(&TestNet::OnTcpFailed, this));
    tcpSender->SetSendCallback(MakeBoundCallback(&TestNet::OnTcpSendable, this));
    Simulator::Schedule(when, [this]() {
        tcpSender->Connect(Inet6SocketAddress(tcrh::SidAddress(SID_D), PORT_TCP));
    });
}

void
TestNet::TcpPump()
{
    while (tcpSent < tcpToSend && tcpSender->GetTxAvailable() > 0)
    {
        const uint32_t n = static_cast<uint32_t>(
            std::min<uint64_t>(tcpToSend - tcpSent, tcpSender->GetTxAvailable()));
        const int sent = tcpSender->Send(Create<Packet>(n));
        if (sent <= 0)
        {
            break;
        }
        tcpSent += sent;
    }
}

void
TestNet::OnTcpConnected(TestNet* net, Ptr<Socket>)
{
    net->TcpPump();
}

void
TestNet::OnTcpFailed(TestNet*, Ptr<Socket>)
{
}

void
TestNet::OnTcpSendable(TestNet* net, Ptr<Socket>, uint32_t)
{
    net->TcpPump();
}

void
TestNet::OnTcpAccept(TestNet* net, Ptr<Socket> s, const Address&)
{
    net->tcpAccepted.push_back(s);
    s->SetRecvCallback(MakeBoundCallback(&TestNet::OnTcpRecv, net));
}

void
TestNet::OnTcpRecv(TestNet* net, Ptr<Socket> s)
{
    while (Ptr<Packet> p = s->Recv())
    {
        net->tcpReceived += p->GetSize();
    }
}

// ============================================================================
//  1. The headers are real ns-3 IPv6 routing headers
// ============================================================================

/**
 * @ingroup chronoroute-test
 * TcrhHeader and CrhHeader derive from Ipv6ExtensionRoutingHeader, the
 * extensions are registered in a node's Ipv6ExtensionRoutingDemux, and ns-3's
 * own base-class accessors read every golden vector correctly through the
 * header object the demux hands out (what ns-3's fragmentation code uses).
 */
class TcrhRoutingHeaderClassTestCase : public TestCase
{
  public:
    TcrhRoutingHeaderClassTestCase()
        : TestCase("P5a: T-CRH and CRH are Ipv6ExtensionRoutingHeader objects in the routing demux")
    {
    }

  private:
    void DoRun() override
    {
        Ptr<Node> node = CreateObject<Node>();
        InternetStackHelper stack;
        stack.SetIpv4StackInstall(false);
        stack.Install(node);
        TcrhHelper helper;
        Ptr<Ipv6ExtensionTcrh> ext = helper.Install(node, 7);
        Ptr<Ipv6ExtensionRoutingDemux> demux = node->GetObject<Ipv6ExtensionRoutingDemux>();

        NS_TEST_ASSERT_MSG_EQ((demux->GetExtensionRouting(253) == ext), true, "type 253 registered");
        NS_TEST_EXPECT_MSG_EQ(+ext->GetTypeRouting(), 253, "GetTypeRouting() == 253");
        NS_TEST_EXPECT_MSG_EQ(+demux->GetExtensionRouting(5)->GetTypeRouting(), 5, "CRH-16 registered");
        NS_TEST_EXPECT_MSG_EQ(+demux->GetExtensionRouting(6)->GetTypeRouting(), 6, "CRH-32 registered");
        NS_TEST_EXPECT_MSG_EQ(static_cast<bool>(demux->GetExtensionRouting(0)), true, "ns-3's own Type 0 kept");
        NS_TEST_EXPECT_MSG_EQ(node->GetObject<CrhFib>()->GetLocalSid().value_or(0), 7U, "local SID");

        // every T-CRH golden vector through the header object the demux makes
        for (size_t n = 0; n < kTcrhEncodeVectorsCount; ++n)
        {
            const TcrhEncodeVector& v = kTcrhEncodeVectors[n];
            const std::string tag = std::string(v.name) + ": ";
            Ipv6ExtensionRoutingHeader* base = demux->GetExtensionRoutingHeaderPtr(253);
            NS_TEST_ASSERT_MSG_EQ((base != nullptr), true, "demux makes a header for type 253");
            NS_TEST_EXPECT_MSG_EQ((dynamic_cast<TcrhHeader*>(base) != nullptr), true, tag + "it is a TcrhHeader");
            std::vector<uint8_t> wire = FromHex(v.expectHex);
            const uint32_t size = wire.size();
            wire.insert(wire.end(), {0xDE, 0xAD, 0xBE, 0xEF, 0x01});
            Ptr<Packet> p = Create<Packet>(wire.data(), wire.size());
            NS_TEST_EXPECT_MSG_EQ(p->RemoveHeader(*base), size, tag + "RemoveHeader via the base");
            NS_TEST_EXPECT_MSG_EQ(p->GetSize(), 5U, tag + "payload left");
            // ns-3's NON-virtual base accessors must see the same values
            NS_TEST_EXPECT_MSG_EQ(+base->GetNextHeader(), v.nextHeader, tag + "base Next Header");
            NS_TEST_EXPECT_MSG_EQ(base->GetLength(), v.expectSize, tag + "base GetLength() bytes");
            NS_TEST_EXPECT_MSG_EQ(+base->GetTypeRouting(), 253, tag + "base Routing Type");
            NS_TEST_EXPECT_MSG_EQ(+base->GetSegmentsLeft(), v.sidsFwd.size(), tag + "base Segments Left");
            p->AddHeader(*base);
            NS_TEST_EXPECT_MSG_EQ(Hex(Bytes(p)).substr(0, 2 * size), std::string(v.expectHex), tag + "re-added bytes");
            delete base;
        }
        // and every CRH golden vector, types 5 and 6
        for (size_t n = 0; n < kCrhEncodeVectorsCount; ++n)
        {
            const CrhEncodeVector& v = kCrhEncodeVectors[n];
            const std::string tag = std::string(v.name) + ": ";
            Ipv6ExtensionRoutingHeader* base =
                demux->GetExtensionRoutingHeaderPtr(static_cast<uint8_t>(v.routingType));
            NS_TEST_ASSERT_MSG_EQ((base != nullptr), true, tag + "demux makes a CRH header");
            NS_TEST_EXPECT_MSG_EQ((dynamic_cast<CrhHeader*>(base) != nullptr), true, tag + "it is a CrhHeader");
            const std::vector<uint8_t> wire = FromHex(v.expectHex);
            Ptr<Packet> p = Create<Packet>(wire.data(), wire.size());
            NS_TEST_EXPECT_MSG_EQ(p->RemoveHeader(*base), v.expectSize, tag + "RemoveHeader via the base");
            NS_TEST_EXPECT_MSG_EQ(+base->GetNextHeader(), v.nextHeader, tag + "base Next Header");
            NS_TEST_EXPECT_MSG_EQ(base->GetLength(), v.expectSize, tag + "base GetLength()");
            NS_TEST_EXPECT_MSG_EQ(+base->GetTypeRouting(), v.routingType, tag + "base Routing Type");
            NS_TEST_EXPECT_MSG_EQ(+base->GetSegmentsLeft(), v.sidsFwd.size(), tag + "base Segments Left");
            p->AddHeader(*base);
            NS_TEST_EXPECT_MSG_EQ(Hex(Bytes(p)), std::string(v.expectHex), tag + "re-added bytes");
            delete base;
        }

        // the address plan, worked by hand
        NS_TEST_EXPECT_MSG_EQ(tcrh::SidAddress(2), Ipv6Address("fd00::2"), "SID 2");
        NS_TEST_EXPECT_MSG_EQ(tcrh::SidAddress(0xF001), Ipv6Address("fd00::f001"), "SID 0xF001");
        NS_TEST_EXPECT_MSG_EQ(tcrh::SidAddress(0x12345678), Ipv6Address("fd00::1234:5678"), "32-bit SID");
        NS_TEST_EXPECT_MSG_EQ(tcrh::LinkAddress(3, 2), Ipv6Address("fd01:0:0:3::2"), "link 3 end 2");
        NS_TEST_EXPECT_MSG_EQ(tcrh::LinkAddress(0x10002, 1), Ipv6Address("fd01:0:1:2::1"), "link 65538");
        uint32_t sid = 0;
        NS_TEST_EXPECT_MSG_EQ(tcrh::SidFromAddress(Ipv6Address("fd00::f001"), &sid), true, "inverse");
        NS_TEST_EXPECT_MSG_EQ(sid, 0xF001U, "inverse value");
        NS_TEST_EXPECT_MSG_EQ(tcrh::SidFromAddress(Ipv6Address("fd01:0:0:3::2"), nullptr), false, "link address");
        Simulator::Destroy();
    }
};

// ============================================================================
//  2. On time: the routing header travels hop by hop
// ============================================================================

/**
 * @ingroup chronoroute-test
 * 20 probes on time along S -> T1 -> T2 -> T3 -> D.
 */
class TcrhOnTimePathTestCase : public TestCase
{
  public:
    TcrhOnTimePathTestCase()
        : TestCase("P5a: on-time T-CRH path: DA rewrite, SL, hop limit, clocks, no transit L4")
    {
    }

  private:
    void DoRun() override
    {
        ChecksumScope checksums;
        TestNet::Options o;
        TestNet net(o);
        const uint32_t n = 20;
        net.ScheduleProbes(PORT_A, MilliSeconds(100), MilliSeconds(50), n);
        Simulator::Stop(Seconds(2));
        Simulator::Run();

        // ---- delivery: D gets all, in order; transit nodes give nothing to L4
        const std::vector<UdpRx> rx = net.Udp(net.d, PORT_A);
        NS_TEST_ASSERT_MSG_EQ(rx.size(), n, "D receives every probe");
        for (uint32_t i = 0; i < n; ++i)
        {
            NS_TEST_EXPECT_MSG_EQ(rx[i].seq, i, "in order");
        }
        for (Ptr<Node> transit : {net.t1, net.t2, net.t3})
        {
            NS_TEST_EXPECT_MSG_EQ(net.Udp(transit, PORT_A).size(), 0U, "transit UDP socket gets nothing");
            NS_TEST_EXPECT_MSG_EQ(net.L4Count(transit, 17), 0U, "transit LocalDeliver to UDP: 0");
        }
        NS_TEST_EXPECT_MSG_EQ(net.L4Count(net.d, 17), n, "D LocalDeliver to UDP");

        // ---- on the wire: Destination Address, Segments Left, Hop Limit per hop
        struct Expect
        {
            Ptr<Node> node;
            uint32_t sid;
            uint8_t sl;
            uint8_t hopLimit;
        };
        const Expect hops[4] = {{net.t1, SID_T1, 3, 64}, {net.t2, SID_T2, 2, 63}, {net.t3, SID_T3, 1, 62}, {net.d, SID_D, 0, 61}};
        for (const Expect& e : hops)
        {
            const std::vector<Rx43>& seen = net.rx43[e.node->GetId()];
            NS_TEST_ASSERT_MSG_EQ(seen.size(), n, "every probe arrives as a routing-header packet");
            for (const Rx43& r : seen)
            {
                NS_TEST_EXPECT_MSG_EQ(r.dst, tcrh::SidAddress(e.sid), "DA = this node's SID address");
                NS_TEST_EXPECT_MSG_EQ(+r.routingType, 253, "Routing Type 253 on the wire");
                NS_TEST_EXPECT_MSG_EQ(+r.segmentsLeft, +e.sl, "Segments Left on arrival");
                NS_TEST_EXPECT_MSG_EQ(+r.hopLimit, +e.hopLimit, "Hop Limit decremented once per hop");
                NS_TEST_EXPECT_MSG_EQ(+r.flags, 0x10, "unit code 1, no DEV");
            }
        }
        NS_TEST_EXPECT_MSG_EQ(net.rx43[net.x->GetId()].size(), 0U, "X sees none of flow A");

        // ---- the clocks, to the unit: hop k arrives 2219.2 us * k after sending
        const std::vector<TcrhHopEvent> ingress = net.At(net.s, "ingress");
        NS_TEST_ASSERT_MSG_EQ(ingress.size(), n, "one ingress event per probe");
        std::map<uint32_t, uint32_t> epochOfSeq;
        for (const TcrhHopEvent& e : ingress)
        {
            const uint32_t seq = net.Seq(e.packetUid);
            const uint64_t tSend = T0_GPS_NS + net.sendNsOfSeq.at(seq);
            NS_TEST_EXPECT_MSG_EQ(e.epochBase, SpecEpoch(tSend), "Epoch_Base = ceil(t_ingress / u) at send time");
            NS_TEST_EXPECT_MSG_EQ(+e.slOut, 3, "ingress SL = h - 1");
            NS_TEST_EXPECT_MSG_EQ(e.nextSid.value_or(0), SID_T1, "first SID");
            NS_TEST_EXPECT_MSG_EQ(+e.nextHeader, 17, "Next Header UDP");
            epochOfSeq[seq] = e.epochBase;
        }
        const struct
        {
            Ptr<Node> node;
            const char* action;
            uint32_t k;
            uint32_t nowOffset; // floor(2219.2 us * k / 100 us)
        } path[4] = {{net.t1, "forward", 1, 22}, {net.t2, "forward", 2, 44}, {net.t3, "forward", 3, 66}, {net.d, "deliver", 4, 88}};
        for (const auto& h : path)
        {
            const std::vector<TcrhHopEvent> evs = net.At(h.node);
            NS_TEST_ASSERT_MSG_EQ(evs.size(), n, "one event per probe at each hop");
            for (const TcrhHopEvent& e : evs)
            {
                const uint32_t E = epochOfSeq.at(net.Seq(e.packetUid));
                NS_TEST_EXPECT_MSG_EQ(std::string(e.action), std::string(h.action), "action");
                NS_TEST_EXPECT_MSG_EQ(e.hopIndex.value_or(99), h.k, "hop index k");
                NS_TEST_EXPECT_MSG_EQ(e.deadlineU.value_or(0), E + 25 * h.k, "D_k = Epoch_Base + 25 k");
                NS_TEST_EXPECT_MSG_EQ(e.nowU.value_or(0), E + h.nowOffset, "unit clock on arrival");
                NS_TEST_EXPECT_MSG_EQ(e.late, false, "on time");
                NS_TEST_EXPECT_MSG_EQ(+e.flagsOut, 0x10, "no flags set");
            }
        }
        // the node's clock IS the spec's floor((t0 + now) / u): check one by hand
        const TcrhHopEvent first = net.At(net.d, "deliver").front(); // a copy: At() returns a temporary
        NS_TEST_EXPECT_MSG_EQ(first.nowU.value(), SpecClock(T0_GPS_NS + first.tNs), "clock formula");

        // ---- counters
        NS_TEST_EXPECT_MSG_EQ(TcrhHelper::GetTcrhExtension(net.t2)->GetCounters().forwarded, n, "T2 forwarded");
        NS_TEST_EXPECT_MSG_EQ(TcrhHelper::GetTcrhExtension(net.d)->GetCounters().delivered, n, "D delivered");
        NS_TEST_EXPECT_MSG_EQ(net.shim->GetCounters().ingress, n, "shim sent");

        // ---- manual addressing installs no queue disc (only the device queue)
        Ptr<TrafficControlLayer> tc = net.t2->GetObject<TrafficControlLayer>();
        NS_TEST_EXPECT_MSG_EQ(static_cast<bool>(tc->GetRootQueueDiscOnDevice(net.links[2].devA)),
                              false,
                              "no qdisc");
        Simulator::Destroy();
    }
};

// ============================================================================
//  3. Late packets: one link slowed mid-run
// ============================================================================

/**
 * @ingroup chronoroute-test
 * Link T2 -> T3 drops from 10 Mb/s to 1 Mb/s between 0.975 s and 1.475 s
 * (MODELLED "up but slow"). The 10 probes sent at 1.00 ... 1.45 s reach T3 at
 * 8630.4 us = 86 units after sending, past D_3 = 75: late at T3, Dev Hop 3.
 */
class TcrhLatePacketTestCase : public TestCase
{
  public:
    TcrhLatePacketTestCase(tcrh::Policy policy, bool fallback)
        : TestCase(std::string("P5a: slowed link -> late at T3, Dev Hop 3, policy ") +
                   tcrh::PolicyName(policy) + (fallback ? " + routing-table fallback" : "")),
          m_policy(policy),
          m_fallback(fallback)
    {
    }

  private:
    void DoRun() override
    {
        ChecksumScope checksums;
        TestNet::Options o;
        o.policy = m_policy;
        o.routingTableFallback = m_fallback;
        TestNet net(o);
        const uint32_t n = 40; // sent at 0.10, 0.15, ..., 2.05 s
        net.ScheduleProbes(PORT_A, MilliSeconds(100), MilliSeconds(50), n);
        Ptr<PointToPointNetDevice> slow = DynamicCast<PointToPointNetDevice>(net.links[2].devA);
        Simulator::Schedule(MilliSeconds(975), &PointToPointNetDevice::SetDataRate, slow, DataRate("1Mbps"));
        Simulator::Schedule(MilliSeconds(1475), &PointToPointNetDevice::SetDataRate, slow, DataRate("10Mbps"));
        Simulator::Stop(Seconds(3));
        Simulator::Run();

        auto isLateSeq = [](uint32_t seq) { return seq >= 18 && seq <= 27; };
        const bool greedyFallback = m_policy == tcrh::Policy::GREEDY && m_fallback;
        const bool dropPolicy = m_policy == tcrh::Policy::DROP;

        // only T3 ever finds a packet late
        for (Ptr<Node> other : {net.t1, net.t2, net.d})
        {
            NS_TEST_EXPECT_MSG_EQ(TcrhHelper::GetTcrhExtension(other)->GetCounters().late, 0U, "not late elsewhere");
        }
        const std::vector<TcrhHopEvent> atT3 = net.At(net.t3);
        NS_TEST_ASSERT_MSG_EQ(atT3.size(), n, "T3 sees every probe");
        uint32_t lateCount = 0;
        for (const TcrhHopEvent& e : atT3)
        {
            const uint32_t seq = net.Seq(e.packetUid);
            const uint32_t E = e.epochBase;
            NS_TEST_EXPECT_MSG_EQ(e.late, isLateSeq(seq), "late exactly inside the slow window, seq " << seq);
            NS_TEST_EXPECT_MSG_EQ(e.nowU.value_or(0), E + (isLateSeq(seq) ? 86 : 66), "T3 clock, seq " << seq);
            if (!isLateSeq(seq))
            {
                NS_TEST_EXPECT_MSG_EQ(std::string(e.action), std::string("forward"), "on time: forward");
                NS_TEST_EXPECT_MSG_EQ(+e.flagsOut, 0x10, "on time: no flags");
                continue;
            }
            lateCount++;
            NS_TEST_EXPECT_MSG_EQ(+e.devHop, 3, "Dev Hop = 3 (T3 is hop 3)");
            if (greedyFallback)
            {
                NS_TEST_EXPECT_MSG_EQ(std::string(e.action), std::string("fallback"), "greedy: fallback");
                NS_TEST_EXPECT_MSG_EQ(+e.flagsOut, 0x13, "DEV | GREEDY | unit 1");
                NS_TEST_EXPECT_MSG_EQ(+e.slOut, 0, "greedy: SL = 0");
                NS_TEST_EXPECT_MSG_EQ(e.dstOut.value_or(Ipv6Address()), tcrh::SidAddress(SID_D), "DA = SID[0]");
            }
            else if (dropPolicy)
            {
                NS_TEST_EXPECT_MSG_EQ(std::string(e.action), std::string("drop_late"), "drop policy");
            }
            else
            {
                NS_TEST_EXPECT_MSG_EQ(std::string(e.action), std::string("forward"), "continue: keep the SID list");
                NS_TEST_EXPECT_MSG_EQ(+e.flagsOut, 0x11, "DEV | unit 1");
                NS_TEST_EXPECT_MSG_EQ(+e.slOut, 0, "SL 1 -> 0");
                if (m_policy == tcrh::Policy::GREEDY)
                {
                    NS_TEST_EXPECT_MSG_EQ(Str(e.reason), std::string("greedy_no_fallback"), "counted");
                }
            }
        }
        NS_TEST_EXPECT_MSG_EQ(lateCount, 10U, "10 late packets");
        const TcrhCounters& c3 = TcrhHelper::GetTcrhExtension(net.t3)->GetCounters();
        NS_TEST_EXPECT_MSG_EQ(c3.late, 10U, "T3 late counter");
        NS_TEST_EXPECT_MSG_EQ(c3.greedyNoFallback, ((m_policy == tcrh::Policy::GREEDY && !m_fallback) ? 10U : 0U),
                              "greedy without fallback counted");
        NS_TEST_EXPECT_MSG_EQ(c3.fallback, (greedyFallback ? 10U : 0U), "fallback counter");
        NS_TEST_EXPECT_MSG_EQ(c3.droppedLate, (dropPolicy ? 10U : 0U), "late drops");
        // what a run record must say this node did with late packets
        const std::string effective = TcrhHelper::GetTcrhExtension(net.t3)->EffectivePolicyName();
        const std::string wantEffective = (m_policy == tcrh::Policy::GREEDY && !m_fallback)
                                              ? std::string("continue (greedy set, no fallback installed)")
                                              : std::string(tcrh::PolicyName(m_policy));
        NS_TEST_EXPECT_MSG_EQ(effective, wantEffective, "effective policy");

        // D: what arrives, and with which flags
        const std::vector<UdpRx> rx = net.Udp(net.d, PORT_A);
        NS_TEST_EXPECT_MSG_EQ(rx.size(), (dropPolicy ? 30U : 40U), "D receives the rest");
        for (const UdpRx& r : rx)
        {
            NS_TEST_EXPECT_MSG_EQ(dropPolicy && isLateSeq(r.seq), false, "a dropped probe never arrives");
        }
        for (const TcrhHopEvent& e : net.At(net.d, "deliver"))
        {
            const uint32_t seq = net.Seq(e.packetUid);
            NS_TEST_EXPECT_MSG_EQ(e.late, false, "D never sets DEV a second time");
            if (isLateSeq(seq))
            {
                NS_TEST_EXPECT_MSG_EQ(+e.flagsIn, (greedyFallback ? 0x13 : 0x11), "flags as delivered");
                NS_TEST_EXPECT_MSG_EQ(+e.devHop, 3, "the late packet carries Dev Hop 3 to D");
                NS_TEST_EXPECT_MSG_EQ(+e.hopLimitIn, 61, "still one decrement per hop");
            }
            else
            {
                NS_TEST_EXPECT_MSG_EQ(+e.flagsIn, 0x10, "on time");
            }
        }
        for (Ptr<Node> transit : {net.t1, net.t2, net.t3})
        {
            NS_TEST_EXPECT_MSG_EQ(net.L4Count(transit, 17), 0U, "transit LocalDeliver to UDP: 0");
        }
        Simulator::Destroy();
    }

    static std::string Str(const char* s)
    {
        return s ? std::string(s) : std::string("null");
    }

    tcrh::Policy m_policy;
    bool m_fallback;
};

// ============================================================================
//  4. Deadline wrap
// ============================================================================

/**
 * @ingroup chronoroute-test
 * t0 is 10 ms before the unit clock wraps past 2^32 (at u = 0.1 ms that is
 * every 4.97 days of GPS time). Deadlines and then Epoch_Base itself wrap.
 * On time stays on time; a slowed link is still late, with Dev Hop 3.
 */
class TcrhDeadlineWrapTestCase : public TestCase
{
  public:
    TcrhDeadlineWrapTestCase()
        : TestCase("P5a: deadlines and Epoch_Base wrap past 2^32 in a running network")
    {
    }

  private:
    void DoRun() override
    {
        ChecksumScope checksums;
        const uint64_t wrapT0 = (uint64_t{1} << 32) * U_NS - 10000000; // 10 ms before the wrap
        for (bool slowed : {false, true})
        {
            const std::string tag = slowed ? "slowed: " : "on time: ";
            TestNet::Options o;
            o.t0GpsNs = wrapT0;
            TestNet net(o);
            // sent at 1, 4, ..., 28 ms: 3 ms apart, longer than the 2.192 ms a
            // packet needs on the slowed link, so nothing ever queues
            const uint32_t n = 10;
            net.ScheduleProbes(PORT_A, MilliSeconds(1), MilliSeconds(3), n);
            if (slowed)
            {
                DynamicCast<PointToPointNetDevice>(net.links[2].devA)->SetDataRate(DataRate("1Mbps"));
            }
            Simulator::Stop(Seconds(1));
            Simulator::Run();

            NS_TEST_EXPECT_MSG_EQ(net.Udp(net.d, PORT_A).size(), n, tag + "all delivered");
            bool sawWrappedDeadline = false;
            bool sawWrappedEpoch = false;
            for (const TcrhHopEvent& e : net.At(net.s, "ingress"))
            {
                const uint32_t seq = net.Seq(e.packetUid);
                NS_TEST_EXPECT_MSG_EQ(e.epochBase,
                                      SpecEpoch(wrapT0 + net.sendNsOfSeq.at(seq)),
                                      tag + "Epoch_Base mod 2^32");
                sawWrappedEpoch = sawWrappedEpoch || e.epochBase < 100;
            }
            for (const TcrhHopEvent& e : net.At(net.t3))
            {
                const uint32_t D3 = e.deadlineU.value_or(0);
                sawWrappedDeadline = sawWrappedDeadline || D3 < e.epochBase;
                NS_TEST_EXPECT_MSG_EQ(e.late, slowed, tag + "late only when slowed");
                NS_TEST_EXPECT_MSG_EQ(D3, static_cast<uint32_t>(e.epochBase + 75), tag + "D_3 mod 2^32");
                if (slowed)
                {
                    NS_TEST_EXPECT_MSG_EQ(+e.devHop, 3, tag + "Dev Hop 3");
                    NS_TEST_EXPECT_MSG_EQ(tcrh::SerialDiff(e.nowU.value(), D3), 11, tag + "11 units late");
                }
                else
                {
                    NS_TEST_EXPECT_MSG_EQ(tcrh::SerialDiff(e.nowU.value(), D3), -9, tag + "9 units early");
                }
            }
            for (const TcrhHopEvent& e : net.At(net.d, "deliver"))
            {
                NS_TEST_EXPECT_MSG_EQ(e.late, false, tag + "D: no second DEV");
                NS_TEST_EXPECT_MSG_EQ(+e.flagsIn, (slowed ? 0x11 : 0x10), tag + "flags at D");
            }
            NS_TEST_EXPECT_MSG_EQ(sawWrappedDeadline, true, tag + "some D_3 wrapped past 2^32");
            NS_TEST_EXPECT_MSG_EQ(sawWrappedEpoch, true, tag + "some Epoch_Base wrapped to small values");
            Simulator::Destroy();
        }
    }
};

// ============================================================================
//  5. A node without T-CRH support
// ============================================================================

/**
 * @ingroup chronoroute-test
 * X runs plain ns-3.44 IPv6 (no Routing Type 253 registered).
 *  - X named with SL != 0 (flow B): ns-3 discards the packet and sends ICMPv6
 *    Parameter Problem, Code 0 (RFC 8200 4.4). ns-3.44 sets the Pointer to
 *    offset + 1 = 1 (ipv6-extension.cc:916-924), i.e. Hdr Ext Len counted from
 *    the routing header; RFC 8200 asks for the Routing Type counted from the
 *    start of the invoking packet (40 + 2 = 42). The test pins ns-3's value.
 *  - X as the FINAL endpoint (SL 0, flow C): RFC 8200 says skip the header and
 *    deliver; ns-3.44 returns the raw Hdr Ext Len (2) instead of 24 bytes
 *    (ipv6-extension.cc:926), so UDP gets 230 misaligned bytes, fails its
 *    checksum and the socket receives nothing.
 */
class TcrhNonSupportingNodeTestCase : public TestCase
{
  public:
    TcrhNonSupportingNodeTestCase()
        : TestCase("P5a: node without T-CRH: SL != 0 -> drop + ICMPv6 Parameter Problem; SL 0 quirk")
    {
    }

  private:
    void DoRun() override
    {
        ChecksumScope checksums;
        TestNet::Options o;
        TestNet net(o);
        net.ScheduleProbes(PORT_B, MilliSeconds(100), MilliSeconds(100), 3);
        net.ScheduleProbes(PORT_C, MilliSeconds(500), MilliSeconds(100), 2);
        Simulator::Stop(Seconds(2));
        Simulator::Run();

        // flow B: T1 forwards to X; X discards; S hears about it
        const std::vector<TcrhHopEvent> t1fwd = net.At(net.t1, "forward");
        NS_TEST_EXPECT_MSG_EQ(t1fwd.size(), 5U, "T1 forwards 3 (flow B) + 2 (flow C) to X");
        for (const TcrhHopEvent& e : t1fwd)
        {
            NS_TEST_EXPECT_MSG_EQ(e.nextSid.value_or(0), SID_X, "towards X");
        }
        std::vector<IcmpRx> paramProblems;
        for (const IcmpRx& m : net.icmpAtS)
        {
            if (m.type == 4)
            {
                paramProblems.push_back(m);
            }
        }
        NS_TEST_ASSERT_MSG_EQ(paramProblems.size(), 3U, "one Parameter Problem per flow-B probe");
        for (const IcmpRx& m : paramProblems)
        {
            NS_TEST_EXPECT_MSG_EQ(+m.code, 0, "Code 0: erroneous header field");
            NS_TEST_EXPECT_MSG_EQ(m.pointer, 1U, "ns-3.44 Pointer = offset + 1 (RFC 8200 would say 42)");
            NS_TEST_ASSERT_MSG_GT_OR_EQ(m.invoking.size(), 48U, "invoking packet included");
            NS_TEST_EXPECT_MSG_EQ(+m.invoking[6], 43, "invoking IPv6 Next Header 43");
            uint8_t dst[16];
            tcrh::SidAddress(SID_X).GetBytes(dst);
            NS_TEST_EXPECT_MSG_EQ(std::equal(dst, dst + 16, m.invoking.begin() + 24), true, "invoking DA = X");
            NS_TEST_EXPECT_MSG_EQ(+m.invoking[40 + 2], 253, "invoking Routing Type 253");
            NS_TEST_EXPECT_MSG_EQ(+m.invoking[40 + 3], 3, "invoking SL 3 (h = 5, two segments done)");
        }
        uint32_t malformedDrops = 0;
        for (auto r : net.drops[net.x->GetId()])
        {
            malformedDrops += r == Ipv6L3Protocol::DROP_MALFORMED_HEADER ? 1 : 0;
        }
        NS_TEST_EXPECT_MSG_EQ(malformedDrops, 3U, "X's Drop trace: DROP_MALFORMED_HEADER x 3");
        NS_TEST_EXPECT_MSG_EQ(net.Udp(net.x, PORT_B).size(), 0U, "X delivers nothing of flow B");
        NS_TEST_EXPECT_MSG_EQ(net.Udp(net.d, PORT_B).size(), 0U, "flow B never reaches D");

        // flow C: X is the final endpoint with SL 0
        uint32_t misaligned = 0;
        for (const auto& [nh, size] : net.l4[net.x->GetId()])
        {
            if (nh == 17)
            {
                NS_TEST_EXPECT_MSG_EQ(size, 24U - 2U + 8U + PAYLOAD_BYTES, "UDP handed 230 bytes, not 208");
                misaligned++;
            }
        }
        NS_TEST_EXPECT_MSG_EQ(misaligned, 2U, "both flow-C probes reach X's UDP misaligned");
        NS_TEST_EXPECT_MSG_EQ(net.Udp(net.x, PORT_C).size(), 0U, "the UDP checksum fails: nothing delivered");
        Simulator::Destroy();
    }
};

// ============================================================================
//  6. Broken packets injected into a real node
// ============================================================================

/**
 * @ingroup chronoroute-test
 * Every malformed golden process vector with Routing Type 253 (and at least
 * the 4 bytes ns-3 reads to dispatch) is sent from S to T1. T1 must discard
 * it with the vector's reason, and send ICMPv6 Parameter Problem with the
 * vector's code and Pointer = 40 + the vector's pointer, or nothing when the
 * vector says none. Then: a SID missing from T1's CRH-FIB (Code 0, pointing at
 * that SID) and Hop Limit 1 (ICMPv6 Time Exceeded).
 */
class TcrhMalformedInNetworkTestCase : public TestCase
{
  public:
    TcrhMalformedInNetworkTestCase()
        : TestCase("P5a: malformed golden vectors, missing FIB SID, hop limit 1 at a real node")
    {
    }

  private:
    void DoRun() override
    {
        ChecksumScope checksums;
        TestNet::Options o;
        TestNet net(o);

        std::vector<const TcrhProcessVector*> used;
        for (size_t i = 0; i < kTcrhProcessVectorsCount; ++i)
        {
            const TcrhProcessVector& v = kTcrhProcessVectors[i];
            const std::vector<uint8_t> raw = FromHex(v.hexIn);
            if (std::string(v.expectAction) != "drop_malformed" || raw.size() < 4 || raw[2] != 253)
            {
                continue; // other types are dispatched elsewhere by ns-3
            }
            Simulator::Schedule(MilliSeconds(100 + 10 * used.size()), &TestNet::InjectToT1, &net, raw, 64);
            used.push_back(&v);
        }
        NS_TEST_ASSERT_MSG_GT(used.size(), 3U, "enough malformed vectors");

        // a valid header whose next SID (0x777) is not in T1's CRH-FIB
        TcrhHeader fibMiss;
        fibMiss.SetPath({SID_T1, 0x777, SID_D}, {25, 25, 25}, 0, UC);
        tcrh::IngressSendHeader(fibMiss); // SL 3 -> 2, as the ingress sends it
        std::vector<uint8_t> fibMissBytes = fibMiss.ToBytes();
        Simulator::Schedule(Seconds(1), &TestNet::InjectToT1, &net, fibMissBytes, 64);
        // a valid header that arrives with Hop Limit 1
        TcrhHeader hl1;
        hl1.SetPath({SID_T1, SID_T2, SID_T3, SID_D}, {25, 25, 25, 25}, 0, UC);
        tcrh::IngressSendHeader(hl1);
        std::vector<uint8_t> hl1Bytes = hl1.ToBytes();
        Simulator::Schedule(Seconds(1.1), &TestNet::InjectToT1, &net, hl1Bytes, 1);
        Simulator::Stop(Seconds(2));
        Simulator::Run();

        const std::vector<TcrhHopEvent> dropped = net.At(net.t1, "drop_malformed");
        NS_TEST_ASSERT_MSG_EQ(dropped.size(), used.size(), "T1 discards every malformed vector");
        for (size_t i = 0; i < used.size(); ++i)
        {
            const TcrhProcessVector& v = *used[i];
            const std::string tag = std::string(v.name) + ": ";
            NS_TEST_EXPECT_MSG_EQ(std::string(dropped[i].reason ? dropped[i].reason : "null"),
                                  std::string(v.expectReason),
                                  tag + "reason");
            // the ICMPv6 messages about this vector (matched by the bytes they quote)
            const std::vector<uint8_t> raw = FromHex(v.hexIn);
            uint32_t found = 0;
            for (const IcmpRx& m : net.icmpAtS)
            {
                if (m.invoking.size() >= 40 + raw.size() &&
                    std::equal(raw.begin(), raw.end(), m.invoking.begin() + 40))
                {
                    found++;
                    NS_TEST_EXPECT_MSG_EQ(+m.type, 4, tag + "Parameter Problem");
                    NS_TEST_EXPECT_MSG_EQ(+m.code, v.expectIcmpCode, tag + "code");
                    NS_TEST_EXPECT_MSG_EQ(m.pointer, 40 + v.expectIcmpPointer, tag + "Pointer = 40 + field offset");
                }
            }
            NS_TEST_EXPECT_MSG_EQ(found, (v.hasExpectIcmpCode ? 1U : 0U), tag + "ICMPv6 only where the spec says");
        }
        NS_TEST_EXPECT_MSG_EQ(net.At(net.t1, "forward").size(), 0U, "nothing broken is forwarded");

        // the CRH-FIB miss: Code 0, Pointer -> SID[1] at offset 12 + 3 * 1
        const std::vector<TcrhHopEvent> noFib = net.At(net.t1, "drop_no_fib");
        NS_TEST_ASSERT_MSG_EQ(noFib.size(), 1U, "FIB miss discarded");
        NS_TEST_EXPECT_MSG_EQ(noFib[0].nextSid.value_or(0), 0x777U, "the missing SID");
        uint32_t fibIcmp = 0;
        for (const IcmpRx& m : net.icmpAtS)
        {
            if (m.invoking.size() >= 40 + fibMissBytes.size() &&
                std::equal(fibMissBytes.begin(), fibMissBytes.end(), m.invoking.begin() + 40))
            {
                fibIcmp++;
                NS_TEST_EXPECT_MSG_EQ(+m.type, 4, "FIB miss: Parameter Problem");
                NS_TEST_EXPECT_MSG_EQ(+m.code, 0, "FIB miss: Code 0");
                NS_TEST_EXPECT_MSG_EQ(m.pointer, 40U + 12U + 3U, "FIB miss: Pointer at the current SID");
            }
        }
        NS_TEST_EXPECT_MSG_EQ(fibIcmp, 1U, "one ICMPv6 for the FIB miss");

        // Hop Limit 1: Time Exceeded, never forwarded
        NS_TEST_EXPECT_MSG_EQ(net.At(net.t1, "drop_hop_limit").size(), 1U, "hop limit drop");
        uint32_t timeExceeded = 0;
        for (const IcmpRx& m : net.icmpAtS)
        {
            if (m.type == 3)
            {
                timeExceeded++;
                NS_TEST_EXPECT_MSG_EQ(+m.code, 0, "Code 0: hop limit exceeded in transit");
            }
        }
        NS_TEST_EXPECT_MSG_EQ(timeExceeded, 1U, "one Time Exceeded");
        Simulator::Destroy();
    }
};

// ============================================================================
//  7. Next link down (spec section 6 step 7)
// ============================================================================

/**
 * @ingroup chronoroute-test
 * T2's interface towards T3 goes down: with a fallback function T2 hands it
 * the packet with DEV, GREEDY, Dev Hop 2, SL 0 and DA = SID[0]'s address;
 * without one it discards. S's own first link down: Dev Hop 0 at the ingress.
 */
class TcrhLinkDownTestCase : public TestCase
{
  public:
    TcrhLinkDownTestCase()
        : TestCase("P5a: next link down at a transit node and at the ingress (spec 6 step 7)")
    {
    }

  private:
    void DoRun() override
    {
        ChecksumScope checksums;
        for (bool withFallback : {true, false})
        {
            const std::string tag = withFallback ? "T2 with fallback: " : "T2 without fallback: ";
            TestNet::Options o;
            o.recordingFallback = withFallback;
            TestNet net(o);
            Ptr<Ipv6> ipv6T2 = net.t2->GetObject<Ipv6>();
            Simulator::Schedule(MilliSeconds(500), &Ipv6::SetDown, ipv6T2, net.links[2].ifA);
            net.ScheduleProbes(PORT_A, MilliSeconds(600), MilliSeconds(100), 2);
            Simulator::Stop(Seconds(2));
            Simulator::Run();
            const std::vector<TcrhHopEvent> at2 = net.At(net.t2);
            NS_TEST_ASSERT_MSG_EQ(at2.size(), 2U, tag + "two probes reach T2");
            for (const TcrhHopEvent& e : at2)
            {
                NS_TEST_EXPECT_MSG_EQ(std::string(e.reason ? e.reason : ""), std::string("link_down"), tag + "reason");
                NS_TEST_EXPECT_MSG_EQ(std::string(e.action),
                                      std::string(withFallback ? "fallback" : "drop_link_down"),
                                      tag + "action");
                NS_TEST_EXPECT_MSG_EQ(e.late, false, tag + "a dead link is not a late packet");
                // step 7 marks the header before the fallback / discard decision
                NS_TEST_EXPECT_MSG_EQ(+e.flagsOut, 0x13, tag + "trace: DEV | GREEDY | unit 1");
                NS_TEST_EXPECT_MSG_EQ(+e.devHop, 2, tag + "trace: Dev Hop 2");
                NS_TEST_EXPECT_MSG_EQ(+e.slOut, 0, tag + "trace: SL 0");
            }
            if (withFallback)
            {
                NS_TEST_ASSERT_MSG_EQ(net.fallbacks.size(), 2U, tag + "fallback called twice");
                for (const FallbackCall& f : net.fallbacks)
                {
                    NS_TEST_EXPECT_MSG_EQ(f.nodeId, net.t2->GetId(), tag + "by T2");
                    NS_TEST_EXPECT_MSG_EQ(f.targetSid, SID_D, tag + "target SID[0]");
                    NS_TEST_EXPECT_MSG_EQ(f.ip.GetDestination(), tcrh::SidAddress(SID_D), tag + "DA = SID[0]'s address");
                    NS_TEST_EXPECT_MSG_EQ(+f.ip.GetHopLimit(), 62, tag + "hop limit 63 - 1");
                    NS_TEST_EXPECT_MSG_EQ(+f.ip.GetNextHeader(), 43, tag + "Next Header 43");
                    NS_TEST_EXPECT_MSG_EQ(+f.bytes[TcrhHeader::OFF_SEGMENTS_LEFT], 0, tag + "SL 0");
                    NS_TEST_EXPECT_MSG_EQ(+f.bytes[TcrhHeader::OFF_FLAGS], 0x13, tag + "DEV | GREEDY | unit 1");
                    NS_TEST_EXPECT_MSG_EQ(+f.bytes[TcrhHeader::OFF_DEV_HOP], 2, tag + "Dev Hop 2");
                }
            }
            else
            {
                NS_TEST_EXPECT_MSG_EQ(TcrhHelper::GetTcrhExtension(net.t2)->GetCounters().droppedLinkDown,
                                      2U,
                                      tag + "counted");
            }
            NS_TEST_EXPECT_MSG_EQ(net.Udp(net.d, PORT_A).size(), 0U, tag + "nothing reaches D");
            Simulator::Destroy();
        }

        // the ingress: S's only link is down
        TestNet::Options o;
        o.recordingFallback = true;
        TestNet net(o);
        Ptr<Ipv6> ipv6S = net.s->GetObject<Ipv6>();
        Simulator::Schedule(MilliSeconds(500), &Ipv6::SetDown, ipv6S, net.links[0].ifA);
        net.ScheduleProbes(PORT_A, MilliSeconds(600), MilliSeconds(100), 1);
        Simulator::Stop(Seconds(2));
        Simulator::Run();
        NS_TEST_ASSERT_MSG_EQ(net.fallbacks.size(), 1U, "ingress: fallback called");
        const FallbackCall& f = net.fallbacks[0];
        NS_TEST_EXPECT_MSG_EQ(f.nodeId, net.s->GetId(), "ingress: by S");
        NS_TEST_EXPECT_MSG_EQ(f.ip.GetDestination(), tcrh::SidAddress(SID_D), "ingress: DA = SID[0]'s address");
        NS_TEST_EXPECT_MSG_EQ(+f.ip.GetHopLimit(), +DEFAULT_HOP_LIMIT, "ingress: originated, no decrement");
        NS_TEST_EXPECT_MSG_EQ(+f.bytes[TcrhHeader::OFF_SEGMENTS_LEFT], 0, "ingress: SL 0");
        NS_TEST_EXPECT_MSG_EQ(+f.bytes[TcrhHeader::OFF_FLAGS], 0x13, "ingress: DEV | GREEDY");
        NS_TEST_EXPECT_MSG_EQ(+f.bytes[TcrhHeader::OFF_DEV_HOP], 0, "ingress: Dev Hop 0 (spec section 2)");
        const std::vector<TcrhHopEvent> ing = net.At(net.s);
        NS_TEST_ASSERT_MSG_EQ(ing.size(), 1U, "ingress event");
        NS_TEST_EXPECT_MSG_EQ(std::string(ing[0].action), std::string("fallback"), "ingress action");
        Simulator::Destroy();

        // The ingress WITHOUT a fallback function: the packet is discarded, but
        // spec 6 step 7 has already set DEV (Dev Hop 0) and GREEDY, and the
        // trace says so, exactly like a transit node's drop_link_down above.
        TestNet::Options o2;
        TestNet bare(o2);
        Ptr<Ipv6> ipv6S2 = bare.s->GetObject<Ipv6>();
        Simulator::Schedule(MilliSeconds(500), &Ipv6::SetDown, ipv6S2, bare.links[0].ifA);
        bare.ScheduleProbes(PORT_A, MilliSeconds(600), MilliSeconds(100), 2);
        Simulator::Stop(Seconds(2));
        Simulator::Run();
        const std::vector<TcrhHopEvent> drops = bare.At(bare.s);
        NS_TEST_ASSERT_MSG_EQ(drops.size(), 2U, "ingress without fallback: one event per probe");
        for (const TcrhHopEvent& e : drops)
        {
            NS_TEST_EXPECT_MSG_EQ(std::string(e.action), std::string("drop_link_down"), "ingress: discarded");
            NS_TEST_EXPECT_MSG_EQ(std::string(e.reason ? e.reason : ""), std::string("link_down"), "reason");
            NS_TEST_EXPECT_MSG_EQ(+e.flagsIn, 0x10, "ingress: built with no flags");
            NS_TEST_EXPECT_MSG_EQ(+e.flagsOut, 0x13, "ingress trace: DEV | GREEDY | unit 1");
            NS_TEST_EXPECT_MSG_EQ(+e.devHop, 0, "ingress trace: Dev Hop 0 (spec section 2)");
            NS_TEST_EXPECT_MSG_EQ(+e.slOut, 0, "ingress trace: SL 0");
            NS_TEST_EXPECT_MSG_EQ(e.nextSid.value_or(0), SID_D, "ingress trace: target SID[0]");
        }
        NS_TEST_EXPECT_MSG_EQ(bare.shim->GetCounters().droppedLinkDown, 2U, "ingress: counted");
        NS_TEST_EXPECT_MSG_EQ(bare.Udp(bare.d, PORT_A).size(), 0U, "ingress: nothing reaches D");
        Simulator::Destroy();
    }
};

// ============================================================================
//  8. TCP over T-CRH, and the CRH-16 baseline
// ============================================================================

/**
 * @ingroup chronoroute-test
 * A 20 000-byte TCP transfer S -> D with T-CRH on every data segment (the ACKs
 * return as plain IPv6), and five CRH-16 (Routing Type 5) probes on the same
 * path.
 */
class TcrhTcpAndCrh16TestCase : public TestCase
{
  public:
    TcrhTcpAndCrh16TestCase()
        : TestCase("P5a: TCP over T-CRH and the CRH-16 baseline through the same nodes")
    {
    }

  private:
    void DoRun() override
    {
        ChecksumScope checksums;
        TestNet::Options o;
        TestNet net(o);
        net.StartTcp(MilliSeconds(100), 20000);
        net.ScheduleProbes(PORT_CRH, MilliSeconds(50), MilliSeconds(10), 5);
        Simulator::Stop(Seconds(5));
        Simulator::Run();

        // TCP
        NS_TEST_EXPECT_MSG_EQ(net.tcpReceived, 20000U, "every TCP byte arrives");
        uint32_t tcpDelivered = 0;
        for (const TcrhHopEvent& e : net.At(net.d, "deliver"))
        {
            if (e.routingType == 253)
            {
                NS_TEST_EXPECT_MSG_EQ(+e.nextHeader, 6, "T-CRH Next Header = TCP");
                tcpDelivered++;
            }
        }
        NS_TEST_EXPECT_MSG_GT(tcpDelivered, 20U, "TCP segments arrive with a T-CRH");
        for (Ptr<Node> transit : {net.t1, net.t2, net.t3})
        {
            NS_TEST_EXPECT_MSG_EQ(net.L4Count(transit, 6), 0U, "transit LocalDeliver to TCP: 0");
        }
        NS_TEST_EXPECT_MSG_GT(net.L4Count(net.s, 6), 0U, "S receives ACKs (plain IPv6)");

        // CRH-16
        NS_TEST_EXPECT_MSG_EQ(net.Udp(net.d, PORT_CRH).size(), 5U, "CRH-16 probes delivered");
        const struct
        {
            Ptr<Node> node;
            const char* action;
            uint8_t slIn;
        } path[4] = {{net.t1, "forward", 3}, {net.t2, "forward", 2}, {net.t3, "forward", 1}, {net.d, "deliver", 0}};
        for (const auto& h : path)
        {
            uint32_t count = 0;
            for (const TcrhHopEvent& e : net.At(h.node))
            {
                if (e.routingType != 5)
                {
                    continue;
                }
                count++;
                NS_TEST_EXPECT_MSG_EQ(std::string(e.action), std::string(h.action), "CRH-16 action");
                NS_TEST_EXPECT_MSG_EQ(+e.slIn, +h.slIn, "CRH-16 Segments Left");
            }
            NS_TEST_EXPECT_MSG_EQ(count, 5U, "one CRH-16 event per probe per hop");
            NS_TEST_EXPECT_MSG_EQ(net.Udp(h.node, PORT_CRH).size(), (h.node == net.d ? 5U : 0U), "L4 only at D");
        }
        uint32_t type5 = 0;
        for (const Rx43& r : net.rx43[net.t2->GetId()])
        {
            type5 += r.routingType == 5 ? 1 : 0;
        }
        NS_TEST_EXPECT_MSG_EQ(type5, 5U, "Routing Type 5 on the wire");
        Simulator::Destroy();
    }
};

} // namespace

std::vector<TestCase*>
MakeTcrhIpv6TestCases()
{
    return {
        new TcrhRoutingHeaderClassTestCase,
        new TcrhOnTimePathTestCase,
        new TcrhLatePacketTestCase(tcrh::Policy::CONTINUE, false),
        new TcrhLatePacketTestCase(tcrh::Policy::GREEDY, false),
        new TcrhLatePacketTestCase(tcrh::Policy::GREEDY, true),
        new TcrhLatePacketTestCase(tcrh::Policy::DROP, false),
        new TcrhDeadlineWrapTestCase,
        new TcrhNonSupportingNodeTestCase,
        new TcrhMalformedInNetworkTestCase,
        new TcrhLinkDownTestCase,
        new TcrhTcpAndCrh16TestCase,
    };
}
