/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#ifndef TCRH_HEADER_H
#define TCRH_HEADER_H

#include "ns3/buffer.h"
#include "ns3/header.h"

#include <cstdint>
#include <ostream>
#include <string>
#include <vector>

/**
 * @defgroup chronoroute ChronoRoute
 *
 * T-CRH v1 (Temporal Compact Routing Header, IPv6 Routing Type 253) and the
 * CRH-16/32 baseline (RFC 9631). spec/tcrh-v1.md in the ChronoRoute
 * repository is normative; every class here is tested byte for byte against
 * the shared golden vectors in spec/golden/.
 */

namespace ns3
{

/**
 * @ingroup chronoroute
 *
 * The Temporal Compact Routing Header, T-CRH v1 (spec/tcrh-v1.md section 2):
 *
 * @verbatim
     0               1               2               3
    +---------------+---------------+---------------+---------------+
    |  Next Header  |  Hdr Ext Len  | Rtg Type =253 | Segments Left |  bytes 0-3
    +---------------+---------------+---------------+---------------+
    |     Flags     |   Num Hops    |    Dev Hop    |   Reserved    |  bytes 4-7
    +---------------+---------------+---------------+---------------+
    |                          Epoch_Base                           |  bytes 8-11
    +---------------+---------------+---------------+---------------+
    |        SID[0] (16 bits)       |  Delta[0]     |  SID[1] ...   |  3 B per entry
    +---------------+---------------+---------------+---------------+
                     (zero padding to a multiple of 8 bytes)
   @endverbatim
 *
 * Entries are stored in REVERSE path order, as in RFC 9631, so that Segments
 * Left can be used directly as an index: SID[0] is the final endpoint and
 * SID[h-1] the first hop. A node decrements Segments Left FIRST and then reads
 * SID[Segments Left].
 *
 * A received header keeps every byte it arrived with: a Reserved byte, reserved
 * flag bits or padding that are not zero, and a Hdr Ext Len larger than needed,
 * are all ignored on receipt (spec section 2) and written back unchanged by
 * Serialize(), as a router must. A header built with SetPath() has them zero.
 *
 * Deserialize() validates (spec section 6 step 1) and never reads past the end
 * of the buffer. On malformed bytes it consumes nothing (returns 0) and
 * GetParseStatus() says why; the reason codes and the order of the checks are
 * the ones in spec/golden/README.md, shared with the Python reference.
 *
 * LATER PHASE (P5, a real IPv6 extension): this class is deliberately shaped
 * so that it can derive from ns3::Ipv6ExtensionRoutingHeader instead of
 * ns3::Header. The accessors for the four bytes every routing header shares
 * already use that class's names (Get/SetNextHeader, GetTypeRouting,
 * Get/SetSegmentsLeft), and Serialize()/Deserialize() read and write the whole
 * header, those four bytes included. To switch: change the base class, keep
 * the fields in the base in sync (SetNextHeader, SetTypeRouting(253),
 * SetSegmentsLeft, SetLength(GetSerializedSize())) or forward these accessors
 * to the base, and keep the overrides of GetSerializedSize/Serialize/
 * Deserialize/Print. Ipv6ExtensionRoutingDemux needs exactly that to fragment a
 * packet that carries the header (ipv6-extension.cc, GetExtensionRoutingHeaderPtr).
 */
class TcrhHeader : public Header
{
  public:
    // ----- header constants (spec sections 2, 3 and 7) -----
    static constexpr uint8_t ROUTING_TYPE = 253; //!< RFC 4727 experimental value
    static constexpr uint32_t FIXED_BYTES = 12;  //!< bytes 0-11
    static constexpr uint32_t ENTRY_BYTES = 3;   //!< SID (2 B) + Delta (1 B)
    static constexpr uint32_t MAX_HOPS = 255;    //!< Num Hops is one byte
    static constexpr uint8_t DEFAULT_NEXT_HEADER = 17; //!< UDP, as in the ns-3 reference

