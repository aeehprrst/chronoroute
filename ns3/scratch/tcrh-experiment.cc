/*
 * tcrh-experiment.cc
 * ------------------
 * ASSESSMENT 8 -- the Temporal Compact Routing Header (T-CRH).
 *
 * Assessment 7 implemented CRH-16 exactly as RFC 9631 defines it. This builds
 * directly on that and adds the one thing that is my own contribution:
 * a TIME DEADLINE for every hop.
 *
 * WHY
 * ---
 * CRH-16 tells a packet WHERE to go. It says nothing about WHEN. In a LEO
 * satellite network the route is pre-computed on the ground from orbital
 * mechanics, so by the time a packet is actually flying, the schedule it was
 * given may no longer match reality -- a link may have slowed down, or the
 * satellites may have moved on.
 *
 * A link-state check cannot see a link that is still UP but has become slow.
 * A deadline can. That is the whole argument for putting time in the header.
 *
 * WHAT CHANGES FROM ASSESSMENT 7
 * ------------------------------
 *   header  : each segment carries a 1-byte delta deadline beside its 2-byte
 *             SID, and the fixed part gains a Flags byte and a 4-byte epoch
 *   algorithm: one extra check on arrival, before the RFC 9631 steps run
 *   behaviour: a packet that misses its deadline raises a Deviation_Flag and
 *             falls back instead of blindly following a stale schedule
 *
 * Everything else -- reverse-ordered SIDs, Segments Left as an index,
 * decrement-then-index, the CRH-FIB lookup, the 64-bit padding rule -- is
 * unchanged from Assessment 7.
 *
 * WIRE FORMAT
 * -----------
 *    0               1               2               3
 *    0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
 *   +---------------+---------------+---------------+---------------+
 *   |  Next Header  |  Hdr Ext Len  | Rtg Type =253 | Segments Left |
 *   +---------------+---------------+---------------+---------------+
 *   |     Flags     |   Num Hops    |           Reserved            |
 *   +---------------+---------------+-------------------------------+
 *   |                  Epoch_Base (milliseconds)                    |
 *   +---------------------------------------------------------------+
 *   |     SID[0] (16 bits)          | Delta[0] (8) |   SID[1] ...   |
 *   +---------------------------------------------------------------+
 *                   (zero-padded to a 64-bit boundary)
 *
 * Routing Type 253 is reserved by IANA for experimentation, which is the
 * correct value for a non-standard header like this one.
 *
 * Build: copy to ~/ns-3-dev/scratch/ and run ./ns3 build
 * Run:   ./ns3 run "scratch/tcrh-experiment"
 *        ./ns3 run "scratch/tcrh-experiment --packets=1000 --RngRun=1"
 *
 * v0.9 (2026-10-10, ChronoRoute Phase 1)
 * --------------------------------------
 * The header on the wire is still the v0 header of this assessment (1 ms
 * units, two Reserved bytes); the T-CRH v1 header lives in the chronoroute
 * contrib module. Two bugs are fixed:
 *
 *   #18 integer-ms truncation. Deadlines were built and checked with
 *       Simulator::Now().GetMilliSeconds(), which floors, and each hop's budget
 *       was rounded to whole ms on its own. Up to 0.999 ms of lateness was
 *       invisible at every hop, and a budget could be rounded DOWN. Budgets are
 *       now integer microseconds, Epoch_Base is the send time rounded UP and the
 *       deltas are encoded ceil-cumulatively (spec v1 sections 4 and 5.1), and
 *       the clock is compared with the deadline in exact nanoseconds.
 *
 *   #21 confounded detection score. Every deviation in the degraded phase was
 *       counted as a "correct detection", and the healthy-phase and
 *       degraded-phase packets were different packets. A packet late only
 *       because of jitter counted as a detection, so the sweep reported
 *       "100% detection" even for a fault that does nothing (see
 *       ns3_rescore_v09.md). The same traffic, with the SAME random jitter, now
 *       runs through three identical copies of the network in one simulation:
 *         healthy     the n3-n4 link never changes
 *         fault       the n3-n4 link is slowed to --degraded ms
 *         null-fault  the n3-n4 link is "slowed" to its own 20 ms (factor 1.0)
 *       Packets are paired by id. A detection is a packet flagged WITH the
 *       fault and NOT flagged without it; the false-positive rate comes from
 *       the healthy network; the null-fault network must score exactly zero.
 *
 * The header's TypeId is ns3::TcrhV0Header, because the chronoroute module now
 * owns ns3::TcrhHeader. Default outputs are tcrh_sizes_v09.csv and
 * tcrh_sweep_v09.csv, so the Assessment 8 CSVs are never overwritten.
 */

#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <sstream>
#include <vector>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("TcrhExperiment");

// ===========================================================================
//  PART 1 -- The T-CRH header
// ===========================================================================

static const uint8_t TCRH_ROUTING_TYPE = 253; // IANA: reserved for experiments

static const uint8_t FLAG_DEVIATION = 0x01;   // set when a deadline is missed

class TcrhHeader : public Header
{
  public:
    TcrhHeader()
        : m_nextHeader(17), // UDP
          m_segmentsLeft(0),
          m_flags(0),
          m_numHops(0),
          m_epochMs(0)
    {
    }

    static TypeId GetTypeId()
    {
        // Not "ns3::TcrhHeader": the chronoroute contrib module (Phase 1)
        // registers that name for the v1 header, and ns-3 links every scratch
        // program against every module, so two classes with one TypeId name
        // abort at start-up ("Trying to allocate twice the same uid").
        static TypeId tid = TypeId("ns3::TcrhV0Header")
                                .SetParent<Header>()
                                .SetGroupName("Internet")
                                .AddConstructor<TcrhHeader>();
        return tid;
    }

    TypeId GetInstanceTypeId() const override
    {
        return GetTypeId();
    }

