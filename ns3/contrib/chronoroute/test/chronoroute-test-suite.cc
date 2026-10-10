/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

/**
 * @file
 * @ingroup chronoroute
 *
 * The "chronoroute" test suite: the ns-3 T-CRH v1 and CRH-16/32 code checked
 * against the SAME golden vectors as the Python reference
 * (spec/golden/tcrh_vectors.json, crh_vectors.json). The vectors are compiled
 * in from golden-vectors.inc, which tools/golden_to_inc.py generates (ns-3 has
 * no JSON library). Any disagreement with a vector is a bug here, not in the
 * vector (spec/golden/README.md).
 *
 * Run: ./test.py -s chronoroute   (or ./ns3 run "test-runner --suite=chronoroute")
 */

#include "ns3/crh-header.h"
#include "ns3/nstime.h"
#include "ns3/packet.h"
#include "ns3/tcrh-header.h"
#include "ns3/tcrh-process.h"
#include "ns3/tcrh-timebase.h"
#include "ns3/test.h"

#include <cstdint>
#include <sstream>
#include <string>
#include <vector>

using namespace ns3;

namespace
{

// ---------------------------------------------------------------- vector types
// Field order is the order tools/golden_to_inc.py writes them in (C++20
// designated initializers must follow declaration order, so a mismatch does
// not compile). Absent / null JSON values stay value-initialised.

struct TcrhEncodeVector
{
    const char* name;
    const char* note;
    std::vector<uint32_t> sidsFwd;
    bool hasDeltasFwd;
    std::vector<uint32_t> deltasFwd;
    bool hasCumulativeBudgetsNs;
    std::vector<uint64_t> cumulativeBudgetsNs;
    bool hasEpochBase;
    uint32_t epochBase;
    bool hasTIngressGpsNs;
    uint64_t tIngressGpsNs;
    uint32_t unitCode;
    uint32_t nextHeader;
    uint32_t flags;
    const char* expectHex;
    std::vector<uint32_t> expectDeadlinesU;
    bool expectSat;
    uint32_t expectEpochBase;
    std::vector<uint32_t> expectDeltasFwd;
    uint32_t expectFlags;
    uint32_t expectSize;
};

struct TcrhProcessVector
{
    const char* name;
    const char* note;
    const char* hexIn;
    uint32_t nowU;
    const char* policy;
    const char* expectAction;
    bool hasExpectNextSid;
    uint32_t expectNextSid;
    const char* expectHexOut; // nullptr: the packet is discarded
    bool expectLate;
    bool hasExpectHopIndex;
    uint32_t expectHopIndex;
    bool hasExpectDeadlineU;
    uint32_t expectDeadlineU;
    const char* expectReason; // nullptr: no reason
    bool hasExpectIcmpCode;   // false: no ICMPv6 message is sent
    uint32_t expectIcmpCode;
    bool hasExpectIcmpPointer;
    uint32_t expectIcmpPointer;
};

struct TcrhLinkDownVector
{
    const char* name;
    const char* note;
    const char* hexIn; // the packet as it leaves step 5
    const char* expectAction;
    bool hasExpectNextSid;
    uint32_t expectNextSid;
    const char* expectHexOut; // nullptr: the packet is discarded
    bool hasExpectHopIndex;
    uint32_t expectHopIndex;
    const char* expectReason;
    bool hasExpectIcmpCode;
    uint32_t expectIcmpCode;
    bool hasExpectIcmpPointer;
    uint32_t expectIcmpPointer;
};

struct CrhEncodeVector
{
    const char* name;
    const char* note;
    uint32_t routingType;
    std::vector<uint32_t> sidsFwd;
    uint32_t nextHeader;
    const char* expectHex;
    uint32_t expectSize;
    uint32_t expectHdrExtLen;
    std::vector<uint32_t> expectDecodedSidsRev;
};

struct CrhProcessVector
{
    const char* name;
    const char* note;
    const char* hexIn;
    const char* expectAction;
    bool hasExpectNextSid;
    uint32_t expectNextSid;
    const char* expectHexOut;
    const char* expectReason;
    bool hasExpectIcmpCode;
    uint32_t expectIcmpCode;
    bool hasExpectIcmpPointer;
    uint32_t expectIcmpPointer;
};

#include "golden-vectors.inc"

// ---------------------------------------------------------------- helpers

std::vector<uint8_t>
FromHex(const std::string& hex)
{
    NS_ABORT_MSG_IF(hex.size() % 2 != 0, "odd-length hex string");
    std::vector<uint8_t> out;
    for (size_t i = 0; i < hex.size(); i += 2)
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

/// Lists as text, so NS_TEST macros can compare and print them.
template <typename T>
std::string
Join(const std::vector<T>& v)
{
    std::ostringstream os;
    os << "[";
    for (size_t i = 0; i < v.size(); ++i)
    {
        os << (i ? "," : "") << +v[i];
    }
    os << "]";
    return os.str();
}

std::string
Str(const char* s)
{
    return s == nullptr ? std::string("null") : std::string(s);
}

/// The bytes a Packet carries.
std::vector<uint8_t>
PacketBytes(Ptr<const Packet> p)
{
    std::vector<uint8_t> out(p->GetSize());
    p->CopyData(out.data(), out.size());
    return out;
}

template <typename T>
std::string
Opt(const std::optional<T>& v)
{
    if (!v.has_value())
    {
        return "null";
    }
    std::ostringstream os;
    os << +*v;
    return os.str();
}

/// Bytes out of a processing step as hex, or "null" when there are none.
std::string
OutHex(const std::optional<std::vector<uint8_t>>& bytes)
{
    return bytes.has_value() ? Hex(*bytes) : std::string("null");
}

std::string
OptExpected(bool has, uint32_t value)
{
    return has ? std::to_string(value) : std::string("null");
}

} // namespace

// ============================================================================
//  Time base (spec section 4): hand-worked values, then the edge cases
// ============================================================================

/**
 * @ingroup chronoroute-test
 * Unit codes, serial arithmetic, the unit clock and Epoch_Base rounding.
 */
class TcrhTimebaseTestCase : public TestCase
{
  public:
    TcrhTimebaseTestCase()
        : TestCase("T-CRH time base: unit codes, serial_diff, is_late, clock, Epoch_Base")
    {
    }

