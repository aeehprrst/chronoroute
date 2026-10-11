/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#ifndef TCRH_SOURCE_SHIM_H
#define TCRH_SOURCE_SHIM_H

#include "ipv6-extension-tcrh.h"
#include "tcrh-timebase.h"

#include "ns3/ip-l4-protocol.h"
#include "ns3/ipv6-address.h"
#include "ns3/node.h"
#include "ns3/object.h"
#include "ns3/traced-callback.h"

#include <cstdint>
#include <map>
#include <utility>
#include <vector>

namespace ns3
{

/**
 * @ingroup chronoroute
 *
 * Source insertion (spec/tcrh-v1.md section 8): the SENDING HOST builds the
 * T-CRH itself, which RFC 8200 section 4 allows (only nodes on the path may
 * not insert extension headers).
 *
 * How it hooks in, with no change to ns-3: UdpL4Protocol and TcpL4Protocol
 * hand every IPv6 packet to a replaceable "down target" callback
 * (IpL4Protocol::SetDownTarget6, normally Ipv6::Send). Install() puts the shim
 * in between. For a packet whose (destination address, destination port) has
 * a route (AddRoute), the shim
 *  1. builds the header with TcrhHeader::Build: Epoch_Base = ceil((T0GpsNs +
 *     now) / u) mod 2^32 stamped for THIS packet at send time, deltas from the
 *     cumulative budgets (spec 5.1), Next Header = 17 (UDP) or 6 (TCP);
 *  2. runs the ingress step (tcrh::IngressSend, golden-tested): no deadline
 *     check, Segments Left = h - 1, next SID = s_1;
 *  3. looks s_1 up in the node's CrhFib (step 6), applies step 7 if that link
 *     is down (DEV with Dev Hop 0, GREEDY, to the fallback, or drop);
 *  4. sends the packet to s_1's SID address with Next Header 43 through the
 *     original down target and a ready-made route.
 * Every other packet goes through untouched (ordinary IPv6).
 *
 * The transport checksum was computed by UDP/TCP with the FINAL destination,
 * which is what RFC 8200 section 8.1 requires, so AddRoute() insists that the
 * last SID's address is that destination.
 *
 * Packets that would need fragmenting abort the run: ns-3.44 asserts when it
 * fragments a packet whose routing header is not Type 0. Keep UDP payloads and
 * TcpSocket::SegmentSize small enough (MTU - 40 - header - transport header).
 *
 * The shim can also insert a CRH-16 (AddCrh16Route): the "same path, no
 * deadline" baseline.
 */
class TcrhSourceShim : public Object
{
  public:
    /// Which routing header a route inserts.
    enum class Kind : uint8_t
    {
        TCRH,  //!< T-CRH v1, Routing Type 253
        CRH16, //!< CRH-16, Routing Type 5 (RFC 9631)
    };

    /// One source route.
    struct Route
    {
        Kind kind{Kind::TCRH};                    //!< header to insert
        std::vector<uint16_t> sidsFwd;            //!< s_1..s_h, final endpoint last
        std::vector<uint64_t> cumulativeBudgetsNs; //!< B_1..B_h in ns (T-CRH only)
        uint8_t unitCode{tcrh::DEFAULT_UNIT_CODE}; //!< deadline unit code (T-CRH only)
    };

    /// Largest routing header the shim inserts: ns-3.44's Process() returns
    /// the header length as uint8_t, so the final endpoint can step over at
    /// most 255 bytes, i.e. 248 (a T-CRH with at most 78 hops).
    static constexpr uint32_t MAX_HEADER_BYTES = 248;

    /**
     * @brief Get the type ID.
     * @return the object TypeId
     */
    static TypeId GetTypeId();

    TcrhSourceShim();
    ~TcrhSourceShim() override;

    /**
     * Hook the node's UDP and TCP (whichever are installed) and aggregate the
     * shim to the node. Call after InternetStackHelper::Install, once.
     * @param node the sending host
     */
    void Install(Ptr<Node> node);