    /**
     * Load the path and its per-hop time budgets.
     *
     * Both lists are given in FORWARD order and stored reversed, exactly as
     * CRH-16 does, so that Segments Left indexes both of them directly.
     *
     * deltaMs[k] is the time budget for the k-th link, in milliseconds. One
     * byte, so the ceiling is 255 ms. A real inter-satellite hop needs 5-25 ms,
     * so we halve the cost of a path entry in exchange for a limit we will
     * never reach.
     */
    void SetPath(const std::vector<uint16_t>& sidsForward,
                 const std::vector<uint8_t>& deltaMsForward,
                 uint32_t epochMs)
    {
        NS_ASSERT_MSG(sidsForward.size() == deltaMsForward.size(),
                      "every segment needs its own deadline");
        m_sids.assign(sidsForward.rbegin(), sidsForward.rend());
        m_deltas.assign(deltaMsForward.rbegin(), deltaMsForward.rend());
        m_segmentsLeft = m_sids.size();
        m_numHops = m_sids.size();
        m_epochMs = epochMs;
    }

    uint8_t GetSegmentsLeft() const { return m_segmentsLeft; }
    void SetSegmentsLeft(uint8_t sl) { m_segmentsLeft = sl; }
    uint8_t GetFlags() const { return m_flags; }
    void SetFlags(uint8_t f) { m_flags = f; }
    bool IsDeviated() const { return (m_flags & FLAG_DEVIATION) != 0; }
    void SetDeviation() { m_flags |= FLAG_DEVIATION; }
    uint32_t GetEpochMs() const { return m_epochMs; }
    uint8_t GetNumHops() const { return m_numHops; }

    uint16_t GetCurrentSid() const
    {
        NS_ASSERT_MSG(m_segmentsLeft < m_sids.size(), "Segments Left out of range");
        return m_sids[m_segmentsLeft];
    }

    /**
     * The latest time this packet may ARRIVE at the node it is now sitting on.
     *
     * Deadlines are cumulative: the budget for every link already crossed is
     * added up. A packet held up at one hop can therefore still make the time
     * back at a later, faster hop, instead of being condemned by one bad hop.
     *
     * Segments already consumed are the entries from m_segmentsLeft upward,
     * because the lists are stored in reverse.
     */
    uint32_t GetArrivalDeadlineMs() const
    {
        uint32_t sum = m_epochMs;
        for (size_t i = m_segmentsLeft; i < m_deltas.size(); ++i)
        {
            sum += m_deltas[i];
        }
        return sum;
    }

    uint8_t GetHdrExtLen() const
    {
        return static_cast<uint8_t>(GetSerializedSize() / 8) - 1;
    }

    /** Minimum length needed to hold Segments Left entries, as in RFC 9631. */
    uint8_t GetMinimumLength() const
    {
        uint32_t bytes = FIXED_BYTES + m_segmentsLeft * 3;
        uint32_t padded = ((bytes + 7) / 8) * 8;
        return static_cast<uint8_t>(padded / 8) - 1;
    }

    uint32_t GetSerializedSize() const override
    {
        uint32_t bytes = FIXED_BYTES + m_sids.size() * 3;
        return ((bytes + 7) / 8) * 8;
    }

    void Serialize(Buffer::Iterator start) const override
    {
        uint32_t total = GetSerializedSize();

        start.WriteU8(m_nextHeader);
        start.WriteU8(static_cast<uint8_t>(total / 8) - 1);
        start.WriteU8(TCRH_ROUTING_TYPE);
        start.WriteU8(m_segmentsLeft);
        start.WriteU8(m_flags);
        start.WriteU8(m_numHops);
        start.WriteHtonU16(0); // Reserved
        start.WriteHtonU32(m_epochMs);

        for (size_t i = 0; i < m_sids.size(); ++i)
        {
            start.WriteHtonU16(m_sids[i]);
            start.WriteU8(m_deltas[i]);
        }

        uint32_t written = FIXED_BYTES + m_sids.size() * 3;
        for (uint32_t i = written; i < total; ++i)
        {
            start.WriteU8(0);
        }
    }

    uint32_t Deserialize(Buffer::Iterator start) override
    {
        m_nextHeader = start.ReadU8();
        uint8_t hdrExtLen = start.ReadU8();
        uint8_t routingType = start.ReadU8();
        m_segmentsLeft = start.ReadU8();
        m_flags = start.ReadU8();
        m_numHops = start.ReadU8();
        start.ReadNtohU16(); // Reserved
        m_epochMs = start.ReadNtohU32();

        NS_ASSERT_MSG(routingType == TCRH_ROUTING_TYPE, "not a T-CRH header");

        uint32_t total = (hdrExtLen + 1) * 8;

        // Unlike CRH-16 we DO have a hop count, so we can read exactly the
        // real entries and skip the padding. Carrying Num Hops costs a byte
        // but removes the ambiguity that made the CRH deserializer awkward.
        m_sids.clear();
        m_deltas.clear();
        for (uint32_t i = 0; i < m_numHops; ++i)
        {
            m_sids.push_back(start.ReadNtohU16());
            m_deltas.push_back(start.ReadU8());
        }

        return total;
    }

    void Print(std::ostream& os) const override
    {
        os << "T-CRH(segsLeft=" << +m_segmentsLeft << " hops=" << +m_numHops
           << " flags=0x" << std::hex << +m_flags << std::dec << " epoch="
           << m_epochMs << "ms " << GetSerializedSize() << "B)";
    }

    std::string ToHex() const
    {
        Buffer buf;
        buf.AddAtStart(GetSerializedSize());
        Serialize(buf.Begin());
        std::ostringstream os;
        Buffer::Iterator it = buf.Begin();
        for (uint32_t i = 0; i < GetSerializedSize(); ++i)
        {
            os << std::hex << std::setw(2) << std::setfill('0') << +it.ReadU8();
        }
        return os.str();
    }

    static const uint32_t FIXED_BYTES = 12; // 8 header bytes + 4 epoch bytes

  private:
    uint8_t m_nextHeader;
    uint8_t m_segmentsLeft;
    uint8_t m_flags;
    uint8_t m_numHops;
    uint32_t m_epochMs;
    std::vector<uint16_t> m_sids;   // reverse path order
    std::vector<uint8_t> m_deltas;  // reverse path order, milliseconds
};

// ---- size helpers ----
static uint32_t TcrhSize(uint32_t n) { return ((12 + n * 3) + 7) / 8 * 8; }
static uint32_t Crh16Size(uint32_t n) { return ((4 + n * 2) + 7) / 8 * 8; }
static uint32_t SrhSize(uint32_t n) { return ((8 + n * 16) + 7) / 8 * 8; }

