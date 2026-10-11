/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#ifndef TCRH_HELPER_H
#define TCRH_HELPER_H

#include "ns3/ipv6-extension-tcrh.h"
#include "ns3/net-device-container.h"
#include "ns3/node-container.h"
#include "ns3/node.h"
#include "ns3/point-to-point-helper.h"
#include "ns3/tcrh-process.h"
#include "ns3/tcrh-source-shim.h"

#include <cstdint>
#include <map>
#include <ostream>
#include <vector>

namespace ns3
{

/**
 * @ingroup chronoroute
 *
 * Builds ChronoRoute IPv6 nodes and links in ns-3.44.
 *
 * Use, after InternetStackHelper::Install (IPv6 on) and before Simulator::Run:
 * @code
 *   TcrhHelper tcrh;
 *   tcrh.SetT0GpsNs(t0);                    // GPS ns of simulation time 0
 *   tcrh.Install(src, 0xF000);              // T-CRH capable node with its SID
 *   tcrh.Install(sat1, 1);
 *   tcrh.InstallPlain(legacy, 99);          // a node WITHOUT T-CRH support
 *   tcrh.Connect(src, sat1, p2p);           // link 0, addresses fd01:0:0:0::1/2
 *   tcrh.PopulateStaticRoutes();            // ordinary IPv6 (ICMPv6 errors, ACKs)
 *   Ptr<TcrhSourceShim> shim = tcrh.InstallSourceShim(src);
 * @endcode
 *
 * Every node gets (ConfigureIpv6):
 *  - Ipv6 IpForward = true (forwarding is off by default in ns-3);
 *  - Ipv6 StrongEndSystemModel = false, so the SID address (on the loopback)
 *    is accepted on every interface (ns-3 drops it otherwise, ipv6.cc:40-46);
 *  - Icmpv6L4Protocol DAD = false: addresses are usable at once and no
 *    Neighbor Solicitations clutter the pcaps.
 * A T-CRH node (Install) also gets a CrhFib and the T-CRH (253), CRH-16 (5)
 * and CRH-32 (6) extensions in its Ipv6ExtensionRoutingDemux. Registering them
 * on EVERY T-CRH node, final endpoints included, matters: for an unknown type
 * with Segments Left 0 ns-3.44 returns the raw Hdr Ext Len instead of a byte
 * count (ipv6-extension.cc:926) and hands misaligned bytes to UDP/TCP.
 *
 * Addresses follow tcrh-address-plan.h and are added by hand with
 * Ipv6::AddAddress (no Ipv6AddressHelper: its allocator is O(n^2) and it would
 * also install a default FqCoDel queue disc). As a consequence NO queue disc
 * is installed on these devices; each point-to-point device keeps its own
 * DropTail queue (100 packets by default). Choose and install a queue disc
 * explicitly if an experiment needs one.
 *
 * PopulateStaticRoutes() (fewest hops, BFS, ties broken by link order) is for
 * the small topologies of examples and tests; it is O(N * (N + L)) routes.
 */
class TcrhHelper
{
  public:
    /// A point-to-point link made by Connect().
    struct Link
    {
        uint32_t id{0};       //!< link number (address plan)
        Ptr<Node> a;          //!< end 1
        Ptr<Node> b;          //!< end 2
        Ptr<NetDevice> devA;  //!< a's device
        Ptr<NetDevice> devB;  //!< b's device
        uint32_t ifA{0};      //!< a's IPv6 interface index
        uint32_t ifB{0};      //!< b's IPv6 interface index
    };

    TcrhHelper();

    /// @param t0GpsNs GPS ns of simulation time 0, for every extension and shim made later
    void SetT0GpsNs(uint64_t t0GpsNs);
    /// @param policy deviation policy for every T-CRH extension made later
    void SetPolicy(tcrh::Policy policy);

    /**
     * IPv6 settings every ChronoRoute node needs (see the class comment).
     * Call before any address is added to the node.
     * @param node a node with the IPv6 stack installed
     */
    static void ConfigureIpv6(Ptr<Node> node);

    /**
     * A T-CRH capable node: ConfigureIpv6, SID address on the loopback, a
     * CrhFib, and the T-CRH / CRH-16 / CRH-32 extensions.
     * @param node the node
     * @param sid its SID
     * @return its T-CRH extension
     */
    Ptr<Ipv6ExtensionTcrh> Install(Ptr<Node> node, uint32_t sid);

    /**
     * A node WITHOUT T-CRH support (plain ns-3.44 IPv6): ConfigureIpv6 and the
     * SID address only, so packets can be addressed to it.
     * @param node the node
     * @param sid its SID
     */
    void InstallPlain(Ptr<Node> node, uint32_t sid);

    /**
     * Connect two nodes (both already given a SID) with a point-to-point link:
     * IPv6 interfaces up, link addresses fd01:0:HHHH:LLLL::1 (a) and ::2 (b)
     * /64, and a CRH-FIB entry on each T-CRH end for the other end's SID.
     * @param a end 1
     * @param b end 2
     * @param p2p the helper that makes the devices and channel
     * @return the link
     */
    Link Connect(Ptr<Node> a, Ptr<Node> b, PointToPointHelper& p2p);

    /// Fewest-hop static routes on every node to every SID address and link prefix.
    void PopulateStaticRoutes() const;

    /**
     * Install a TcrhSourceShim on a sending host (with this helper's T0GpsNs).
     * @param node the host
     * @return the shim
     */
    Ptr<TcrhSourceShim> InstallSourceShim(Ptr<Node> node) const;

    /// @param node a node @return its T-CRH extension, or null
    static Ptr<Ipv6ExtensionTcrh> GetTcrhExtension(Ptr<Node> node);
    /// @param node a node @return its CRH-16 extension, or null
    static Ptr<Ipv6ExtensionCrh> GetCrh16Extension(Ptr<Node> node);
    /// @param node a node given a SID by this helper @return the SID (aborts otherwise)
    uint32_t GetSid(Ptr<Node> node) const;
    /// @return the links, in creation order
    const std::vector<Link>& GetLinks() const;

    /**
     * Print the address plan: every node's SID address and link addresses.
     * @param os the stream
     */
    void PrintAddressPlan(std::ostream& os) const;

  private:
    /// SID address on the loopback, remember the node.
    /// @param node the node @param sid its SID
    void AssignSid(Ptr<Node> node, uint32_t sid);

    uint64_t m_t0GpsNs;                       //!< GPS ns of simulation time 0
    tcrh::Policy m_policy;                    //!< deviation policy
    std::map<uint32_t, uint32_t> m_sids;      //!< node id -> SID
    std::map<uint32_t, uint32_t> m_nodeOfSid; //!< SID -> node id (uniqueness check)
    std::map<uint32_t, Ptr<Node>> m_nodes;    //!< node id -> node
    std::vector<Link> m_links;                //!< links in creation order
};

} // namespace ns3

#endif /* TCRH_HELPER_H */