  private:
    void DoRun() override
    {
        using namespace tcrh;
        NS_TEST_EXPECT_MSG_EQ(UnitNs(0), 1000000ULL, "uc 0 = 1 ms");
        NS_TEST_EXPECT_MSG_EQ(UnitNs(1), 100000ULL, "uc 1 = 0.1 ms");
        NS_TEST_EXPECT_MSG_EQ(UnitNs(2), 250000ULL, "uc 2 = 0.25 ms");
        NS_TEST_EXPECT_MSG_EQ(UnitNs(3), 125000ULL, "uc 3 = 0.125 ms");
        NS_TEST_EXPECT_MSG_EQ(IsValidUnitCode(4), false, "only two UNIT bits");

        // serial_diff(a, b) = ((a - b + 2^31) mod 2^32) - 2^31, in [-2^31, 2^31)
        NS_TEST_EXPECT_MSG_EQ(SerialDiff(1007, 1006), 1, "plain difference");
        NS_TEST_EXPECT_MSG_EQ(SerialDiff(1006, 1007), -1, "plain difference, negative");
        NS_TEST_EXPECT_MSG_EQ(SerialDiff(0, 0xFFFFFFFFU), 1, "wraps forward past 2^32");
        NS_TEST_EXPECT_MSG_EQ(SerialDiff(0xFFFFFFFFU, 0), -1, "wraps backward past 0");
        NS_TEST_EXPECT_MSG_EQ(SerialDiff(0x7FFFFFFFU, 0), INT32_MAX, "largest positive");
        NS_TEST_EXPECT_MSG_EQ(SerialDiff(0x80000000U, 0), INT32_MIN, "half range is -2^31");
        NS_TEST_EXPECT_MSG_EQ(SerialDiff(0, 0x80000000U), INT32_MIN, "half range is -2^31 both ways");
        for (uint32_t a : {0U, 1U, 999U, 0x7FFFFFFEU, 0x80000001U, 0xFFFFFFFFU})
        {
            for (uint32_t b : {0U, 5U, 0x80000000U, 0xFFFFFFF0U})
            {
                const int64_t d = SerialDiff(a, b);
                // the defining property: d == a - b (mod 2^32), d in [-2^31, 2^31)
                NS_TEST_EXPECT_MSG_EQ(static_cast<uint32_t>(static_cast<int64_t>(b) + d),
                                      a,
                                      "serial_diff is a - b mod 2^32");
                if (d != INT32_MIN)
                {
                    NS_TEST_EXPECT_MSG_EQ(SerialDiff(b, a), -d, "antisymmetric off the half range");
                }
            }
        }

        // late means strictly after the deadline UNIT
        NS_TEST_EXPECT_MSG_EQ(IsLate(1006, 1006), false, "inside the deadline unit is on time");
        NS_TEST_EXPECT_MSG_EQ(IsLate(1007, 1006), true, "one unit later is late");
        NS_TEST_EXPECT_MSG_EQ(IsLate(0, 0xFFFFFFFFU), true, "late across the wrap");
        NS_TEST_EXPECT_MSG_EQ(IsLate(0xFFFFFFFFU, 0), false, "on time across the wrap");
        NS_TEST_EXPECT_MSG_EQ(IsLate(2147483647U, 4294967295U), false, "diff -2^31 is not late");

        // clock = floor, Epoch_Base = ceil, both mod 2^32
        NS_TEST_EXPECT_MSG_EQ(ClockU(1000000123ULL, 1), 10000U, "clock floors");
        NS_TEST_EXPECT_MSG_EQ(EpochBaseAtIngress(1000000123ULL, 1), 10001U, "anchor rounds up");
        NS_TEST_EXPECT_MSG_EQ(EpochBaseAtIngress(1000000000ULL, 1), 10000U, "exact: no rounding");
        NS_TEST_EXPECT_MSG_EQ(ClockU(429496729599999ULL, 1), 4294967295U, "just before 2^32 units");
        NS_TEST_EXPECT_MSG_EQ(EpochBaseAtIngress(429496729599999ULL, 1), 0U, "ceil wraps to 0");
        NS_TEST_EXPECT_MSG_EQ(ClockU(429496729600000ULL, 1), 0U, "clock wraps to 0");
        // 2026-10-10T13:58:00.123456Z in GPS ns, from the h10 golden vector
        NS_TEST_EXPECT_MSG_EQ(EpochBaseAtIngress(1475675898123456000ULL, 1),
                              3546319475U,
                              "real GPS time, 64-bit input");

        // the simulator clock: GPS = t0 + simulation time, exactly (integer ns)
        const uint64_t t0 = 1475675880000000000ULL;
        NS_TEST_EXPECT_MSG_EQ(SimToGpsNs(t0, NanoSeconds(123)), t0 + 123, "t0 + sim time");
        NS_TEST_EXPECT_MSG_EQ(NodeClockU(MicroSeconds(250), 0, 1), 2U, "250 us = 2 units of 0.1 ms");
        NS_TEST_EXPECT_MSG_EQ(NodeClockU(MicroSeconds(300), 0, 1), 3U, "300 us = exactly 3 units");
        NS_TEST_EXPECT_MSG_EQ(NodeClockU(NanoSeconds(299999), 0, 1), 2U, "1 ns short stays in unit 2");

        // section 5.1: exact ceil-cumulative encoding
        bool sat = true;
        std::vector<uint8_t> d =
            TcrhHeader::EncodeDeltas({300000ULL, 300001ULL, 400000ULL, 400000ULL}, 1, &sat);
        NS_TEST_EXPECT_MSG_EQ(Join(d), "[3,1,0,0]", "3.0 units -> 3; +1 ns -> 4 cumulative");
        NS_TEST_EXPECT_MSG_EQ(sat, false, "no saturation");
        d = TcrhHeader::EncodeDeltas({300000000ULL, 700000000ULL, 701000000ULL}, 0, &sat);
        NS_TEST_EXPECT_MSG_EQ(Join(d), "[255,255,191]", "repeated saturation");
        NS_TEST_EXPECT_MSG_EQ(sat, true, "SAT set");
        d = TcrhHeader::EncodeDeltas({5000000ULL, 4000000ULL}, 0, &sat);
        NS_TEST_EXPECT_MSG_EQ(Join(d), "[5,0]", "a decreasing budget gives delta 0, never wraps");
    }
};

// ============================================================================
//  T-CRH encode vectors: build, compare bytes, decode back
// ============================================================================

/**
 * @ingroup chronoroute-test
 * Every encode vector byte-exact, plus decode, Packet round trip and ingress.
 */
class TcrhEncodeVectorsTestCase : public TestCase
{
  public:
    TcrhEncodeVectorsTestCase()
        : TestCase("T-CRH v1 golden encode vectors (byte-exact) and decode")
    {
    }