    // byte offsets inside the header; also the ICMPv6 Parameter Problem pointers
    static constexpr uint8_t OFF_NEXT_HEADER = 0;   //!< Next Header
    static constexpr uint8_t OFF_HDR_EXT_LEN = 1;   //!< Hdr Ext Len
    static constexpr uint8_t OFF_ROUTING_TYPE = 2;  //!< Routing Type
    static constexpr uint8_t OFF_SEGMENTS_LEFT = 3; //!< Segments Left (mutable)
    static constexpr uint8_t OFF_FLAGS = 4;         //!< Flags (mutable)
    static constexpr uint8_t OFF_NUM_HOPS = 5;      //!< Num Hops
    static constexpr uint8_t OFF_DEV_HOP = 6;       //!< Dev Hop (mutable; Reserved in v0)
    static constexpr uint8_t OFF_RESERVED = 7;      //!< Reserved
    static constexpr uint8_t OFF_EPOCH_BASE = 8;    //!< Epoch_Base, 4 bytes
    static constexpr uint8_t OFF_ENTRIES = 12;      //!< first entry

    static constexpr uint8_t FLAG_DEV = 0x01;    //!< late (or plan broken); set once, never cleared
    static constexpr uint8_t FLAG_GREEDY = 0x02; //!< forwarded by the fallback function
    static constexpr uint8_t FLAG_SAT = 0x04;    //!< a Delta was clamped to 255 at encode time
    static constexpr uint8_t FLAG_UNIT_MASK = 0x30;     //!< deadline unit code
    static constexpr uint8_t FLAG_UNIT_SHIFT = 4;       //!< (flags >> 4) & 3
    static constexpr uint8_t FLAG_RESERVED_MASK = 0xC8; //!< zero on transmit, ignored on receipt
    static constexpr uint8_t FLAG_STATE_MASK = 0x07;    //!< DEV | GREEDY | SAT

    static constexpr uint16_t SID_SATELLITE_MAX = 0xEFFF; //!< 0x0000-0xEFFF: satellites
    static constexpr uint16_t SID_GROUND_BASE = 0xF000;   //!< ground station g -> 0xF000 + g
    static constexpr uint16_t SID_GROUND_MAX = 0xFFFE;    //!< last ground-station SID
    static constexpr uint16_t SID_RESERVED = 0xFFFF;      //!< never in a path

    /**
     * Result of validating bytes (spec section 6 step 1). The checks run in
     * this order, so every implementation reports the same reason for the same
     * bytes: TRUNCATED (fewer than 8 bytes), WRONG_TYPE, NUMHOPS_ZERO,
     * SL_GT_NUMHOPS, LENGTH_MISMATCH, TRUNCATED (fewer bytes than Hdr Ext Len
     * announces), TRAILING_BYTES (exact parsing only).
     */
    enum ParseStatus : uint8_t
    {
        OK = 0,          //!< valid
        TRUNCATED,       //!< "truncated": the bytes stop early
        WRONG_TYPE,      //!< "wrong_type": Routing Type is not 253
        SL_GT_NUMHOPS,   //!< "sl_gt_numhops": Segments Left > Num Hops
        LENGTH_MISMATCH, //!< "length_mismatch": (HdrExtLen+1)*8 < pad8(12 + 3 NumHops)
        TRAILING_BYTES,  //!< "trailing_bytes": more bytes than Hdr Ext Len (exact parse)
        NUMHOPS_ZERO,    //!< "numhops_zero": Num Hops is 0 (spec section 2: 1..255)
    };

    /**
     * @param status a parse status
     * @return the reason code used by the golden vectors ("truncated", ...), or "ok"
     */
    static const char* ParseStatusName(ParseStatus status);

    /**
     * ICMPv6 Parameter Problem pointer (offset of the offending field inside the
     * routing header) for a parse failure, or -1 when there is no field to point
     * at (the bytes just stop). Code 0 is used whenever a pointer exists.
     * @param status a parse status
     * @return the pointer or -1
     */
    static int ParseStatusIcmpPointer(ParseStatus status);

    /// Size on the wire of a header with @p numHops entries: pad8(12 + 3 h).
    /// @param numHops number of entries
    /// @return bytes
    static uint32_t SizeForHops(uint32_t numHops);

