/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#include "leo-bundle-helper.h"

#include "ns3/abort.h"
#include "ns3/attribute.h"
#include "ns3/internet-stack-helper.h"
#include "ns3/ipv6-l3-protocol.h"
#include "ns3/log.h"
#include "ns3/simulator.h"
#include "ns3/string.h"
#include "ns3/tcrh-address-plan.h"
#include "ns3/tcrh-header.h"
#include "ns3/tcrh-timebase.h"

#include <algorithm>
#include <cctype>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <deque>
#include <fstream>
#include <sstream>

namespace ns3
{
namespace leo
{

NS_LOG_COMPONENT_DEFINE("LeoBundleHelper");

// ===================================================================== parsing

namespace
{

/// Split a CSV line on ','. The bundle never quotes fields (docs/bundle-format.md 2.3).
std::vector<std::string>
SplitComma(const std::string& line)
{
    std::vector<std::string> out;
    size_t start = 0;
    while (true)
    {
        const size_t pos = line.find(',', start);
        if (pos == std::string::npos)
        {
            out.push_back(line.substr(start));
            return out;
        }
        out.push_back(line.substr(start, pos - start));
        start = pos + 1;
    }
}

/// Strict decimal integer (the whole field, optional leading '-').
int64_t
ToInt(const std::string& s, const std::string& where)
{
    NS_ABORT_MSG_IF(s.empty(), where << ": empty integer field");
    errno = 0;
    char* end = nullptr;
    const long long v = std::strtoll(s.c_str(), &end, 10);
    NS_ABORT_MSG_IF(errno != 0 || end == s.c_str() || *end != '\0',
                    where << ": not an integer: '" << s << "'");
    return static_cast<int64_t>(v);
}

/// Strict unsigned 64-bit integer.
uint64_t
ToUint(const std::string& s, const std::string& where)
{
    NS_ABORT_MSG_IF(s.empty() || s[0] == '-', where << ": not an unsigned integer: '" << s << "'");
    errno = 0;
    char* end = nullptr;
    const unsigned long long v = std::strtoull(s.c_str(), &end, 10);
    NS_ABORT_MSG_IF(errno != 0 || end == s.c_str() || *end != '\0',
                    where << ": not an unsigned integer: '" << s << "'");
    return static_cast<uint64_t>(v);
}

/// Decimal number (lat/lon, positions).
double
ToDouble(const std::string& s, const std::string& where)
{
    NS_ABORT_MSG_IF(s.empty(), where << ": empty number field");
    char* end = nullptr;
    const double v = std::strtod(s.c_str(), &end);
    NS_ABORT_MSG_IF(end == s.c_str() || *end != '\0', where << ": not a number: '" << s << "'");
    return v;
}

/// Space-separated list of integers (sids_fwd, budgets, path_nodes ...).
std::vector<int64_t>
ToIntList(const std::string& s, const std::string& where)
{
    std::vector<int64_t> out;
    std::istringstream is(s);
    std::string tok;
    while (is >> tok)
    {
        out.push_back(ToInt(tok, where));
    }
    return out;
}

/// Open a bundle file; abort with the path if it is missing.
std::ifstream
OpenFile(const std::string& path)
{
    std::ifstream f(path);
    NS_ABORT_MSG_UNLESS(f.is_open(), "bundle file missing or unreadable: " << path);
    return f;
}

/// Read the header line and check it is exactly @p expected.
void
ExpectHeader(std::ifstream& f, const std::string& path, const std::string& expected)
{
    std::string line;
    NS_ABORT_MSG_UNLESS(std::getline(f, line), path << ": empty file");
    NS_ABORT_MSG_UNLESS(line == expected,
                        path << ": header is '" << line << "', expected '" << expected << "'");
}

/**
 * The integer value of a key that must appear exactly once in scenario.json.
 * ns-3 has no JSON library; the bundle writer uses fixed keys and plain
 * integers for these fields, so a strict text search is enough and fails
 * loudly if the format ever changes.
 */
int64_t
JsonInt(const std::string& text, const std::string& key, const std::string& path)
{
    const std::string needle = "\"" + key + "\":";
    const size_t pos = text.find(needle);
    NS_ABORT_MSG_IF(pos == std::string::npos, path << ": key " << key << " not found");
    NS_ABORT_MSG_IF(text.find(needle, pos + 1) != std::string::npos,
                    path << ": key " << key << " appears more than once");
    size_t i = pos + needle.size();
    while (i < text.size() && (text[i] == ' ' || text[i] == '\n'))
    {
        ++i;
    }
    size_t j = i;
    while (j < text.size() && (std::isdigit(static_cast<unsigned char>(text[j])) || text[j] == '-'))
    {
        ++j;
    }
    return ToInt(text.substr(i, j - i), path + " " + key);
}

/// Ordered pair key for an undirected link.
std::pair<uint32_t, uint32_t>
Key(uint32_t a, uint32_t b)
{
    return a < b ? std::make_pair(a, b) : std::make_pair(b, a);
}

} // namespace

// ===================================================================== Bundle

Bundle
Bundle::Load(const std::string& dirIn, bool loadPositions)
{
    Bundle b;
    b.dir = dirIn;
    const std::string dir = dirIn.empty() || dirIn.back() == '/' ? dirIn : dirIn + "/";

    // ---- scenario.json: the time base and the step sizes
    {
        const std::string path = dir + "scenario.json";
        std::ifstream f = OpenFile(path);
        std::stringstream ss;
        ss << f.rdbuf();
        const std::string text = ss.str();
        NS_ABORT_MSG_IF(text.find("\"schema\": \"chronoroute.bundle/1\"") == std::string::npos,
                        path << ": not a chronoroute.bundle/1 scenario");
        b.t0GpsNs = static_cast<uint64_t>(JsonInt(text, "t0_gps_ns", path));
        b.t0UnixNs = static_cast<uint64_t>(JsonInt(text, "t0_unix_ns", path));
        b.windowMs = JsonInt(text, "window_ms", path);
        b.stepMs = JsonInt(text, "step_ms", path);
        b.positionStepMs = JsonInt(text, "position_step_ms", path);
        b.refreshMs = JsonInt(text, "schedule_refresh_ms", path);
        const int64_t uc = JsonInt(text, "unit_code", path);
        NS_ABORT_MSG_UNLESS(uc >= 0 && uc <= 3, path << ": unit_code " << uc);
        b.unitCode = static_cast<uint8_t>(uc);
        NS_ABORT_MSG_UNLESS(b.stepMs > 0 && b.windowMs >= 0 && b.windowMs % b.stepMs == 0,
                            path << ": window_ms must be a multiple of step_ms");
        NS_ABORT_MSG_UNLESS(b.positionStepMs > 0 && b.windowMs % b.positionStepMs == 0,
                            path << ": window_ms must be a multiple of position_step_ms");
        b.nSteps = static_cast<uint32_t>(b.windowMs / b.stepMs + 1);
    }

    // ---- nodes.csv
    {
        const std::string path = dir + "nodes.csv";
        std::ifstream f = OpenFile(path);
        ExpectHeader(f, path, "node_id,kind,sid,norad,name,shell,plane,slot,lat,lon");
        std::string line;
        while (std::getline(f, line))
        {
            const std::vector<std::string> c = SplitComma(line);
            const std::string where = path + " row " + std::to_string(b.nodes.size() + 2);
            NS_ABORT_MSG_UNLESS(c.size() == 10, where << ": expected 10 fields");
            BundleNode n;
            n.id = static_cast<uint32_t>(ToUint(c[0], where));
            NS_ABORT_MSG_UNLESS(n.id == b.nodes.size(), where << ": node ids must be 0, 1, 2, ...");
            NS_ABORT_MSG_UNLESS(c[1] == "sat" || c[1] == "gs", where << ": kind " << c[1]);
            n.isSat = c[1] == "sat";
            n.sid = static_cast<uint32_t>(ToUint(c[2], where));
            NS_ABORT_MSG_UNLESS(n.sid < TcrhHeader::SID_RESERVED, where << ": SID " << n.sid);
            n.norad = c[3];
            n.name = c[4];
            if (n.isSat)
            {
                NS_ABORT_MSG_UNLESS(b.nSats == b.nodes.size(),
                                    where << ": satellites must come before ground stations");
                b.nSats++;
            }
            else
            {
                n.latDeg = ToDouble(c[8], where);
                n.lonDeg = ToDouble(c[9], where);
            }
            b.nodes.push_back(n);
        }
        NS_ABORT_MSG_IF(b.nodes.empty(), path << ": no nodes");
    }

    // ---- isl.csv
    {
        const std::string path = dir + "isl.csv";
        std::ifstream f = OpenFile(path);
        ExpectHeader(f, path, "link_id,a,b,kind");
        std::string line;
        while (std::getline(f, line))
        {
            const std::vector<std::string> c = SplitComma(line);
            const std::string where = path + " row " + std::to_string(b.isls.size() + 2);
            NS_ABORT_MSG_UNLESS(c.size() == 4, where << ": expected 4 fields");
            BundleIsl l;
            l.id = static_cast<uint32_t>(ToUint(c[0], where));
            l.a = static_cast<uint32_t>(ToUint(c[1], where));
            l.b = static_cast<uint32_t>(ToUint(c[2], where));
            NS_ABORT_MSG_UNLESS(l.id == b.isls.size(), where << ": link ids must be 0, 1, 2, ...");
            NS_ABORT_MSG_UNLESS(l.a < l.b && l.b < b.nSats, where << ": need a < b, both satellites");
            NS_ABORT_MSG_UNLESS(c[3] == "intra" || c[3] == "cross", where << ": kind " << c[3]);
            l.cross = c[3] == "cross";
            NS_ABORT_MSG_IF(b.m_islOfPair.count(Key(l.a, l.b)), where << ": duplicate pair");
            b.m_islOfPair[Key(l.a, l.b)] = l.id;
            b.isls.push_back(l);
        }
    }

    // ---- isl_delay.csv: nSteps blocks of every link, in link order
    {
        const std::string path = dir + "isl_delay.csv";
        std::ifstream f = OpenFile(path);
        ExpectHeader(f, path, "t_ms,link_id,up,delay_ns");
        const size_t nIsl = b.isls.size();
        b.islDelayNs.assign(static_cast<size_t>(b.nSteps) * nIsl, -1);
        b.islUp.assign(static_cast<size_t>(b.nSteps) * nIsl, 0);
        std::string line;
        size_t i = 0;
        while (std::getline(f, line))
        {
            NS_ABORT_MSG_UNLESS(i < b.islDelayNs.size(), path << ": more rows than steps x links");
            const std::vector<std::string> c = SplitComma(line);
            NS_ABORT_MSG_UNLESS(c.size() == 4, path << " row " << i + 2 << ": expected 4 fields");
            const size_t step = i / nIsl;
            const size_t link = i % nIsl;
            NS_ABORT_MSG_UNLESS(ToInt(c[0], path) == static_cast<int64_t>(step) * b.stepMs &&
                                    ToUint(c[1], path) == link,
                                path << " row " << i + 2 << ": rows must be sorted by (t_ms, link_id)"
                                     << " and list every link at every step");
            const int64_t up = ToInt(c[2], path);
            NS_ABORT_MSG_UNLESS(up == 0 || up == 1, path << " row " << i + 2 << ": up must be 0/1");
            const int64_t d = ToInt(c[3], path);
            NS_ABORT_MSG_UNLESS(d >= -1 && d < (int64_t(1) << 31), path << " row " << i + 2 << ": delay");
            b.islUp[i] = static_cast<uint8_t>(up);
            b.islDelayNs[i] = static_cast<int32_t>(d);
            ++i;
        }
        NS_ABORT_MSG_UNLESS(i == b.islDelayNs.size(),
                            path << ": " << i << " rows, expected " << b.islDelayNs.size());
    }

    // ---- gsl.csv: nSteps blocks of the same (gs, sat) pairs
    {
        const std::string path = dir + "gsl.csv";
        std::ifstream f = OpenFile(path);
        ExpectHeader(f, path, "t_ms,gs_node,sat_node,up,delay_ns,elev_mdeg");
        struct Row
        {
            int64_t t;
            uint32_t gs;
            uint32_t sat;
            uint8_t up;
            int32_t d;
        };
        std::vector<Row> rows;
        std::string line;
        while (std::getline(f, line))
        {
            const std::vector<std::string> c = SplitComma(line);
            const std::string where = path + " row " + std::to_string(rows.size() + 2);
            NS_ABORT_MSG_UNLESS(c.size() == 6, where << ": expected 6 fields");
            Row r;
            r.t = ToInt(c[0], where);
            r.gs = static_cast<uint32_t>(ToUint(c[1], where));
            r.sat = static_cast<uint32_t>(ToUint(c[2], where));
            const int64_t up = ToInt(c[3], where);
            NS_ABORT_MSG_UNLESS(up == 0 || up == 1, where << ": up must be 0/1");
            r.up = static_cast<uint8_t>(up);
            const int64_t d = ToInt(c[4], where);
            NS_ABORT_MSG_UNLESS(d >= -1 && d < (int64_t(1) << 31), where << ": delay");
            r.d = static_cast<int32_t>(d);
            NS_ABORT_MSG_UNLESS(r.gs >= b.nSats && r.gs < b.nodes.size() && r.sat < b.nSats,
                                where << ": gs_node must be a ground station, sat_node a satellite");
            rows.push_back(r);
        }
        NS_ABORT_MSG_UNLESS(rows.size() % b.nSteps == 0,
                            path << ": " << rows.size() << " rows is not a multiple of " << b.nSteps
                                 << " steps");
        const size_t nPairs = rows.size() / b.nSteps;
        b.gslDelayNs.assign(rows.size(), -1);
        b.gslUp.assign(rows.size(), 0);
        for (size_t p = 0; p < nPairs; ++p)
        {
            b.gslPairs.push_back(BundleGslPair{rows[p].gs, rows[p].sat});
        }
        for (size_t i = 0; i < rows.size(); ++i)
        {
            const size_t step = i / nPairs;
            const size_t p = i % nPairs;
            NS_ABORT_MSG_UNLESS(rows[i].t == static_cast<int64_t>(step) * b.stepMs &&
                                    rows[i].gs == b.gslPairs[p].gs && rows[i].sat == b.gslPairs[p].sat,
                                path << " row " << i + 2
                                     << ": every step must list the same pairs in the same order");
            b.gslUp[i] = rows[i].up;
            b.gslDelayNs[i] = rows[i].d;
        }
    }

    // ---- schedule.csv
    {
        const std::string path = dir + "schedule.csv";
        std::ifstream f = OpenFile(path);
        ExpectHeader(f,
                     path,
                     "flow_id,src_gs,dst_gs,valid_from_ms,valid_to_ms,sids_fwd,cumulative_budgets_ns,"
                     "predicted_hop_delays_ns,tcrh_hex_template,path_nodes");
        std::string line;
        while (std::getline(f, line))
        {
            const std::vector<std::string> c = SplitComma(line);
            const std::string where = path + " row " + std::to_string(b.schedule.size() + 2);
            NS_ABORT_MSG_UNLESS(c.size() == 10, where << ": expected 10 fields");
            ScheduleRow r;
            r.flow = static_cast<uint32_t>(ToUint(c[0], where));
            r.srcGs = static_cast<uint32_t>(ToUint(c[1], where));
            r.dstGs = static_cast<uint32_t>(ToUint(c[2], where));
            r.fromMs = ToInt(c[3], where);
            r.toMs = ToInt(c[4], where);
            NS_ABORT_MSG_UNLESS(r.fromMs >= 0 && r.fromMs < r.toMs, where << ": bad validity");
            for (int64_t s : ToIntList(c[5], where))
            {
                NS_ABORT_MSG_UNLESS(s >= 0 && s < TcrhHeader::SID_RESERVED, where << ": SID " << s);
                r.sidsFwd.push_back(static_cast<uint16_t>(s));
            }
            for (int64_t v : ToIntList(c[6], where))
            {
                NS_ABORT_MSG_UNLESS(v >= 0, where << ": negative budget");
                r.budgetsNs.push_back(static_cast<uint64_t>(v));
            }
            r.predictedHopNs = ToIntList(c[7], where);
            r.templateHex = c[8];
            for (int64_t n : ToIntList(c[9], where))
            {
                NS_ABORT_MSG_UNLESS(n >= 0 && static_cast<size_t>(n) < b.nodes.size(),
                                    where << ": path node " << n);
                r.pathNodes.push_back(static_cast<uint32_t>(n));
            }
            const size_t h = r.sidsFwd.size();
            NS_ABORT_MSG_UNLESS(h >= 1 && r.budgetsNs.size() == h && r.predictedHopNs.size() == h &&
                                    r.pathNodes.size() == h + 1,
                                where << ": list lengths disagree");
            NS_ABORT_MSG_UNLESS(r.pathNodes.front() == r.srcGs && r.pathNodes.back() == r.dstGs,
                                where << ": path_nodes must run from src_gs to dst_gs");
            for (size_t k = 1; k <= h; ++k)
            {
                NS_ABORT_MSG_UNLESS(b.nodes[r.pathNodes[k]].sid == r.sidsFwd[k - 1],
                                    where << ": SID of path node " << k << " disagrees with sids_fwd");
            }
            // The C++ encoder must rebuild Python's template byte for byte
            // (Epoch_Base 0, Next Header 17): one more cross-implementation check.
            const TcrhHeader built = TcrhHeader::Build(r.sidsFwd, r.budgetsNs, 0, b.unitCode, 17);
            NS_ABORT_MSG_UNLESS(built.ToHex() == r.templateHex,
                                where << ": C++ TcrhHeader::Build gives " << built.ToHex()
                                      << ", the bundle template is " << r.templateHex);
            // cumulative deltas in units: D_k = Epoch_Base + cumDeltaU[k-1]
            const std::vector<uint8_t> d = built.GetDeltasForward();
            uint32_t sum = 0;
            for (uint8_t x : d)
            {
                sum += x;
                r.cumDeltaU.push_back(sum);
            }
            NS_ABORT_MSG_UNLESS(b.schedule.empty() ||
                                    std::make_pair(b.schedule.back().fromMs, b.schedule.back().flow) <
                                        std::make_pair(r.fromMs, r.flow),
                                where << ": rows must be sorted by (valid_from_ms, flow_id)");
            b.m_rowsOfFlow[r.flow].push_back(static_cast<uint32_t>(b.schedule.size()));
            b.schedule.push_back(r);
        }
    }

    // ---- positions.csv (NetAnim only)
    if (loadPositions)
    {
        const std::string path = dir + "positions.csv";
        std::ifstream f = OpenFile(path);
        ExpectHeader(f, path, "t_ms,node_id,x_m,y_m,z_m");
        b.nPosSteps = static_cast<uint32_t>(b.windowMs / b.positionStepMs + 1);
        const size_t n = b.nodes.size();
        b.posM.assign(static_cast<size_t>(b.nPosSteps) * n * 3, 0.0);
        std::string line;
        size_t i = 0;
        while (std::getline(f, line))
        {
            NS_ABORT_MSG_UNLESS(i < static_cast<size_t>(b.nPosSteps) * n, path << ": too many rows");
            const std::vector<std::string> c = SplitComma(line);
            NS_ABORT_MSG_UNLESS(c.size() == 5, path << " row " << i + 2 << ": expected 5 fields");
            NS_ABORT_MSG_UNLESS(ToInt(c[0], path) == static_cast<int64_t>(i / n) * b.positionStepMs &&
                                    ToUint(c[1], path) == i % n,
                                path << " row " << i + 2 << ": rows must be sorted by (t_ms, node_id)");
            b.posM[i * 3 + 0] = ToDouble(c[2], path);
            b.posM[i * 3 + 1] = ToDouble(c[3], path);
            b.posM[i * 3 + 2] = ToDouble(c[4], path);
            ++i;
        }
        NS_ABORT_MSG_UNLESS(i == static_cast<size_t>(b.nPosSteps) * n,
                            path << ": " << i << " rows, expected " << b.nPosSteps * n);
    }
    return b;
}

uint32_t
Bundle::StepAt(int64_t tNs) const
{
    NS_ABORT_MSG_IF(tNs < 0, "negative time");
    const int64_t s = tNs / (stepMs * 1000000);
    return static_cast<uint32_t>(std::min<int64_t>(s, nSteps - 1));
}

const ScheduleRow*
Bundle::RowAt(uint32_t flow, int64_t tNs) const
{
    auto it = m_rowsOfFlow.find(flow);
    if (it == m_rowsOfFlow.end())
    {
        return nullptr;
    }
    // rows of one flow are sorted by fromMs and never overlap: binary search
    const std::vector<uint32_t>& idx = it->second;
    auto pos = std::upper_bound(idx.begin(), idx.end(), tNs, [this](int64_t t, uint32_t r) {
        return t < schedule[r].fromMs * 1000000;
    });
    if (pos == idx.begin())
    {
        return nullptr;
    }
    const ScheduleRow& row = schedule[*(pos - 1)];
    return tNs < row.toMs * 1000000 ? &row : nullptr;
}

std::vector<uint32_t>
Bundle::Flows() const
{
    std::vector<uint32_t> out;
    for (const auto& [flow, rows] : m_rowsOfFlow)
    {
        out.push_back(flow);
    }
    return out;
}

std::pair<uint32_t, uint32_t>
Bundle::FlowEnds(uint32_t flow) const
{
    auto it = m_rowsOfFlow.find(flow);
    NS_ABORT_MSG_IF(it == m_rowsOfFlow.end() || it->second.empty(), "flow " << flow << " has no rows");
    const ScheduleRow& r = schedule[it->second.front()];
    return {r.srcGs, r.dstGs};
}

int32_t
Bundle::IslBetween(uint32_t a, uint32_t b) const
{
    auto it = m_islOfPair.find(Key(a, b));
    return it == m_islOfPair.end() ? -1 : static_cast<int32_t>(it->second);
}

// ===================================================================== choices

uint32_t
ChooseFaultIsl(const Bundle& b, uint32_t flow, int64_t startMs, int64_t stopMs)
{
    const ScheduleRow* row = b.RowAt(flow, startMs * 1000000);
    NS_ABORT_MSG_UNLESS(row, "flow " << flow << " has no scheduled path at " << startMs << " ms");
    const uint32_t step = b.StepAt(startMs * 1000000);
    std::vector<uint32_t> candidates;
    for (size_t i = 0; i + 1 < row->pathNodes.size(); ++i)
    {
        const int32_t isl = b.IslBetween(row->pathNodes[i], row->pathNodes[i + 1]);
        if (isl >= 0 && b.islUp[static_cast<size_t>(step) * b.isls.size() + isl])
        {
            candidates.push_back(static_cast<uint32_t>(isl));
        }
    }
    NS_ABORT_MSG_IF(candidates.empty(),
                    "flow " << flow << "'s path at " << startMs << " ms has no laser link that is up");
    // score = schedule-milliseconds (any flow) in [start, stop) whose path uses the link
    std::map<uint32_t, int64_t> score;
    for (uint32_t c : candidates)
    {
        score[c] = 0;
    }
    for (const ScheduleRow& r : b.schedule)
    {
        const int64_t overlap = std::min(r.toMs, stopMs) - std::max(r.fromMs, startMs);
        if (overlap <= 0)
        {
            continue;
        }
        std::set<uint32_t> used;
        for (size_t i = 0; i + 1 < r.pathNodes.size(); ++i)
        {
            const int32_t isl = b.IslBetween(r.pathNodes[i], r.pathNodes[i + 1]);
            if (isl >= 0 && score.count(static_cast<uint32_t>(isl)))
            {
                used.insert(static_cast<uint32_t>(isl));
            }
        }
        for (uint32_t isl : used)
        {
            score[isl] += overlap;
        }
    }
    // std::map iterates in ascending id order and only a strictly larger score
    // replaces the best, so a tie keeps the lowest id
    uint32_t best = score.begin()->first;
    int64_t bestScore = score.begin()->second;
    for (const auto& [isl, s] : score)
    {
        if (s > bestScore)
        {
            best = isl;
            bestScore = s;
        }
    }
    return best;
}

std::vector<uint32_t>
SelectSliceSatellites(const Bundle& b, uint32_t flow, int64_t fromMs, int64_t toMs, uint32_t maxSats)
{
    std::set<uint32_t> chosen;
    std::vector<uint32_t> ring;
    for (const ScheduleRow& r : b.schedule)
    {
        if (r.flow != flow || r.toMs <= fromMs || r.fromMs >= toMs)
        {
            continue;
        }
        for (uint32_t n : r.pathNodes)
        {
            if (n < b.nSats && chosen.insert(n).second)
            {
                ring.push_back(n);
            }
        }
    }
    NS_ABORT_MSG_IF(chosen.empty(), "flow " << flow << " has no satellites in the slice window");
    NS_ABORT_MSG_IF(chosen.size() > maxSats,
                    "the paths alone use " << chosen.size() << " satellites, more than " << maxSats);
    // laser-link neighbours, breadth first
    std::vector<std::vector<uint32_t>> adj(b.nSats);
    for (const BundleIsl& l : b.isls)
    {
        adj[l.a].push_back(l.b);
        adj[l.b].push_back(l.a);
    }
    std::sort(ring.begin(), ring.end());
    while (chosen.size() < maxSats && !ring.empty())
    {
        std::set<uint32_t> next;
        for (uint32_t n : ring)
        {
            for (uint32_t m : adj[n])
            {
                if (!chosen.count(m))
                {
                    next.insert(m);
                }
            }
        }
        ring.clear();
        for (uint32_t m : next) // ascending node id
        {
            if (chosen.size() >= maxSats)
            {
                break;
            }
            chosen.insert(m);
            ring.push_back(m);
        }
    }
    return std::vector<uint32_t>(chosen.begin(), chosen.end());
}

void
EcefToLatLon(double x, double y, double z, double* latDeg, double* lonDeg)
{
    // WGS84; a few fixed-point iterations of the standard formula are far more
    // precise than a NetAnim pixel needs
    const double a = 6378137.0;
    const double f = 1.0 / 298.257223563;
    const double e2 = f * (2.0 - f);
    const double p = std::hypot(x, y);
    double lat = std::atan2(z, p * (1.0 - e2));
    for (int i = 0; i < 6; ++i)
    {
        const double s = std::sin(lat);
        const double n = a / std::sqrt(1.0 - e2 * s * s);
        const double h = p / std::cos(lat) - n;
        lat = std::atan2(z, p * (1.0 - e2 * n / (n + h)));
    }
    *latDeg = lat * 180.0 / M_PI;
    *lonDeg = std::atan2(y, x) * 180.0 / M_PI;
}

std::pair<double, double>
ProjectWorldMap(double latDeg, double lonDeg, double lon0Deg)
{
    double u = std::fmod(lonDeg - lon0Deg + 540.0, 360.0);
    if (u < 0)
    {
        u += 360.0;
    }
    return {u * 10.0, (90.0 - latDeg) * 10.0};
}

// ===================================================================== LeoNetwork

namespace
{

/// The Delay attribute's accessor, looked up once (millions of writes per run).
Ptr<const AttributeAccessor>
DelayAccessor()
{
    static Ptr<const AttributeAccessor> accessor;
    if (!accessor)
    {
        TypeId::AttributeInformation info;
        NS_ABORT_MSG_UNLESS(PointToPointChannel::GetTypeId().LookupAttributeByName("Delay", &info),
                            "PointToPointChannel has no Delay attribute");
        accessor = info.accessor;
    }
    return accessor;
}

} // namespace

LeoNetwork::LeoNetwork(const Bundle& bundle, Config config)
    : m_bundle(bundle),
      m_config(config)
{
}

void
LeoNetwork::Build(const std::vector<bool>* include)
{
    NS_ABORT_MSG_UNLESS(m_nodeOfBundle.empty(), "LeoNetwork::Build called twice");
    const Bundle& b = m_bundle;
    NS_ABORT_MSG_IF(include && include->size() != b.nodes.size(), "include must have one flag per node");
    auto wanted = [&](uint32_t id) { return include == nullptr || (*include)[id]; };

    // nodes, in bundle order (so ns-3 id == bundle id when everything is built
    // and no node existed before)
    m_nodeOfBundle.assign(b.nodes.size(), nullptr);
    NodeContainer all;
    for (const BundleNode& bn : b.nodes)
    {
        if (!wanted(bn.id))
        {
            continue;
        }
        Ptr<Node> n = CreateObject<Node>();
        m_nodeOfBundle[bn.id] = n;
        m_bundleOfNode[n->GetId()] = bn.id;
        all.Add(n);
    }
    InternetStackHelper stack;
    stack.SetIpv4StackInstall(false); // IPv6 only: T-CRH is an IPv6 routing header
    stack.Install(all);

    m_tcrh.SetT0GpsNs(b.t0GpsNs);
    m_tcrh.SetPolicy(m_config.policy);
    for (const BundleNode& bn : b.nodes)
    {
        if (m_nodeOfBundle[bn.id])
        {
            m_tcrh.Install(m_nodeOfBundle[bn.id], bn.sid);
        }
    }

    PointToPointHelper p2p;
    p2p.SetDeviceAttribute("DataRate", StringValue(m_config.dataRate));
    p2p.SetQueue("ns3::DropTailQueue<Packet>", "MaxSize", StringValue(m_config.queueSize));
    // No flow control: the device's DropTail queue is the ONLY queue and a
    // full queue drops at the device (MacTxDrop), as in Hypatia. With flow
    // control on and no queue disc, the traffic-control layer would drop
    // instead (TcDrop) once the device queue stops.
    p2p.DisableFlowControl();
    p2p.SetChannelAttribute("Delay", TimeValue(Seconds(0)));

    auto connect = [&](bool isIsl, uint32_t index, uint32_t a, uint32_t bb) {
        Link l;
        l.isIsl = isIsl;
        l.index = index;
        l.a = a;
        l.b = bb;
        l.link = m_tcrh.Connect(m_nodeOfBundle[a], m_nodeOfBundle[bb], p2p);
        l.channel = DynamicCast<PointToPointChannel>(l.link.devA->GetChannel());
        NS_ABORT_MSG_UNLESS(l.channel, "point-to-point link without a PointToPointChannel");
        l.up = true;
        l.delayNs = 0;
        const uint32_t li = static_cast<uint32_t>(m_links.size());
        m_linkOfPair[Key(a, bb)] = li;
        m_links.push_back(l);
        return static_cast<int32_t>(li);
    };
    m_linkOfIsl.assign(b.isls.size(), -1);
    for (const BundleIsl& isl : b.isls)
    {
        if (m_nodeOfBundle[isl.a] && m_nodeOfBundle[isl.b])
        {
            m_linkOfIsl[isl.id] = connect(true, isl.id, isl.a, isl.b);
        }
    }
    m_linkOfGsl.assign(b.gslPairs.size(), -1);
    for (size_t p = 0; p < b.gslPairs.size(); ++p)
    {
        const BundleGslPair& g = b.gslPairs[p];
        if (m_nodeOfBundle[g.gs] && m_nodeOfBundle[g.sat])
        {
            NS_ABORT_MSG_IF(m_linkOfPair.count(Key(g.gs, g.sat)), "ground pair listed twice");
            m_linkOfGsl[p] = connect(false, static_cast<uint32_t>(p), g.gs, g.sat);
        }
    }
    NS_LOG_INFO("LeoNetwork: " << all.GetN() << " nodes, " << m_links.size() << " links");
}

void
LeoNetwork::ScheduleSteps()
{
    for (uint32_t s = 0; s < m_bundle.nSteps; ++s)
    {
        Simulator::Schedule(MilliSeconds(static_cast<uint64_t>(s) * m_bundle.stepMs),
                            &LeoNetwork::ApplyStep,
                            this,
                            s);
    }
}

void
LeoNetwork::ApplyStep(uint32_t step)
{
    const Bundle& b = m_bundle;
    const size_t nIsl = b.isls.size();
    const size_t nPairs = b.gslPairs.size();
    for (uint32_t li = 0; li < m_links.size(); ++li)
    {
        Link& l = m_links[li];
        const size_t at = l.isIsl ? static_cast<size_t>(step) * nIsl + l.index
                                  : static_cast<size_t>(step) * nPairs + l.index;
        const int32_t d = l.isIsl ? b.islDelayNs[at] : b.gslDelayNs[at];
        const bool up = (l.isIsl ? b.islUp[at] : b.gslUp[at]) != 0;
        if (d >= 0) // -1 = no position: keep the last known light time (the link is down then anyway)
        {
            SetDelay(l, d);
        }
        if (up != l.up)
        {
            SetUp(l, up);
            if (!m_toggleCb.IsNull())
            {
                m_toggleCb(li, up);
            }
        }
    }
    m_stats.stepsApplied++;
}

void
LeoNetwork::SetDelay(Link& l, int64_t delayNs)
{
    l.delayNs = delayNs;
    const int64_t want = delayNs + l.extraDelayNs;
    if (want == l.appliedNs)
    {
        return; // unchanged since the last step: no attribute write
    }
    DelayAccessor()->Set(PeekPointer(l.channel), TimeValue(NanoSeconds(want)));
    l.appliedNs = want;
    m_stats.delayUpdates++;
}

void
LeoNetwork::BringInterfaceUp(Ptr<Node> node, uint32_t ifIndex, uint32_t linkId, uint8_t end)
{
    Ptr<Ipv6L3Protocol> ipv6 = node->GetObject<Ipv6L3Protocol>();
    ipv6->SetUp(ifIndex); // re-adds the link-local address
    // SetDown cleared every address; put the address-plan one back
    ipv6->AddAddress(ifIndex,
                     Ipv6InterfaceAddress(tcrh::LinkAddress(linkId, end),
                                          Ipv6Prefix(tcrh::LINK_PREFIX_LENGTH)),
                     true);
}

void
LeoNetwork::SetUp(Link& l, bool up)
{
    if (l.up == up)
    {
        return;
    }
    Ptr<Node> na = m_nodeOfBundle[l.a];
    Ptr<Node> nb = m_nodeOfBundle[l.b];
    if (up)
    {
        BringInterfaceUp(na, l.link.ifA, l.link.id, 1);
        BringInterfaceUp(nb, l.link.ifB, l.link.id, 2);
        m_stats.upEvents++;
    }
    else
    {
        na->GetObject<Ipv6L3Protocol>()->SetDown(l.link.ifA);
        nb->GetObject<Ipv6L3Protocol>()->SetDown(l.link.ifB);
        m_stats.downEvents++;
    }
    l.up = up;
}

Ptr<Node>
LeoNetwork::GetNode(uint32_t bundleId) const
{
    return bundleId < m_nodeOfBundle.size() ? m_nodeOfBundle[bundleId] : nullptr;
}

uint32_t
LeoNetwork::BundleIdOf(uint32_t nodeId) const
{
    auto it = m_bundleOfNode.find(nodeId);
    NS_ABORT_MSG_IF(it == m_bundleOfNode.end(), "ns-3 node " << nodeId << " is not a bundle node");
    return it->second;
}

TcrhHelper&
LeoNetwork::GetTcrhHelper()
{
    return m_tcrh;
}

const std::vector<LeoNetwork::Link>&
LeoNetwork::GetLinks() const
{
    return m_links;
}

int32_t
LeoNetwork::LinkOfIsl(uint32_t isl) const
{
    return isl < m_linkOfIsl.size() ? m_linkOfIsl[isl] : -1;
}

int32_t
LeoNetwork::LinkBetween(uint32_t a, uint32_t b) const
{
    auto it = m_linkOfPair.find(Key(a, b));
    return it == m_linkOfPair.end() ? -1 : static_cast<int32_t>(it->second);
}

const LeoNetwork::Stats&
LeoNetwork::GetStats() const
{
    return m_stats;
}

void
LeoNetwork::SetLinkRate(uint32_t link, DataRate rate)
{
    NS_ABORT_MSG_UNLESS(link < m_links.size(), "no link " << link);
    for (Ptr<NetDevice> d : {m_links[link].link.devA, m_links[link].link.devB})
    {
        DynamicCast<PointToPointNetDevice>(d)->SetDataRate(rate);
    }
}

void
LeoNetwork::SetLinkExtraDelay(uint32_t link, int64_t extra)
{
    NS_ABORT_MSG_UNLESS(link < m_links.size(), "no link " << link);
    NS_ABORT_MSG_IF(extra < 0, "extra delay must not be negative");
    Link& l = m_links[link];
    l.extraDelayNs = extra;
    SetDelay(l, l.delayNs); // light time unchanged, extra delay now included
}

void
LeoNetwork::SetToggleCallback(ToggleCallback cb)
{
    m_toggleCb = cb;
}

} // namespace leo
} // namespace ns3
