/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#ifndef CRH_FIB_H
#define CRH_FIB_H

#include "ns3/ipv6-address.h"
#include "ns3/object.h"

#include <cstdint>
#include <map>
#include <optional>
#include <ostream>

namespace ns3
{

/**
 * @ingroup chronoroute
 *
 * A node's CRH-FIB (RFC 9631 section 4): the table that turns a SID taken from
 * a T-CRH or CRH into "where do I send this packet next". One CrhFib is
 * aggregated to every ChronoRoute node; T-CRH (253), CRH-16 (5) and CRH-32 (6)
 * all use it, because they share one SID space.
 *
 * Each entry says three things:
 *  - sidAddress: the IPv6 address the packet must carry as Destination Address
 *    after this segment (the SID address of the next node, see
 *    tcrh-address-plan.h). Writing it into the IPv6 header is what makes the
 *    next node process the routing header (RFC 8200 section 4.4);
 *  - interface: the IPv6 interface index to send on;
 *  - nextHop: the neighbour's address on that link (the gateway of the
 *    Ipv6Route). On a point-to-point link any address would do; a real
 *    on-link address keeps the entry correct for links that need neighbour
 *    discovery too.
 *
 * Only neighbours are in the table (strict source routing: every SID in a
 * ChronoRoute path is one hop from the previous one). The table also records
 * the node's own SID, which the trace sources report.
 *
 * Entries are kept in a std::map, so printing and iteration are sorted and
 * deterministic; a lookup costs O(log degree).
 */
class CrhFib : public Object
{
  public:
    /// One CRH-FIB entry.
    struct Entry
    {
        Ipv6Address sidAddress; //!< new IPv6 Destination Address (the next node's SID address)
        uint32_t interface{0};  //!< IPv6 interface index to send on
        Ipv6Address nextHop;    //!< neighbour's on-link address (Ipv6Route gateway)
    };

    /**
     * @brief Get the type ID.
     * @return the object TypeId
     */
    static TypeId GetTypeId();

    CrhFib();

    /// @param sid this node's own SID
    void SetLocalSid(uint32_t sid);
    /// @return this node's SID, if one was set
    std::optional<uint32_t> GetLocalSid() const;

    /**
     * Add or replace the entry for @p sid.
     * @param sid the SID
     * @param entry where to send packets whose next SID is @p sid
     */
    void AddEntry(uint32_t sid, const Entry& entry);

    /**
     * @param sid the SID
     * @return true if an entry was removed
     */
    bool RemoveEntry(uint32_t sid);

    /**
     * @param sid the SID to look up
     * @return the entry, or nothing (the caller then discards the packet and
     *         sends ICMPv6 Parameter Problem, Code 0, pointing at the SID)
     */
    std::optional<Entry> Lookup(uint32_t sid) const;

    /// @return number of entries
    uint32_t GetNEntries() const;

    /**
     * Print the table, one entry per line, sorted by SID.
     * @param os the output stream
     */
    void Print(std::ostream& os) const;

  private:
    std::map<uint32_t, Entry> m_entries; //!< SID -> entry
    std::optional<uint32_t> m_localSid;  //!< this node's SID
};

} // namespace ns3

#endif /* CRH_FIB_H */