// ===========================================================================
//  PART 1b -- exact deadline arithmetic (bug #18)
// ===========================================================================
//
// The wire still carries whole milliseconds, but nothing that produces or
// checks those milliseconds truncates any more:
//   * budgets are integer MICROSECONDS; the one double -> integer step rounds
//     to the nearest microsecond (so 20 ms x 1.1 = 22.000000000000004 ms is
//     22000 us, not 22001);
//   * Epoch_Base is the send time rounded UP to a whole ms, and the deltas are
//     the ceil of the CUMULATIVE budget minus what is already encoded, so a
//     deadline is never earlier than its budget and rounding never adds up
//     along the path (spec v1 sections 4 and 5.1);
//   * the clock is compared with the deadline in exact nanoseconds, so a
//     packet that arrives 0.4 ms after its deadline is late. The first version
//     compared Now().GetMilliSeconds(), which floors: up to 0.999 ms of
//     lateness was invisible at every hop.

static const int64_t US_PER_MS = 1000;
static const int64_t NS_PER_MS = 1000000;

/** A time in ms (double) as integer microseconds, rounded to the nearest us. */
static int64_t
MsToUs(double ms)
{
    return std::llround(ms * US_PER_MS);
}

/** Epoch_Base in ms: the send time rounded UP (the anchor may only add slack). */
static uint32_t
EpochMsCeil(Time sendTime)
{
    const int64_t ns = sendTime.GetNanoSeconds();
    return static_cast<uint32_t>((ns + NS_PER_MS - 1) / NS_PER_MS);
}

/**
 * Per-hop budgets (integer us) -> 1 ms deltas, ceil-cumulative: hop k gets
 * ceil(B_k / 1 ms) minus the deltas already encoded, where B_k is the budget
 * from the source to hop k. One byte per delta, as in the v0 header.
 */
static std::vector<uint8_t>
EncodeDeltasMs(const std::vector<int64_t>& perHopBudgetUs)
{
    std::vector<uint8_t> deltas;
    int64_t cumulativeUs = 0;
    int64_t encodedMs = 0;
    for (int64_t b : perHopBudgetUs)
    {
        cumulativeUs += b;
        const int64_t target = (cumulativeUs + US_PER_MS - 1) / US_PER_MS; // exact ceil
        int64_t d = std::max<int64_t>(0, target - encodedMs);
        d = std::min<int64_t>(255, d); // one byte (v0 has no SAT flag to report a clamp)
        encodedMs += d;
        deltas.push_back(static_cast<uint8_t>(d));
    }
    return deltas;
}

/** Late = strictly after the deadline instant, in exact nanoseconds. */
static bool
IsLate(Time now, uint32_t deadlineMs)
{
    return now.GetNanoSeconds() > static_cast<int64_t>(deadlineMs) * NS_PER_MS;
}

// ===========================================================================
//  PART 2 -- Trace records
// ===========================================================================

// The same traffic runs through three identical copies of the network (bug
// #21, see main): HEALTHY never changes, FAULT has the n3-n4 link slowed, and
// NULL_FAULT "slows" it to its own delay (degradation factor 1.0), a control
// that must give exactly the same result as HEALTHY.
enum Arm
{
    ARM_HEALTHY = 0,
    ARM_FAULT = 1,
    ARM_NULL_FAULT = 2,
    N_ARMS = 3
};

static const char* const ARM_NAMES[N_ARMS] = {"healthy", "fault", "null-fault"};

struct Record
{
    double slack = 0;
    uint32_t slackIndex = 0;
    Time sent;                    // exact send time
    std::vector<double> jitterMs; // pre-drawn jitter for each sending hop (k = 0..h-1)
    bool deviated = false;
    uint32_t devHop = 0;          // hop index k where DEV was set (kept here; v0 has no Dev Hop byte)
    bool delivered = false;
    bool viaFallback = false;
    double latencyMs = 0;         // exact, send to delivery
    uint32_t hops = 0;
};

static std::map<uint32_t, Record> g_records[N_ARMS]; // packet id -> record, per network

// ===========================================================================
//  PART 3 -- The T-CRH forwarder
// ===========================================================================

