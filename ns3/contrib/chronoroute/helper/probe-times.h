/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef CHRONOROUTE_PROBE_TIMES_H
#define CHRONOROUTE_PROBE_TIMES_H

#include <algorithm>
#include <cstdint>
#include <istream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace ns3::tcrh
{
/** Read the shared explicit probe schedule, rejecting ambiguous packet IDs. */
inline std::map<uint32_t, std::vector<std::pair<uint32_t, int64_t>>>
ReadProbeTimes(std::istream& input, const std::vector<uint32_t>& flows, int64_t stopNs)
{
    std::string line;
    if (!std::getline(input, line) || line != "flow_id,seq,send_ns")
    {
        throw std::invalid_argument("explicit sends require flow_id,seq,send_ns header");
    }
    std::map<uint32_t, std::vector<std::pair<uint32_t, int64_t>>> result;
    while (std::getline(input, line))
    {
        std::istringstream row(line);
        std::vector<int64_t> values;
        std::string token;
        while (std::getline(row, token, ','))
        {
            size_t end = 0;
            const int64_t v = std::stoll(token, &end);
            if (end != token.size() || v < 0)
            {
                throw std::invalid_argument("explicit sends require nonnegative integers");
            }
            values.push_back(v);
        }
        if (values.size() != 3 || values[0] > UINT32_MAX || values[1] > UINT32_MAX || values[2] >= stopNs ||
            std::find(flows.begin(), flows.end(), values[0]) == flows.end())
        {
            throw std::invalid_argument("invalid explicit send row");
        }
        auto& times = result[static_cast<uint32_t>(values[0])];
        if (values[1] != static_cast<int64_t>(times.size()) ||
            (!times.empty() && values[2] <= times.back().second))
        {
            throw std::invalid_argument("explicit sends need contiguous sequence IDs and strictly increasing times");
        }
        times.emplace_back(static_cast<uint32_t>(values[1]), values[2]);
    }
    for (uint32_t flow : flows)
    {
        if (result[flow].empty())
        {
            throw std::invalid_argument("explicit sends missing a selected flow");
        }
    }
    return result;
}
} // namespace ns3::tcrh
#endif
