/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

/**
 * @file
 * @ingroup chronoroute
 *
 * chronoroute-leo: ChronoRoute on the REAL Starlink 53.2 deg / 463 km sub-shell
 * in ns-3, with link delays and link states that change every 100 ms and a
 * schedule that changes every second. Course milestone "LEO topology +
 * time-varying schedule in ns-3".
 *
 * Input: a scenario bundle written by `cr export bundle` (docs/bundle-format.md):
 * REAL satellite positions (SGP4 on CelesTrak elements), MODELLED Grid-4 laser
 * links and ground links, DERIVED routes and T-CRH templates.
 *
 * What runs:
 *  - every bundle node becomes an ns-3 node with IPv6 and T-CRH support
 *    (Routing Type 253 as a REAL IPv6 routing header, contrib/chronoroute);
 *  - every laser link and every ever-visible ground link becomes a stock
 *    point-to-point link (1 Gb/s, DropTail 100 packets: MODELLED) whose Delay
 *    and up/down state follow the bundle every 100 ms (leo-bundle-helper.h);
 *  - UDP probes, 100 per second x 200-byte payload, on every flow of
 *    schedule.csv. The source host's shim inserts the T-CRH of the schedule row
 *    valid at SEND time, with Epoch_Base stamped at send time: the
 *    time-varying schedule;
 *  - optional fault (--fault=1): one laser link on a scheduled path becomes
 *    "up but slow" (its data rate is cut, so a queue builds) for a while. It
 *    is written to fault_log.csv (ground truth);
 *  - deviation policy "continue": a late packet gets DEV and Dev Hop and keeps
 *    following its path (greedy fallback is a later phase).
 *
 * Output (in --outDir):
 *  - packets.csv: one row per probe: path planned and taken, arrival time,
 *    clock and deadline at every hop, DEV / Dev Hop, outcome, latency;
 *  - fault_log.csv: the fault as it was applied;
 *  - capture.pcap: T-CRH frames sent by a few nodes on one path, one file
 *    (PcapFileWrapper, DLT_PPP, nanosecond time stamps = UTC Unix time, i.e.
 *    GPS - 18 s, which is the Wireshark dissector's default time base);
 *  - anim.xml (only with --anim=1, the "NetAnim slice" run): 100-300 satellites
 *    around the fault flow's path on a world map;
 *  - run_info.json: counts, timings, peak memory, self-check results.
 *
 * The program checks its own results (see "Self-checks" at the end) and exits
 * with status 1 if any check fails.
 *
 * Example:
 *   ./ns3 run "chronoroute-leo --bundle=/tmp/cr-sa/bundles/c5-463-10s-small
 *              --outDir=/tmp/cr-sa/course/run1 --fault=1 --faultStartMs=4000
 *              --faultDurationMs=3000"
 */

#include "ns3/animation-interface.h"
#include "ns3/boolean.h"
#include "ns3/command-line.h"
#include "ns3/constant-position-mobility-model.h"
#include "ns3/global-value.h"
#include "ns3/inet6-socket-address.h"
#include "ns3/ipv6-extension-tcrh.h"
#include "ns3/ipv6-l3-protocol.h"
#include "ns3/leo-bundle-helper.h"
#include "ns3/packet.h"
#include "ns3/pcap-file-wrapper.h"
#include "ns3/point-to-point-net-device.h"
#include "ns3/random-variable-stream.h"
#include "ns3/rng-seed-manager.h"
#include "ns3/simulator.h"
#include "ns3/socket.h"
#include "ns3/string.h"
#include "ns3/tcrh-address-plan.h"
#include "ns3/tcrh-header.h"
#include "ns3/tcrh-helper.h"
#include "ns3/tcrh-source-shim.h"
#include "ns3/tcrh-timebase.h"
#include "ns3/trace-helper.h"
#include "ns3/traffic-control-layer.h"
#include "ns3/udp-socket-factory.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

using namespace ns3;
using namespace ns3::leo;

NS_LOG_COMPONENT_DEFINE("ChronorouteLeo");