  private:
    void DoRun() override
    {
        NS_TEST_ASSERT_MSG_GT(kTcrhEncodeVectorsCount, 0, "no T-CRH encode vectors compiled in");
        bool sawV0 = false;
        for (size_t n = 0; n < kTcrhEncodeVectorsCount; ++n)
        {
            const TcrhEncodeVector& v = kTcrhEncodeVectors[n];
            const std::string tag = std::string(v.name) + ": ";
            sawV0 = sawV0 || std::string(v.name) == "v0-3hop";
            const uint8_t uc = static_cast<uint8_t>(v.unitCode);

            std::vector<uint16_t> sids;
            for (uint32_t s : v.sidsFwd)
            {
                sids.push_back(static_cast<uint16_t>(s));
            }

            // 1. Epoch_Base: given, or ceil(t / u) mod 2^32 in exact integers
            NS_TEST_ASSERT_MSG_EQ((v.hasEpochBase != v.hasTIngressGpsNs), true, tag + "one epoch input");
            const uint32_t epoch =
                v.hasEpochBase ? v.epochBase : tcrh::EpochBaseAtIngress(v.tIngressGpsNs, uc);
            NS_TEST_EXPECT_MSG_EQ(epoch, v.expectEpochBase, tag + "Epoch_Base");

            // 2. deltas: given, or the section 5.1 encoder on the budgets
            std::vector<uint8_t> deltas;
            bool sat = false;
            if (v.hasDeltasFwd)
            {
                for (uint32_t d : v.deltasFwd)
                {
                    NS_TEST_ASSERT_MSG_LT_OR_EQ(d, 255U, tag + "given delta fits a byte");
                    deltas.push_back(static_cast<uint8_t>(d));
                }
            }
            else
            {
                deltas = TcrhHeader::EncodeDeltas(v.cumulativeBudgetsNs, uc, &sat);
            }
            std::vector<uint32_t> deltas32(deltas.begin(), deltas.end());
            NS_TEST_EXPECT_MSG_EQ(Join(deltas32), Join(v.expectDeltasFwd), tag + "deltas");

            // 3-4. flags = (uc << 4) | flags | SAT; fresh header, reverse entries
            TcrhHeader h;
            h.SetNextHeader(static_cast<uint8_t>(v.nextHeader));
            h.SetPath(sids,
                      deltas,
                      epoch,
                      uc,
                      static_cast<uint8_t>(v.flags | (sat ? TcrhHeader::FLAG_SAT : 0)));
            NS_TEST_EXPECT_MSG_EQ(h.ToHex(), std::string(v.expectHex), tag + "encoded bytes");
            NS_TEST_EXPECT_MSG_EQ(+h.GetFlags(), v.expectFlags, tag + "Flags byte");
            NS_TEST_EXPECT_MSG_EQ(h.IsSat(), v.expectSat, tag + "SAT");
            NS_TEST_EXPECT_MSG_EQ(h.GetSerializedSize(), v.expectSize, tag + "size");
            NS_TEST_EXPECT_MSG_EQ(TcrhHeader::SizeForHops(sids.size()), v.expectSize, tag + "pad8(12+3h)");
            NS_TEST_EXPECT_MSG_EQ(+h.GetHdrExtLen(), v.expectSize / 8 - 1, tag + "Hdr Ext Len");
            NS_TEST_EXPECT_MSG_EQ(Join(h.GetDeadlines()), Join(v.expectDeadlinesU), tag + "deadlines");
            for (size_t k = 1; k <= v.expectDeadlinesU.size(); ++k)
            {
                NS_TEST_EXPECT_MSG_EQ(h.GetDeadline(static_cast<uint8_t>(k)),
                                      v.expectDeadlinesU[k - 1],
                                      tag + "D_" + std::to_string(k));
            }

            // the one-call ingress builder agrees when it applies
            if (v.hasCumulativeBudgetsNs && v.hasTIngressGpsNs && v.flags == 0)
            {
                TcrhHeader b = TcrhHeader::Build(sids,
                                                 v.cumulativeBudgetsNs,
                                                 v.tIngressGpsNs,
                                                 uc,
                                                 static_cast<uint8_t>(v.nextHeader));
                NS_TEST_EXPECT_MSG_EQ(b.ToHex(), std::string(v.expectHex), tag + "Build()");
            }

            // decode the expected bytes (exact) and recover every field
            const std::vector<uint8_t> wire = FromHex(v.expectHex);
            TcrhHeader d;
            uint32_t used = 0;
            NS_TEST_EXPECT_MSG_EQ(
                TcrhHeader::ParseStatusName(TcrhHeader::Parse(wire.data(), wire.size(), true, &d, &used)),
                std::string("ok"),
                tag + "decode");
            NS_TEST_EXPECT_MSG_EQ(used, v.expectSize, tag + "decoded length");
            NS_TEST_EXPECT_MSG_EQ(Join(d.GetSidsForward()), Join(v.sidsFwd), tag + "decoded SIDs");
            NS_TEST_EXPECT_MSG_EQ(Join(d.GetDeadlines()), Join(v.expectDeadlinesU), tag + "decoded deadlines");
            NS_TEST_EXPECT_MSG_EQ(d.GetEpochBase(), v.expectEpochBase, tag + "decoded Epoch_Base");
            NS_TEST_EXPECT_MSG_EQ(+d.GetUnitCode(), v.unitCode, tag + "decoded unit code");
            NS_TEST_EXPECT_MSG_EQ(+d.GetNumHops(), sids.size(), tag + "decoded Num Hops");
            NS_TEST_EXPECT_MSG_EQ(+d.GetSegmentsLeft(), sids.size(), tag + "decoded SL");
            NS_TEST_EXPECT_MSG_EQ(+d.GetDevHop(), 0U, tag + "decoded Dev Hop");
            NS_TEST_EXPECT_MSG_EQ(d.ToHex(), std::string(v.expectHex), tag + "decode -> encode");
            // an exact decode refuses extra bytes; a prefix decode ignores them
            std::vector<uint8_t> longer = wire;
            longer.push_back(0xAB);
            NS_TEST_EXPECT_MSG_EQ(
                TcrhHeader::ParseStatusName(TcrhHeader::Parse(longer.data(), longer.size(), true, nullptr, nullptr)),
                std::string("trailing_bytes"),
                tag + "exact decode with a payload byte");
            NS_TEST_EXPECT_MSG_EQ(
                TcrhHeader::ParseStatusName(TcrhHeader::Parse(longer.data(), longer.size(), false, nullptr, nullptr)),
                std::string("ok"),
                tag + "prefix decode with a payload byte");

            // through a real ns-3 Packet: AddHeader writes these bytes in front
            // of the payload, RemoveHeader gets the same header back
            Ptr<Packet> p = Create<Packet>(37);
            p->AddHeader(h);
            std::vector<uint8_t> onWire = PacketBytes(p);
            onWire.resize(v.expectSize);
            NS_TEST_EXPECT_MSG_EQ(Hex(onWire), std::string(v.expectHex), tag + "bytes in a Packet");
            TcrhHeader back;
            NS_TEST_EXPECT_MSG_EQ(p->RemoveHeader(back), v.expectSize, tag + "RemoveHeader size");
            NS_TEST_EXPECT_MSG_EQ(p->GetSize(), 37U, tag + "payload intact");
            NS_TEST_EXPECT_MSG_EQ(back.ToHex(), std::string(v.expectHex), tag + "Packet round trip");

            // the ingress forwards to s_1 = SID[h-1] with SL = h - 1
            tcrh::IngressResult ing = tcrh::IngressSend(wire);
            NS_TEST_EXPECT_MSG_EQ(ing.ok, true, tag + "ingress: " + ing.error);
            if (ing.ok)
            {
                NS_TEST_EXPECT_MSG_EQ(ing.firstSid, sids.front(), tag + "ingress first SID");
                NS_TEST_EXPECT_MSG_EQ(+ing.outBytes[3], sids.size() - 1, tag + "ingress SL");
                std::vector<uint8_t> same = wire;
                same[3] = ing.outBytes[3];
                NS_TEST_EXPECT_MSG_EQ(Hex(ing.outBytes), Hex(same), tag + "ingress changes only SL");
            }
        }
        NS_TEST_EXPECT_MSG_EQ(sawV0, true, "the ns-3 reference vector v0-3hop must be present");
    }
};

// ============================================================================
//  T-CRH process vectors: one node's processing step (spec section 6)
// ============================================================================

/**
 * @ingroup chronoroute-test
 * Every process vector, on raw bytes (ProcessAtNode) and through the header
 * class (Packet::RemoveHeader -> ProcessHeader -> Serialize).
 */
class TcrhProcessVectorsTestCase : public TestCase
{
  public:
    TcrhProcessVectorsTestCase()
        : TestCase("T-CRH v1 golden process vectors (action, next SID, bytes, late, hop, deadline)")
    {
    }

