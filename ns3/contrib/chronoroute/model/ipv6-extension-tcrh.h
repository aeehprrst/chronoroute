/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#ifndef IPV6_EXTENSION_TCRH_H
#define IPV6_EXTENSION_TCRH_H

#include "crh-fib.h"
#include "tcrh-process.h"

#include "ns3/callback.h"
#include "ns3/ipv6-address.h"
#include "ns3/ipv6-extension.h"
#include "ns3/ipv6-header.h"
#include "ns3/ipv6-l3-protocol.h"
#include "ns3/traced-callback.h"

#include <cstdint>
#include <optional>
#include <ostream>
#include <string>

/**
 * @file
 * @ingroup chronoroute
 *
 * T-CRH (IPv6 Routing Type 253) and CRH-16/32 (Routing Types 5 and 6) as
 * GENUINE IPv6 routing headers inside ns-3.44's IPv6 stack.
 *
 * How ns-3.44 gets a routing header to us (checked in the 3.44 sources):
 *  1. Ipv6L3Protocol::Receive hands a packet to LocalDeliver only when its
 *     Destination Address is one of the node's own addresses (RFC 8200 4.4:
 *     only the node named in the Destination Address looks at a routing
 *     header). Every other node just forwards it.
 *  2. LocalDeliver walks the extension headers; Next Header 43 goes to
 *     Ipv6ExtensionRouting::Process, which reads the Routing Type and calls the
 *     extension registered for it in the node's Ipv6ExtensionRoutingDemux.
 *     TcrhHelper registers the classes below on every node.
 *  3. Our Process() runs spec/tcrh-v1.md section 6 with the golden-tested pure
 *     functions of tcrh-process.h, rewrites the IPv6 Destination Address to the
 *     next SID's address and sends the packet on with the PUBLIC
 *     Ipv6L3Protocol::Send (SendRealOut, which ns-3's own Type 0 code uses, is
 *     private). It then sets stopProcessing = true and isDropped = false, so a
 *     transit node never hands the payload to UDP/TCP (ns-3's Type 0 code
 *     forgets this and delivers the payload at every segment endpoint).
 *
 * Known ns-3.44 limits we work around (documented in README.md):
 *  - the routing type is read from the start of the packet, not from the
 *    header's offset, so the routing header must be the FIRST extension
 *    header (our source shim guarantees it; Process() drops anything else);
 *  - Process() returns the header length as uint8_t, so a header that must be
 *    stepped over at the final endpoint may be at most 248 bytes (T-CRH with
 *    at most 78 hops); the shim refuses longer paths;
 *  - forwarding with Ipv6L3Protocol::Send resets the Flow Label to 0 and fires
 *    the SendOutgoing trace at every hop.
 */

