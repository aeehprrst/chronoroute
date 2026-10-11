/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#ifndef CRH_HEADER_H
#define CRH_HEADER_H

#include "ns3/buffer.h"
#include "ns3/ipv6-extension-header.h"

#include <cstdint>
#include <optional>
#include <ostream>
#include <string>
#include <vector>

namespace ns3
{

/**
 * @ingroup chronoroute
 *
 * The IPv6 Compact Routing Header, CRH-16 (Routing Type 5) and CRH-32
 * (Routing Type 6), RFC 9631. T-CRH extends it; ChronoRoute uses it as the
 * "no time information" baseline. Moved here from the Assessment 7 program
 * scratch/crh-experiment.cc (byte-identical for CRH-16) and extended to
 * CRH-32. C++ twin of Python chronoroute.proto.crh.
 *
 * @verbatim
     0               1               2               3
    +---------------+---------------+---------------+---------------+
    |  Next Header  |  Hdr Ext Len  | Routing Type  | Segments Left |   4 fixed bytes
    +---------------+---------------+---------------+---------------+
    |      SID[0]  |  SID[1]  |  ...   (16 bits each for CRH-16;
    |                                   32 bits each for CRH-32)
    +---------------------------------------------------------------+
                  (zero padding to a 64-bit boundary)
   @endverbatim
 *
 * Rules (RFC 9631 sections 3 and 5):
 *  - SIDs are stored in REVERSE path order, so SID[0] is the last hop.
 *  - A node decrements Segments Left FIRST, then reads SID[Segments Left].
 *  - There is no SID count. A receiver cannot tell a real SID from a zero
 *    padding slot and never needs to: it only reads SID[Segments Left - 1], and
 *    the minimum-length check (section 5.1) proves that slot is inside the
 *    header before it is read. Deserialize() therefore keeps EVERY SID slot,
 *    padding included, exactly like the Assessment 7 code.
 *
 * Segments Left may exceed the number of slots: that is exactly the forged
 * header the minimum-length check rejects, so it must be representable.
 *
 * Like TcrhHeader, this is a REAL IPv6 routing header (phase P5a): it derives
 * from ns3::Ipv6ExtensionRoutingHeader and keeps Next Header, Hdr Ext Len,
 * Routing Type and Segments Left in that base class, so ns-3 code holding a
 * base pointer sees the same values. Wireshark decodes Routing Types 5 and 6
 * natively (packet-ipv6.c), which makes CRH-16 a handy cross-check in pcaps.
 */
class CrhHeader : public Ipv6ExtensionRoutingHeader
{
  public:
    static constexpr uint8_t ROUTING_TYPE_CRH16 = 5; //!< RFC 9631, 16-bit SIDs
    static constexpr uint8_t ROUTING_TYPE_CRH32 = 6; //!< RFC 9631, 32-bit SIDs
    static constexpr uint32_t FIXED_BYTES = 4;       //!< bytes before SID[0]
    static constexpr uint8_t DEFAULT_NEXT_HEADER = 17; //!< UDP
    static constexpr uint8_t OFF_HDR_EXT_LEN = 1;    //!< Hdr Ext Len
    static constexpr uint8_t OFF_ROUTING_TYPE = 2;   //!< Routing Type
    static constexpr uint8_t OFF_SEGMENTS_LEFT = 3;  //!< Segments Left
    static constexpr uint8_t ICMP_CODE_ERRONEOUS_FIELD = 0; //!< SID not in the FIB, wrong type
    static constexpr uint8_t ICMP_CODE_MIN_LENGTH = 6;      //!< L > Hdr Ext Len (RFC 9631 5)

    /// Result of validating bytes. Checks in this order: TRUNCATED (fewer than
    /// 8 bytes), WRONG_TYPE, TRUNCATED (fewer than Hdr Ext Len announces),
    /// TRAILING_BYTES (exact parsing only).
    enum ParseStatus : uint8_t
    {
        OK = 0,         //!< valid
        TRUNCATED,      //!< "truncated"
        WRONG_TYPE,     //!< "wrong_type": not 5 or 6
        TRAILING_BYTES, //!< "trailing_bytes"
    };

    /// @param status a parse status
    /// @return the golden-vector reason code ("truncated", ...) or "ok"
    static const char* ParseStatusName(ParseStatus status);

    /// @param routingType 5 or 6 (aborts otherwise)
    /// @return SID size in bytes (2 or 4)
    static uint32_t SidBytes(uint8_t routingType);

    /// @param numSids number of SIDs
    /// @param routingType 5 or 6
    /// @return pad8(4 + n * SID size)
    static uint32_t SizeForSids(uint32_t numSids, uint8_t routingType);