  private:
    void DoRun() override
    {
        NS_TEST_ASSERT_MSG_GT(kTcrhProcessVectorsCount, 0, "no T-CRH process vectors compiled in");
        for (size_t n = 0; n < kTcrhProcessVectorsCount; ++n)
        {
            const TcrhProcessVector& v = kTcrhProcessVectors[n];
            const std::string tag = std::string(v.name) + ": ";
            tcrh::Policy policy;
            NS_TEST_ASSERT_MSG_EQ(tcrh::PolicyFromName(v.policy, &policy), true, tag + "policy name");
            const std::vector<uint8_t> raw = FromHex(v.hexIn);

            // ---- raw bytes, exactly like Python process_at_node ----
            tcrh::ProcessResult r = tcrh::ProcessAtNode(raw, v.nowU, policy);
            NS_TEST_EXPECT_MSG_EQ(std::string(tcrh::ActionName(r.action)),
                                  std::string(v.expectAction),
                                  tag + "action");
            NS_TEST_EXPECT_MSG_EQ(Opt(r.nextSid), OptExpected(v.hasExpectNextSid, v.expectNextSid), tag + "next SID");
            NS_TEST_EXPECT_MSG_EQ(OutHex(r.outBytes),
                                  Str(v.expectHexOut),
                                  tag + "bytes out");
            NS_TEST_EXPECT_MSG_EQ(r.late, v.expectLate, tag + "late");
            NS_TEST_EXPECT_MSG_EQ(Opt(r.hopIndex), OptExpected(v.hasExpectHopIndex, v.expectHopIndex), tag + "hop index");
            NS_TEST_EXPECT_MSG_EQ(Opt(r.deadlineU), OptExpected(v.hasExpectDeadlineU, v.expectDeadlineU), tag + "deadline");
            NS_TEST_EXPECT_MSG_EQ(Str(r.reason), Str(v.expectReason), tag + "reason");
            // ICMP: the exact code and pointer (spec section 6 step 1), or none
            NS_TEST_EXPECT_MSG_EQ(Opt(r.icmpCode),
                                  OptExpected(v.hasExpectIcmpCode, v.expectIcmpCode),
                                  tag + "ICMP code");
            NS_TEST_EXPECT_MSG_EQ(Opt(r.icmpPointer),
                                  OptExpected(v.hasExpectIcmpPointer, v.expectIcmpPointer),
                                  tag + "ICMP pointer");

            // ---- a payload after the header passes through untouched ----
            std::vector<uint8_t> withPayload = raw;
            for (uint8_t b : {0xDE, 0xAD, 0xBE, 0xEF})
            {
                withPayload.push_back(b);
            }
            tcrh::ProcessResult rp = tcrh::ProcessAtNode(withPayload, v.nowU, policy);
            if (v.expectHexOut != nullptr)
            {
                NS_TEST_EXPECT_MSG_EQ(OutHex(rp.outBytes),
                                      std::string(v.expectHexOut) + "deadbeef",
                                      tag + "payload passes through");
            }
            else if (Str(v.expectReason) != "truncated")
            {
                // (a truncated header with 4 more bytes may become a different case)
                NS_TEST_EXPECT_MSG_EQ(std::string(tcrh::ActionName(rp.action)),
                                      std::string(v.expectAction),
                                      tag + "action with payload");
            }

            // ---- the header class: what an ns-3 node would run ----
            Ptr<Packet> p = Create<Packet>(raw.data(), raw.size());
            TcrhHeader h;
            uint32_t used = p->RemoveHeader(h);
            if (std::string(v.expectAction) == "drop_malformed" ||
                std::string(v.expectAction) == "ignore")
            {
                // not a valid T-CRH (an ignored one is not a T-CRH at all)
                NS_TEST_EXPECT_MSG_EQ(used, 0U, tag + "malformed: Deserialize consumes nothing");
                NS_TEST_EXPECT_MSG_EQ(std::string(TcrhHeader::ParseStatusName(h.GetParseStatus())),
                                      Str(v.expectReason),
                                      tag + "Deserialize reason");
                NS_TEST_EXPECT_MSG_EQ(p->GetSize(), raw.size(), tag + "malformed packet left alone");
                continue;
            }
            NS_TEST_EXPECT_MSG_EQ(std::string(TcrhHeader::ParseStatusName(h.GetParseStatus())),
                                  std::string("ok"),
                                  tag + "Deserialize");
            NS_TEST_EXPECT_MSG_EQ(h.ToHex(), Hex(std::vector<uint8_t>(raw.begin(), raw.begin() + used)),
                                  tag + "Deserialize -> Serialize keeps every byte");
            tcrh::ProcessResult rh = tcrh::ProcessHeader(h, v.nowU, policy);
            NS_TEST_EXPECT_MSG_EQ(std::string(tcrh::ActionName(rh.action)),
                                  std::string(v.expectAction),
                                  tag + "header action");
            NS_TEST_EXPECT_MSG_EQ(Opt(rh.nextSid), OptExpected(v.hasExpectNextSid, v.expectNextSid), tag + "header next SID");
            NS_TEST_EXPECT_MSG_EQ(rh.late, v.expectLate, tag + "header late");
            NS_TEST_EXPECT_MSG_EQ(Opt(rh.hopIndex), OptExpected(v.hasExpectHopIndex, v.expectHopIndex), tag + "header hop index");
            NS_TEST_EXPECT_MSG_EQ(Opt(rh.deadlineU), OptExpected(v.hasExpectDeadlineU, v.expectDeadlineU), tag + "header deadline");
            if (v.expectHexOut != nullptr)
            {
                NS_TEST_EXPECT_MSG_EQ(h.ToHex(),
                                      std::string(v.expectHexOut).substr(0, 2 * used),
                                      tag + "header bytes out");
            }
        }
    }
};

// ============================================================================
//  T-CRH link-down vectors (spec section 6 step 7)
// ============================================================================

/**
 * @ingroup chronoroute-test
 * Every link-down vector: the packet as it leaves step 5, the next link is
 * down, so DEV (Dev Hop k, 0 at the ingress), GREEDY, SL = 0, head for SID[0].
 */
class TcrhLinkDownVectorsTestCase : public TestCase
{
  public:
    TcrhLinkDownVectorsTestCase()
        : TestCase("T-CRH v1 golden link-down vectors (spec 6 step 7, Dev Hop 0 at the ingress)")
    {
    }

