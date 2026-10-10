/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#include "tcrh-process.h"

#include "tcrh-timebase.h"

#include "ns3/abort.h"
#include "ns3/log.h"

namespace ns3
{

NS_LOG_COMPONENT_DEFINE("TcrhProcess");

namespace tcrh
{

const char*
PolicyName(Policy policy)
{
    switch (policy)
    {
    case Policy::GREEDY:
        return "greedy";
    case Policy::CONTINUE:
        return "continue";
    case Policy::DROP:
        return "drop";
    }
    return "unknown";
}

bool
PolicyFromName(const std::string& name, Policy* policy)
{
    for (Policy p : {Policy::GREEDY, Policy::CONTINUE, Policy::DROP})
    {
        if (name == PolicyName(p))
        {
            *policy = p;
            return true;
        }
    }
    return false;
}

const char*
ActionName(Action action)
{
    switch (action)
    {
    case Action::DELIVER:
        return "deliver";
    case Action::FORWARD:
        return "forward";
    case Action::FALLBACK:
        return "fallback";
    case Action::DROP_LATE:
        return "drop_late";
    case Action::DROP_MALFORMED:
        return "drop_malformed";
    case Action::IGNORE:
        return "ignore";
    }
    return "unknown";
}

namespace
{

/// Step 1 failed: discard, with the reason and (if there is a field to point
/// at) ICMPv6 Parameter Problem Code 0 and the pointer.
ProcessResult
Malformed(TcrhHeader::ParseStatus status)
{
    ProcessResult r;
    r.action = Action::DROP_MALFORMED;
    r.reason = TcrhHeader::ParseStatusName(status);
    int pointer = TcrhHeader::ParseStatusIcmpPointer(status);
    if (pointer >= 0)
    {
        r.icmpCode = 0;
        r.icmpPointer = static_cast<uint8_t>(pointer);
    }
    NS_LOG_LOGIC("drop malformed T-CRH: " << r.reason);
    return r;
}

} // namespace

ProcessResult
ProcessHeader(TcrhHeader& hdr, uint32_t nowU, Policy policy)
{
    NS_ABORT_MSG_UNLESS(hdr.GetParseStatus() == TcrhHeader::OK,
                        "ProcessHeader needs a valid header; validate first (ProcessAtNode does)");
    ProcessResult r;
    const uint8_t numHops = hdr.GetNumHops();
    uint8_t sl = hdr.GetSegmentsLeft();
    uint8_t flags = hdr.GetFlags();
    uint8_t devHop = hdr.GetDevHop();
    const uint8_t k = hdr.GetCurrentHopIndex(); // 0 means SL == NumHops: the ingress
    r.hopIndex = k;
    if (k >= 1)
    {
        r.deadlineU = hdr.GetDeadline(k);
    }

    // 2. Deadline check: only if DEV is clear and this is not the ingress.
    //    Late means strictly after the deadline unit (serial arithmetic).
    if ((flags & TcrhHeader::FLAG_DEV) == 0 && sl < numHops)
    {
        if (IsLate(nowU, *r.deadlineU))
        {
            r.late = true;
            flags |= TcrhHeader::FLAG_DEV;
            devHop = k;
        }
    }
    hdr.SetFlags(flags);
    hdr.SetDevHop(devHop);

    // 3. Final segment endpoint: deliver, late or not (DEV records the miss).
    if (sl == 0)
    {
        r.action = Action::DELIVER;
        return r;
    }

    // 4. Deviation policy, for a packet found late here or upstream.
    if ((flags & TcrhHeader::FLAG_DEV) != 0)
    {
        if (policy == Policy::GREEDY)
        {
            hdr.SetFlags(flags | TcrhHeader::FLAG_GREEDY);
            hdr.SetSegmentsLeft(0);
            r.action = Action::FALLBACK;
            r.nextSid = hdr.GetSid(0); // head for the final endpoint
            return r;
        }
        if (policy == Policy::DROP)
        {
            r.action = Action::DROP_LATE;
            r.reason = "late_strict";
            return r;
        }
        // CONTINUE: keep following the SID list; DEV records the miss.
    }

    // 5. Decrement first, then index.
    sl -= 1;
    hdr.SetSegmentsLeft(sl);
    r.action = Action::FORWARD;
    r.nextSid = hdr.GetSid(sl);
    // 6. (caller) CRH-FIB lookup of nextSid.
    return r;
}

ProcessResult
ProcessAtNode(const uint8_t* raw, uint32_t len, uint32_t nowU, Policy policy)
{
    // 1. Validate.
    TcrhHeader hdr;
    TcrhHeader::ParseStatus status = TcrhHeader::Parse(raw, len, false, &hdr, nullptr);
    if (status == TcrhHeader::WRONG_TYPE && raw[TcrhHeader::OFF_SEGMENTS_LEFT] == 0)
    {
        // Step 1b: not a T-CRH, and RFC 8200 section 4.4 says an unrecognised
        // routing header with Segments Left 0 is ignored (process Next Header).
        // WRONG_TYPE implies at least 8 bytes, so byte 3 exists.
        ProcessResult r;
        r.action = Action::IGNORE;
        r.reason = TcrhHeader::ParseStatusName(status);
        r.outBytes = std::vector<uint8_t>(raw, raw + len);
        return r;
    }
    if (status != TcrhHeader::OK)
    {
        return Malformed(status);
    }

    ProcessResult r = ProcessHeader(hdr, nowU, policy);
    if (r.action != Action::DROP_LATE)
    {
        // Rewrite only the mutable fields (SL, Flags, Dev Hop; spec section 2)
        // in a copy. Every other byte passes through untouched.
        std::vector<uint8_t> out(raw, raw + len);
        out[TcrhHeader::OFF_SEGMENTS_LEFT] = hdr.GetSegmentsLeft();
        out[TcrhHeader::OFF_FLAGS] = hdr.GetFlags();
        out[TcrhHeader::OFF_DEV_HOP] = hdr.GetDevHop();
        r.outBytes = std::move(out);
    }
    return r;
}

ProcessResult
ProcessAtNode(const std::vector<uint8_t>& raw, uint32_t nowU, Policy policy)
{
    return ProcessAtNode(raw.data(), static_cast<uint32_t>(raw.size()), nowU, policy);
}

ProcessResult
LinkDownFallback(const std::vector<uint8_t>& raw)
{
    TcrhHeader hdr;
    TcrhHeader::ParseStatus status =
        TcrhHeader::Parse(raw.data(), static_cast<uint32_t>(raw.size()), false, &hdr, nullptr);
    if (status != TcrhHeader::OK)
    {
        return Malformed(status);
    }
    const uint8_t numHops = hdr.GetNumHops();
    const uint8_t sl = hdr.GetSegmentsLeft();
    uint8_t flags = hdr.GetFlags();
    NS_ABORT_MSG_IF(sl >= numHops,
                    "LinkDownFallback needs the bytes as they leave step 5 (SL < NumHops)");
    NS_ABORT_MSG_IF((flags & TcrhHeader::FLAG_GREEDY) != 0,
                    "a GREEDY packet is already in fallback mode; it skips dead links itself");
    ProcessResult r;
    // step 5 already decremented SL, so this node's hop index is one less
    // than NumHops - SL: 0 at the ingress (spec section 6 step 7)
    const uint8_t k = numHops - sl - 1;
    uint8_t devHop = hdr.GetDevHop();
    if ((flags & TcrhHeader::FLAG_DEV) == 0)
    {
        flags |= TcrhHeader::FLAG_DEV;
        devHop = k;
    }
    flags |= TcrhHeader::FLAG_GREEDY;
    std::vector<uint8_t> out = raw;
    out[TcrhHeader::OFF_SEGMENTS_LEFT] = 0;
    out[TcrhHeader::OFF_FLAGS] = flags;
    out[TcrhHeader::OFF_DEV_HOP] = devHop;
    r.action = Action::FALLBACK;
    r.nextSid = hdr.GetSid(0); // head for the final endpoint
    r.outBytes = std::move(out);
    r.hopIndex = k;
    r.reason = "link_down";
    return r;
}

IngressResult
IngressSend(const std::vector<uint8_t>& raw)
{
    IngressResult r;
    TcrhHeader hdr;
    r.status =
        TcrhHeader::Parse(raw.data(), static_cast<uint32_t>(raw.size()), false, &hdr, nullptr);
    if (r.status != TcrhHeader::OK)
    {
        r.error = std::string("malformed T-CRH: ") + TcrhHeader::ParseStatusName(r.status);
        return r;
    }
    if (hdr.GetNumHops() == 0 || hdr.GetSegmentsLeft() != hdr.GetNumHops())
    {
        r.error = "ingress expects a fresh header (SL == NumHops >= 1)";
        return r;
    }
    r.firstSid = IngressSendHeader(hdr);
    r.outBytes = raw;
    r.outBytes[TcrhHeader::OFF_SEGMENTS_LEFT] = hdr.GetSegmentsLeft();
    r.ok = true;
    return r;
}

uint16_t
IngressSendHeader(TcrhHeader& hdr)
{
    NS_ABORT_MSG_UNLESS(hdr.GetNumHops() >= 1 && hdr.GetSegmentsLeft() == hdr.GetNumHops(),
                        "ingress expects a fresh header (SL == NumHops >= 1)");
    // no deadline check at the ingress; steps 5-6 only: decrement, then index
    const uint8_t sl = hdr.GetSegmentsLeft() - 1;
    hdr.SetSegmentsLeft(sl);
    return hdr.GetSid(sl);
}

} // namespace tcrh
} // namespace ns3
