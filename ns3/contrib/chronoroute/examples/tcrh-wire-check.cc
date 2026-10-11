/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

/**
 * @file
 * @ingroup chronoroute
 *
 * tcrh-wire-check: T-CRH (IPv6 Routing Type 253) as a REAL IPv6 routing header
 * in ns-3.44, small enough to read every packet in Wireshark.
 *
 *     S (0xF000) -- T1 (1) -- T2 (2) -- T3 (3) -- D (0xF001)
 *                    |
 *                    X (0x63)   plain ns-3 IPv6, NO T-CRH support
 *
 *  - flow A: UDP probes S -> T1 -> T2 -> T3 -> D (the source host inserts the
 *    T-CRH; every hop rewrites the IPv6 Destination Address and decrements
 *    Segments Left). Link T2 -> T3 is slowed from 10 Mb/s to 1 Mb/s for half
 *    a second, so the probes sent then reach T3 after their deadline: T3 sets
 *    DEV with Dev Hop 3 and applies its deviation policy.
 *  - flow B: three probes whose path names X. X cannot process Routing Type
 *    253 with Segments Left != 0, so ns-3 discards them and S receives ICMPv6
 *    Parameter Problem.
 *  - flow C: three probes with a CRH-16 (Routing Type 5, RFC 9631) on flow A's
 *    path: the "same path, no deadline" baseline, which Wireshark decodes
 *    natively (a cross-check of our CRH bytes).
 *
 * Every device writes a pcap (DLT_PPP). Look at them with
 *     tshark -r <outDir>/tcrh-wire-check-2-1.pcap -V -Y ipv6.routing
 *
 * Labels: link rates, delays and the slow-down are MODELLED; the header bytes
 * follow the spec v1 wire format (spec/tcrh-v1.md) exactly; t0 is the GPS time
 * of the pinned CelesTrak snapshot (2026-10-10T13:58:00Z). The greedy fallback
 * here is the routing-table stand-in (tcrh::RoutingTableFallback), MODELLED,
 * not geographic forwarding.
 *
 * The program checks its own results and exits with status 1 if any check
 * fails, so it doubles as a smoke test:
 *     ./ns3 run "tcrh-wire-check --outDir=/tmp/wire"
 */

#include "ns3/boolean.h"
#include "ns3/command-line.h"
#include "ns3/crh-fib.h"
#include "ns3/data-rate.h"
#include "ns3/global-value.h"
#include "ns3/inet6-socket-address.h"
#include "ns3/internet-stack-helper.h"
#include "ns3/ipv6-extension-tcrh.h"
#include "ns3/ipv6-header.h"
#include "ns3/ipv6-l3-protocol.h"
#include "ns3/node-container.h"
#include "ns3/packet.h"
#include "ns3/point-to-point-helper.h"
#include "ns3/point-to-point-net-device.h"
#include "ns3/simulator.h"
#include "ns3/socket.h"
#include "ns3/string.h"
#include "ns3/tcrh-address-plan.h"
#include "ns3/tcrh-helper.h"
#include "ns3/tcrh-process.h"
#include "ns3/tcrh-source-shim.h"
#include "ns3/udp-socket-factory.h"

#include <cstdio>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("TcrhWireCheck");