class TcrhForwarder : public Application
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::TcrhForwarder")
                                .SetParent<Application>()
                                .SetGroupName("Applications")
                                .AddConstructor<TcrhForwarder>();
        return tid;
    }

    TcrhForwarder()
        : m_socket(nullptr),
          m_port(7777),
          m_arm(ARM_HEALTHY)
    {
    }

    void AddFibEntry(uint16_t sid, Ipv4Address nextHop) { m_fib[sid] = nextHop; }
    void SetFinalDestination(Ipv4Address a) { m_finalDest = a; }
    /** Which copy of the network this node belongs to (selects its records). */
    void SetArm(Arm arm) { m_arm = arm; }

    class IdTag : public Tag
    {
      public:
        uint32_t id = 0;
        static TypeId GetTypeId()
        {
            static TypeId tid = TypeId("ns3::TcrhIdTag")
                                    .SetParent<Tag>()
                                    .SetGroupName("Applications")
                                    .AddConstructor<IdTag>();
            return tid;
        }
        TypeId GetInstanceTypeId() const override { return GetTypeId(); }
        uint32_t GetSerializedSize() const override { return 4; }
        void Serialize(TagBuffer i) const override { i.WriteU32(id); }
        void Deserialize(TagBuffer i) override { id = i.ReadU32(); }
        void Print(std::ostream& os) const override { os << "id=" << id; }
    };

    /**
     * Build a T-CRH and inject the packet.
     *
     * slack is the factor applied to the predicted per-hop delay to get the
     * deadline budget. This is the single most important knob in the whole
     * project, and Part C sweeps it.
     *
     * pid and jitterMs come from the traffic generator in main, which sends
     * the same packet (same id, same random jitter) into all three networks,
     * so the packets can be paired afterwards (bug #21).
     */
    void SendWithSchedule(uint32_t pid,
                          const std::vector<uint16_t>& sids,
                          const std::vector<double>& predictedMs,
                          double slack,
                          uint32_t slackIndex,
                          const std::vector<double>& jitterMs,
                          uint32_t payloadBytes)
    {
        // Budgets in integer microseconds, then exact ceil-cumulative 1 ms
        // deltas (bug #18: each hop used to be rounded to whole ms on its own,
        // which could round a budget DOWN).
        std::vector<int64_t> budgetUs;
        for (double d : predictedMs)
        {
            budgetUs.push_back(MsToUs(d * slack));
        }
        std::vector<uint8_t> deltas = EncodeDeltasMs(budgetUs);

        // Epoch_Base = the send time rounded UP to a whole ms (it used to be
        // floored, which moved every deadline up to 1 ms EARLIER)
        Time now = Simulator::Now();

        TcrhHeader h;
        h.SetPath(sids, deltas, EpochMsCeil(now));

        Record r;
        r.slack = slack;
        r.slackIndex = slackIndex;
        r.sent = now;
        r.jitterMs = jitterMs;
        g_records[m_arm][pid] = r;

        Ptr<Packet> p = Create<Packet>(payloadBytes);
        IdTag tag;
        tag.id = pid;
        p->AddByteTag(tag);
        p->AddHeader(h);

        Process(p, pid);
    }

  protected:
    void StartApplication() override
    {
        if (!m_socket)
        {
            m_socket = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
            m_socket->Bind(InetSocketAddress(Ipv4Address::GetAny(), m_port));
            m_socket->SetRecvCallback(MakeCallback(&TcrhForwarder::HandleRead, this));
        }
    }

    void StopApplication() override
    {
        if (m_socket)
        {
            m_socket->Close();
        }
    }

  private:
    void HandleRead(Ptr<Socket> socket)
    {
        Ptr<Packet> packet;
        Address from;
        while ((packet = socket->RecvFrom(from)))
        {
            IdTag tag;
            uint32_t pid = 0;
            if (packet->FindFirstMatchingByteTag(tag))
            {
                pid = tag.id;
            }
            Process(packet, pid);
        }
    }

    /**
     * The forwarding algorithm.
     *
     * Steps 1 to 6 are RFC 9631 unchanged from Assessment 7.
     * Step 0 is the addition: the deadline check.
     */
    void Process(Ptr<Packet> packet, uint32_t pid)
    {
        TcrhHeader h;
        packet->RemoveHeader(h);

        Record& rec = g_records[m_arm][pid];
        Time now = Simulator::Now();
        // this node's hop index on the path: 0 at the source, k at the k-th SID
        uint32_t k = h.GetNumHops() - h.GetSegmentsLeft();

        // ---- STEP 0 (NEW): have I arrived later than my deadline? ----
        //
        // This is the whole contribution. One comparison, no routing table, no
        // neighbour state. A link that is still up but has slowed down is
        // invisible to a link-state check and visible here.
        //
        // Compared in exact nanoseconds (bug #18), and not at the source, which
        // has consumed no budget yet (spec v1 section 6; with Epoch_Base
        // rounded up the source could never be late anyway).
        if (!h.IsDeviated() && k > 0 && IsLate(now, h.GetArrivalDeadlineMs()))
        {
            h.SetDeviation();
            rec.deviated = true;
            rec.devHop = k;
        }

        // ---- STEP 1: Segments Left == 0 means this packet is for me ----
        if (h.GetSegmentsLeft() == 0)
        {
            rec.delivered = true;
            rec.latencyMs = (now - rec.sent).GetNanoSeconds() / 1e6; // exact, not floored
            return;
        }

        // ---- FAIL-SAFE: the schedule is broken, stop following it ----
        //
        // In the satellite design this hands over to zero-state geographic
        // forwarding, using neighbour positions the satellite already holds.
        // That needs orbital position data, so in this terrestrial test the
        // fallback is the network's own routing: the packet is sent straight
        // to the destination and normal IP forwarding delivers it. The point
        // being demonstrated is that the flag changes the packet's behaviour,
        // not merely that it was recorded.
        if (h.IsDeviated())
        {
            rec.viaFallback = true;

            // Segments Left is zeroed before handing the packet over. Without
            // this the destination arrives with Segments Left still above zero,
            // falls into this same branch, and posts the packet to itself
            // forever -- which is exactly how my first version hung.
            h.SetSegmentsLeft(0);
            packet->AddHeader(h);
            SendTo(packet, m_finalDest, 0.0);
            return;
        }

        // ---- STEP 2: minimum-length check (RFC 9631 Section 5.1) ----
        if (h.GetMinimumLength() > h.GetHdrExtLen())
        {
            return; // malformed: discard
        }

        // ---- STEP 3: decrement Segments Left ----
        h.SetSegmentsLeft(h.GetSegmentsLeft() - 1);

        // ---- STEP 4: the current SID is the one Segments Left now points at ----
        uint16_t sid = h.GetCurrentSid();

        // ---- STEP 5: CRH-FIB lookup ----
        auto e = m_fib.find(sid);
        if (e == m_fib.end())
        {
            return; // no entry: discard
        }

        // ---- STEP 6: forward ----
        // The jitter for this hop was drawn once, when the packet was created,
        // so the same packet gets the same jitter in all three networks.
        rec.hops++;
        packet->AddHeader(h);
        SendTo(packet, e->second, k < rec.jitterMs.size() ? rec.jitterMs[k] : 0.0);
    }

    /**
     * Send after a small random delay, which stands in for the queueing and
     * processing jitter a real router adds. Without it every hop would take
     * exactly the predicted time, the deadline would never be missed by
     * accident, and the slack sweep in Part C would be a meaningless
     * straight line.
     */
    void SendTo(Ptr<Packet> packet, Ipv4Address dest, double jitterMs)
    {
        Simulator::Schedule(NanoSeconds(static_cast<uint64_t>(jitterMs * 1e6)),
                            &TcrhForwarder::DoSend,
                            this,
                            packet,
                            dest);
    }

    void DoSend(Ptr<Packet> packet, Ipv4Address dest)
    {
        Ptr<Socket> tx = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
        tx->Connect(InetSocketAddress(dest, m_port));
        tx->Send(packet);
        tx->Close();
    }

    Ptr<Socket> m_socket;
    uint16_t m_port;
    Ipv4Address m_finalDest;
    std::map<uint16_t, Ipv4Address> m_fib;
    Arm m_arm;
};

// ===========================================================================
//  PART A -- header conformance self-test
// ===========================================================================

