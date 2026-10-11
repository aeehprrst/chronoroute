/*
 * Copyright (c) 2026 The ChronoRoute authors
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#ifndef LEO_BUNDLE_HELPER_H
#define LEO_BUNDLE_HELPER_H

#include "ns3/callback.h"
#include "ns3/data-rate.h"
#include "ns3/node.h"
#include "ns3/nstime.h"
#include "ns3/point-to-point-channel.h"
#include "ns3/point-to-point-helper.h"
#include "ns3/point-to-point-net-device.h"
#include "ns3/tcrh-helper.h"
#include "ns3/tcrh-process.h"

#include <cstdint>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

/**
 * @file
 * @ingroup chronoroute
 *
 * Course milestone "LEO topology + time-varying schedule in ns-3": read a
 * ChronoRoute scenario bundle (docs/bundle-format.md, written by
 * `cr export bundle`) and build it as an ns-3 network whose links change every
 * 100 ms.
 *
 * Why a bundle and not orbits inside ns-3: Python computes the REAL satellite
 * positions (SGP4 on CelesTrak elements), the MODELLED laser links (Grid-4) and
 * ground links, and the DERIVED routes once. ns-3 replays exactly those numbers,
 * so the two simulators can be compared packet by packet (E16-lite).
 *
 * What gets built (LeoNetwork::Build):
 *  - one ns-3 node per bundle node (satellites, then ground stations), each a
 *    T-CRH node (TcrhHelper::Install) with its bundle SID;
 *  - one STOCK point-to-point link (ns3::PointToPointChannel, so NetAnim can
 *    draw it) per Grid-4 laser link, and one per (ground station, satellite)
 *    pair that is ever visible in the window;
 *  - every link: 1 Gb/s (MODELLED) and a DropTail queue of 100 packets per
 *    device (MODELLED). No queue disc is installed (TcrhHelper adds addresses
 *    by hand) and flow control is off, so the device queue is the only queue
 *    and a full queue drops at the device (MacTxDrop trace).
 *
 * What changes over time (LeoNetwork::ScheduleSteps): one event per bundle
 * step (every 100 ms) that, for every link,
 *  - sets the channel's Delay attribute to that step's light time from
 *    isl_delay.csv / gsl.csv. The delay is held constant for the whole step
 *    (a step function, not the linear interpolation the bundle recommends).
 *    A laser link's length changes by at most ~0.7 km in 100 ms, so a held
 *    value is off by at most ~2.3 us; Python replays the same held values, so
 *    the cross-check is exact;
 *  - takes the link down or up. DOWN means "SetDown semantics": the IPv6
 *    interface at BOTH ends is set down (Ipv6L3Protocol::SetDown). That is what
 *    the T-CRH extension and the source shim test before they forward
 *    (spec/tcrh-v1.md section 6 step 7, "next link down"), so a node that holds
 *    a packet for a dead link sees it and discards it (policy continue, no
 *    fallback yet). A packet already in flight when the link goes down is
 *    dropped by the receiving interface (ns-3 drops input on a down
 *    interface). ns-3 clears an interface's addresses when it goes down, so
 *    bringing it up again re-adds the link address of the address plan.
 *
 * Exactly-the-same-instant rule: the step events are scheduled before any
 * packet event, so at a tie (a packet event at exactly t = k * 100 ms) the new
 * link state is already in force. Python uses the same rule: the state at
 * time t is the row of step floor(t / 100 ms).
 */