    /**
     * L, the minimum CRH length for this Segments Left, in 8-octet units not
     * counting the first 8 (RFC 9631 section 5.1, implemented literally):
     * CRH-16: SL <= 2 -> 0, else ceil((SL - 2) / 4);
     * CRH-32: SL <= 1 -> 0, else ceil((SL - 1) / 2).
     * @param segmentsLeft Segments Left
     * @param routingType 5 or 6
     * @return L
     */
    static uint8_t MinHdrExtLen(uint8_t segmentsLeft, uint8_t routingType);

    /**
     * Parse raw bytes (every SID slot is kept).
     * @param data bytes starting with the CRH
     * @param len number of bytes
     * @param exact refuse bytes beyond Hdr Ext Len
     * @param out the parsed header on success (may be nullptr)
     * @param headerBytes out: (HdrExtLen + 1) * 8 (may be nullptr)
     * @return OK or the reason
     */
    static ParseStatus Parse(const uint8_t* data,
                             uint32_t len,
                             bool exact,
                             CrhHeader* out,
                             uint32_t* headerBytes);

    CrhHeader();

    /**
     * @brief Get the type ID.
     * @return the object TypeId
     */
    static TypeId GetTypeId();
    TypeId GetInstanceTypeId() const override;

    /**
     * Load a path in FORWARD order; it is stored reversed and Segments Left
     * is set to n. Aborts on n outside 1..255, a bad routing type, a SID too
     * large for CRH-16, or a header longer than Hdr Ext Len can describe.
     * @param sidsFwd SIDs in the order the packet visits them
     * @param routingType 5 (CRH-16) or 6 (CRH-32)
     */
    void SetPath(const std::vector<uint32_t>& sidsFwd, uint8_t routingType = ROUTING_TYPE_CRH16);

    // Next Header (Get/SetNextHeader), Routing Type (GetTypeRouting: 5 or 6)
    // and Segments Left (Get/SetSegmentsLeft, not checked: forged values must
    // be representable) are the inherited base-class accessors.

    /// @return Hdr Ext Len
    uint8_t GetHdrExtLen() const;
    /// @return L for the current Segments Left (RFC 9631 5.1)
    uint8_t GetMinimumLength() const;
    /// @return number of SID slots (padding slots of a decoded header included)
    uint32_t GetNumSids() const;
    /// @param i wire index
    /// @return SID[i]
    uint32_t GetSid(uint32_t i) const;
    /// @return every SID slot in wire order
    const std::vector<uint32_t>& GetSidsReversed() const;
    /// @return SID[Segments Left], the SID a node has just decremented onto
    uint32_t GetCurrentSid() const;

    /// @return the serialized bytes
    std::vector<uint8_t> ToBytes() const;
    /// @return the serialized bytes as lowercase hex
    std::string ToHex() const;
    /// @return OK, or why the last Deserialize() rejected the bytes
    ParseStatus GetParseStatus() const;

    uint32_t GetSerializedSize() const override;
    void Serialize(Buffer::Iterator start) const override;
    uint32_t Deserialize(Buffer::Iterator start) override;
    void Print(std::ostream& os) const override;

  private:
    /// Keep the base class's Hdr Ext Len equal to the size the SID slots need
    /// (a CRH has no other length information).
    void SyncLength();

    // Next Header, Hdr Ext Len, Routing Type and Segments Left live in the base.
    std::vector<uint32_t> m_sids; //!< SID slots, REVERSE path order
    ParseStatus m_status;         //!< result of the last Deserialize()
};

/// Outcome of CrhProcessAtNode() (Python CrhProcessResult).
struct CrhProcessResult
{
    std::string action; //!< "deliver", "forward", "drop_malformed" or "ignore" (unknown type, SL 0)
    std::optional<uint32_t> nextSid;              //!< SID to look up in the CRH-FIB
    std::optional<std::vector<uint8_t>> outBytes; //!< bytes with Segments Left updated
    const char* reason{nullptr};                  //!< "wrong_type", "truncated", "min_length"
    std::optional<uint8_t> icmpCode;              //!< ICMPv6 Parameter Problem code
    std::optional<uint8_t> icmpPointer;           //!< offending field offset
};

/**
 * RFC 9631 section 5 forwarding step as a pure function of the bytes (the
 * source runs it too, Appendix A.1). Anything after the CRH passes through.
 *  0. Segments Left == 0: the packet is for this node -> deliver
 *  1. L = minimum CRH length; L > Hdr Ext Len -> discard, ICMPv6 Parameter
 *     Problem Code 6, pointer to Segments Left
 *  2. decrement Segments Left; 3. current SID = SID[Segments Left]
 *  4. (caller) CRH-FIB lookup; no entry -> discard, Code 0
 * @param raw bytes starting with the CRH
 * @param len number of bytes
 * @return the outcome
 */
CrhProcessResult CrhProcessAtNode(const uint8_t* raw, uint32_t len);

} // namespace ns3

#endif /* CRH_HEADER_H */