static bool
RunSelfTest()
{
    std::cout << "\n=== PART A: T-CRH header conformance self-test ===\n\n";
    bool ok = true;

    // path 2 -> 3 -> 7, budgets 6 ms, 7 ms, 8 ms, epoch 1000 ms
    TcrhHeader h;
    h.SetPath({2, 3, 7}, {6, 7, 8}, 1000);

    // Expected bytes, worked out by hand:
    //   11        Next Header  = 17 (UDP)
    //   02        Hdr Ext Len  = 2   (24 bytes total)
    //   fd        Routing Type = 253 (experimental)
    //   03        Segments Left= 3
    //   00        Flags        = 0   (no deviation yet)
    //   03        Num Hops     = 3
    //   0000      Reserved
    //   000003e8  Epoch        = 1000 ms
    //   0007 08   SID 7, delta 8      <- reversed, so the LAST hop comes first
    //   0003 07   SID 3, delta 7
    //   0002 06   SID 2, delta 6
    //   000000    padding to the 64-bit boundary (12 + 9 = 21 -> 24)
    const std::string expected =
        "1102fd0300030000000003e8000708000307000206000000";

    std::cout << "  encoded : " << h.ToHex() << "\n";
    std::cout << "  expected: " << expected << "\n";
    if (h.ToHex() != expected)
    {
        std::cout << "  *** MISMATCH ***\n";
        ok = false;
    }
    else
    {
        std::cout << "  byte-for-byte match: PASS\n";
    }

    // round trip
    Ptr<Packet> p = Create<Packet>(64);
    p->AddHeader(h);
    TcrhHeader back;
    p->RemoveHeader(back);
    bool rt = (back.GetSegmentsLeft() == h.GetSegmentsLeft() &&
               back.GetNumHops() == h.GetNumHops() &&
               back.GetEpochMs() == h.GetEpochMs() &&
               back.GetSerializedSize() == h.GetSerializedSize());
    std::cout << "\n  round trip: " << (rt ? "PASS" : "*** FAIL ***") << "\n";
    if (!rt)
    {
        ok = false;
    }

    // cumulative arrival deadlines
    std::cout << "\n  cumulative arrival deadlines (epoch = 1000 ms):\n";
    TcrhHeader w;
    w.SetPath({2, 3, 7}, {6, 7, 8}, 1000);
    std::cout << "    at the source            : " << w.GetArrivalDeadlineMs()
              << " ms\n";
    uint32_t expectDl[] = {1006, 1013, 1021};
    uint32_t k = 0;
    while (w.GetSegmentsLeft() > 0)
    {
        w.SetSegmentsLeft(w.GetSegmentsLeft() - 1);
        uint32_t dl = w.GetArrivalDeadlineMs();
        bool good = (dl == expectDl[k]);
        std::cout << "    after hop to SID " << std::setw(2) << w.GetCurrentSid()
                  << "       : " << dl << " ms"
                  << (good ? "   (correct)" : "   *** WRONG ***") << "\n";
        if (!good)
        {
            ok = false;
        }
        k++;
    }
    std::cout << "    Budgets accumulate, so time lost at one hop can be made\n"
                 "    up at a later, faster hop.\n";

    // the deviation flag
    std::cout << "\n  Deviation_Flag:\n";
    TcrhHeader f;
    f.SetPath({2, 3}, {5, 5}, 0);
    std::cout << "    before : flags=0x" << std::hex << +f.GetFlags() << std::dec
              << "  deviated=" << (f.IsDeviated() ? "yes" : "no") << "\n";
    f.SetDeviation();
    std::cout << "    after  : flags=0x" << std::hex << +f.GetFlags() << std::dec
              << "  deviated=" << (f.IsDeviated() ? "yes" : "no") << "\n";
    if (!f.IsDeviated())
    {
        ok = false;
    }

    // exact deadline arithmetic (bug #18): each of these failed with the
    // first version's floored milliseconds and per-hop rounding
    std::cout << "\n  exact deadline arithmetic (no ms truncation):\n";
    auto check = [&ok](const std::string& what, bool good) {
        std::cout << "    " << what << (good ? "   (correct)" : "   *** WRONG ***") << "\n";
        if (!good)
        {
            ok = false;
        }
    };
    check("sent at 1000.7 ms -> Epoch_Base 1001 (rounded up)",
          EpochMsCeil(MicroSeconds(1000700)) == 1001);
    check("sent at exactly 1000 ms -> Epoch_Base 1000",
          EpochMsCeil(MilliSeconds(1000)) == 1000);
    check("0.5 ms after a 1006 ms deadline is late", IsLate(MicroSeconds(1006500), 1006));
    check("1 ns after the deadline is late", IsLate(NanoSeconds(1006000001), 1006));
    check("exactly at the deadline is on time", !IsLate(MilliSeconds(1006), 1006));
    check("3 hops of 20.4 ms -> deltas 21,20,21 (deadlines 21/41/62 >= 20.4/40.8/61.2)",
          EncodeDeltasMs({20400, 20400, 20400}) == std::vector<uint8_t>({21, 20, 21}));
    check("20 ms x 1.1 -> 22 ms per hop, not 23 (22.000000000000004 is 22000 us)",
          EncodeDeltasMs({MsToUs(20.0 * 1.1), MsToUs(20.0 * 1.1)}) ==
              std::vector<uint8_t>({22, 22}));

    return ok;
}

// ===========================================================================
//  PART B -- what the deadlines cost
// ===========================================================================

static void
RunSizeComparison(const std::string& csv)
{
    std::cout << "\n=== PART B: the byte cost of adding time ===\n\n";
    std::cout << "  " << std::setw(6) << "hops" << std::setw(10) << "CRH-16"
              << std::setw(10) << "T-CRH" << std::setw(14) << "cost of time"
              << std::setw(12) << "SRv6 SRH" << std::setw(16)
              << "T-CRH vs SRv6" << "\n";

    std::ofstream out;
    if (!csv.empty())
    {
        out.open(csv);
        out << "hops,crh16_bytes,tcrh_bytes,srh_bytes\n";
    }

    for (uint32_t n = 1; n <= 20; ++n)
    {
        uint32_t c = Crh16Size(n), t = TcrhSize(n), s = SrhSize(n);
        if (n <= 10 || n == 15 || n == 20)
        {
            std::cout << "  " << std::setw(6) << n << std::setw(9) << c << "B"
                      << std::setw(9) << t << "B" << std::setw(10) << "+"
                      << std::setw(2) << (t - c) << "B" << std::setw(11) << s << "B"
                      << std::setw(15) << std::fixed << std::setprecision(1)
                      << (double)s / t << "x\n";
        }
        if (out.is_open())
        {
            out << n << "," << c << "," << t << "," << s << "\n";
        }
    }
    if (out.is_open())
    {
        out.close();
        std::cout << "\n  wrote " << csv << "\n";
    }
}