    /**
     * Ceil-cumulative delta encoding, exactly as spec section 5.1, in integer
     * nanoseconds: target_k = ceil(B_k / u), d_k = target_k - E (clamped to
     * 0..255; a clamp to 255 sets *sat). Because every target is the ceil of a
     * CUMULATIVE budget, rounding error never accumulates along the path and no
     * deadline is earlier than its budget unless SAT is set.
     *
     * @param cumulativeBudgetsNs B_1 <= ... <= B_h, time allowed from ingress to
     *        arrival at hop k, in ns
     * @param unitCode deadline unit code 0..3
     * @param sat out: true if any delta was clamped to 255 (may be nullptr)
     * @return the h one-byte deltas d_1..d_h in path order
     */
    static std::vector<uint8_t> EncodeDeltas(const std::vector<uint64_t>& cumulativeBudgetsNs,
                                             uint8_t unitCode,
                                             bool* sat);

    /**
     * What the ingress does (Python proto.build_header): stamp
     * Epoch_Base = ceil(T_ingress / u) mod 2^32 for THIS packet, encode the
     * budgets (section 5.1), set SAT if a delta saturated.
     *
     * @param sidsFwd SIDs in path order (first hop first, final endpoint last)
     * @param cumulativeBudgetsNs B_1..B_h in ns
     * @param tIngressGpsNs ingress GPS time in ns
     * @param unitCode deadline unit code 0..3
     * @param nextHeader Next Header value
     * @return a fresh header (Segments Left = Num Hops)
     */
    static TcrhHeader Build(const std::vector<uint16_t>& sidsFwd,
                            const std::vector<uint64_t>& cumulativeBudgetsNs,
                            uint64_t tIngressGpsNs,
                            uint8_t unitCode,
                            uint8_t nextHeader = DEFAULT_NEXT_HEADER);

    /**
     * Parse and validate raw bytes. With @p exact the bytes must be exactly one
     * header; otherwise a payload may follow (only the header is read).
     *
     * @param data the bytes, starting with the routing header
     * @param len number of bytes available at @p data
     * @param exact refuse bytes beyond Hdr Ext Len
     * @param out where to store the parsed header on success (may be nullptr)
     * @param headerBytes out: (HdrExtLen + 1) * 8 on success (may be nullptr)
     * @return OK or the reason the bytes are malformed (*out untouched then)
     */
    static ParseStatus Parse(const uint8_t* data,
                             uint32_t len,
                             bool exact,
                             TcrhHeader* out,
                             uint32_t* headerBytes);

    TcrhHeader();

    /**
     * @brief Get the type ID.
     * @return the object TypeId
     */
    static TypeId GetTypeId();
    TypeId GetInstanceTypeId() const override;

    /**
     * Load a fresh path (Python TcrhHeader.from_forward). Lists are given in
     * FORWARD order and stored reversed. Segments Left = Num Hops = h, Dev Hop,
     * Reserved and padding = 0, Flags = (unitCode << 4) | extraFlags.
     * Aborts on a caller error: unequal lengths, h outside 1..255, SID 0xFFFF,
     * unit code > 3, or extraFlags outside DEV/GREEDY/SAT. No silent clamping:
     * clamping is EncodeDeltas' job, and it sets SAT.
     *
     * @param sidsFwd SIDs in path order
     * @param deltasFwd d_1..d_h in units
     * @param epochBase Epoch_Base in units
     * @param unitCode 0..3
     * @param extraFlags DEV / GREEDY / SAT bits to set
     */
    void SetPath(const std::vector<uint16_t>& sidsFwd,
                 const std::vector<uint8_t>& deltasFwd,
                 uint32_t epochBase,
                 uint8_t unitCode,
                 uint8_t extraFlags = 0);