namespace ns3
{

/**
 * @ingroup chronoroute
 *
 * One routing-header event at one node, for trace export (the future
 * chronoroute.trace/1 writer). Emitted by Ipv6ExtensionTcrh, Ipv6ExtensionCrh
 * (action at a segment endpoint) and TcrhSourceShim (action "ingress").
 *
 * Fields that do not apply are empty optionals. "In" values are the bytes as
 * the packet arrived; "out" values are as it leaves (or is delivered). For a
 * "drop_late" event, flagsOut/devHop are what the deadline check decided
 * (DEV, and Dev Hop = this node if it found the miss), although the packet
 * never leaves.
 */
struct TcrhHopEvent
{
    int64_t tNs{0};                   //!< simulation time, ns
    uint32_t nodeId{0};               //!< ns-3 node id
    std::optional<uint32_t> nodeSid;  //!< this node's SID (from its CrhFib)
    uint64_t packetUid{0};            //!< ns-3 packet uid (survives Packet::Copy)
    uint8_t routingType{0};           //!< 253 (T-CRH), 5 (CRH-16) or 6 (CRH-32)
    /// "ingress", "forward", "deliver", "fallback", "ignore", or a drop:
    /// "drop_late", "drop_malformed", "drop_no_fib", "drop_hop_limit",
    /// "drop_link_down", "drop_fallback_refused", "drop_unsupported"
    const char* action{""};
    const char* reason{nullptr};      //!< detail: parse reason, "link_down", "greedy_no_fallback", ...
    uint8_t nextHeader{0};            //!< the routing header's Next Header (17 UDP, 6 TCP, ...)
    uint8_t hopLimitIn{0};            //!< IPv6 Hop Limit on arrival
    Ipv6Address src;                  //!< IPv6 Source Address
    Ipv6Address dstIn;                //!< IPv6 Destination Address on arrival
    std::optional<Ipv6Address> dstOut; //!< Destination Address it leaves with
    uint8_t numHops{0};               //!< T-CRH Num Hops (CRH: number of SID slots)
    uint8_t slIn{0};                  //!< Segments Left on arrival
    uint8_t slOut{0};                 //!< Segments Left as it leaves / is delivered
    uint8_t flagsIn{0};               //!< T-CRH Flags on arrival
    uint8_t flagsOut{0};              //!< T-CRH Flags as it leaves / is delivered
    uint8_t devHop{0};                //!< T-CRH Dev Hop as it leaves / is delivered
    uint32_t epochBase{0};            //!< T-CRH Epoch_Base
    std::optional<uint8_t> hopIndex;  //!< k = NumHops - SL on arrival (0 at the ingress)
    std::optional<uint32_t> deadlineU; //!< D_k (empty at the ingress)
    std::optional<uint32_t> nowU;     //!< the node's unit clock when it processed the packet
    bool late{false};                 //!< THIS node's deadline check set DEV
    std::optional<uint32_t> nextSid;  //!< SID the packet heads for next
};

/**
 * @return the CSV header line that matches TcrhHopEventCsv()
 */
std::string TcrhHopEventCsvHeader();

/**
 * One event as a CSV line (no newline). Empty optionals are empty fields.
 * @param e the event
 * @return the line
 */
std::string TcrhHopEventCsv(const TcrhHopEvent& e);

/// Counters kept by every routing-header extension and by the source shim.
struct TcrhCounters
{
    uint64_t processed{0};              //!< Process() calls (or shim packets)
    uint64_t ingress{0};                //!< packets the shim sent with a routing header
    uint64_t forwarded{0};              //!< sent on along the SID list
    uint64_t delivered{0};              //!< SL == 0 here: handed to the Next Header
    uint64_t late{0};                   //!< this node's deadline check fired
    uint64_t fallback{0};               //!< handed to the fallback callback
    uint64_t greedyNoFallback{0};       //!< policy greedy but no fallback: continued instead
    uint64_t ignored{0};                //!< not ours and SL == 0 (RFC 8200 4.4)
    uint64_t droppedLate{0};            //!< policy drop
    uint64_t droppedMalformed{0};       //!< spec section 6 step 1
    uint64_t droppedNoFib{0};           //!< next SID not in the CRH-FIB
    uint64_t droppedHopLimit{0};        //!< Hop Limit expired
    uint64_t droppedLinkDown{0};        //!< next link down and no fallback
    uint64_t droppedFallbackRefused{0}; //!< the fallback callback did not take it
    uint64_t droppedUnsupported{0};     //!< an ns-3.44 limit (header not first, too long)
    uint64_t icmpSent{0};               //!< ICMPv6 errors sent
};

namespace tcrh
{

/**
 * Send a packet that begins with a routing header one more segment, through
 * the public Ipv6L3Protocol::Send path with a ready-made route (the "case 1"
 * branch of Send: it builds the IPv6 header and calls SendRealOut). The Hop
 * Limit and Traffic Class travel as SocketIpv6HopLimitTag/SocketIpv6TclassTag,
 * which Send reads. Next Header is always 43 (routing header).
 *
 * @param ipv6 the node's IPv6 layer
 * @param p the packet, starting with the routing header
 * @param src IPv6 Source Address (unchanged along the path)
 * @param dst new IPv6 Destination Address
 * @param hopLimit Hop Limit to send with (already decremented by the caller)
 * @param tclass Traffic Class to keep
 * @param interface IPv6 interface index to send on
 * @param nextHop gateway of the route (the neighbour's address; :: = on-link)
 */
void SendSegment(Ptr<Ipv6L3Protocol> ipv6,
                 Ptr<Packet> p,
                 Ipv6Address src,
                 Ipv6Address dst,
                 uint8_t hopLimit,
                 uint8_t tclass,
                 uint32_t interface,
                 Ipv6Address nextHop);

/**
 * A ready-made fallback function: send the packet towards its (new)
 * Destination Address with the node's ordinary IPv6 routing table. It stands
 * in for greedy geographic forwarding until the ChronoRoute routing protocol
 * exists (plan P5c), so experiments must label it MODELLED. Bind it with
 * MakeBoundCallback(&tcrh::RoutingTableFallback, ipv6).
 *
 * @param ipv6 the node's IPv6 layer
 * @param p the packet, starting with the (rewritten) routing header
 * @param header the IPv6 header to send with (Hop Limit already decremented)
 * @param targetSid the SID the packet is heading for (SID[0])
 * @return false if the routing table has no route (the packet is then dropped)
 */
bool RoutingTableFallback(Ptr<Ipv6L3Protocol> ipv6,
                          Ptr<Packet> p,
                          const Ipv6Header& header,
                          uint32_t targetSid);

} // namespace tcrh

/**
 * @ingroup chronoroute
 *
 * T-CRH v1 (Routing Type 253) processing at a segment endpoint, spec/tcrh-v1.md
 * section 6, inside ns-3's IPv6 stack. See the file comment for how ns-3 calls
 * it.
 *
 * What Process() does with a packet addressed to this node:
 *  - step 1-5 run in tcrh::ProcessAtNode() (golden-tested): validate, deadline
 *    check against this node's unit clock, final endpoint, deviation policy,
 *    decrement Segments Left then index;
 *  - the unit clock is floor((T0GpsNs + Simulator::Now()) / u) mod 2^32, where
 *    T0GpsNs is the GPS time of simulation time 0 (spec section 4), and u comes
 *    from the packet's own UNIT bits;
 *  - step 6: CRH-FIB lookup; missing SID -> discard + ICMPv6 Parameter Problem
 *    Code 0 pointing at the SID (RFC 9631 section 5);
 *  - step 7: the entry's interface is down -> DEV (Dev Hop k), GREEDY, SL 0,
 *    hand to the fallback callback, or discard if there is none;
 *  - forwarding: Hop Limit expired -> ICMPv6 Time Exceeded; otherwise the
 *    Destination Address becomes the next SID's address and the packet goes
 *    out with Hop Limit - 1 on the entry's interface;
 *  - step 1 failures -> discard, with ICMPv6 Parameter Problem Code 0 where
 *    the spec gives a pointer. The ICMPv6 Pointer counts from the start of the
 *    invoking packet: 40 (IPv6 header) + the routing header's offset + the
 *    field offset (spec section 6, "ICMPv6 pointers").
 *
 * Deviation policies (attribute Policy): greedy, continue, drop (spec 6 step 4).
 * "greedy" hands the packet (DEV|GREEDY, SL 0, Destination Address = SID[0]'s
 * address) to the fallback callback set with SetFallback(). With no fallback
 * installed, a greedy node behaves like "continue" and counts it in
 * TcrhCounters::greedyNoFallback (and the event's reason says so). Because
 * that would make a run labelled "greedy" really a "continue" run, the node
 * also prints ONE warning on std::clog the first time it happens, and
 * EffectivePolicyName() reports what the node really does, for run records.
 *
 * Trace source "Hop" fires once per packet processed, with a TcrhHopEvent.
 */
class Ipv6ExtensionTcrh : public Ipv6ExtensionRouting
{
  public:
    /// Routing Type of T-CRH (RFC 4727 experimental value).
    static constexpr uint8_t TYPE_ROUTING = 253;