    /**
     * Send packets to (@p finalDst, @p dstPort) with a T-CRH along @p sidsFwd.
     * @param finalDst the transport destination; must equal the SID address of
     *        sidsFwd.back() (aborts otherwise)
     * @param dstPort destination port, or 0 for every port
     * @param sidsFwd s_1..s_h (1..78 hops)
     * @param cumulativeBudgetsNs B_1 <= ... <= B_h, ns from ingress
     * @param unitCode deadline unit code 0..3
     */
    void AddRoute(Ipv6Address finalDst,
                  uint16_t dstPort,
                  const std::vector<uint16_t>& sidsFwd,
                  const std::vector<uint64_t>& cumulativeBudgetsNs,
                  uint8_t unitCode = tcrh::DEFAULT_UNIT_CODE);

    /**
     * Send packets to (@p finalDst, @p dstPort) with a CRH-16 along @p sidsFwd.
     * @param finalDst must equal the SID address of sidsFwd.back()
     * @param dstPort destination port, or 0 for every port
     * @param sidsFwd s_1..s_n
     */
    void AddCrh16Route(Ipv6Address finalDst, uint16_t dstPort, const std::vector<uint16_t>& sidsFwd);

    /**
     * @param finalDst destination
     * @param dstPort port (0 = the wildcard route)
     * @return true if a route was removed
     */
    bool RemoveRoute(Ipv6Address finalDst, uint16_t dstPort);

    /// @param cb fallback for an ingress whose first link is down (spec 6 step 7)
    void SetFallback(Ipv6ExtensionTcrh::FallbackCallback cb);
    /// @param t0GpsNs GPS time (ns) of simulation time 0
    void SetT0GpsNs(uint64_t t0GpsNs);
    /// @return GPS time (ns) of simulation time 0
    uint64_t GetT0GpsNs() const;
    /// @return the counters (processed = packets that matched a route)
    const TcrhCounters& GetCounters() const;

  protected:
    void DoDispose() override;

  private:
    /// UDP's down target.
    /// @param p packet (UDP header on top) @param src source @param dst final destination
    /// @param protocol 17 @param route the route UDP found (may be null)
    void SendUdp(Ptr<Packet> p, Ipv6Address src, Ipv6Address dst, uint8_t protocol, Ptr<Ipv6Route> route);
    /// TCP's down target.
    /// @param p packet (TCP header on top) @param src source @param dst final destination
    /// @param protocol 6 @param route the route TCP found (may be null)
    void SendTcp(Ptr<Packet> p, Ipv6Address src, Ipv6Address dst, uint8_t protocol, Ptr<Ipv6Route> route);
    /// The work of SendUdp / SendTcp.
    /// @param down the original down target @param p packet @param src source
    /// @param dst final destination @param protocol transport protocol @param route route or null
    void Send(const IpL4Protocol::DownTargetCallback6& down,
              Ptr<Packet> p,
              Ipv6Address src,
              Ipv6Address dst,
              uint8_t protocol,
              Ptr<Ipv6Route> route);
    /// @param dst destination @param port destination port
    /// @return the route for (dst, port), else (dst, any port), else nullptr
    const Route* FindRoute(Ipv6Address dst, uint16_t port) const;
    /// @param finalDst destination @param port port @param route the route to store
    void StoreRoute(Ipv6Address finalDst, uint16_t port, const Route& route);

    Ptr<Node> m_node;                                        //!< the sending host
    IpL4Protocol::DownTargetCallback6 m_udpDown;             //!< UDP's original down target
    IpL4Protocol::DownTargetCallback6 m_tcpDown;             //!< TCP's original down target
    std::map<std::pair<Ipv6Address, uint16_t>, Route> m_routes; //!< (dst, port) -> route
    uint64_t m_t0GpsNs;                                      //!< GPS ns of simulation time 0
    Ipv6ExtensionTcrh::FallbackCallback m_fallback;          //!< ingress link-down fallback
    TracedCallback<const TcrhHopEvent&> m_ingressTrace;      //!< "Ingress"
    TcrhCounters m_counters;                                 //!< counters
};

} // namespace ns3

#endif /* TCRH_SOURCE_SHIM_H */
