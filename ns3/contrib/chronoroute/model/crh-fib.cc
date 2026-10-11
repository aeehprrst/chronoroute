/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#include "crh-fib.h"

#include "ns3/log.h"

namespace ns3
{

NS_LOG_COMPONENT_DEFINE("CrhFib");

NS_OBJECT_ENSURE_REGISTERED(CrhFib);

TypeId
CrhFib::GetTypeId()
{
    static TypeId tid = TypeId("ns3::CrhFib")
                            .SetParent<Object>()
                            .SetGroupName("Chronoroute")
                            .AddConstructor<CrhFib>();
    return tid;
}

CrhFib::CrhFib()
{
}

void
CrhFib::SetLocalSid(uint32_t sid)
{
    m_localSid = sid;
}

std::optional<uint32_t>
CrhFib::GetLocalSid() const
{
    return m_localSid;
}

void
CrhFib::AddEntry(uint32_t sid, const Entry& entry)
{
    NS_LOG_FUNCTION(this << sid << entry.sidAddress << entry.interface << entry.nextHop);
    m_entries[sid] = entry;
}

bool
CrhFib::RemoveEntry(uint32_t sid)
{
    return m_entries.erase(sid) > 0;
}

std::optional<CrhFib::Entry>
CrhFib::Lookup(uint32_t sid) const
{
    auto it = m_entries.find(sid);
    if (it == m_entries.end())
    {
        return std::nullopt;
    }
    return it->second;
}

uint32_t
CrhFib::GetNEntries() const
{
    return static_cast<uint32_t>(m_entries.size());
}

void
CrhFib::Print(std::ostream& os) const
{
    for (const auto& [sid, e] : m_entries)
    {
        os << "  SID " << sid << " (0x" << std::hex << sid << std::dec << ") -> DA " << e.sidAddress
           << " via if " << e.interface << " next hop " << e.nextHop << "\n";
    }
}

} // namespace ns3