  private:
    void DoRun() override
    {
        NS_TEST_ASSERT_MSG_GT(kTcrhLinkDownVectorsCount, 0, "no T-CRH link-down vectors compiled in");
        bool sawIngress = false;
        for (size_t n = 0; n < kTcrhLinkDownVectorsCount; ++n)
        {
            const TcrhLinkDownVector& v = kTcrhLinkDownVectors[n];
            const std::string tag = std::string(v.name) + ": ";
            sawIngress = sawIngress || (v.hasExpectHopIndex && v.expectHopIndex == 0);
            const std::vector<uint8_t> raw = FromHex(v.hexIn);
            tcrh::ProcessResult r = tcrh::LinkDownFallback(raw);
            NS_TEST_EXPECT_MSG_EQ(std::string(tcrh::ActionName(r.action)),
                                  std::string(v.expectAction),
                                  tag + "action");
            NS_TEST_EXPECT_MSG_EQ(Opt(r.nextSid), OptExpected(v.hasExpectNextSid, v.expectNextSid), tag + "next SID");
            NS_TEST_EXPECT_MSG_EQ(OutHex(r.outBytes), Str(v.expectHexOut), tag + "bytes out");
            NS_TEST_EXPECT_MSG_EQ(Opt(r.hopIndex), OptExpected(v.hasExpectHopIndex, v.expectHopIndex), tag + "hop index");
            NS_TEST_EXPECT_MSG_EQ(Str(r.reason), Str(v.expectReason), tag + "reason");
            NS_TEST_EXPECT_MSG_EQ(Opt(r.icmpCode), OptExpected(v.hasExpectIcmpCode, v.expectIcmpCode), tag + "ICMP code");
            NS_TEST_EXPECT_MSG_EQ(Opt(r.icmpPointer),
                                  OptExpected(v.hasExpectIcmpPointer, v.expectIcmpPointer),
                                  tag + "ICMP pointer");
            NS_TEST_EXPECT_MSG_EQ(r.late, false, tag + "a dead link is not a late packet");
            if (v.expectHexOut != nullptr)
            {
                // a payload after the header passes through untouched
                std::vector<uint8_t> withPayload = raw;
                withPayload.push_back(0xAB);
                NS_TEST_EXPECT_MSG_EQ(OutHex(tcrh::LinkDownFallback(withPayload).outBytes),
                                      std::string(v.expectHexOut) + "ab",
                                      tag + "payload passes through");
                // the final endpoint accepts and delivers the fallback packet
                tcrh::ProcessResult d =
                    tcrh::ProcessAtNode(*r.outBytes, 0xFFFFFFF0U, tcrh::Policy::GREEDY);
                NS_TEST_EXPECT_MSG_EQ(std::string(tcrh::ActionName(d.action)),
                                      std::string("deliver"),
                                      tag + "delivered at SID[0]");
            }
        }
        NS_TEST_EXPECT_MSG_EQ(sawIngress, true, "a vector with Dev Hop 0 (the ingress) must be present");
    }
};

// ============================================================================
//  A whole path, hop by hop (ingress, transit, final endpoint)
// ============================================================================

/**
 * @ingroup chronoroute-test
 * Walk the v0-3hop packet along 2 -> 3 -> 7 with the clock exactly at each
 * deadline (on time, spec: "anywhere inside unit D_k is on time"), then again
 * one unit late at hop 2 under each policy.
 */
class TcrhPathWalkTestCase : public TestCase
{
  public:
    TcrhPathWalkTestCase()
        : TestCase("T-CRH v1 path walk: ingress, transit, final endpoint, policies")
    {
    }