    // ----- the four bytes shared by every IPv6 routing header -----
    /// @return the Next Header field
    uint8_t GetNextHeader() const;
    /// @param nextHeader the Next Header field
    void SetNextHeader(uint8_t nextHeader);
    /// @return the Routing Type (always 253)
    uint8_t GetTypeRouting() const;
    /// @return Segments Left
    uint8_t GetSegmentsLeft() const;
    /// Set Segments Left (mutable in flight). Aborts if it exceeds Num Hops.
    /// @param segmentsLeft new value, 0..Num Hops
    void SetSegmentsLeft(uint8_t segmentsLeft);
    /// @return Hdr Ext Len as on the wire
    uint8_t GetHdrExtLen() const;

    // ----- T-CRH fields -----
    /// @return the whole Flags byte
    uint8_t GetFlags() const;
    /// Set the whole Flags byte (mutable in flight).
    /// @param flags the new Flags byte
    void SetFlags(uint8_t flags);
    /// @return the deadline unit code, (flags >> 4) & 3
    uint8_t GetUnitCode() const;
    /// @return the deadline unit in ns
    uint64_t GetUnitNs() const;
    /// @return true if DEV is set
    bool IsDev() const;
    /// @return true if GREEDY is set
    bool IsGreedy() const;
    /// @return true if SAT is set
    bool IsSat() const;
    /// @return Num Hops (h)
    uint8_t GetNumHops() const;
    /// @return Dev Hop (0 while DEV is clear)
    uint8_t GetDevHop() const;
    /// Set Dev Hop (mutable in flight).
    /// @param devHop hop index at which DEV was first set
    void SetDevHop(uint8_t devHop);
    /// @return the Reserved byte as received (0 for a built header)
    uint8_t GetReserved() const;
    /// @return Epoch_Base in units
    uint32_t GetEpochBase() const;

    /// @param i wire index 0..h-1 (SID[0] is the final endpoint)
    /// @return SID[i]
    uint16_t GetSid(uint8_t i) const;
    /// @param i wire index 0..h-1
    /// @return Delta[i]
    uint8_t GetDelta(uint8_t i) const;
    /// @return SIDs in path order (first hop first)
    std::vector<uint16_t> GetSidsForward() const;
    /// @return deltas d_1..d_h in path order
    std::vector<uint8_t> GetDeltasForward() const;

    /**
     * Cumulative arrival deadline at hop k (spec section 5):
     * D_k = (Epoch_Base + d_1 + ... + d_k) mod 2^32. In wire order those are
     * the entries SL..h-1 for SL = h - k, the ones consumed on arrival at hop k.
     * @param k hop index 1..h (aborts otherwise)
     * @return D_k in units
     */
    uint32_t GetDeadline(uint8_t k) const;
    /// @return D_1..D_h
    std::vector<uint32_t> GetDeadlines() const;
    /// k = NumHops - SL: hop index of the node holding the packet (0 = ingress).
    /// @return k
    uint8_t GetCurrentHopIndex() const;

    /// @return OK, or why the last Deserialize() rejected the bytes
    ParseStatus GetParseStatus() const;

    /// @return the serialized bytes
    std::vector<uint8_t> ToBytes() const;
    /// @return the serialized bytes as lowercase hex
    std::string ToHex() const;

    uint32_t GetSerializedSize() const override;
    void Serialize(Buffer::Iterator start) const override;
    uint32_t Deserialize(Buffer::Iterator start) override;
    void Print(std::ostream& os) const override;

  private:
    uint8_t m_nextHeader;           //!< Next Header
    uint8_t m_hdrExtLen;            //!< Hdr Ext Len (as received, or minimal for a built header)
    uint8_t m_segmentsLeft;         //!< Segments Left
    uint8_t m_flags;                //!< Flags
    uint8_t m_devHop;               //!< Dev Hop
    uint8_t m_reserved;             //!< Reserved byte, kept as received
    uint32_t m_epochBase;           //!< Epoch_Base
    std::vector<uint16_t> m_sids;   //!< SID[0..h-1], wire (reverse path) order
    std::vector<uint8_t> m_deltas;  //!< Delta[0..h-1], wire order
    std::vector<uint8_t> m_tail;    //!< bytes after the entries up to (HdrExtLen+1)*8
    ParseStatus m_status;           //!< result of the last Deserialize()
};

} // namespace ns3

#endif /* TCRH_HEADER_H */