namespace
{

// ---------------------------------------------------------------- constants

constexpr uint16_t PORT_SINK_BASE = 9000;   // destination port = 9000 + flow id
constexpr uint16_t PORT_SOURCE_BASE = 50000; // source port = 50000 + flow id
constexpr uint32_t PID_FLOW_FACTOR = 1000000; // probe id = flow * 10^6 + seq
constexpr uint32_t PPP_BYTES = 2;            // the point-to-point header
constexpr uint32_t IPV6_BYTES = 40;
constexpr uint32_t UDP_BYTES = 8;

/// How a probe ended.
enum class Outcome : uint8_t
{
    PENDING,          //!< nothing final seen (yet)
    DELIVERED,        //!< the destination's UDP socket got it
    NO_ROUTE,         //!< no schedule row at send time (a gap): never sent
    SEND_ERROR,       //!< the socket refused it
    DROP_LINK_DOWN,   //!< a node held it for a link that was down (spec 6 step 7)
    DROP_IFACE_DOWN,  //!< in flight when the link went down (receiving interface down)
    DROP_QUEUE,       //!< DropTail queue full
    DROP_OTHER,       //!< any other drop (reason in the detail)
};

const char*
OutcomeName(Outcome o)
{
    switch (o)
    {
    case Outcome::PENDING:
        return "pending";
    case Outcome::DELIVERED:
        return "delivered";
    case Outcome::NO_ROUTE:
        return "no_route";
    case Outcome::SEND_ERROR:
        return "send_error";
    case Outcome::DROP_LINK_DOWN:
        return "drop_link_down";
    case Outcome::DROP_IFACE_DOWN:
        return "drop_iface_down";
    case Outcome::DROP_QUEUE:
        return "drop_queue";
    case Outcome::DROP_OTHER:
        return "drop_other";
    }
    return "?";
}

/// One node a probe visited (the ingress first).
struct HopRec
{
    uint32_t node{0};       // bundle node id
    int64_t tNs{0};         // arrival (ingress: send) time, simulation ns
    uint32_t nowU{0};       // the node's unit clock then
    uint8_t hopIndex{0};    // k = NumHops - SL on arrival
    uint8_t flagsOut{0};    // T-CRH flags as it left / was delivered
    uint8_t devHop{0};      // Dev Hop as it left
};

/// Everything recorded about one probe.
struct PacketRec
{
    uint32_t flow{0};
    uint32_t seq{0};
    uint64_t uid{0};
    int64_t sendNs{0};
    const ScheduleRow* row{nullptr};
    uint32_t epochBase{0};
    bool ingressSeen{false};
    std::vector<HopRec> hops;
    int firstLateHop{-1};   // hop whose deadline check fired
    int linkDownHop{-1};    // hop that found its next link down
    Outcome outcome{Outcome::PENDING};
    uint32_t outcomeNode{0};
    int64_t outcomeNs{-1};
    std::string outcomeDetail;
    int64_t rxNs{-1};
};

/// Per-flow sending state.
struct FlowState
{
    uint32_t flow{0};
    uint32_t src{0};
    uint32_t dst{0};
    Ipv6Address dstAddr;
    uint16_t port{0};
    Ptr<Socket> sender;
    Ptr<TcrhSourceShim> shim;
    const ScheduleRow* current{nullptr};
    int64_t offsetNs{0};
    uint32_t routeChanges{0};
};

// ---------------------------------------------------------------- globals (one run)

const Bundle* g_bundle = nullptr;
LeoNetwork* g_net = nullptr;
uint32_t g_payloadBytes = 200;
std::vector<PacketRec> g_packets;
std::unordered_map<uint64_t, uint32_t> g_idxOfUid;
std::vector<FlowState> g_flows;
uint64_t g_foreignEvents = 0;      // routing-header events of packets that are not probes
uint64_t g_udpAtSatellites = 0;    // UDP deliveries at satellites (must stay 0)
uint64_t g_lateEvents = 0;
uint64_t g_lateAnomalies = 0;      // late hop events after the packet already ended
uint64_t g_doubleOutcome = 0;      // a second final outcome for one packet
Ptr<PcapFileWrapper> g_pcap;
uint64_t g_pcapFrames = 0;
AnimationInterface* g_anim = nullptr;
std::set<uint32_t> g_redNodes;     // NetAnim: nodes already painted red
struct FaultLogRow
{
    int64_t tNs;
    std::string event;
    uint64_t rateBps;
    int64_t extraDelayNs;
};
std::vector<FaultLogRow> g_faultLog;

PacketRec*
RecOfUid(uint64_t uid)
{
    auto it = g_idxOfUid.find(uid);
    return it == g_idxOfUid.end() ? nullptr : &g_packets[it->second];
}

void
SetOutcome(PacketRec& r, Outcome o, uint32_t node, const std::string& detail)
{
    if (r.outcome != Outcome::PENDING)
    {
        g_doubleOutcome++;
        return;
    }
    r.outcome = o;
    r.outcomeNode = node;
    r.outcomeNs = Simulator::Now().GetNanoSeconds();
    r.outcomeDetail = detail;
}

// ---------------------------------------------------------------- trace sinks

/// Source shim: the packet left its ground station (or could not).
void
OnIngress(const TcrhHopEvent& e)
{
    PacketRec* r = RecOfUid(e.packetUid);
    if (r == nullptr)
    {
        g_foreignEvents++;
        return;
    }
    r->ingressSeen = true;
    r->epochBase = e.epochBase;
    HopRec h;
    h.node = g_net->BundleIdOf(e.nodeId);
    h.tNs = e.tNs;
    h.nowU = e.nowU.value_or(0);
    h.hopIndex = 0;
    h.flagsOut = e.flagsOut;
    h.devHop = e.devHop;
    r->hops.push_back(h);
    if (std::strcmp(e.action, "ingress") != 0)
    {
        // the first link is down (no fallback in this phase) or no FIB entry
        if (std::strcmp(e.action, "drop_link_down") == 0)
        {
            r->linkDownHop = 0;
            SetOutcome(*r, Outcome::DROP_LINK_DOWN, h.node, "ingress");
        }
        else
        {
            SetOutcome(*r, Outcome::DROP_OTHER, h.node, e.action);
        }
    }
}

/// T-CRH extension at a node: the packet arrived there.
void
OnHop(const TcrhHopEvent& e)
{
    PacketRec* r = RecOfUid(e.packetUid);
    if (r == nullptr)
    {
        g_foreignEvents++;
        return;
    }
    const uint32_t node = g_net->BundleIdOf(e.nodeId);
    HopRec h;
    h.node = node;
    h.tNs = e.tNs;
    h.nowU = e.nowU.value_or(0);
    h.hopIndex = e.hopIndex.value_or(0);
    h.flagsOut = e.flagsOut;
    h.devHop = e.devHop;
    r->hops.push_back(h);
    if (e.late)
    {
        g_lateEvents++;
        if (r->firstLateHop >= 0 || r->outcome != Outcome::PENDING)
        {
            g_lateAnomalies++;
        }
        r->firstLateHop = h.hopIndex;
        if (g_anim && g_redNodes.insert(e.nodeId).second)
        {
            g_anim->UpdateNodeColor(e.nodeId, 255, 0, 0); // a deviation was detected here
        }
    }
    const std::string action = e.action;
    if (action == "forward" || action == "deliver")
    {
        return; // delivery is confirmed by the UDP socket
    }
    if (action == "drop_link_down")
    {
        r->linkDownHop = h.hopIndex;
        SetOutcome(*r, Outcome::DROP_LINK_DOWN, node, e.reason ? e.reason : "");
        return;
    }
    SetOutcome(*r, Outcome::DROP_OTHER, node, action);
}

/// IPv6 dropped a packet (in flight to a down interface, ...). Drops that the
/// T-CRH extension already reported also pass through here; they are ignored
/// because the packet already has its outcome.
void
OnIpv6Drop(uint32_t node,
           const Ipv6Header& /*h*/,
           Ptr<const Packet> p,
           Ipv6L3Protocol::DropReason reason,
           Ptr<Ipv6> /*ipv6*/,
           uint32_t /*iface*/)
{
    PacketRec* r = RecOfUid(p->GetUid());
    if (r == nullptr || r->outcome != Outcome::PENDING)
    {
        return;
    }
    if (reason == Ipv6L3Protocol::DROP_INTERFACE_DOWN)
    {
        r->outcome = Outcome::DROP_IFACE_DOWN;
    }
    else
    {
        r->outcome = Outcome::DROP_OTHER;
        r->outcomeDetail = "ipv6_drop_reason_" + std::to_string(static_cast<int>(reason));
    }
    r->outcomeNode = node;
    r->outcomeNs = Simulator::Now().GetNanoSeconds();
}

/// A device queue was full (DropTail).
void
OnMacTxDrop(uint32_t node, Ptr<const Packet> p)
{
    PacketRec* r = RecOfUid(p->GetUid());
    if (r == nullptr)
    {
        return;
    }
    SetOutcome(*r, Outcome::DROP_QUEUE, node, "droptail");
}

/// The traffic-control layer dropped a packet. That only happens with flow
/// control on; LeoNetwork turns it off, so this sink should stay silent, but
/// a drop here must still end the probe's record.
void
OnTcDrop(uint32_t node, Ptr<const Packet> p)
{
    PacketRec* r = RecOfUid(p->GetUid());
    if (r == nullptr)
    {
        return;
    }
    SetOutcome(*r, Outcome::DROP_QUEUE, node, "tc_layer");
}

/// Something was handed to an upper layer: count UDP at satellites (must be 0:
/// a transit node never delivers the payload of a T-CRH packet).
void
OnLocalDeliver(uint32_t node, const Ipv6Header& h, Ptr<const Packet> /*p*/, uint32_t /*iface*/)
{
    if (node < g_bundle->nSats && h.GetNextHeader() == 17)
    {
        g_udpAtSatellites++;
    }
}

/// The destination's UDP socket got probes.
void
OnRecv(uint32_t flow, Ptr<Socket> socket)
{
    Address from;
    while (Ptr<Packet> p = socket->RecvFrom(from))
    {
        PacketRec* r = RecOfUid(p->GetUid());
        uint8_t b[8];
        p->CopyData(b, 8);
        const uint32_t pid = (uint32_t(b[4]) << 24) | (uint32_t(b[5]) << 16) | (uint32_t(b[6]) << 8) | b[7];
        if (r == nullptr || std::memcmp(b, "CRT1", 4) != 0 || r->flow != flow ||
            pid != r->flow * PID_FLOW_FACTOR + r->seq)
        {
            g_foreignEvents++;
            continue;
        }
        r->rxNs = Simulator::Now().GetNanoSeconds();
        SetOutcome(*r, Outcome::DELIVERED, r->row->dstGs, "");
    }
}

/// Pcap: a probe started to leave one of the capture nodes.
void
OnPhyTxBegin(Ptr<const Packet> p)
{
    if (RecOfUid(p->GetUid()) == nullptr)
    {
        return; // only probes (there is no other traffic, but be strict)
    }
    // time stamp = UTC Unix time = t0_unix + simulation time (GPS - 18 s)
    const int64_t t = static_cast<int64_t>(g_bundle->t0UnixNs) + Simulator::Now().GetNanoSeconds();
    g_pcap->Write(NanoSeconds(t), p);
    g_pcapFrames++;
}

// ---------------------------------------------------------------- probes

/// Send probe @p seq of flow @p fi (index into g_flows).
void
SendProbe(uint32_t fi, uint32_t seq)
{
    FlowState& fs = g_flows[fi];
    const int64_t now = Simulator::Now().GetNanoSeconds();
    PacketRec rec;
    rec.flow = fs.flow;
    rec.seq = seq;
    rec.sendNs = now;
    // the schedule row valid at SEND time (rows hold for [from, to))
    const ScheduleRow* row = g_bundle->RowAt(fs.flow, now);
    rec.row = row;
    if (row == nullptr)
    {
        rec.outcome = Outcome::NO_ROUTE;
        rec.outcomeNode = fs.src;
        rec.outcomeNs = now;
        g_packets.push_back(rec);
        return;
    }
    if (row != fs.current)
    {
        // a new refresh interval: the shim now inserts the new path and budgets
        fs.shim->AddRoute(fs.dstAddr, fs.port, row->sidsFwd, row->budgetsNs, g_bundle->unitCode);
        fs.current = row;
        fs.routeChanges++;
    }
    // payload: "CRT1", probe id (u32), send time in GPS ns (u64), zeros
    std::vector<uint8_t> payload(g_payloadBytes, 0);
    std::memcpy(payload.data(), "CRT1", 4);
    const uint32_t pid = fs.flow * PID_FLOW_FACTOR + seq;
    for (int i = 0; i < 4; ++i)
    {
        payload[4 + i] = static_cast<uint8_t>(pid >> (24 - 8 * i));
    }
    const uint64_t sendGps = g_bundle->t0GpsNs + static_cast<uint64_t>(now);
    for (int i = 0; i < 8; ++i)
    {
        payload[8 + i] = static_cast<uint8_t>(sendGps >> (56 - 8 * i));
    }
    Ptr<Packet> p = Create<Packet>(payload.data(), payload.size());
    rec.uid = p->GetUid();
    g_idxOfUid[rec.uid] = static_cast<uint32_t>(g_packets.size());
    g_packets.push_back(rec);
    if (fs.sender->SendTo(p, 0, Inet6SocketAddress(fs.dstAddr, fs.port)) < 0)
    {
        SetOutcome(g_packets.back(), Outcome::SEND_ERROR, fs.src, "socket");
    }
}

// ---------------------------------------------------------------- NetAnim positions

double g_lon0 = 0;
std::vector<uint32_t> g_animNodes; // bundle ids of the built nodes

void
SetAnimPositions(uint32_t pstep)
{
    const Bundle& b = *g_bundle;
    for (uint32_t id : g_animNodes)
    {
        double lat = 0;
        double lon = 0;
        if (b.nodes[id].isSat)
        {
            const size_t at = (static_cast<size_t>(pstep) * b.nodes.size() + id) * 3;
            EcefToLatLon(b.posM[at], b.posM[at + 1], b.posM[at + 2], &lat, &lon);
        }
        else
        {
            lat = b.nodes[id].latDeg;
            lon = b.nodes[id].lonDeg;
        }
        const auto [x, y] = ProjectWorldMap(lat, lon, g_lon0);
        g_net->GetNode(id)->GetObject<ConstantPositionMobilityModel>()->SetPosition(Vector(x, y, 0));
    }
}

void
OnLinkToggle(uint32_t link, bool up)
{
    if (g_anim)
    {
        const LeoNetwork::Link& l = g_net->GetLinks()[link];
        g_anim->UpdateLinkDescription(g_net->GetNode(l.a)->GetId(),
                                      g_net->GetNode(l.b)->GetId(),
                                      up ? "up" : "DOWN (bundle)");
    }
}

// ---------------------------------------------------------------- fault

void
FaultStart(uint32_t link, DataRate slow, int64_t extraNs)
{
    g_net->SetLinkRate(link, slow);
    if (extraNs > 0)
    {
        g_net->SetLinkExtraDelay(link, extraNs);
    }
    g_faultLog.push_back({Simulator::Now().GetNanoSeconds(), "slow_start", slow.GetBitRate(), extraNs});
    if (g_anim)
    {
        const LeoNetwork::Link& l = g_net->GetLinks()[link];
        std::ostringstream os;
        os << "DEGRADED " << slow.GetBitRate() << " b/s (still UP)";
        g_anim->UpdateLinkDescription(g_net->GetNode(l.a)->GetId(), g_net->GetNode(l.b)->GetId(), os.str());
    }
}

void
FaultStop(uint32_t link, DataRate normal)
{
    g_net->SetLinkRate(link, normal);
    g_net->SetLinkExtraDelay(link, 0);
    g_faultLog.push_back({Simulator::Now().GetNanoSeconds(), "slow_end", normal.GetBitRate(), 0});
    if (g_anim)
    {
        const LeoNetwork::Link& l = g_net->GetLinks()[link];
        g_anim->UpdateLinkDescription(g_net->GetNode(l.a)->GetId(), g_net->GetNode(l.b)->GetId(), "up");
    }
}

// ---------------------------------------------------------------- output helpers

std::string
JsonStr(const std::string& s)
{
    std::string out = "\"";
    for (char c : s)
    {
        if (c == '"' || c == '\\')
        {
            out += '\\';
        }
        out += c;
    }
    return out + "\"";
}

/// Strings joined with a separator (a std::set comes out sorted, so the text is deterministic).
std::string
JoinStrings(const std::set<std::string>& items, const char* sep)
{
    std::string out;
    for (const std::string& s : items)
    {
        out += (out.empty() ? "" : sep) + s;
    }
    return out;
}

/// A list as one CSV field: space-separated (the bundle's list convention).
template <typename T>
std::string
Join(const std::vector<T>& v, const char* sep = " ")
{
    std::ostringstream os;
    for (size_t i = 0; i < v.size(); ++i)
    {
        os << (i ? sep : "") << +v[i];
    }
    return os.str();
}

/// A list for a JSON array.
template <typename T>
std::string
JoinComma(const std::vector<T>& v)
{
    return Join(v, ", ");
}

/// Peak resident set size of this process in kB (Linux /proc), 0 if unknown.
uint64_t
PeakRssKb()
{
    std::ifstream f("/proc/self/status");
    std::string line;
    while (std::getline(f, line))
    {
        if (line.rfind("VmHWM:", 0) == 0)
        {
            return std::strtoull(line.c_str() + 6, nullptr, 10);
        }
    }
    return 0;
}

double
SecondsSince(std::chrono::steady_clock::time_point t)
{
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - t).count();
}

} // namespace