namespace
{

constexpr uint32_t SID_S = 0xF000;
constexpr uint32_t SID_T1 = 1;
constexpr uint32_t SID_T2 = 2;
constexpr uint32_t SID_T3 = 3;
constexpr uint32_t SID_D = 0xF001;
constexpr uint32_t SID_X = 0x63;
constexpr uint16_t PORT_A = 9000;
constexpr uint16_t PORT_B = 9001;
constexpr uint16_t PORT_C = 9002; // flow C: CRH-16 (Routing Type 5) on flow A's path

/// Everything the run records.
struct Record
{
    std::map<uint32_t, std::string> nodeName;                 // node id -> "T1"
    std::map<uint64_t, std::pair<char, uint32_t>> flowSeqOfUid; // uid -> (flow, seq)
    std::map<std::pair<char, uint32_t>, int64_t> sentNs;      // (flow, seq) -> send time
    std::map<std::pair<char, uint32_t>, int64_t> rxNs;        // (flow, seq) -> receive time at D
    std::map<uint64_t, std::vector<TcrhHopEvent>> eventsOfUid;
    std::vector<TcrhHopEvent> allEvents;
    std::map<uint32_t, uint32_t> udpToL4;                     // node id -> LocalDeliver(UDP) count
    struct Icmp
    {
        int64_t tNs;
        uint8_t type;
        uint8_t code;
        uint32_t pointer;
        uint8_t quotedSl;
    };
    std::vector<Icmp> icmpAtS;
};

Record g_rec;

void
OnHop(const TcrhHopEvent& e)
{
    g_rec.allEvents.push_back(e);
    g_rec.eventsOfUid[e.packetUid].push_back(e);
}

void
OnLocalDeliver(uint32_t node, const Ipv6Header& h, Ptr<const Packet> p, uint32_t)
{
    if (h.GetNextHeader() == 17)
    {
        g_rec.udpToL4[node]++;
    }
    if (g_rec.nodeName[node] == "S" && h.GetNextHeader() == 58 && p->GetSize() >= 8 + 44)
    {
        std::vector<uint8_t> b(p->GetSize());
        p->CopyData(b.data(), b.size());
        g_rec.icmpAtS.push_back(Record::Icmp{Simulator::Now().GetNanoSeconds(),
                                             b[0],
                                             b[1],
                                             (uint32_t(b[4]) << 24) | (uint32_t(b[5]) << 16) |
                                                 (uint32_t(b[6]) << 8) | b[7],
                                             b[8 + 40 + 3]});
    }
}

void
OnRecvAtD(Ptr<Socket> socket)
{
    Address from;
    while (Ptr<Packet> p = socket->RecvFrom(from))
    {
        uint8_t b[5];
        p->CopyData(b, 5);
        const char flow = static_cast<char>(b[0]);
        const uint32_t seq = (uint32_t(b[1]) << 24) | (uint32_t(b[2]) << 16) | (uint32_t(b[3]) << 8) | b[4];
        g_rec.rxNs[{flow, seq}] = Simulator::Now().GetNanoSeconds();
    }
}

/// Count datagrams that reach a UDP socket on a node that must see none.
std::map<uint32_t, uint32_t> g_transitSocketRx;

void
OnRecvTransit(uint32_t node, Ptr<Socket> socket)
{
    Address from;
    while (socket->RecvFrom(from))
    {
        g_transitSocketRx[node]++;
    }
}

void
SendProbe(Ptr<Socket> sender, char flow, uint16_t port, uint32_t seq, uint32_t payloadBytes)
{
    // payload: flow letter, sequence number, zeros
    std::vector<uint8_t> payload(payloadBytes, 0);
    payload[0] = static_cast<uint8_t>(flow);
    payload[1] = static_cast<uint8_t>(seq >> 24);
    payload[2] = static_cast<uint8_t>(seq >> 16);
    payload[3] = static_cast<uint8_t>(seq >> 8);
    payload[4] = static_cast<uint8_t>(seq);
    Ptr<Packet> p = Create<Packet>(payload.data(), payload.size());
    g_rec.flowSeqOfUid[p->GetUid()] = {flow, seq};
    g_rec.sentNs[{flow, seq}] = Simulator::Now().GetNanoSeconds();
    sender->SendTo(p, 0, Inet6SocketAddress(tcrh::SidAddress(SID_D), port));
}

std::string
Ms(int64_t ns)
{
    std::ostringstream os;
    os << std::fixed << std::setprecision(3) << ns / 1e6;
    return os.str();
}

std::string
FlagsText(uint8_t f)
{
    std::ostringstream os;
    os << "0x" << std::hex << std::setw(2) << std::setfill('0') << +f;
    return os.str();
}

/// "T3 LATE 86>75 fallback" / "T1 fwd 22<=25" / "D dlv 88<=100"
std::string
HopText(const TcrhHopEvent& e, uint32_t epoch)
{
    std::ostringstream os;
    os << g_rec.nodeName[e.nodeId] << " ";
    const std::string action = e.action;
    if (action == "ingress")
    {
        os << "send SL" << +e.slOut;
        return os.str();
    }
    if (e.nowU && e.deadlineU && (e.flagsIn & 0x01) == 0)
    {
        // the deadline check ran: show clock vs deadline, relative to Epoch_Base
        const uint32_t now = *e.nowU - epoch;
        const uint32_t dl = *e.deadlineU - epoch;
        os << (e.late ? "LATE " : "") << now << (e.late ? ">" : "<=") << dl << " ";
    }
    if (action == "forward")
    {
        os << "fwd";
    }
    else if (action == "deliver")
    {
        os << "dlv";
    }
    else
    {
        os << action;
    }
    return os.str();
}

} // namespace