namespace ns3
{
namespace leo
{

/// One row of nodes.csv.
struct BundleNode
{
    uint32_t id{0};    //!< node_id (satellites first, then ground stations)
    bool isSat{false}; //!< kind == "sat"
    uint32_t sid{0};   //!< T-CRH SID
    std::string norad; //!< NORAD id (satellites), empty for ground stations
    std::string name;  //!< OBJECT_NAME or city
    double latDeg{0};  //!< ground stations only
    double lonDeg{0};  //!< ground stations only
};

/// One row of isl.csv.
struct BundleIsl
{
    uint32_t id{0};     //!< link_id
    uint32_t a{0};      //!< node id, a < b
    uint32_t b{0};      //!< node id
    bool cross{false};  //!< kind == "cross" (else "intra")
};

/// One (ground station, satellite) pair of gsl.csv.
struct BundleGslPair
{
    uint32_t gs{0};  //!< ground station node id
    uint32_t sat{0}; //!< satellite node id
};

/// One row of schedule.csv.
struct ScheduleRow
{
    uint32_t flow{0};                          //!< flow_id
    uint32_t srcGs{0};                         //!< source ground station node id
    uint32_t dstGs{0};                         //!< destination ground station node id
    int64_t fromMs{0};                         //!< valid for [fromMs, toMs)
    int64_t toMs{0};                           //!< end (exclusive)
    std::vector<uint16_t> sidsFwd;             //!< s_1..s_h (the last is the destination)
    std::vector<uint64_t> budgetsNs;           //!< ceil(B_k), ns
    std::vector<int64_t> predictedHopNs;       //!< d_k = light time + 0.5 ms
    std::string templateHex;                   //!< T-CRH bytes with Epoch_Base 0
    std::vector<uint32_t> pathNodes;           //!< src_gs .. dst_gs
    std::vector<uint32_t> cumDeltaU;           //!< d_1 + ... + d_k in units (from the encoder)
};

/**
 * A scenario bundle, read into memory. Large tables are dense arrays indexed
 * [step * count + index], because every step lists every link (the format
 * guarantees it and Load checks it).
 */
class Bundle
{
  public:
    /**
     * Read and check a bundle directory. Aborts with a clear message if a file
     * is missing, malformed or not in the documented order.
     * @param dir the bundle directory
     * @param loadPositions also read positions.csv (only NetAnim needs it)
     * @return the bundle
     */
    static Bundle Load(const std::string& dir, bool loadPositions);

    std::string dir;              //!< where it was read from
    uint64_t t0GpsNs{0};          //!< scenario.json time.t0_gps_ns
    uint64_t t0UnixNs{0};         //!< scenario.json time.t0_unix_ns (UTC)
    int64_t windowMs{0};          //!< time.window_ms
    int64_t stepMs{0};            //!< time.step_ms
    int64_t positionStepMs{0};    //!< time.position_step_ms
    int64_t refreshMs{0};         //!< time.schedule_refresh_ms
    uint8_t unitCode{0};          //!< tcrh.unit_code

    std::vector<BundleNode> nodes; //!< all nodes, index = node id
    uint32_t nSats{0};             //!< satellites are nodes 0..nSats-1
    std::vector<BundleIsl> isls;   //!< laser links, index = link id
    std::vector<BundleGslPair> gslPairs; //!< ground-link pairs in file order
    uint32_t nSteps{0};            //!< window / step + 1

    std::vector<int32_t> islDelayNs; //!< [step * nIsl + link], -1 = no position
    std::vector<uint8_t> islUp;      //!< [step * nIsl + link]
    std::vector<int32_t> gslDelayNs; //!< [step * nPairs + pair]
    std::vector<uint8_t> gslUp;      //!< [step * nPairs + pair]

    std::vector<ScheduleRow> schedule; //!< sorted by (fromMs, flow)

    uint32_t nPosSteps{0};    //!< positions.csv steps (0 if not loaded)
    std::vector<double> posM; //!< [(pstep * nNodes + node) * 3 + xyz], ECEF metres

    /// @param tNs simulation time in ns @return the step in force (clamped to the last)
    uint32_t StepAt(int64_t tNs) const;
    /// @param flow flow id @param tNs time @return the row valid at tNs, or nullptr (gap)
    const ScheduleRow* RowAt(uint32_t flow, int64_t tNs) const;
    /// @return the flow ids that appear in schedule.csv, ascending
    std::vector<uint32_t> Flows() const;
    /// @param flow a flow id @return (src_gs, dst_gs) of its first row (aborts if none)
    std::pair<uint32_t, uint32_t> FlowEnds(uint32_t flow) const;
    /// @param a node @param b node @return the ISL id joining them, or -1
    int32_t IslBetween(uint32_t a, uint32_t b) const;