int
main(int argc, char* argv[])
{
    const auto wallStart = std::chrono::steady_clock::now();
    std::string bundleDir;
    std::string outDir;
    uint32_t seed = 1;
    bool fault = false;
    uint32_t faultFlow = 0;
    int64_t faultIslArg = -1;
    int64_t faultStartMs = 20000;
    int64_t faultDurationMs = 20000;
    std::string faultRate = "200kbps";
    int64_t faultExtraDelayNs = 0;
    std::string policyName = "continue";
    uint32_t probeRate = 100;
    uint32_t payloadBytes = 200;
    std::string dataRate = "1Gbps";
    std::string queueSize = "100p";
    int64_t drainMs = 2000;
    bool pcap = true;
    std::string pcapNodesArg;
    bool anim = false;
    uint32_t animMaxSats = 200;
    int64_t animFromMs = -1;
    int64_t animToMs = -1;

    CommandLine cmd(__FILE__);
    cmd.AddValue("bundle", "scenario bundle directory (cr export bundle)", bundleDir);
    cmd.AddValue("outDir", "output directory (must exist)", outDir);
    cmd.AddValue("seed", "ns-3 RngRun: draws each flow's probe start offset", seed);
    cmd.AddValue("fault", "slow down one laser link on a scheduled path", fault);
    cmd.AddValue("faultFlow", "flow whose path at the fault start holds the slowed link", faultFlow);
    cmd.AddValue("faultIsl", "ISL id to slow down (-1: ChooseFaultIsl rule)", faultIslArg);
    cmd.AddValue("faultStartMs", "fault start, ms after t0", faultStartMs);
    cmd.AddValue("faultDurationMs", "fault duration, ms", faultDurationMs);
    cmd.AddValue("faultRate", "data rate of the slowed link (both directions)", faultRate);
    cmd.AddValue("faultExtraDelayNs", "extra one-way delay on the slowed link, ns", faultExtraDelayNs);
    cmd.AddValue("policy", "deviation policy: continue, greedy or drop", policyName);
    cmd.AddValue("probeRate", "probes per second per flow (must divide 10^9)", probeRate);
    cmd.AddValue("payload", "UDP payload bytes per probe (>= 16)", payloadBytes);
    cmd.AddValue("dataRate", "data rate of every link", dataRate);
    cmd.AddValue("queueSize", "DropTail size of every device queue", queueSize);
    cmd.AddValue("drainMs", "simulated time after the last probe", drainMs);
    cmd.AddValue("pcap", "write capture.pcap", pcap);
    cmd.AddValue("pcapNodes", "bundle node ids to capture at, comma separated (default: auto)", pcapNodesArg);
    cmd.AddValue("anim", "NetAnim slice run: build only satellites around the fault flow", anim);
    cmd.AddValue("animMaxSats", "satellites in the NetAnim slice (100-300)", animMaxSats);
    cmd.AddValue("animFromMs", "slice window start, ms (default 0)", animFromMs);
    cmd.AddValue("animToMs", "slice window end, ms (default: the bundle window)", animToMs);
    cmd.Parse(argc, argv);

    NS_ABORT_MSG_IF(bundleDir.empty() || outDir.empty(), "--bundle and --outDir are required");
    tcrh::Policy policy;
    NS_ABORT_MSG_UNLESS(tcrh::PolicyFromName(policyName, &policy), "unknown policy " << policyName);
    NS_ABORT_MSG_UNLESS(probeRate > 0 && 1000000000ULL % probeRate == 0,
                        "probeRate must divide 10^9 so probe times are whole ns");
    NS_ABORT_MSG_UNLESS(payloadBytes >= 16, "payload must hold CRT1, the probe id and the send time");
    g_payloadBytes = payloadBytes;
    // UDP over IPv6 must carry a real checksum (RFC 8200 section 8.1), and
    // Wireshark flags zero checksums
    GlobalValue::Bind("ChecksumEnabled", BooleanValue(true));
    RngSeedManager::SetSeed(1);
    RngSeedManager::SetRun(seed);

    // ------------------------------------------------------------ the bundle
    auto t = std::chrono::steady_clock::now();
    const Bundle bundle = Bundle::Load(bundleDir, anim);
    g_bundle = &bundle;
    const double loadS = SecondsSince(t);
    const int64_t windowNs = bundle.windowMs * 1000000;
    std::cout << "chronoroute-leo: bundle " << bundleDir << "\n  " << bundle.nodes.size() << " nodes ("
              << bundle.nSats << " satellites), " << bundle.isls.size() << " laser links, "
              << bundle.gslPairs.size() << " ground-link pairs, " << bundle.nSteps << " steps of "
              << bundle.stepMs << " ms, " << bundle.schedule.size()
              << " schedule rows (every T-CRH template rebuilt byte-identical by the C++ encoder)\n"
              << "  t0_gps_ns " << bundle.t0GpsNs << ", t0_unix_ns " << bundle.t0UnixNs << ", unit code "
              << +bundle.unitCode << "; load " << std::fixed << std::setprecision(2) << loadS << " s\n";

    // ------------------------------------------------------------ the fault link
    // chosen in EVERY run (also without the fault), so the paired no-fault run
    // can tag the same packets
    const int64_t faultStopMs = faultStartMs + faultDurationMs;
    NS_ABORT_MSG_UNLESS(faultStartMs >= 0 && faultDurationMs > 0 && faultStopMs <= bundle.windowMs,
                        "the fault must lie inside the bundle window");
    const uint32_t faultIsl = faultIslArg >= 0
                                  ? static_cast<uint32_t>(faultIslArg)
                                  : ChooseFaultIsl(bundle, faultFlow, faultStartMs, faultStopMs);
    NS_ABORT_MSG_UNLESS(faultIsl < bundle.isls.size(), "no ISL " << faultIsl);
    const BundleIsl& fIsl = bundle.isls[faultIsl];

    // ------------------------------------------------------------ what to build
    std::vector<uint32_t> flows = bundle.Flows();
    std::vector<bool> include;
    int64_t sendFromNs = 0;
    int64_t sendToNs = windowNs;
    if (anim)
    {
        if (animFromMs < 0)
        {
            animFromMs = 0;
        }
        if (animToMs < 0)
        {
            animToMs = bundle.windowMs;
        }
        NS_ABORT_MSG_UNLESS(animFromMs < animToMs && animToMs <= bundle.windowMs, "bad slice window");
        NS_ABORT_MSG_UNLESS(animMaxSats >= 2, "animMaxSats too small");
        // only the fault flow, only inside the window: its paths there use
        // slice satellites only
        flows = {faultFlow};
        sendFromNs = animFromMs * 1000000;
        sendToNs = animToMs * 1000000;
        const std::vector<uint32_t> sats =
            SelectSliceSatellites(bundle, faultFlow, animFromMs, animToMs, animMaxSats);
        include.assign(bundle.nodes.size(), false);
        for (uint32_t s : sats)
        {
            include[s] = true;
        }
        include[fIsl.a] = true;
        include[fIsl.b] = true;
        const auto [src, dst] = bundle.FlowEnds(faultFlow);
        include[src] = true;
        include[dst] = true;
    }

    LeoNetwork::Config cfg;
    cfg.dataRate = dataRate;
    cfg.queueSize = queueSize;
    cfg.policy = policy;
    t = std::chrono::steady_clock::now();
    LeoNetwork net(bundle, cfg);
    g_net = &net;
    net.Build(anim ? &include : nullptr);
    // the topology events go FIRST, so at a tie the new link state is in force
    net.ScheduleSteps();
    const double buildS = SecondsSince(t);

    bool idsMatch = true;
    uint32_t nodesBuilt = 0;
    uint32_t satsBuilt = 0;
    for (const BundleNode& bn : bundle.nodes)
    {
        Ptr<Node> n = net.GetNode(bn.id);
        if (!n)
        {
            continue;
        }
        nodesBuilt++;
        satsBuilt += bn.isSat ? 1 : 0;
        idsMatch = idsMatch && n->GetId() == bn.id;
    }
    uint32_t islLinks = 0;
    for (const LeoNetwork::Link& l : net.GetLinks())
    {
        islLinks += l.isIsl ? 1 : 0;
    }
    const uint32_t gslLinks = static_cast<uint32_t>(net.GetLinks().size()) - islLinks;
    const int32_t faultLink = net.LinkOfIsl(faultIsl);
    NS_ABORT_MSG_IF(faultLink < 0, "the fault link was not built");
    std::cout << "  built " << nodesBuilt << " nodes (" << satsBuilt << " satellites), " << islLinks
              << " laser links + " << gslLinks << " ground links, 1 link = stock PointToPointChannel, "
              << dataRate << ", DropTail " << queueSize << " [MODELLED]; build " << buildS << " s\n";
    std::cout << "  fault link: ISL " << faultIsl << " (" << bundle.nodes[fIsl.a].name << " <-> "
              << bundle.nodes[fIsl.b].name << ", " << (fIsl.cross ? "cross" : "intra")
              << "-plane), on flow " << faultFlow << "'s path at " << faultStartMs << " ms; "
              << (fault ? "slowed to " + faultRate : std::string("NOT slowed (paired no-fault run)"))
              << "\n";

    // ------------------------------------------------------------ traces
    // What every node really does with a late packet (a "greedy" node without
    // a fallback function behaves as "continue"); written to run_info.json.
    std::set<std::string> effectivePolicies;
    for (const BundleNode& bn : bundle.nodes)
    {
        Ptr<Node> n = net.GetNode(bn.id);
        if (!n)
        {
            continue;
        }
        effectivePolicies.insert(TcrhHelper::GetTcrhExtension(n)->EffectivePolicyName());
        TcrhHelper::GetTcrhExtension(n)->TraceConnectWithoutContext("Hop", MakeCallback(&OnHop));
        Ptr<Ipv6L3Protocol> ipv6 = n->GetObject<Ipv6L3Protocol>();
        ipv6->TraceConnectWithoutContext("Drop", MakeBoundCallback(&OnIpv6Drop, bn.id));
        ipv6->TraceConnectWithoutContext("LocalDeliver", MakeBoundCallback(&OnLocalDeliver, bn.id));
        n->GetObject<TrafficControlLayer>()->TraceConnectWithoutContext("TcDrop",
                                                                        MakeBoundCallback(&OnTcDrop, bn.id));
        for (uint32_t d = 0; d < n->GetNDevices(); ++d)
        {
            Ptr<PointToPointNetDevice> dev = DynamicCast<PointToPointNetDevice>(n->GetDevice(d));
            if (dev)
            {
                dev->TraceConnectWithoutContext("MacTxDrop", MakeBoundCallback(&OnMacTxDrop, bn.id));
            }
        }
    }

    // ------------------------------------------------------------ flows
    // every flow's start offset is drawn (in flow order) even if the flow is
    // not sent, so a slice run's probes are sent at the same instants as the
    // full run's
    Ptr<UniformRandomVariable> rv = CreateObject<UniformRandomVariable>();
    rv->SetStream(0);
    const int64_t intervalNs = 1000000000LL / probeRate;
    std::map<uint32_t, int64_t> offsetOf;
    for (uint32_t f : bundle.Flows())
    {
        offsetOf[f] = static_cast<int64_t>(rv->GetInteger(0, static_cast<uint32_t>(intervalNs - 1)));
    }
    std::map<uint32_t, Ptr<TcrhSourceShim>> shimOf;
    for (uint32_t f : flows)
    {
        NS_ABORT_MSG_UNLESS(f < 1000, "flow ids above 999 do not fit the port plan");
        const auto [src, dst] = bundle.FlowEnds(f);
        FlowState fs;
        fs.flow = f;
        fs.src = src;
        fs.dst = dst;
        fs.dstAddr = tcrh::SidAddress(bundle.nodes[dst].sid);
        fs.port = static_cast<uint16_t>(PORT_SINK_BASE + f);
        fs.offsetNs = offsetOf[f];
        if (!shimOf.count(src))
        {
            shimOf[src] = net.GetTcrhHelper().InstallSourceShim(net.GetNode(src));
            shimOf[src]->TraceConnectWithoutContext("Ingress", MakeCallback(&OnIngress));
        }
        fs.shim = shimOf[src];
        fs.sender = Socket::CreateSocket(net.GetNode(src), UdpSocketFactory::GetTypeId());
        // bound to the station's SID address: UDP then needs no routing table
        NS_ABORT_MSG_UNLESS(fs.sender->Bind(Inet6SocketAddress(tcrh::SidAddress(bundle.nodes[src].sid),
                                                               static_cast<uint16_t>(PORT_SOURCE_BASE + f))) == 0,
                            "cannot bind the probe sender of flow " << f);
        Ptr<Socket> sink = Socket::CreateSocket(net.GetNode(dst), UdpSocketFactory::GetTypeId());
        NS_ABORT_MSG_UNLESS(sink->Bind(Inet6SocketAddress(Ipv6Address::GetAny(), fs.port)) == 0,
                            "cannot bind the sink of flow " << f);
        sink->SetRecvCallback(MakeBoundCallback(&OnRecv, f));
        g_flows.push_back(fs);
    }
    uint64_t scheduledProbes = 0;
    for (uint32_t fi = 0; fi < g_flows.size(); ++fi)
    {
        // probe n at offset + n * interval; seq = n in every mode
        for (int64_t tp = g_flows[fi].offsetNs, n = 0; tp < sendToNs; tp += intervalNs, ++n)
        {
            if (tp >= sendFromNs)
            {
                Simulator::Schedule(NanoSeconds(tp), &SendProbe, fi, static_cast<uint32_t>(n));
                scheduledProbes++;
            }
        }
    }
    g_packets.reserve(scheduledProbes);

    // ------------------------------------------------------------ fault events
    if (fault)
    {
        Simulator::Schedule(MilliSeconds(faultStartMs),
                            &FaultStart,
                            static_cast<uint32_t>(faultLink),
                            DataRate(faultRate),
                            faultExtraDelayNs);
        Simulator::Schedule(MilliSeconds(faultStopMs), &FaultStop, static_cast<uint32_t>(faultLink), DataRate(dataRate));
    }

    // ------------------------------------------------------------ pcap
    std::vector<uint32_t> captureNodes;
    if (pcap)
    {
        if (!pcapNodesArg.empty())
        {
            std::istringstream is(pcapNodesArg);
            std::string tok;
            while (std::getline(is, tok, ','))
            {
                captureNodes.push_back(static_cast<uint32_t>(std::stoul(tok)));
            }
        }
        else
        {
            // a few nodes on the fault flow's path at the fault start: the
            // source station, both ends of the fault link, the last satellite
            const ScheduleRow* row = bundle.RowAt(faultFlow, faultStartMs * 1000000);
            NS_ABORT_MSG_UNLESS(row, "no path for the capture nodes");
            const std::vector<uint32_t>& pn = row->pathNodes;
            uint32_t up = fIsl.a;
            uint32_t down = fIsl.b;
            for (uint32_t n : pn)
            {
                if (n == fIsl.b)
                {
                    up = fIsl.b;
                    down = fIsl.a;
                    break;
                }
                if (n == fIsl.a)
                {
                    break;
                }
            }
            for (uint32_t n : {pn.front(), up, down, pn[pn.size() - 2]})
            {
                if (std::find(captureNodes.begin(), captureNodes.end(), n) == captureNodes.end())
                {
                    captureNodes.push_back(n);
                }
            }
        }
        g_pcap = CreateObject<PcapFileWrapper>();
        g_pcap->SetAttribute("NanosecMode", BooleanValue(true));
        g_pcap->Open(outDir + "/capture.pcap", std::ios::out | std::ios::binary);
        g_pcap->Init(PcapHelper::DLT_PPP);
        for (uint32_t id : captureNodes)
        {
            Ptr<Node> n = net.GetNode(id);
            NS_ABORT_MSG_UNLESS(n, "capture node " << id << " was not built");
            for (uint32_t d = 0; d < n->GetNDevices(); ++d)
            {
                Ptr<PointToPointNetDevice> dev = DynamicCast<PointToPointNetDevice>(n->GetDevice(d));
                if (dev)
                {
                    dev->TraceConnectWithoutContext("PhyTxBegin", MakeCallback(&OnPhyTxBegin));
                }
            }
        }
    }

    // ------------------------------------------------------------ NetAnim slice
    std::unique_ptr<AnimationInterface> animIf;
    if (anim)
    {
        const auto [src, dst] = bundle.FlowEnds(faultFlow);
        // map centre between the two cities, so the path never crosses the map edge
        const double a1 = bundle.nodes[src].lonDeg * M_PI / 180.0;
        const double a2 = bundle.nodes[dst].lonDeg * M_PI / 180.0;
        g_lon0 = std::atan2(std::sin(a1) + std::sin(a2), std::cos(a1) + std::cos(a2)) * 180.0 / M_PI;
        for (const BundleNode& bn : bundle.nodes)
        {
            Ptr<Node> n = net.GetNode(bn.id);
            if (n)
            {
                n->AggregateObject(CreateObject<ConstantPositionMobilityModel>());
                g_animNodes.push_back(bn.id);
            }
        }
        SetAnimPositions(0);
        for (uint32_t ps = 1; ps < bundle.nPosSteps; ++ps)
        {
            Simulator::Schedule(MilliSeconds(static_cast<uint64_t>(ps) * bundle.positionStepMs),
                                &SetAnimPositions,
                                ps);
        }
        // constructed after the links exist and before any link goes down:
        // AnimationInterface reads every interface's address when it starts
        animIf = std::make_unique<AnimationInterface>(outDir + "/anim.xml");
        g_anim = animIf.get();
        g_anim->SetMobilityPollInterval(Seconds(1));
        g_anim->EnablePacketMetadata(true);
        g_anim->SetStartTime(MilliSeconds(animFromMs));
        g_anim->SetStopTime(MilliSeconds(animToMs + drainMs));
        for (uint32_t id : g_animNodes)
        {
            const uint32_t nid = net.GetNode(id)->GetId();
            const BundleNode& bn = bundle.nodes[id];
            g_anim->UpdateNodeDescription(nid, bn.name + " SID " + std::to_string(bn.sid));
            if (bn.isSat)
            {
                g_anim->UpdateNodeColor(nid, 40, 90, 200);
                g_anim->UpdateNodeSize(nid, 12, 12);
            }
            else
            {
                g_anim->UpdateNodeColor(nid, 0, 160, 0);
                g_anim->UpdateNodeSize(nid, 30, 30);
            }
        }
        net.SetToggleCallback(MakeCallback(&OnLinkToggle));
    }

    // ------------------------------------------------------------ run
    const int64_t stopNs = sendToNs + drainMs * 1000000;
    std::cout << "  flows " << flows.size() << ", " << scheduledProbes << " probes (" << probeRate
              << "/s x " << payloadBytes << " B payload) in [" << sendFromNs / 1000000 << ", "
              << sendToNs / 1000000 << ") ms; policy " << policyName << "; stop at " << stopNs / 1000000
              << " ms\n"
              << std::flush;
    Simulator::Stop(NanoSeconds(stopNs));
    t = std::chrono::steady_clock::now();
    Simulator::Run();
    const double runS = SecondsSince(t);
    animIf.reset();
    g_anim = nullptr;
    if (g_pcap)
    {
        g_pcap->Close();
    }

    // ------------------------------------------------------------ per packet
    t = std::chrono::steady_clock::now();
    const uint32_t fa = fIsl.a;
    const uint32_t fb = fIsl.b;
    std::map<std::string, uint64_t> outcomeCount;
    uint64_t delivered = 0;
    uint64_t latePackets = 0;
    uint64_t pathMismatchDelivered = 0;
    uint64_t epochMismatch = 0;
    uint64_t lateNotAtFaultLink = 0;
    uint64_t pending = 0;
    std::ofstream csv(outDir + "/packets.csv");
    csv << "flow_id,seq,uid,send_ns,row_from_ms,num_hops,epoch_base,wire_bytes,planned_path,taken_path,"
           "hop_t_ns,hop_now_u,hop_deadline_u,hop_margin_u,first_late_hop,link_down_hop,dev,dev_hop,"
           "outcome,outcome_node,outcome_t_ns,rx_ns,latency_ns,fault_link,fault_link_t_ns,phase\n";
    for (PacketRec& r : g_packets)
    {
        outcomeCount[OutcomeName(r.outcome)]++;
        pending += r.outcome == Outcome::PENDING ? 1 : 0;
        const ScheduleRow* row = r.row;
        const size_t h = row ? row->sidsFwd.size() : 0;
        std::vector<uint32_t> taken;
        std::vector<int64_t> ht;
        std::vector<uint32_t> nowU;
        std::vector<uint32_t> deadline;
        std::vector<int32_t> margin;
        for (size_t i = 0; i < r.hops.size(); ++i)
        {
            taken.push_back(r.hops[i].node);
            if (i == 0)
            {
                continue;
            }
            const HopRec& hr = r.hops[i];
            ht.push_back(hr.tNs);
            nowU.push_back(hr.nowU);
            // D_k = Epoch_Base + d_1 + ... + d_k (mod 2^32), spec section 5
            const uint32_t dk = r.epochBase + row->cumDeltaU[hr.hopIndex - 1];
            deadline.push_back(dk);
            margin.push_back(tcrh::SerialDiff(dk, hr.nowU)); // > 0: early
        }
        uint8_t dev = 0;
        uint8_t devHop = 0;
        if (!r.hops.empty())
        {
            dev = r.hops.back().flagsOut & TcrhHeader::FLAG_DEV;
            devHop = r.hops.back().devHop;
        }
        if (r.outcome == Outcome::DELIVERED)
        {
            delivered++;
            if (taken != row->pathNodes)
            {
                pathMismatchDelivered++;
            }
        }
        if (r.ingressSeen)
        {
            const uint32_t eb = tcrh::EpochBaseAtIngress(bundle.t0GpsNs + static_cast<uint64_t>(r.sendNs),
                                                         bundle.unitCode);
            epochMismatch += eb == r.epochBase ? 0 : 1;
        }
        // did it use the (would-be) slowed link?
        std::string faultUse;
        int64_t faultT = -1;
        int downstreamIndex = -1;
        if (row)
        {
            for (size_t i = 0; i < taken.size(); ++i)
            {
                const uint32_t u = taken[i];
                if (u != fa && u != fb)
                {
                    continue;
                }
                const uint32_t other = u == fa ? fb : fa;
                const auto pos = std::find(row->pathNodes.begin(), row->pathNodes.end(), u);
                if (pos + 1 >= row->pathNodes.end() || *(pos + 1) != other)
                {
                    continue; // not heading over the fault link from here
                }
                faultT = r.hops[i].tNs;
                downstreamIndex = static_cast<int>(pos - row->pathNodes.begin()) + 1;
                if (i + 1 < taken.size())
                {
                    faultUse = "crossed";
                }
                else if (r.outcome == Outcome::DROP_QUEUE && r.outcomeNode == u)
                {
                    faultUse = "queue_drop";
                }
                else
                {
                    faultUse = std::string("entered_") + OutcomeName(r.outcome);
                }
                break;
            }
        }
        if (r.firstLateHop >= 0)
        {
            latePackets++;
            if (faultUse != "crossed" || r.firstLateHop != downstreamIndex)
            {
                lateNotAtFaultLink++;
            }
        }
        const char* phase = r.sendNs < faultStartMs * 1000000   ? "before"
                            : r.sendNs < faultStopMs * 1000000 ? "during"
                                                               : "after";
        const uint32_t wire = row ? PPP_BYTES + IPV6_BYTES + TcrhHeader::SizeForHops(h) + UDP_BYTES + payloadBytes : 0;
        csv << r.flow << "," << r.seq << "," << r.uid << "," << r.sendNs << ","
            << (row ? std::to_string(row->fromMs) : "") << "," << h << "," << r.epochBase << "," << wire
            << "," << (row ? Join(row->pathNodes) : "") << "," << Join(taken) << "," << Join(ht) << ","
            << Join(nowU) << "," << Join(deadline) << "," << Join(margin) << ","
            << (r.firstLateHop >= 0 ? std::to_string(r.firstLateHop) : "") << ","
            << (r.linkDownHop >= 0 ? std::to_string(r.linkDownHop) : "") << "," << +dev << "," << +devHop
            << "," << OutcomeName(r.outcome) << "," << r.outcomeNode << "," << r.outcomeNs << ","
            << (r.rxNs >= 0 ? std::to_string(r.rxNs) : "") << ","
            << (r.rxNs >= 0 ? std::to_string(r.rxNs - r.sendNs) : "") << "," << faultUse << ","
            << (faultT >= 0 ? std::to_string(faultT) : "") << "," << phase << "\n";
    }
    csv.close();

    // ------------------------------------------------------------ fault log (ground truth)
    std::ofstream flog(outDir + "/fault_log.csv");
    flog << "t_ns,event,isl_id,node_a,node_b,sid_a,sid_b,name_a,name_b,data_rate_bps,extra_delay_ns,label\n";
    for (const FaultLogRow& fr : g_faultLog)
    {
        flog << fr.tNs << "," << fr.event << "," << faultIsl << "," << fIsl.a << "," << fIsl.b << ","
             << bundle.nodes[fIsl.a].sid << "," << bundle.nodes[fIsl.b].sid << ","
             << bundle.nodes[fIsl.a].name << "," << bundle.nodes[fIsl.b].name << "," << fr.rateBps << ","
             << fr.extraDelayNs << ",MODELLED\n";
    }
    flog.close();
    const double writeS = SecondsSince(t);

    // ------------------------------------------------------------ self-checks
    struct Check
    {
        std::string what;
        bool ok;
    };
    std::vector<Check> checks = {
        {"every schedule row's T-CRH template rebuilt byte-identical in C++ (Bundle::Load)", true},
        {"every probe has exactly one final outcome", pending == 0 && g_doubleOutcome == 0},
        {"no routing-header event or reception of a non-probe packet", g_foreignEvents == 0},
        {"transit satellites delivered 0 packets to UDP", g_udpAtSatellites == 0},
        {"every delivered probe took exactly its planned path", pathMismatchDelivered == 0},
        {"every probe's Epoch_Base = ceil((t0_gps + send) / u) mod 2^32", epochMismatch == 0},
        {"no deadline miss after a probe had already ended", g_lateAnomalies == 0},
    };
    if (!anim)
    {
        checks.push_back({"ns-3 node id == bundle node id for every node", idsMatch});
    }
    if (fault)
    {
        checks.push_back({"the fault made probes late", latePackets > 0});
        checks.push_back({"every late probe crossed the slowed link and was caught at its far end",
                          lateNotAtFaultLink == 0});
    }
    else
    {
        checks.push_back({"no probe was late without a fault", latePackets == 0});
    }
    bool allOk = true;
    std::cout << "\nSelf-checks:\n";
    for (const Check& c : checks)
    {
        std::cout << "  [" << (c.ok ? "ok" : "FAIL") << "] " << c.what << "\n";
        allOk = allOk && c.ok;
    }

    // ------------------------------------------------------------ summary
    std::cout << "\nPer flow (sent / delivered / late / link-down drops / queue drops / route changes):\n";
    for (const FlowState& fs : g_flows)
    {
        uint64_t sent = 0;
        uint64_t dl = 0;
        uint64_t late = 0;
        uint64_t ld = 0;
        uint64_t qd = 0;
        for (const PacketRec& r : g_packets)
        {
            if (r.flow != fs.flow)
            {
                continue;
            }
            sent++;
            dl += r.outcome == Outcome::DELIVERED ? 1 : 0;
            late += r.firstLateHop >= 0 ? 1 : 0;
            ld += r.outcome == Outcome::DROP_LINK_DOWN || r.outcome == Outcome::DROP_IFACE_DOWN ? 1 : 0;
            qd += r.outcome == Outcome::DROP_QUEUE ? 1 : 0;
        }
        std::cout << "  flow " << std::setw(2) << fs.flow << "  " << std::setw(12)
                  << bundle.nodes[fs.src].name << " -> " << std::setw(12) << std::left
                  << bundle.nodes[fs.dst].name << std::right << "  " << sent << " / " << dl << " / "
                  << late << " / " << ld << " / " << qd << " / " << fs.routeChanges << "\n";
    }
    const uint64_t rss = PeakRssKb();
    const LeoNetwork::Stats& st = net.GetStats();
    std::cout << "\nOutcomes:";
    for (const auto& [k, v] : outcomeCount)
    {
        std::cout << " " << k << " " << v << ";";
    }
    std::cout << "\nTopology: " << st.stepsApplied << " steps applied, " << st.delayUpdates
              << " Delay writes, " << st.downEvents << " link-down and " << st.upEvents
              << " link-up events\n";
    if (pcap)
    {
        std::cout << "pcap: " << outDir << "/capture.pcap, " << g_pcapFrames << " frames from nodes "
                  << Join(captureNodes) << "\n";
    }
    std::cout << "Wall time: load " << loadS << " s, build " << buildS << " s, run " << runS
              << " s, write " << writeS << " s, total " << SecondsSince(wallStart)
              << " s; peak RSS " << rss / 1024.0 << " MiB\n";
    std::cout << "chronoroute-leo: " << (allOk ? "PASS" : "FAIL") << "\n";

    // ------------------------------------------------------------ run_info.json
    std::ofstream ri(outDir + "/run_info.json");
    ri << "{\n"
       << "  \"program\": \"chronoroute-leo\",\n"
       << "  \"mode\": " << JsonStr(anim ? "anim-slice" : "full") << ",\n"
       << "  \"bundle\": " << JsonStr(bundleDir) << ",\n"
       << "  \"seed_rng_run\": " << seed << ",\n"
       << "  \"t0_gps_ns\": " << bundle.t0GpsNs << ",\n"
       << "  \"t0_unix_ns\": " << bundle.t0UnixNs << ",\n"
       << "  \"window_ms\": " << bundle.windowMs << ",\n"
       << "  \"step_ms\": " << bundle.stepMs << ",\n"
       << "  \"unit_code\": " << +bundle.unitCode << ",\n"
       << "  \"nodes_built\": " << nodesBuilt << ",\n"
       << "  \"satellites_built\": " << satsBuilt << ",\n"
       << "  \"isl_links\": " << islLinks << ",\n"
       << "  \"gsl_links\": " << gslLinks << ",\n"
       << "  \"data_rate\": " << JsonStr(dataRate) << ",\n"
       << "  \"queue\": " << JsonStr("DropTail " + queueSize + " per device, no queue disc") << ",\n"
       << "  \"policy\": " << JsonStr(policyName) << ",\n"
       << "  \"effective_policy\": " << JsonStr(JoinStrings(effectivePolicies, "; ")) << ",\n"
       << "  \"probe_rate_pps\": " << probeRate << ",\n"
       << "  \"payload_bytes\": " << payloadBytes << ",\n"
       << "  \"send_window_ns\": [" << sendFromNs << ", " << sendToNs << "],\n"
       << "  \"stop_ns\": " << stopNs << ",\n"
       << "  \"flows\": [";
    for (size_t i = 0; i < g_flows.size(); ++i)
    {
        const FlowState& fs = g_flows[i];
        ri << (i ? ", " : "") << "{\"flow_id\": " << fs.flow << ", \"src\": " << JsonStr(bundle.nodes[fs.src].name)
           << ", \"dst\": " << JsonStr(bundle.nodes[fs.dst].name) << ", \"offset_ns\": " << fs.offsetNs
           << ", \"route_changes\": " << fs.routeChanges << "}";
    }
    ri << "],\n"
       << "  \"fault\": {\"enabled\": " << (fault ? "true" : "false") << ", \"isl_id\": " << faultIsl
       << ", \"node_a\": " << fIsl.a << ", \"node_b\": " << fIsl.b << ", \"name_a\": "
       << JsonStr(bundle.nodes[fIsl.a].name) << ", \"name_b\": " << JsonStr(bundle.nodes[fIsl.b].name)
       << ", \"sid_a\": " << bundle.nodes[fIsl.a].sid << ", \"sid_b\": " << bundle.nodes[fIsl.b].sid
       << ", \"flow\": " << faultFlow << ", \"start_ms\": " << faultStartMs << ", \"stop_ms\": " << faultStopMs
       << ", \"rate\": " << JsonStr(fault ? faultRate : std::string("unchanged"))
       << ", \"extra_delay_ns\": " << (fault ? faultExtraDelayNs : 0)
       << ", \"chosen_by\": " << JsonStr(faultIslArg >= 0 ? "--faultIsl" : "ChooseFaultIsl rule") << "},\n"
       << "  \"capture_nodes\": [" << JoinComma(captureNodes) << "],\n"
       << "  \"pcap_frames\": " << g_pcapFrames << ",\n"
       << "  \"probes\": " << g_packets.size() << ",\n"
       << "  \"delivered\": " << delivered << ",\n"
       << "  \"late_packets\": " << latePackets << ",\n"
       << "  \"outcomes\": {";
    {
        bool first = true;
        for (const auto& [k, v] : outcomeCount)
        {
            ri << (first ? "" : ", ") << JsonStr(k) << ": " << v;
            first = false;
        }
    }
    ri << "},\n"
       << "  \"topology_updates\": {\"steps_applied\": " << st.stepsApplied << ", \"delay_writes\": "
       << st.delayUpdates << ", \"down_events\": " << st.downEvents << ", \"up_events\": " << st.upEvents
       << "},\n"
       << "  \"wall_s\": {\"load\": " << loadS << ", \"build\": " << buildS << ", \"run\": " << runS
       << ", \"write\": " << writeS << ", \"total\": " << SecondsSince(wallStart) << "},\n"
       << "  \"peak_rss_kb\": " << rss << ",\n"
       << "  \"checks\": {";
    for (size_t i = 0; i < checks.size(); ++i)
    {
        ri << (i ? ", " : "") << JsonStr(checks[i].what) << ": " << (checks[i].ok ? "true" : "false");
    }
    ri << "},\n"
       << "  \"all_checks_ok\": " << (allOk ? "true" : "false") << "\n"
       << "}\n";
    ri.close();

    Simulator::Destroy();
    return allOk ? 0 : 1;
}
