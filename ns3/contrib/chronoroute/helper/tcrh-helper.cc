/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#include "tcrh-helper.h"

#include "ns3/abort.h"
#include "ns3/boolean.h"
#include "ns3/crh-fib.h"
#include "ns3/crh-header.h"
#include "ns3/icmpv6-l4-protocol.h"
#include "ns3/ipv6-extension-demux.h"
#include "ns3/ipv6-extension.h"
#include "ns3/ipv6-l3-protocol.h"
#include "ns3/ipv6-static-routing-helper.h"
#include "ns3/ipv6-static-routing.h"
#include "ns3/log.h"
#include "ns3/tcrh-address-plan.h"
#include "ns3/tcrh-header.h"

#include <deque>
#include <limits>

namespace ns3
{

NS_LOG_COMPONENT_DEFINE("TcrhHelper");

TcrhHelper::TcrhHelper()
    : m_t0GpsNs(0),
      m_policy(tcrh::Policy::GREEDY)
{
}

void
TcrhHelper::SetT0GpsNs(uint64_t t0GpsNs)
{
    m_t0GpsNs = t0GpsNs;
}

void
TcrhHelper::SetPolicy(tcrh::Policy policy)
{
    m_policy = policy;
}

void
TcrhHelper::ConfigureIpv6(Ptr<Node> node)
{
    Ptr<Ipv6> ipv6 = node->GetObject<Ipv6>();
    NS_ABORT_MSG_UNLESS(ipv6, "node " << node->GetId() << " has no IPv6 stack");
    // forwarding is off by default in ns-3 (ipv6.cc:29-34)
    ipv6->SetAttribute("IpForward", BooleanValue(true));
    // accept the SID address (on the loopback) on any interface
    ipv6->SetAttribute("StrongEndSystemModel", BooleanValue(false));
    // no Duplicate Address Detection: addresses are usable at once
    Ptr<Icmpv6L4Protocol> icmpv6 = node->GetObject<Icmpv6L4Protocol>();
    NS_ABORT_MSG_UNLESS(icmpv6, "node " << node->GetId() << " has no ICMPv6");
    icmpv6->SetAttribute("DAD", BooleanValue(false));
}

void
TcrhHelper::AssignSid(Ptr<Node> node, uint32_t sid)
{
    NS_ABORT_MSG_IF(m_sids.count(node->GetId()), "node " << node->GetId() << " already has a SID");
    // a map lookup, not a scan: thousands of satellites must not cost O(n^2)
    auto used = m_nodeOfSid.find(sid);
    NS_ABORT_MSG_IF(used != m_nodeOfSid.end(), "SID " << sid << " is already used by node " << used->second);
    m_nodeOfSid[sid] = node->GetId();
    Ptr<Ipv6> ipv6 = node->GetObject<Ipv6>();
    // interface 0 is the loopback; a /128 needs no on-link route
    ipv6->AddAddress(0,
                     Ipv6InterfaceAddress(tcrh::SidAddress(sid), Ipv6Prefix(tcrh::SID_PREFIX_LENGTH)),
                     false);
    m_sids[node->GetId()] = sid;
    m_nodes[node->GetId()] = node;
}

Ptr<Ipv6ExtensionTcrh>
TcrhHelper::Install(Ptr<Node> node, uint32_t sid)
{
    // spec section 7: 16-bit SIDs, 0xFFFF reserved
    NS_ABORT_MSG_IF(sid >= TcrhHeader::SID_RESERVED, "a T-CRH node's SID is 0..0xFFFE, got " << sid);
    ConfigureIpv6(node);
    AssignSid(node, sid);

    Ptr<CrhFib> fib = CreateObject<CrhFib>();
    fib->SetLocalSid(sid);
    node->AggregateObject(fib);

    Ptr<Ipv6ExtensionRoutingDemux> demux = node->GetObject<Ipv6ExtensionRoutingDemux>();
    NS_ABORT_MSG_UNLESS(demux,
                        "node " << node->GetId()
                                << " has no Ipv6ExtensionRoutingDemux (install IPv6 first)");
    NS_ABORT_MSG_IF(demux->GetExtensionRouting(Ipv6ExtensionTcrh::TYPE_ROUTING),
                    "node " << node->GetId() << " already has a Routing Type 253 extension");

    Ptr<Ipv6ExtensionTcrh> tcrhExt = CreateObject<Ipv6ExtensionTcrh>();
    tcrhExt->SetT0GpsNs(m_t0GpsNs);
    tcrhExt->SetPolicy(m_policy);
    Ptr<Ipv6ExtensionCrh16> crh16 = CreateObject<Ipv6ExtensionCrh16>();
    Ptr<Ipv6ExtensionCrh32> crh32 = CreateObject<Ipv6ExtensionCrh32>();
    for (Ptr<Ipv6ExtensionRouting> ext :
         {Ptr<Ipv6ExtensionRouting>(tcrhExt), Ptr<Ipv6ExtensionRouting>(crh16), Ptr<Ipv6ExtensionRouting>(crh32)})
    {
        ext->SetNode(node);
        demux->Insert(ext);
    }
    return tcrhExt;
}

void
TcrhHelper::InstallPlain(Ptr<Node> node, uint32_t sid)
{
    ConfigureIpv6(node);
    AssignSid(node, sid);
}

TcrhHelper::Link
TcrhHelper::Connect(Ptr<Node> a, Ptr<Node> b, PointToPointHelper& p2p)
{
    NS_ABORT_MSG_UNLESS(m_sids.count(a->GetId()) && m_sids.count(b->GetId()),
                        "give both nodes a SID (Install / InstallPlain) before Connect");
    Link link;
    link.id = static_cast<uint32_t>(m_links.size());
    link.a = a;
    link.b = b;
    NetDeviceContainer devs = p2p.Install(a, b);
    link.devA = devs.Get(0);
    link.devB = devs.Get(1);

    // the same order as Ipv6AddressHelper::Assign, minus its queue disc
    auto bringUp = [&](Ptr<Node> n, Ptr<NetDevice> dev, uint8_t end) {
        Ptr<Ipv6> ipv6 = n->GetObject<Ipv6>();
        const uint32_t ifIndex = ipv6->AddInterface(dev);
        ipv6->SetUp(ifIndex); // also adds the link-local address
        ipv6->SetMetric(ifIndex, 1);
        ipv6->AddAddress(ifIndex,
                         Ipv6InterfaceAddress(tcrh::LinkAddress(link.id, end),
                                              Ipv6Prefix(tcrh::LINK_PREFIX_LENGTH)),
                         true);
        return ifIndex;
    };
    link.ifA = bringUp(a, link.devA, 1);
    link.ifB = bringUp(b, link.devB, 2);

    // CRH-FIB: each T-CRH end can now reach the other end's SID directly
    auto addFib = [&](Ptr<Node> n, uint32_t ifIndex, Ptr<Node> peer, uint8_t peerEnd) {
        Ptr<CrhFib> fib = n->GetObject<CrhFib>();
        if (!fib)
        {
            return; // a plain node has no CRH-FIB
        }
        CrhFib::Entry e;
        e.sidAddress = tcrh::SidAddress(m_sids.at(peer->GetId()));
        e.interface = ifIndex;
        e.nextHop = tcrh::LinkAddress(link.id, peerEnd);
        fib->AddEntry(m_sids.at(peer->GetId()), e);
    };
    addFib(a, link.ifA, b, 2);
    addFib(b, link.ifB, a, 1);
    m_links.push_back(link);
    return link;
}

void
TcrhHelper::PopulateStaticRoutes() const
{
    // adjacency in link order, so the result is deterministic
    std::map<uint32_t, std::vector<const Link*>> adj;
    for (const Link& l : m_links)
    {
        adj[l.a->GetId()].push_back(&l);
        adj[l.b->GetId()].push_back(&l);
    }
    Ipv6StaticRoutingHelper srh;
    for (const auto& [srcId, srcNode] : m_nodes)
    {
        // BFS from srcNode; firstHop[v] = (interface, next hop address) on src
        struct Hop
        {
            uint32_t iface;
            Ipv6Address nextHop;
        };
        std::map<uint32_t, Hop> firstHop;
        std::map<uint32_t, uint32_t> dist;
        std::deque<uint32_t> queue;
        dist[srcId] = 0;
        queue.push_back(srcId);
        while (!queue.empty())
        {
            const uint32_t u = queue.front();
            queue.pop_front();
            auto it = adj.find(u);
            if (it == adj.end())
            {
                continue;
            }
            for (const Link* l : it->second)
            {
                const bool fromA = l->a->GetId() == u;
                const uint32_t v = fromA ? l->b->GetId() : l->a->GetId();
                if (dist.count(v))
                {
                    continue;
                }
                dist[v] = dist[u] + 1;
                if (u == srcId)
                {
                    // leaving src on this link: its interface, the peer's address
                    firstHop[v] = Hop{fromA ? l->ifA : l->ifB,
                                      tcrh::LinkAddress(l->id, fromA ? 2 : 1)};
                }
                else
                {
                    firstHop[v] = firstHop[u];
                }
                queue.push_back(v);
            }
        }
        Ptr<Ipv6StaticRouting> rt = srh.GetStaticRouting(srcNode->GetObject<Ipv6>());
        NS_ABORT_MSG_UNLESS(rt, "node " << srcId << " has no Ipv6StaticRouting");
        // host routes to every other node's SID address
        for (const auto& [dstId, hop] : firstHop)
        {
            rt->AddHostRouteTo(tcrh::SidAddress(m_sids.at(dstId)), hop.nextHop, hop.iface);
        }
        // network routes to every link this node is not on, via the nearer end
        for (const Link& l : m_links)
        {
            const uint32_t ia = l.a->GetId();
            const uint32_t ib = l.b->GetId();
            if (ia == srcId || ib == srcId)
            {
                continue; // on-link route already added with the address
            }
            const bool aReach = dist.count(ia) > 0;
            const bool bReach = dist.count(ib) > 0;
            if (!aReach && !bReach)
            {
                continue;
            }
            uint32_t via = ia;
            if (!aReach || (bReach && dist.at(ib) < dist.at(ia)))
            {
                via = ib;
            }
            const Hop& hop = firstHop.at(via);
            rt->AddNetworkRouteTo(tcrh::LinkPrefix(l.id),
                                  Ipv6Prefix(tcrh::LINK_PREFIX_LENGTH),
                                  hop.nextHop,
                                  hop.iface);
        }
    }
}

Ptr<TcrhSourceShim>
TcrhHelper::InstallSourceShim(Ptr<Node> node) const
{
    Ptr<TcrhSourceShim> shim = CreateObject<TcrhSourceShim>();
    shim->SetT0GpsNs(m_t0GpsNs);
    shim->Install(node);
    return shim;
}

Ptr<Ipv6ExtensionTcrh>
TcrhHelper::GetTcrhExtension(Ptr<Node> node)
{
    Ptr<Ipv6ExtensionRoutingDemux> demux = node->GetObject<Ipv6ExtensionRoutingDemux>();
    if (!demux)
    {
        return nullptr;
    }
    return DynamicCast<Ipv6ExtensionTcrh>(demux->GetExtensionRouting(Ipv6ExtensionTcrh::TYPE_ROUTING));
}

Ptr<Ipv6ExtensionCrh>
TcrhHelper::GetCrh16Extension(Ptr<Node> node)
{
    Ptr<Ipv6ExtensionRoutingDemux> demux = node->GetObject<Ipv6ExtensionRoutingDemux>();
    if (!demux)
    {
        return nullptr;
    }
    return DynamicCast<Ipv6ExtensionCrh>(demux->GetExtensionRouting(CrhHeader::ROUTING_TYPE_CRH16));
}

uint32_t
TcrhHelper::GetSid(Ptr<Node> node) const
{
    auto it = m_sids.find(node->GetId());
    NS_ABORT_MSG_IF(it == m_sids.end(), "node " << node->GetId() << " has no SID");
    return it->second;
}

const std::vector<TcrhHelper::Link>&
TcrhHelper::GetLinks() const
{
    return m_links;
}

void
TcrhHelper::PrintAddressPlan(std::ostream& os) const
{
    os << "Address plan v1 (ns3/contrib/chronoroute/model/tcrh-address-plan.h):\n";
    for (const auto& [id, sid] : m_sids)
    {
        const bool tcrhNode = static_cast<bool>(m_nodes.at(id)->GetObject<CrhFib>());
        os << "  node " << id << "  SID " << sid << " (0x" << std::hex << sid << std::dec
           << ")  " << tcrh::SidAddress(sid) << "/128 on lo"
           << (tcrhNode ? "" : "  [NO T-CRH support]") << "\n";
    }
    for (const Link& l : m_links)
    {
        os << "  link " << l.id << "  node " << l.a->GetId() << " if " << l.ifA << " "
           << tcrh::LinkAddress(l.id, 1) << "/64  <->  node " << l.b->GetId() << " if " << l.ifB
           << " " << tcrh::LinkAddress(l.id, 2) << "/64\n";
    }
}

} // namespace ns3