// ===========================================================================
//  PART C helpers -- scoring the paired runs (bug #21)
// ===========================================================================

/** Wilson 95% interval for x successes out of n, in percent ({nan, nan} if n = 0). */
static std::pair<double, double>
Wilson95(uint32_t x, uint32_t n)
{
    if (n == 0)
    {
        return {std::nan(""), std::nan("")};
    }
    const double z = 1.959963984540054;
    const double p = static_cast<double>(x) / n;
    const double z2n = z * z / n;
    const double centre = (p + z2n / 2) / (1 + z2n);
    const double half = z * std::sqrt(p * (1 - p) / n + z2n / (4.0 * n)) / (1 + z2n);
    // the bounds are exactly 0 and 100 at x = 0 and x = n (avoid 2e-17 rounding noise)
    const double lo = (x == 0) ? 0.0 : std::max(0.0, centre - half);
    const double hi = (x == n) ? 1.0 : std::min(1.0, centre + half);
    return {100.0 * lo, 100.0 * hi};
}

/** 100 x / n, or nan when there is nothing to divide by. */
static double
Pct(uint32_t x, uint32_t n)
{
    return n ? 100.0 * x / n : std::nan("");
}

/**
 * One packet of traffic, sent into all three networks at the same instant.
 * The forwarding jitter for every sending hop is drawn ONCE here, from one
 * random stream, so a packet meets exactly the same jitter in every network
 * (common random numbers). Only the fault differs between the networks, which
 * is what lets a flag be attributed to the fault.
 */
static void
SendToAllNetworks(std::vector<Ptr<TcrhForwarder>> sources,
                  Ptr<ExponentialRandomVariable> jitterRv,
                  uint32_t pid,
                  std::vector<uint16_t> path,
                  std::vector<double> predictedMs,
                  double slack,
                  uint32_t slackIndex,
                  uint32_t payload)
{
    std::vector<double> jitter(path.size()); // the source and every transit node send once
    for (double& j : jitter)
    {
        j = jitterRv->GetValue();
    }
    for (auto& src : sources)
    {
        src->SendWithSchedule(pid, path, predictedMs, slack, slackIndex, jitter, payload);
    }
}

// ===========================================================================
//  main
// ===========================================================================