  private:
    void DoRun() override
    {
        TcrhHeader h;
        h.SetPath({2, 3, 7}, {6, 7, 8}, 1000, 0);
        tcrh::IngressResult ing = tcrh::IngressSend(h.ToBytes());
        NS_TEST_ASSERT_MSG_EQ(ing.ok, true, ing.error);
        NS_TEST_EXPECT_MSG_EQ(ing.firstSid, 2, "ingress sends to the first hop");

        // on time everywhere: forward, forward, deliver; DEV never set
        std::vector<uint8_t> pkt = ing.outBytes;
        const uint32_t deadlines[3] = {1006, 1013, 1021};
        const char* actions[3] = {"forward", "forward", "deliver"};
        const int next[3] = {3, 7, -1};
        for (int k = 0; k < 3; ++k)
        {
            tcrh::ProcessResult r = tcrh::ProcessAtNode(pkt, deadlines[k], tcrh::Policy::GREEDY);
            NS_TEST_EXPECT_MSG_EQ(std::string(tcrh::ActionName(r.action)), std::string(actions[k]), "on-time action");
            NS_TEST_EXPECT_MSG_EQ(r.late, false, "on time inside D_k");
            NS_TEST_EXPECT_MSG_EQ(Opt(r.hopIndex), std::to_string(k + 1), "hop index");
            NS_TEST_EXPECT_MSG_EQ(Opt(r.deadlineU), std::to_string(deadlines[k]), "deadline");
            const std::string expectNext = next[k] < 0 ? std::string("null") : std::to_string(next[k]);
            NS_TEST_EXPECT_MSG_EQ(Opt(r.nextSid), expectNext, "next SID");
            NS_TEST_ASSERT_MSG_EQ(r.outBytes.has_value(), true, "bytes out");
            pkt = *r.outBytes;
        }
        NS_TEST_EXPECT_MSG_EQ(+pkt[TcrhHeader::OFF_FLAGS], 0, "never flagged");

        // one unit late at hop 2, under each policy
        std::vector<uint8_t> atHop2 = tcrh::ProcessAtNode(ing.outBytes, 1006, tcrh::Policy::GREEDY).outBytes.value();
        tcrh::ProcessResult g = tcrh::ProcessAtNode(atHop2, 1014, tcrh::Policy::GREEDY);
        NS_TEST_EXPECT_MSG_EQ(std::string(tcrh::ActionName(g.action)), std::string("fallback"), "greedy");
        NS_TEST_EXPECT_MSG_EQ(Opt(g.nextSid), std::string("7"), "greedy heads for SID[0]");
        NS_TEST_EXPECT_MSG_EQ(+g.outBytes.value()[TcrhHeader::OFF_FLAGS], 0x03, "DEV|GREEDY");
        NS_TEST_EXPECT_MSG_EQ(+g.outBytes.value()[TcrhHeader::OFF_DEV_HOP], 2, "Dev Hop 2");
        NS_TEST_EXPECT_MSG_EQ(+g.outBytes.value()[TcrhHeader::OFF_SEGMENTS_LEFT], 0, "SL 0");
        tcrh::ProcessResult c = tcrh::ProcessAtNode(atHop2, 1014, tcrh::Policy::CONTINUE);
        NS_TEST_EXPECT_MSG_EQ(std::string(tcrh::ActionName(c.action)), std::string("forward"), "continue");
        NS_TEST_EXPECT_MSG_EQ(+c.outBytes.value()[TcrhHeader::OFF_FLAGS], 0x01, "DEV only");
        // the final endpoint does not check again once DEV is set: Dev Hop stays 2
        tcrh::ProcessResult f = tcrh::ProcessAtNode(c.outBytes.value(), 5000, tcrh::Policy::CONTINUE);
        NS_TEST_EXPECT_MSG_EQ(std::string(tcrh::ActionName(f.action)), std::string("deliver"), "delivered");
        NS_TEST_EXPECT_MSG_EQ(f.late, false, "no second check");
        NS_TEST_EXPECT_MSG_EQ(+f.outBytes.value()[TcrhHeader::OFF_DEV_HOP], 2, "Dev Hop kept");
        tcrh::ProcessResult x = tcrh::ProcessAtNode(atHop2, 1014, tcrh::Policy::DROP);
        NS_TEST_EXPECT_MSG_EQ(std::string(tcrh::ActionName(x.action)), std::string("drop_late"), "drop");
        NS_TEST_EXPECT_MSG_EQ(x.outBytes.has_value(), false, "dropped: no bytes");

        // a stale header with SL < NumHops is not fresh: the ingress refuses it
        NS_TEST_EXPECT_MSG_EQ(tcrh::IngressSend(atHop2).ok, false, "ingress needs SL == NumHops");
    }
};

// ============================================================================
//  CRH-16 / CRH-32 (RFC 9631)
// ============================================================================

/**
 * @ingroup chronoroute-test
 * Every CRH encode vector byte-exact; decode returns every SID slot.
 */
class CrhEncodeVectorsTestCase : public TestCase
{
  public:
    CrhEncodeVectorsTestCase()
        : TestCase("CRH-16 and CRH-32 golden encode vectors (byte-exact) and decode")
    {
    }