  private:
    std::map<std::pair<uint32_t, uint32_t>, uint32_t> m_islOfPair; //!< (min, max) -> isl id
    std::map<uint32_t, std::vector<uint32_t>> m_rowsOfFlow; //!< flow -> row indices by fromMs
};

/**
 * Which laser link to slow down for the "up but slow" fault, chosen by a fixed
 * rule so that the fault and no-fault runs (and Python) agree on it:
 * among the laser links on @p flow's scheduled path at @p startMs, take the one
 * used by the most schedule-milliseconds of ANY flow during [startMs, stopMs)
 * (most probes cross it); ties go to the lowest link id. The link must be up
 * at @p startMs.
 * @return the ISL id (aborts if the path has no laser link)
 */
uint32_t ChooseFaultIsl(const Bundle& b, uint32_t flow, int64_t startMs, int64_t stopMs);

/**
 * Satellites for the NetAnim slice: every satellite on @p flow's paths in
 * [fromMs, toMs), then their laser-link neighbours, breadth first (node id
 * order inside each ring), until @p maxSats are taken.
 * @return satellite node ids, ascending
 */
std::vector<uint32_t> SelectSliceSatellites(const Bundle& b,
                                            uint32_t flow,
                                            int64_t fromMs,
                                            int64_t toMs,
                                            uint32_t maxSats);

/// Geodetic WGS84 latitude and longitude (degrees) of an ECEF point (metres).
/// Display only (NetAnim); nothing physical depends on it.
/// @param x ECEF x @param y ECEF y @param z ECEF z @param latDeg out @param lonDeg out
void EcefToLatLon(double x, double y, double z, double* latDeg, double* lonDeg);

/**
 * World-map projection for NetAnim (equirectangular, y pointing down):
 * X = ((lon - lon0 + 540) mod 360) * 10, Y = (90 - lat) * 10.
 * The x10 matters: NetAnim only records a move when ceil(x) or ceil(y)
 * changes, so one unit must be small (0.1 degree here). lon0 is the map's
 * centre longitude, chosen near the path so it never crosses the map edge.
 * @param latDeg latitude @param lonDeg longitude @param lon0Deg centre longitude
 * @return (X, Y)
 */
std::pair<double, double> ProjectWorldMap(double latDeg, double lonDeg, double lon0Deg);

/**
 * A bundle built as an ns-3 network (see the file comment).
 */
class LeoNetwork
{
  public:
    /// One link of the network: a laser link or a ground-link pair.
    struct Link
    {
        bool isIsl{true};          //!< laser link (else ground link)
        uint32_t index{0};         //!< ISL id or ground-link pair index
        uint32_t a{0};             //!< bundle node id of end 1 (ISL: a; GSL: the ground station)
        uint32_t b{0};             //!< bundle node id of end 2 (ISL: b; GSL: the satellite)
        TcrhHelper::Link link;     //!< devices, interfaces, address-plan link id
        Ptr<PointToPointChannel> channel; //!< the stock channel
        bool up{true};             //!< current state
        int64_t delayNs{0};        //!< light time currently set (without extra delay)
        int64_t extraDelayNs{0};   //!< fault: added on top of the light time
        int64_t appliedNs{-1};     //!< the Delay last written to the channel
    };

    /// Settings of the build (all MODELLED).
    struct Config
    {
        std::string dataRate{"1Gbps"};  //!< every link, both directions
        std::string queueSize{"100p"};  //!< DropTail size of every device queue
        tcrh::Policy policy{tcrh::Policy::CONTINUE}; //!< deviation policy of every node
    };