int
main(int argc, char* argv[])
{
    uint32_t payload = 100;
    double normalDelayMs = 20.0;
    double degradedDelayMs = 45.0;
    uint32_t packetsPerPoint = 60;
    double jitterMs = 2.0;
    std::string sizeCsv = "tcrh_sizes_v09.csv";
    std::string sweepCsv = "tcrh_sweep_v09.csv";
    std::string packetCsv = "";
    // Operating point rule, the same as Python's Experiment 1 (P1 review): the
    // highest paired detection whose false-alarm rate is at most fprMaxPct,
    // counted only if that detection is at least minDetectionPct.
    double fprMaxPct = 1.0;
    double minDetectionPct = 1.0;

    CommandLine cmd(__FILE__);
    cmd.AddValue("payload", "Payload bytes", payload);
    cmd.AddValue("degraded",
                 "Delay of the degraded link in ms (20 = the normal delay = a null fault)",
                 degradedDelayMs);
    cmd.AddValue("packets",
                 "Packets per slack value (each one goes through all three networks)",
                 packetsPerPoint);
    cmd.AddValue("jitterMs", "Mean of the exponential per-hop forwarding jitter in ms", jitterMs);
    cmd.AddValue("sizeCsv", "Size comparison output", sizeCsv);
    cmd.AddValue("sweepCsv", "Slack sweep output", sweepCsv);
    cmd.AddValue("packetCsv", "Optional per-packet output (one row per packet and network)", packetCsv);
    cmd.AddValue("fprMaxPct", "Operating point: largest allowed false-alarm rate (%)", fprMaxPct);
    cmd.AddValue("minDetectionPct",
                 "Operating point: smallest paired detection that counts (%)",
                 minDetectionPct);
    cmd.Parse(argc, argv);

    if (!RunSelfTest())
    {
        std::cout << "\nSELF-TEST FAILED -- stopping.\n";
        return 1;
    }
    RunSizeComparison(sizeCsv);

    // ---------------- the scheduled path: the 5-hop route ------------------
    std::vector<uint16_t> path = {3, 4, 5, 6, 7};     // n2, n3, n4, n5, n6
    std::vector<double> predicted(5, normalDelayMs);   // 20 ms per hop: the link delay
    std::vector<double> slacks = {1.0, 1.1, 1.2, 1.3, 1.5, 1.75, 2.0, 2.5, 3.0};

    // The slowed link is n3-n4, so the first node whose arrival can show the
    // fault is n4 (SID 5): hop index 3 on this path. A flag the fault caused
    // can only be raised there or later.
    const uint32_t faultHop =
        static_cast<uint32_t>(std::find(path.begin(), path.end(), 5) - path.begin()) + 1;

    // traffic timing: one packet every 50 ms from t = 1 s, as before
    const Time firstSend = Seconds(1.0);
    const Time spacing = MilliSeconds(50);
    const uint32_t totalPackets = packetsPerPoint * slacks.size();
    const Time stopTime = firstSend + spacing * static_cast<int64_t>(totalPackets) + Seconds(2.0);
    const Time faultOnset = MilliSeconds(500); // before the first packet

    // ---------------- topology: three copies of the seven nodes of Assessment 7
    //
    // One copy per network (healthy / fault / null-fault). They share nothing
    // but the simulator clock and the traffic generator below.
    PointToPointHelper p2p;
    p2p.SetDeviceAttribute("DataRate", StringValue("10Mbps"));
    std::ostringstream d;
    d << normalDelayMs << "ms";
    p2p.SetChannelAttribute("Delay", StringValue(d.str()));

    struct Link { uint32_t a, b; };
    std::vector<Link> links = {
        {0, 1}, {1, 6},
        {0, 2}, {2, 3}, {3, 4}, {4, 5}, {5, 6},
    };

    InternetStackHelper stack;
    Ipv4AddressHelper addr;
    std::vector<std::vector<Ptr<TcrhForwarder>>> apps(N_ARMS);
    std::vector<Ptr<Channel>> slowChannel(N_ARMS);

    for (uint32_t arm = 0; arm < N_ARMS; ++arm)
    {
        NodeContainer nodes;
        nodes.Create(7);
        stack.Install(nodes);

        std::map<uint32_t, std::map<uint32_t, Ipv4Address>> addrOf;
        for (size_t i = 0; i < links.size(); ++i)
        {
            NetDeviceContainer dev = p2p.Install(nodes.Get(links[i].a), nodes.Get(links[i].b));
            std::ostringstream base;
            base << "10." << (arm + 1) << "." << (i + 1) << ".0";
            addr.SetBase(base.str().c_str(), "255.255.255.0");
            Ipv4InterfaceContainer ifc = addr.Assign(dev);
            addrOf[links[i].a][links[i].b] = ifc.GetAddress(1);
            addrOf[links[i].b][links[i].a] = ifc.GetAddress(0);

            // remember the n3-n4 channel so we can slow it down later
            if (links[i].a == 3 && links[i].b == 4)
            {
                slowChannel[arm] = dev.Get(0)->GetChannel();
            }
        }

        for (uint32_t i = 0; i < nodes.GetN(); ++i)
        {
            Ptr<TcrhForwarder> a = CreateObject<TcrhForwarder>();
            nodes.Get(i)->AddApplication(a);
            a->SetArm(static_cast<Arm>(arm));
            a->SetStartTime(Seconds(0.0));
            a->SetStopTime(stopTime);
            apps[arm].push_back(a);
        }
        for (const Link& l : links)
        {
            apps[arm][l.a]->AddFibEntry(l.b + 1, addrOf[l.a][l.b]);
            apps[arm][l.b]->AddFibEntry(l.a + 1, addrOf[l.b][l.a]);
        }
        // where the fail-safe should send a packet whose schedule has broken
        Ipv4Address finalDest = addrOf[5][6];
        for (auto& a : apps[arm])
        {
            a->SetFinalDestination(finalDest);
        }
    }

    Ipv4GlobalRoutingHelper::PopulateRoutingTables();

    // ---- slow the n3-n4 link down. The link is still UP, so a link-state
    //      check sees nothing wrong. Only a deadline can catch this.
    //      The null-fault network goes through the same motions with the
    //      normal delay (degradation factor 1.0): nothing physical changes.
    for (uint32_t arm : {ARM_FAULT, ARM_NULL_FAULT})
    {
        double ms = (arm == ARM_FAULT) ? degradedDelayMs : normalDelayMs;
        Ptr<Channel> ch = slowChannel[arm];
        Simulator::Schedule(faultOnset, [ch, ms, arm]() {
            std::ostringstream v;
            v << ms << "ms";
            ch->SetAttribute("Delay", StringValue(v.str()));
            std::cout << "\n  [t=" << Simulator::Now().GetSeconds() << "s] " << ARM_NAMES[arm]
                      << " network: link n3-n4 set to " << ms
                      << " ms (still up, still forwarding)\n";
        });
    }

    // ---- traffic: identical in the three networks. The jitter stream is
    //      fixed, so the draws depend only on the seed and --RngRun.
    Ptr<ExponentialRandomVariable> jitterRv = CreateObject<ExponentialRandomVariable>();
    jitterRv->SetAttribute("Mean", DoubleValue(jitterMs));
    jitterRv->SetStream(0);

    std::vector<Ptr<TcrhForwarder>> sources;
    for (uint32_t arm = 0; arm < N_ARMS; ++arm)
    {
        sources.push_back(apps[arm][0]);
    }

    std::vector<std::vector<uint32_t>> idsBySlack(slacks.size());
    uint32_t pid = 1;
    Time t = firstSend;
    for (uint32_t si = 0; si < slacks.size(); ++si)
    {
        for (uint32_t k = 0; k < packetsPerPoint; ++k)
        {
            Simulator::Schedule(t,
                                &SendToAllNetworks,
                                sources,
                                jitterRv,
                                pid,
                                path,
                                predicted,
                                slacks[si],
                                si,
                                payload);
            idsBySlack[si].push_back(pid);
            pid++;
            t += spacing;
        }
    }

    Simulator::Stop(stopTime);
    Simulator::Run();

    // ---------------------------------------------------------------- results
    std::cout << "\n=== PART C: does the deadline catch a slow link? ===\n\n";
    std::cout << "  Same packets, same jitter, three networks (RngRun "
              << RngSeedManager::GetRun() << ", " << packetsPerPoint << " packets per S,\n"
              << "  n3-n4 slowed from " << normalDelayMs << " to " << degradedDelayMs
              << " ms in the fault network).\n"
              << "  false alarms : flagged in the healthy network\n"
              << "  detections   : flagged WITH the fault and NOT without it, out of the\n"
              << "                 packets the healthy network did not flag\n"
              << "  old score    : every flag in the fault network (the v0 metric, confounded)\n"
              << "  null control : detections when the 'fault' changes nothing (must be 0)\n\n";

    std::cout << "  " << std::setw(6) << "S" << std::setw(14) << "false alarms" << std::setw(28)
              << "detections [95% CI]" << std::setw(12) << "old score" << std::setw(14)
              << "null control" << std::setw(12) << "delivered" << "\n";

    std::ofstream sw;
    if (!sweepCsv.empty())
    {
        sw.open(sweepCsv);
        sw << "slack,packets,fp_flagged,fp_pct,fp_ci_lo,fp_ci_hi,"
              "fault_flagged,raw_detect_pct,clean_without_fault,attributed,"
              "detect_attributed_pct,detect_ci_lo,detect_ci_hi,attributed_of_all_pct,"
              "attributed_before_fault_hop,unflagged_by_fault,"
              "null_flagged,null_raw_detect_pct,null_attributed,null_differs,"
              "delivered_healthy_pct,delivered_fault_pct,fallback_fault_pct,"
              "mean_latency_healthy_ms,mean_latency_fault_ms,"
              "degraded_ms,normal_ms,jitter_mean_ms,rng_seed,rng_run\n";
    }

    // Operating point (Neyman-Pearson, as Python Experiment 1): highest paired
    // detection with false alarms <= fprMaxPct and detection >= minDetectionPct;
    // ties go to fewer false alarms, then to the larger slack.
    bool haveBest = false;
    double best = 0.0, bestDet = 0.0, bestFp = 0.0;
    // Youden J (detection minus false alarms) is printed for continuity with
    // Assessment 8 only: it recommended S = 1.30 at 7 % false alarms.
    double youden = slacks[0];
    double youdenJ = -1e9;
    bool anyDetection = false;
    for (uint32_t si = 0; si < slacks.size(); ++si)
    {
        uint32_t n = 0, fp = 0, faultFlagged = 0, attributed = 0, attributedEarly = 0;
        uint32_t unflagged = 0, nullFlagged = 0, nullAttributed = 0, nullDiffers = 0;
        uint32_t delivHealthy = 0, delivFault = 0, fallbackFault = 0;
        double latHealthy = 0, latFault = 0;
        for (uint32_t id : idsBySlack[si])
        {
            const Record& h = g_records[ARM_HEALTHY][id];
            const Record& f = g_records[ARM_FAULT][id];
            const Record& z = g_records[ARM_NULL_FAULT][id];
            n++;
            fp += h.deviated;
            faultFlagged += f.deviated;
            if (f.deviated && !h.deviated)
            {
                attributed++; // the fault, and only the fault, made this packet late
                attributedEarly += (f.devHop < faultHop);
            }
            unflagged += (!f.deviated && h.deviated);
            nullFlagged += z.deviated;
            nullAttributed += (z.deviated && !h.deviated);
            // the null-fault network must reproduce the healthy one exactly
            nullDiffers += (z.deviated != h.deviated || z.devHop != h.devHop ||
                            z.delivered != h.delivered || z.latencyMs != h.latencyMs);
            if (h.delivered)
            {
                delivHealthy++;
                latHealthy += h.latencyMs;
            }
            if (f.delivered)
            {
                delivFault++;
                latFault += f.latencyMs;
            }
            fallbackFault += f.viaFallback;
        }
        const uint32_t clean = n - fp;
        const double fpPct = Pct(fp, n);
        const double detPct = Pct(attributed, clean);
        const auto fpCi = Wilson95(fp, n);
        const auto detCi = Wilson95(attributed, clean);

        std::ostringstream ci;
        ci << std::fixed << std::setprecision(1) << detPct << " % [" << detCi.first << ", "
           << detCi.second << "]";
        std::cout << "  " << std::setw(6) << std::fixed << std::setprecision(2) << slacks[si]
                  << std::setw(12) << std::setprecision(1) << fpPct << " %" << std::setw(28)
                  << ci.str() << std::setw(10) << Pct(faultFlagged, n) << " %" << std::setw(12)
                  << Pct(nullAttributed, n) << " %" << std::setw(10) << Pct(delivFault, n)
                  << " %\n";

        if (sw.is_open())
        {
            sw << std::defaultfloat << std::setprecision(6) << slacks[si] << "," << n << ","
               << fp << "," << fpPct << "," << fpCi.first << "," << fpCi.second << ","
               << faultFlagged << "," << Pct(faultFlagged, n) << "," << clean << ","
               << attributed << "," << detPct << "," << detCi.first << "," << detCi.second
               << "," << Pct(attributed, n) << "," << attributedEarly << "," << unflagged << ","
               << nullFlagged << "," << Pct(nullFlagged, n) << "," << nullAttributed << ","
               << nullDiffers << "," << Pct(delivHealthy, n) << "," << Pct(delivFault, n) << ","
               << Pct(fallbackFault, n) << ","
               << (delivHealthy ? latHealthy / delivHealthy : std::nan("")) << ","
               << (delivFault ? latFault / delivFault : std::nan("")) << ","
               << degradedDelayMs << "," << normalDelayMs << "," << jitterMs << ","
               << RngSeedManager::GetSeed() << "," << RngSeedManager::GetRun() << "\n";
        }

        anyDetection = anyDetection || attributed > 0;
        if (!std::isnan(detPct) && fpPct <= fprMaxPct && detPct >= minDetectionPct &&
            detPct > 0.0)
        {
            const bool better = !haveBest || detPct > bestDet ||
                                (detPct == bestDet && (fpPct < bestFp ||
                                                       (fpPct == bestFp && slacks[si] > best)));
            if (better)
            {
                haveBest = true;
                best = slacks[si];
                bestDet = detPct;
                bestFp = fpPct;
            }
        }
        if (!std::isnan(detPct) && detPct - fpPct > youdenJ)
        {
            youdenJ = detPct - fpPct;
            youden = slacks[si];
        }
    }
    if (sw.is_open())
    {
        sw.close();
        std::cout << "\n  wrote " << sweepCsv << "\n";
    }

    if (!packetCsv.empty())
    {
        std::ofstream pk(packetCsv);
        pk << "network,packet,slack,flagged,dev_hop,delivered,via_fallback,latency_ms\n";
        for (uint32_t arm = 0; arm < N_ARMS; ++arm)
        {
            for (const auto& kv : g_records[arm])
            {
                const Record& r = kv.second;
                pk << ARM_NAMES[arm] << "," << kv.first << "," << r.slack << "," << r.deviated
                   << "," << r.devHop << "," << r.delivered << "," << r.viaFallback << ","
                   << std::setprecision(9) << r.latencyMs << std::setprecision(6) << "\n";
            }
        }
        std::cout << "  wrote " << packetCsv << "\n";
    }

    if (anyDetection)
    {
        std::cout << std::fixed << std::setprecision(2);
        if (haveBest)
        {
            std::cout << "\n  Operating point for this fault (highest paired detection with false"
                         " alarms <= "
                      << fprMaxPct << " % and detection >= " << minDetectionPct << " %): S = "
                      << best << " (detection " << std::setprecision(1) << bestDet
                      << " %, false alarms " << bestFp << " %)\n";
        }
        else
        {
            std::cout << "\n  No operating point: no slack keeps false alarms <= " << fprMaxPct
                      << " % and detects >= " << minDetectionPct << " % of this fault.\n";
        }
        std::cout << "  (one 7-node path, one jitter model, one fault size: not a general answer;"
                     " the slack must be chosen per fault size)\n"
                  << "  Youden J (detections minus false alarms), for continuity with"
                     " Assessment 8 only, NOT a recommendation: S = "
                  << std::setprecision(2) << youden << "\n";
    }
    else
    {
        std::cout << "\n  The fault was not detected at any slack (a null fault, or too small for"
                     " this jitter):\n  there is no operating point to choose.\n";
    }

    Simulator::Destroy();
    return 0;
}