  private:
    void DoRun() override
    {
        NS_TEST_ASSERT_MSG_GT(kCrhEncodeVectorsCount, 0, "no CRH encode vectors compiled in");
        bool sawNs3 = false;
        for (size_t n = 0; n < kCrhEncodeVectorsCount; ++n)
        {
            const CrhEncodeVector& v = kCrhEncodeVectors[n];
            const std::string tag = std::string(v.name) + ": ";
            sawNs3 = sawNs3 || std::string(v.name) == "ns3-crh16-3hop";
            CrhHeader h;
            h.SetNextHeader(static_cast<uint8_t>(v.nextHeader));
            h.SetPath(v.sidsFwd, static_cast<uint8_t>(v.routingType));
            NS_TEST_EXPECT_MSG_EQ(h.ToHex(), std::string(v.expectHex), tag + "encoded bytes");
            NS_TEST_EXPECT_MSG_EQ(h.GetSerializedSize(), v.expectSize, tag + "size");
            NS_TEST_EXPECT_MSG_EQ(+h.GetHdrExtLen(), v.expectHdrExtLen, tag + "Hdr Ext Len");
            NS_TEST_EXPECT_MSG_EQ(+h.GetSegmentsLeft(), v.sidsFwd.size(), tag + "SL = n");

            const std::vector<uint8_t> wire = FromHex(v.expectHex);
            CrhHeader d;
            NS_TEST_EXPECT_MSG_EQ(
                std::string(CrhHeader::ParseStatusName(CrhHeader::Parse(wire.data(), wire.size(), true, &d, nullptr))),
                std::string("ok"),
                tag + "decode");
            NS_TEST_EXPECT_MSG_EQ(Join(d.GetSidsReversed()), Join(v.expectDecodedSidsRev), tag + "every SID slot");
            NS_TEST_EXPECT_MSG_EQ(d.ToHex(), std::string(v.expectHex), tag + "decode -> encode");

            Ptr<Packet> p = Create<Packet>(11);
            p->AddHeader(h);
            CrhHeader back;
            NS_TEST_EXPECT_MSG_EQ(p->RemoveHeader(back), v.expectSize, tag + "RemoveHeader size");
            NS_TEST_EXPECT_MSG_EQ(back.ToHex(), std::string(v.expectHex), tag + "Packet round trip");
        }
        NS_TEST_EXPECT_MSG_EQ(sawNs3, true, "the ns-3 reference vector ns3-crh16-3hop must be present");

        // RFC 9631 64-bit boundary rule, as the Assessment 7 self-test printed it
        const uint32_t crh16[8] = {8, 8, 16, 16, 16, 16, 24, 24};
        for (uint32_t k = 1; k <= 8; ++k)
        {
            NS_TEST_EXPECT_MSG_EQ(CrhHeader::SizeForSids(k, CrhHeader::ROUTING_TYPE_CRH16),
                                  crh16[k - 1],
                                  "CRH-16 size for " << k << " SIDs");
        }
        // the literal RFC 9631 5.1 formula for L
        NS_TEST_EXPECT_MSG_EQ(+CrhHeader::MinHdrExtLen(2, 5), 0, "CRH-16 L(2)");
        NS_TEST_EXPECT_MSG_EQ(+CrhHeader::MinHdrExtLen(3, 5), 1, "CRH-16 L(3)");
        NS_TEST_EXPECT_MSG_EQ(+CrhHeader::MinHdrExtLen(6, 5), 1, "CRH-16 L(6)");
        NS_TEST_EXPECT_MSG_EQ(+CrhHeader::MinHdrExtLen(7, 5), 2, "CRH-16 L(7)");
        NS_TEST_EXPECT_MSG_EQ(+CrhHeader::MinHdrExtLen(1, 6), 0, "CRH-32 L(1)");
        NS_TEST_EXPECT_MSG_EQ(+CrhHeader::MinHdrExtLen(2, 6), 1, "CRH-32 L(2)");
        NS_TEST_EXPECT_MSG_EQ(+CrhHeader::MinHdrExtLen(4, 6), 2, "CRH-32 L(4)");
    }
};

/**
 * @ingroup chronoroute-test
 * Every CRH process vector (RFC 9631 section 5).
 */
class CrhProcessVectorsTestCase : public TestCase
{
  public:
    CrhProcessVectorsTestCase()
        : TestCase("CRH-16 and CRH-32 golden process vectors (RFC 9631 section 5)")
    {
    }

