/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#ifndef TCRH_PROCESS_H
#define TCRH_PROCESS_H

#include "tcrh-header.h"

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

/**
 * @file
 * @ingroup chronoroute
 *
 * Per-node T-CRH processing, spec/tcrh-v1.md section 6, as PURE functions of
 * the packet bytes (or a TcrhHeader) and the node's unit clock. C++ twin of
 * Python chronoroute.proto.process_at_node / ingress_send: same actions, same
 * reason codes, same bytes out, checked against the same golden vectors.
 *
 * The CRH-FIB lookup (step 6: SID -> neighbour / interface) is deliberately
 * NOT in here: it depends on the simulator's topology. The caller maps the
 * returned next SID to a neighbour, and discards the packet (ICMPv6 Parameter
 * Problem, Code 0) if the SID has no FIB entry.
 */

namespace ns3
{
namespace tcrh
{

/// A node's deviation policy (spec section 6 step 4).
enum class Policy : uint8_t
{
    GREEDY,   //!< set GREEDY, SL = 0, head for SID[0] with the fallback function
    CONTINUE, //!< keep following the SID list; DEV records the miss
    DROP,     //!< discard (counted as "late, strict")
};

/// What the node does with the packet.
enum class Action : uint8_t
{
    DELIVER,        //!< SL was 0: this node is the final segment endpoint (step 3)
    FORWARD,        //!< send towards nextSid via the CRH-FIB (steps 5-6)
    FALLBACK,       //!< GREEDY set, SL = 0: send towards nextSid = SID[0] (step 4)
    DROP_LATE,      //!< DEV set and policy DROP (step 4)
    DROP_MALFORMED, //!< failed validation (step 1); see reason
    /// Not a T-CRH and Segments Left is 0: RFC 8200 section 4.4 says to ignore
    /// the routing header and process the Next Header (step 1b). The bytes go
    /// on unchanged; reason "wrong_type", no ICMP.
    IGNORE,
};

/// @param policy a policy
/// @return "greedy", "continue" or "drop"
const char* PolicyName(Policy policy);
/// @param name "greedy", "continue" or "drop"
/// @param policy out: the policy
/// @return false if the name is unknown
bool PolicyFromName(const std::string& name, Policy* policy);
/// @param action an action
/// @return "deliver", "forward", "fallback", "drop_late", "drop_malformed" or "ignore"
const char* ActionName(Action action);

/**
 * Outcome of processing one packet at one node (Python ProcessResult).
 * Fields that Python returns as None are empty optionals here.
 */
struct ProcessResult
{
    Action action{Action::DROP_MALFORMED}; //!< what to do
    std::optional<uint16_t> nextSid;       //!< SID to look up / head for
    /// Packet bytes to send on (or deliver): only Segments Left, Flags and Dev
    /// Hop differ from the input. Empty when the packet is discarded. Only the
    /// byte-level ProcessAtNode() fills it.
    std::optional<std::vector<uint8_t>> outBytes;
    /// True when THIS node's deadline check (step 2) fired and set DEV. Never
    /// true for a packet that already had DEV set: such packets are not
    /// checked again (one Dev Hop per packet).
    bool late{false};
    std::optional<uint8_t> hopIndex;   //!< k = NumHops - SL on arrival (0 = ingress)
    std::optional<uint32_t> deadlineU; //!< D_k for this node (empty at the ingress)
    /// nullptr for deliver/forward/fallback; "late_strict" for DROP_LATE; the
    /// TcrhHeader::ParseStatusName() for DROP_MALFORMED.
    const char* reason{nullptr};
    std::optional<uint8_t> icmpCode;    //!< 0 when a Parameter Problem should be sent
    std::optional<uint8_t> icmpPointer; //!< offset of the offending field
};

/**
 * Spec section 6 steps 2-5 on an already valid header, in place: the deadline
 * check, the final endpoint, the deviation policy, decrement-then-index. The
 * header's Segments Left, Flags and Dev Hop are updated as they go on the wire
 * (for DROP_LATE the header is left as it was at the drop). Call it only at the
 * node named in the Destination Address. A packet in GREEDY mode is addressed
 * to SID[0], so the satellites it crosses on the way do not run this; they use
 * the fallback function directly.
 *
 * @param hdr a valid header (GetParseStatus() == OK)
 * @param nowU the node's unit clock, ClockU(t_gps_ns, hdr.GetUnitCode())
 * @param policy the node's deviation policy
 * @return the outcome (outBytes not filled)
 */
ProcessResult ProcessHeader(TcrhHeader& hdr, uint32_t nowU, Policy policy);

/**
 * Spec section 6 on raw bytes, exactly like Python process_at_node: validate
 * (step 1, DROP_MALFORMED with the reason and ICMP code/pointer), then
 * ProcessHeader(), then rewrite only the mutable bytes (3, 4, 6) in a copy of
 * the input. Every other byte (Reserved, padding, reserved flag bits, and any
 * payload after the header) passes through unchanged, as a router would.
 *
 * @param raw packet bytes starting with the T-CRH
 * @param len number of bytes
 * @param nowU the node's unit clock in the packet's unit
 * @param policy the node's deviation policy
 * @return the outcome
 */
ProcessResult ProcessAtNode(const uint8_t* raw, uint32_t len, uint32_t nowU, Policy policy);

/// Convenience overload of ProcessAtNode().
/// @param raw packet bytes starting with the T-CRH
/// @param nowU the node's unit clock in the packet's unit
/// @param policy the node's deviation policy
/// @return the outcome
ProcessResult ProcessAtNode(const std::vector<uint8_t>& raw, uint32_t nowU, Policy policy);

/**
 * Spec section 6 step 7, "next link down", on raw bytes: C++ twin of Python
 * chronoroute.proto.link_down_fallback. @p raw is the packet as it leaves
 * step 5 (from ProcessAtNode() FORWARD, or IngressSend()), and the node has
 * just found the link to the next SID down. If DEV is clear it is set with
 * Dev Hop = k = NumHops - SL - 1 (0 at the ingress); then GREEDY is set and
 * SL = 0, and the packet heads for SID[0] with the fallback function.
 * Result: FALLBACK, nextSid = SID[0], hopIndex = k, reason "link_down"; or
 * DROP_MALFORMED for bytes that fail step 1. Aborts on a packet that cannot be
 * in this state (SL == NumHops: step 5 not done; GREEDY already set: greedy
 * forwarding skips dead links itself).
 *
 * @param raw packet bytes starting with the T-CRH
 * @return the outcome
 */
ProcessResult LinkDownFallback(const std::vector<uint8_t>& raw);

/// Outcome of IngressSend().
struct IngressResult
{
    bool ok{false};                                    //!< false: see status / error
    TcrhHeader::ParseStatus status{TcrhHeader::OK};    //!< parse result of the input
    std::string error;                                 //!< why it failed, or empty
    std::vector<uint8_t> outBytes;                     //!< bytes to send (SL = h - 1)
    uint16_t firstSid{0};                              //!< s_1 = SID[h-1]
};

/**
 * The ingress node's own forwarding of a header it has just built (spec
 * section 6, last paragraph): steps 5-6 without a deadline check. Fails for
 * malformed bytes and for a header that is not fresh (SL != NumHops or
 * NumHops == 0).
 *
 * @param raw bytes starting with a fresh T-CRH
 * @return the outcome
 */
IngressResult IngressSend(const std::vector<uint8_t>& raw);

/**
 * Header-level IngressSend(): decrement Segments Left of a fresh header in
 * place and return the first SID. Aborts if the header is not fresh.
 *
 * @param hdr a fresh header (SL == NumHops >= 1)
 * @return s_1 = SID[h-1]
 */
uint16_t IngressSendHeader(TcrhHeader& hdr);

} // namespace tcrh
} // namespace ns3

#endif /* TCRH_PROCESS_H */