    /**
     * Fallback hook: (packet starting with the rewritten T-CRH, the IPv6 header
     * to send it with -- Destination Address = address of SID[0], Hop Limit
     * already decremented --, the target SID). Returns true if it took the
     * packet; false means the packet is dropped (drop_fallback_refused).
     */
    using FallbackCallback = Callback<bool, Ptr<Packet>, const Ipv6Header&, uint32_t>;

    /**
     * TracedCallback signature of the "Hop" trace source.
     * @param event the event
     */
    typedef void (*HopTracedCallback)(const TcrhHopEvent& event);

    /**
     * @brief Get the type ID.
     * @return the object TypeId
     */
    static TypeId GetTypeId();

    Ipv6ExtensionTcrh();
    ~Ipv6ExtensionTcrh() override;

    uint8_t GetTypeRouting() const override;
    Ipv6ExtensionRoutingHeader* GetExtensionRoutingHeaderPtr() override;

    uint8_t Process(Ptr<Packet>& packet,
                    uint8_t offset,
                    const Ipv6Header& ipv6Header,
                    Ipv6Address dst,
                    uint8_t* nextHeader,
                    bool& stopProcessing,
                    bool& isDropped,
                    Ipv6L3Protocol::DropReason& dropReason) override;

    /// @param cb the fallback function (a null callback removes it)
    void SetFallback(FallbackCallback cb);
    /// @return true if a fallback function is installed
    bool HasFallback() const;
    /// @param policy the deviation policy
    void SetPolicy(tcrh::Policy policy);
    /// @return the deviation policy
    tcrh::Policy GetPolicy() const;
    /**
     * What a late packet really gets at this node: "greedy", "continue",
     * "drop", or "continue (greedy set, no fallback installed)" when the
     * policy is greedy but SetFallback() was never given a function.
     * @return the effective policy, for run_info files and manifests
     */
    std::string EffectivePolicyName() const;
    /// @param t0GpsNs GPS time (ns) of simulation time 0
    void SetT0GpsNs(uint64_t t0GpsNs);
    /// @return GPS time (ns) of simulation time 0
    uint64_t GetT0GpsNs() const;
    /// @return the counters
    const TcrhCounters& GetCounters() const;