int
main(int argc, char* argv[])
{
    std::string policyName = "greedy";
    std::string fallbackName = "routing-table";
    std::string outDir = ".";
    uint64_t t0GpsNs = 1475675898000000000ULL; // 2026-10-10T13:58:00Z, GPS = UTC + 18 s
    uint32_t probes = 40;
    uint32_t payloadBytes = 200;
    Time interval = MilliSeconds(50);
    Time slowStart = MilliSeconds(975);
    Time slowStop = MilliSeconds(1475);
    std::string slowRate = "1Mbps";
    bool pcap = true;

    CommandLine cmd(__FILE__);
    cmd.AddValue("policy", "deviation policy: greedy, continue or drop", policyName);
    cmd.AddValue("fallback", "greedy fallback: routing-table or none", fallbackName);
    cmd.AddValue("outDir", "directory for the pcaps and hops.csv", outDir);
    cmd.AddValue("t0GpsNs", "GPS ns of simulation time 0", t0GpsNs);
    cmd.AddValue("probes", "flow A probes", probes);
    cmd.AddValue("payload", "UDP payload bytes", payloadBytes);
    cmd.AddValue("interval", "time between flow A probes", interval);
    cmd.AddValue("slowStart", "when link T2-T3 slows down", slowStart);
    cmd.AddValue("slowStop", "when it recovers", slowStop);
    cmd.AddValue("slowRate", "data rate of T2 -> T3 while slow", slowRate);
    cmd.AddValue("pcap", "write a pcap per device", pcap);
    cmd.Parse(argc, argv);

    tcrh::Policy policy;
    NS_ABORT_MSG_UNLESS(tcrh::PolicyFromName(policyName, &policy), "unknown policy " << policyName);
    NS_ABORT_MSG_UNLESS(fallbackName == "routing-table" || fallbackName == "none",
                        "fallback must be routing-table or none");
    NS_ABORT_MSG_UNLESS(payloadBytes >= 5, "payload must hold the flow letter and sequence number");
    // UDP over IPv6 must carry a real checksum (RFC 8200 section 8.1)
    GlobalValue::Bind("ChecksumEnabled", BooleanValue(true));

    NodeContainer nodes;
    nodes.Create(6);
    Ptr<Node> s = nodes.Get(0);
    Ptr<Node> t1 = nodes.Get(1);
    Ptr<Node> t2 = nodes.Get(2);
    Ptr<Node> t3 = nodes.Get(3);
    Ptr<Node> d = nodes.Get(4);
    Ptr<Node> x = nodes.Get(5);
    const char* names[6] = {"S", "T1", "T2", "T3", "D", "X"};
    for (uint32_t i = 0; i < 6; ++i)
    {
        g_rec.nodeName[nodes.Get(i)->GetId()] = names[i];
    }

    InternetStackHelper stack;
    stack.SetIpv4StackInstall(false);
    stack.Install(nodes);

    TcrhHelper tcrhHelper;
    tcrhHelper.SetT0GpsNs(t0GpsNs);
    tcrhHelper.SetPolicy(policy);
    tcrhHelper.Install(s, SID_S);
    tcrhHelper.Install(t1, SID_T1);
    tcrhHelper.Install(t2, SID_T2);
    tcrhHelper.Install(t3, SID_T3);
    tcrhHelper.Install(d, SID_D);
    tcrhHelper.InstallPlain(x, SID_X); // the node WITHOUT T-CRH support

    PointToPointHelper p2p;
    p2p.SetDeviceAttribute("DataRate", StringValue("10Mbps"));
    p2p.SetChannelAttribute("Delay", StringValue("2ms"));
    tcrhHelper.Connect(s, t1, p2p);
    tcrhHelper.Connect(t1, t2, p2p);
    TcrhHelper::Link slowLink = tcrhHelper.Connect(t2, t3, p2p);
    tcrhHelper.Connect(t3, d, p2p);
    tcrhHelper.Connect(t1, x, p2p);
    tcrhHelper.PopulateStaticRoutes();

    // the source host inserts the routing header: 2.5 ms per hop at u = 0.1 ms
    Ptr<TcrhSourceShim> shim = tcrhHelper.InstallSourceShim(s);
    shim->AddRoute(tcrh::SidAddress(SID_D),
                   PORT_A,
                   {SID_T1, SID_T2, SID_T3, SID_D},
                   {2500000, 5000000, 7500000, 10000000},
                   1);
    shim->AddRoute(tcrh::SidAddress(SID_D),
                   PORT_B,
                   {SID_T1, SID_X, SID_T2, SID_T3, SID_D},
                   {2500000, 5000000, 7500000, 10000000, 12500000},
                   1);
    // the "same path, no deadline" baseline: Wireshark decodes Type 5 natively
    shim->AddCrh16Route(tcrh::SidAddress(SID_D), PORT_C, {SID_T1, SID_T2, SID_T3, SID_D});
    shim->TraceConnectWithoutContext("Ingress", MakeCallback(&OnHop));

    for (uint32_t i = 0; i < nodes.GetN(); ++i)
    {
        Ptr<Node> n = nodes.Get(i);
        Ptr<Ipv6L3Protocol> ipv6 = n->GetObject<Ipv6L3Protocol>();
        ipv6->TraceConnectWithoutContext("LocalDeliver", MakeBoundCallback(&OnLocalDeliver, n->GetId()));
        Ptr<Ipv6ExtensionTcrh> ext = TcrhHelper::GetTcrhExtension(n);
        if (ext)
        {
            ext->TraceConnectWithoutContext("Hop", MakeCallback(&OnHop));
            TcrhHelper::GetCrh16Extension(n)->TraceConnectWithoutContext("Hop", MakeCallback(&OnHop));
            if (fallbackName == "routing-table")
            {
                ext->SetFallback(MakeBoundCallback(&tcrh::RoutingTableFallback, ipv6));
            }
        }
        // a socket on the probe port of EVERY node: only D may ever receive
        Ptr<Socket> sock = Socket::CreateSocket(n, UdpSocketFactory::GetTypeId());
        sock->Bind(Inet6SocketAddress(Ipv6Address::GetAny(), PORT_A));
        if (n == d)
        {
            sock->SetRecvCallback(MakeCallback(&OnRecvAtD));
            for (uint16_t port : {PORT_B, PORT_C})
            {
                Ptr<Socket> other = Socket::CreateSocket(n, UdpSocketFactory::GetTypeId());
                other->Bind(Inet6SocketAddress(Ipv6Address::GetAny(), port));
                other->SetRecvCallback(MakeCallback(&OnRecvAtD));
            }
        }
        else
        {
            sock->SetRecvCallback(MakeBoundCallback(&OnRecvTransit, n->GetId()));
        }
    }

    Ptr<Socket> sender = Socket::CreateSocket(s, UdpSocketFactory::GetTypeId());
    sender->Bind(Inet6SocketAddress(tcrh::SidAddress(SID_S), 50000));
    for (uint32_t i = 0; i < probes; ++i)
    {
        Simulator::Schedule(MilliSeconds(100) + interval * i, &SendProbe, sender, 'A', PORT_A, i, payloadBytes);
    }
    for (uint32_t i = 0; i < 3; ++i)
    {
        Simulator::Schedule(MilliSeconds(330) + MilliSeconds(300) * i, &SendProbe, sender, 'B', PORT_B, i, payloadBytes);
        Simulator::Schedule(MilliSeconds(360) + MilliSeconds(300) * i, &SendProbe, sender, 'C', PORT_C, i, payloadBytes);
    }
    Ptr<PointToPointNetDevice> slowDev = DynamicCast<PointToPointNetDevice>(slowLink.devA);
    Simulator::Schedule(slowStart, &PointToPointNetDevice::SetDataRate, slowDev, DataRate(slowRate));
    Simulator::Schedule(slowStop, &PointToPointNetDevice::SetDataRate, slowDev, DataRate("10Mbps"));

    if (pcap)
    {
        p2p.EnablePcapAll(outDir + "/tcrh-wire-check");
    }

    std::cout << "tcrh-wire-check: T-CRH (IPv6 Routing Type 253) through ns-3.44's IPv6 stack\n"
              << "  policy " << policyName << ", fallback " << fallbackName << ", t0_gps " << t0GpsNs
              << " ns (2026-10-10T13:58:00Z), unit 0.1 ms, budget 2.5 ms per hop\n"
              << "  labels: link rates/delays MODELLED (10 Mb/s, 2 ms), slow-down MODELLED (" << slowRate
              << " from " << slowStart.As(Time::MS) << " to " << slowStop.As(Time::MS)
              << " on T2->T3), header bytes = spec v1 wire format\n"
              << "  effective policy (what a late packet really gets at T3): "
              << TcrhHelper::GetTcrhExtension(t3)->EffectivePolicyName() << "\n\n";
    tcrhHelper.PrintAddressPlan(std::cout);
    std::cout << "\nCRH-FIB of T1:\n";
    t1->GetObject<CrhFib>()->Print(std::cout);
    std::cout << "\n";

    Simulator::Stop(MilliSeconds(100) + interval * probes + Seconds(1));
    Simulator::Run();

    // ---------------------------------------------------------- per-packet summary
    std::cout << "Flow A (S -> T1 -> T2 -> T3 -> D); hop entries are clock<=deadline in 0.1 ms units"
                 " after Epoch_Base:\n";
    std::cout << " seq   sent_ms    rx_ms  lat_ms  flags@D devHop  path\n";
    uint32_t deliveredA = 0;
    uint32_t lateA = 0;
    bool devHopOk = true;
    for (uint32_t seq = 0; seq < probes; ++seq)
    {
        uint64_t uid = 0;
        for (const auto& [u, fs] : g_rec.flowSeqOfUid)
        {
            if (fs.first == 'A' && fs.second == seq)
            {
                uid = u;
            }
        }
        const std::vector<TcrhHopEvent>& evs = g_rec.eventsOfUid[uid];
        uint32_t epoch = 0;
        std::string path;
        std::string flagsAtD = "-";
        std::string devHop = "-";
        bool lateHere = false;
        for (const TcrhHopEvent& e : evs)
        {
            if (std::string(e.action) == "ingress")
            {
                epoch = e.epochBase;
            }
            path += (path.empty() ? "" : " | ") + HopText(e, epoch);
            if (std::string(e.action) == "deliver")
            {
                flagsAtD = FlagsText(e.flagsOut);
                devHop = (e.flagsOut & 0x01) ? std::to_string(+e.devHop) : "-";
                devHopOk = devHopOk && (!(e.flagsOut & 0x01) || e.devHop == 3);
            }
            lateHere = lateHere || e.late;
        }
        lateA += lateHere ? 1 : 0;
        const auto rx = g_rec.rxNs.find({'A', seq});
        const int64_t sent = g_rec.sentNs[{'A', seq}];
        std::string rxText = "lost";
        std::string latText = "-";
        if (rx != g_rec.rxNs.end())
        {
            deliveredA++;
            rxText = Ms(rx->second);
            latText = Ms(rx->second - sent);
        }
        std::printf("%4u %9s %8s %7s %8s %6s  %s\n",
                    seq,
                    Ms(sent).c_str(),
                    rxText.c_str(),
                    latText.c_str(),
                    flagsAtD.c_str(),
                    devHop.c_str(),
                    path.c_str());
    }

    std::cout << "\nFlow B (path names X, which has no T-CRH support):\n";
    for (const Record::Icmp& m : g_rec.icmpAtS)
    {
        std::cout << "  t=" << Ms(m.tNs) << " ms  S received ICMPv6 type " << +m.type << " code " << +m.code
                  << " pointer " << m.pointer << " (quoted packet: Segments Left " << +m.quotedSl << ")\n";
    }
    uint32_t paramProblems = 0;
    for (const Record::Icmp& m : g_rec.icmpAtS)
    {
        paramProblems += (m.type == 4 && m.code == 0) ? 1 : 0;
    }
    uint32_t deliveredC = 0;
    for (uint32_t i = 0; i < 3; ++i)
    {
        deliveredC += g_rec.rxNs.count({'C', i}) ? 1 : 0;
    }
    std::cout << "\nFlow C (CRH-16, Routing Type 5, same path, no deadlines): " << deliveredC
              << "/3 delivered\n";

    // ---------------------------------------------------------- counters
    std::cout << "\nPer-node counters (T-CRH extension):\n";
    for (Ptr<Node> n : {s, t1, t2, t3, d})
    {
        const TcrhCounters& c = TcrhHelper::GetTcrhExtension(n)->GetCounters();
        std::cout << "  " << std::setw(2) << g_rec.nodeName[n->GetId()] << ": processed " << c.processed
                  << ", forwarded " << c.forwarded << ", delivered " << c.delivered << ", late "
                  << c.late << ", fallback " << c.fallback << ", greedy-without-fallback "
                  << c.greedyNoFallback << ", dropped late " << c.droppedLate << "; UDP LocalDeliver "
                  << g_rec.udpToL4[n->GetId()] << "\n";
    }
    std::cout << "   X: (no T-CRH) UDP LocalDeliver " << g_rec.udpToL4[x->GetId()] << "\n";

    // ---------------------------------------------------------- hops.csv
    const std::string csvPath = outDir + "/tcrh-wire-check-hops.csv";
    std::ofstream csv(csvPath);
    csv << TcrhHopEventCsvHeader() << "\n";
    for (const TcrhHopEvent& e : g_rec.allEvents)
    {
        csv << TcrhHopEventCsv(e) << "\n";
    }
    csv.close();
    std::cout << "\nHop events: " << csvPath << " (" << g_rec.allEvents.size() << " rows)\n";
    if (pcap)
    {
        std::cout << "pcaps: " << outDir << "/tcrh-wire-check-<node>-<device>.pcap (node ids: S 0, T1 1, "
                  << "T2 2, T3 3, D 4, X 5)\n";
    }

    // ---------------------------------------------------------- self-check
    uint32_t transitL4 = 0;
    for (Ptr<Node> n : {t1, t2, t3, x})
    {
        transitL4 += g_rec.udpToL4[n->GetId()] + g_transitSocketRx[n->GetId()];
    }
    const uint32_t expectDelivered = policy == tcrh::Policy::DROP ? probes - lateA : probes;
    struct Check
    {
        const char* what;
        bool ok;
    };
    const Check checks[] = {
        {"transit nodes delivered 0 packets to UDP", transitL4 == 0},
        {"D received every probe the policy keeps", deliveredA == expectDelivered},
        {"some probes were late (the slow-down worked)", lateA > 0},
        {"every late probe delivered with DEV carries Dev Hop 3", devHopOk},
        {"S got one ICMPv6 Parameter Problem per flow-B probe", paramProblems == 3},
        {"D received the 3 CRH-16 probes of flow C", deliveredC == 3},
    };
    bool allOk = true;
    std::cout << "\nChecks:\n";
    for (const Check& c : checks)
    {
        std::cout << "  [" << (c.ok ? "ok" : "FAIL") << "] " << c.what << "\n";
        allOk = allOk && c.ok;
    }
    std::cout << "flow A: " << deliveredA << "/" << probes << " delivered, " << lateA << " late\n";
    std::cout << "wire-check: " << (allOk ? "PASS" : "FAIL") << "\n";

    Simulator::Destroy();
    return allOk ? 0 : 1;
}