  private:
    void DoRun() override
    {
        NS_TEST_ASSERT_MSG_GT(kCrhProcessVectorsCount, 0, "no CRH process vectors compiled in");
        for (size_t n = 0; n < kCrhProcessVectorsCount; ++n)
        {
            const CrhProcessVector& v = kCrhProcessVectors[n];
            const std::string tag = std::string(v.name) + ": ";
            const std::vector<uint8_t> raw = FromHex(v.hexIn);
            CrhProcessResult r = CrhProcessAtNode(raw.data(), raw.size());
            NS_TEST_EXPECT_MSG_EQ(r.action, std::string(v.expectAction), tag + "action");
            NS_TEST_EXPECT_MSG_EQ(Opt(r.nextSid), OptExpected(v.hasExpectNextSid, v.expectNextSid), tag + "next SID");
            NS_TEST_EXPECT_MSG_EQ(OutHex(r.outBytes),
                                  Str(v.expectHexOut),
                                  tag + "bytes out");
            NS_TEST_EXPECT_MSG_EQ(Str(r.reason), Str(v.expectReason), tag + "reason");
            NS_TEST_EXPECT_MSG_EQ(Opt(r.icmpCode), OptExpected(v.hasExpectIcmpCode, v.expectIcmpCode), tag + "ICMP code");
            NS_TEST_EXPECT_MSG_EQ(Opt(r.icmpPointer),
                                  OptExpected(v.hasExpectIcmpPointer, v.expectIcmpPointer),
                                  tag + "ICMP pointer");
        }
    }
};

/**
 * @ingroup chronoroute-test
 * The chronoroute test suite.
 */
class ChronorouteTestSuite : public TestSuite
{
  public:
    ChronorouteTestSuite()
        : TestSuite("chronoroute", Type::UNIT)
    {
        AddTestCase(new TcrhTimebaseTestCase, TestCase::Duration::QUICK);
        AddTestCase(new TcrhEncodeVectorsTestCase, TestCase::Duration::QUICK);
        AddTestCase(new TcrhProcessVectorsTestCase, TestCase::Duration::QUICK);
        AddTestCase(new TcrhLinkDownVectorsTestCase, TestCase::Duration::QUICK);
        AddTestCase(new TcrhPathWalkTestCase, TestCase::Duration::QUICK);
        AddTestCase(new CrhEncodeVectorsTestCase, TestCase::Duration::QUICK);
        AddTestCase(new CrhProcessVectorsTestCase, TestCase::Duration::QUICK);
    }
};

/// Static variable for test initialization
static ChronorouteTestSuite g_chronorouteTestSuite;