    /// Counters of the time-varying part.
    struct Stats
    {
        uint64_t stepsApplied{0};    //!< step events run
        uint64_t delayUpdates{0};    //!< Delay attribute writes
        uint64_t downEvents{0};      //!< link up -> down
        uint64_t upEvents{0};        //!< link down -> up
    };

    /**
     * @param bundle the bundle (must outlive this object)
     * @param config link settings
     */
    LeoNetwork(const Bundle& bundle, Config config);

    /**
     * Create the nodes and links. With @p include, only the bundle nodes for
     * which include[id] is true are built (NetAnim slice); links need both
     * ends. Ground stations are always taken from @p include too.
     * Must run before any other ns-3 node is created when building the whole
     * bundle, so that ns-3 node id == bundle node id.
     * @param include nullptr for every node
     */
    void Build(const std::vector<bool>* include = nullptr);

    /// Schedule one event per bundle step that applies that step (call before
    /// scheduling any packet event, see the file comment).
    void ScheduleSteps();

    /// Apply step @p step now: delays and up/down of every link.
    /// @param step the step index
    void ApplyStep(uint32_t step);

    /// @param bundleId a bundle node id @return its ns-3 node (null if not built)
    Ptr<Node> GetNode(uint32_t bundleId) const;
    /// @param nodeId an ns-3 node id @return its bundle id (aborts if unknown)
    uint32_t BundleIdOf(uint32_t nodeId) const;
    /// @return the TcrhHelper (SIDs, address plan, shims)
    TcrhHelper& GetTcrhHelper();
    /// @return the links
    const std::vector<Link>& GetLinks() const;
    /// @param isl an ISL id @return its index in GetLinks(), or -1 if not built
    int32_t LinkOfIsl(uint32_t isl) const;
    /// @param a node @param b node @return index in GetLinks() of the link joining them, or -1
    int32_t LinkBetween(uint32_t a, uint32_t b) const;
    /// @return the counters
    const Stats& GetStats() const;

    /**
     * Fault helpers: change a link's data rate (both directions) or add an
     * extra delay on top of its light time (re-applied at every step).
     * @param link index in GetLinks() @param rate the new rate
     */
    void SetLinkRate(uint32_t link, DataRate rate);
    /// @param link index in GetLinks() @param extra extra one-way delay, ns
    void SetLinkExtraDelay(uint32_t link, int64_t extra);

    /// Callback fired when a link changes state: (link index, now up?).
    using ToggleCallback = Callback<void, uint32_t, bool>;
    /// @param cb called after every up/down change (e.g. NetAnim descriptions)
    void SetToggleCallback(ToggleCallback cb);

  private:
    /// @param l the link @param up new state
    void SetUp(Link& l, bool up);
    /// @param l the link @param delayNs light time to set (extra delay added)
    void SetDelay(Link& l, int64_t delayNs);
    /// @param node a node @param ifIndex its interface @param linkId address-plan link
    /// @param end 1 or 2
    void BringInterfaceUp(Ptr<Node> node, uint32_t ifIndex, uint32_t linkId, uint8_t end);

    const Bundle& m_bundle;                  //!< the bundle
    Config m_config;                         //!< link settings
    TcrhHelper m_tcrh;                       //!< SIDs, CRH-FIB, address plan
    std::vector<Ptr<Node>> m_nodeOfBundle;   //!< bundle id -> node (null if not built)
    std::map<uint32_t, uint32_t> m_bundleOfNode; //!< ns-3 node id -> bundle id
    std::vector<Link> m_links;               //!< ISLs first, then ground links
    std::vector<int32_t> m_linkOfIsl;        //!< ISL id -> link index
    std::vector<int32_t> m_linkOfGsl;        //!< ground pair index -> link index
    std::map<std::pair<uint32_t, uint32_t>, uint32_t> m_linkOfPair; //!< (min,max) -> link index
    Stats m_stats;                           //!< counters
    ToggleCallback m_toggleCb;               //!< optional
};

} // namespace leo
} // namespace ns3

#endif /* LEO_BUNDLE_HELPER_H */