  protected:
    void DoDispose() override;

  private:
    uint64_t m_t0GpsNs;                            //!< GPS ns of simulation time 0
    tcrh::Policy m_policy;                         //!< deviation policy
    FallbackCallback m_fallback;                   //!< greedy / link-down fallback
    TracedCallback<const TcrhHopEvent&> m_hopTrace; //!< "Hop"
    TcrhCounters m_counters;                       //!< counters
    bool m_warnedGreedyNoFallback;                 //!< the one-time warning was printed
};

/**
 * @ingroup chronoroute
 *
 * CRH (RFC 9631) processing at a segment endpoint: the "same path, no
 * deadline" baseline. Same CRH-FIB, same forwarding and same ns-3 workarounds
 * as Ipv6ExtensionTcrh, with the golden-tested CrhProcessAtNode() as the
 * per-node step. There are no flags, so a dead next link simply drops the
 * packet (counted). Use the concrete Ipv6ExtensionCrh16 / Ipv6ExtensionCrh32.
 */
class Ipv6ExtensionCrh : public Ipv6ExtensionRouting
{
  public:
    /**
     * @brief Get the type ID.
     * @return the object TypeId
     */
    static TypeId GetTypeId();

    /// @param routingType 5 (CRH-16) or 6 (CRH-32)
    explicit Ipv6ExtensionCrh(uint8_t routingType);
    ~Ipv6ExtensionCrh() override;

    uint8_t GetTypeRouting() const override;
    Ipv6ExtensionRoutingHeader* GetExtensionRoutingHeaderPtr() override;

    uint8_t Process(Ptr<Packet>& packet,
                    uint8_t offset,
                    const Ipv6Header& ipv6Header,
                    Ipv6Address dst,
                    uint8_t* nextHeader,
                    bool& stopProcessing,
                    bool& isDropped,
                    Ipv6L3Protocol::DropReason& dropReason) override;

    /// @return the counters
    const TcrhCounters& GetCounters() const;

  private:
    uint8_t m_routingType;                         //!< 5 or 6
    TracedCallback<const TcrhHopEvent&> m_hopTrace; //!< "Hop"
    TcrhCounters m_counters;                       //!< counters
};

/// @ingroup chronoroute
/// CRH-16, Routing Type 5.
class Ipv6ExtensionCrh16 : public Ipv6ExtensionCrh
{
  public:
    /**
     * @brief Get the type ID.
     * @return the object TypeId
     */
    static TypeId GetTypeId();
    Ipv6ExtensionCrh16();
};

/// @ingroup chronoroute
/// CRH-32, Routing Type 6.
class Ipv6ExtensionCrh32 : public Ipv6ExtensionCrh
{
  public:
    /**
     * @brief Get the type ID.
     * @return the object TypeId
     */
    static TypeId GetTypeId();
    Ipv6ExtensionCrh32();
};

} // namespace ns3

#endif /* IPV6_EXTENSION_TCRH_H */
