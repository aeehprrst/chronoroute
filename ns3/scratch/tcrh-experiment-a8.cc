/*
 * tcrh-experiment-a8.cc -- THE ORIGINAL ASSESSMENT 8 PROGRAM, KEPT AS EVIDENCE.
 *
 * This is scratch/tcrh-experiment.cc exactly as committed in the ns-3 tree
 * (commit 6314c8a, "Assessments 6-8"), BEFORE the Phase 1 fixes for bugs #18
 * and #21. It still has the confounded detection score and the integer-ms
 * deadline checks. Do not use its numbers; it exists so that
 * results/legacy-v0.9/ns3/tcrh_sweep/tcrh_sweep_v09_oldcode_nullfault.csv
 * (the old score "detecting" a fault that does nothing) can be regenerated:
 *
 *   build/scratch/ns3.44-tcrh-experiment-a8-default --degraded=20 \
 *       --sizeCsv=/tmp/s.csv --sweepCsv=tcrh_sweep_v09_oldcode_nullfault.csv
 *
 * (ns3/run_tcrh_sweep.py does this.) The only change from 6314c8a is the
 * header's TypeId name: the chronoroute contrib module registers
 * "ns3::TcrhHeader", and ns-3 links every scratch program against every
 * module, so two classes with that TypeId name abort at start-up. The name
 * is not used in any output.
 */

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
 */

#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"

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
        static TypeId tid = TypeId("ns3::TcrhA8Header") // was "ns3::TcrhHeader"; see the note at the top
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
//  PART 2 -- Trace records
// ===========================================================================

struct Record
{
    double slack = 0;
    bool degradedPhase = false;
    bool deviated = false;
    bool delivered = false;
    bool viaFallback = false;
    double latencyMs = 0;
    uint32_t hops = 0;
};

static std::map<uint32_t, Record> g_records;
static uint32_t g_nextId = 1;

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
          m_port(7777)
    {
        m_jitter = CreateObject<ExponentialRandomVariable>();
        m_jitter->SetAttribute("Mean", DoubleValue(2.0)); // ms
    }

    void AddFibEntry(uint16_t sid, Ipv4Address nextHop) { m_fib[sid] = nextHop; }
    void SetFinalDestination(Ipv4Address a) { m_finalDest = a; }

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
     * project, and Part D sweeps it.
     */
    void SendWithSchedule(const std::vector<uint16_t>& sids,
                          const std::vector<double>& predictedMs,
                          double slack,
                          bool degradedPhase,
                          uint32_t payloadBytes)
    {
        uint32_t pid = g_nextId++;

        std::vector<uint8_t> deltas;
        for (double d : predictedMs)
        {
            double budget = d * slack;
            deltas.push_back(static_cast<uint8_t>(
                std::min(255.0, std::max(1.0, budget + 0.5))));
        }

        uint32_t nowMs = static_cast<uint32_t>(Simulator::Now().GetMilliSeconds());

        TcrhHeader h;
        h.SetPath(sids, deltas, nowMs);

        Record r;
        r.slack = slack;
        r.degradedPhase = degradedPhase;
        g_records[pid] = r;

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

        Record& rec = g_records[pid];
        uint32_t nowMs = static_cast<uint32_t>(Simulator::Now().GetMilliSeconds());

        // ---- STEP 0 (NEW): have I arrived later than my deadline? ----
        //
        // This is the whole contribution. One unsigned comparison, no routing
        // table, no neighbour state. A link that is still up but has slowed
        // down is invisible to a link-state check and visible here.
        if (!h.IsDeviated() && nowMs > h.GetArrivalDeadlineMs())
        {
            h.SetDeviation();
            rec.deviated = true;
        }

        // ---- STEP 1: Segments Left == 0 means this packet is for me ----
        if (h.GetSegmentsLeft() == 0)
        {
            rec.delivered = true;
            rec.latencyMs = nowMs - h.GetEpochMs();
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
        rec.hops++;
        packet->AddHeader(h);
        SendTo(packet, e->second, m_jitter->GetValue());
    }

    /**
     * Send after a small random delay, which stands in for the queueing and
     * processing jitter a real router adds. Without it every hop would take
     * exactly the predicted time, the deadline would never be missed by
     * accident, and the slack sweep in Part D would be a meaningless
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
    Ptr<ExponentialRandomVariable> m_jitter;
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
//  main
// ===========================================================================

int
main(int argc, char* argv[])
{
    uint32_t payload = 100;
    double normalDelayMs = 20.0;
    double degradedDelayMs = 45.0;
    uint32_t packetsPerPoint = 60;
    std::string sizeCsv = "tcrh_sizes.csv";
    std::string sweepCsv = "tcrh_sweep.csv";

    CommandLine cmd(__FILE__);
    cmd.AddValue("payload", "Payload bytes", payload);
    cmd.AddValue("degraded", "Delay of the degraded link in ms", degradedDelayMs);
    cmd.AddValue("packets", "Packets per slack value per phase", packetsPerPoint);
    cmd.AddValue("sizeCsv", "Size comparison output", sizeCsv);
    cmd.AddValue("sweepCsv", "Slack sweep output", sweepCsv);
    cmd.Parse(argc, argv);

    if (!RunSelfTest())
    {
        std::cout << "\nSELF-TEST FAILED -- stopping.\n";
        return 1;
    }
    RunSizeComparison(sizeCsv);

    // ---------------- topology: the same seven nodes as Assessment 7 -------
    NodeContainer nodes;
    nodes.Create(7);

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
    stack.Install(nodes);

    Ipv4AddressHelper addr;
    std::map<uint32_t, std::map<uint32_t, Ipv4Address>> addrOf;
    Ptr<Channel> degradedChannel;

    for (size_t i = 0; i < links.size(); ++i)
    {
        NetDeviceContainer dev = p2p.Install(nodes.Get(links[i].a), nodes.Get(links[i].b));
        std::ostringstream base;
        base << "10.1." << (i + 1) << ".0";
        addr.SetBase(base.str().c_str(), "255.255.255.0");
        Ipv4InterfaceContainer ifc = addr.Assign(dev);
        addrOf[links[i].a][links[i].b] = ifc.GetAddress(1);
        addrOf[links[i].b][links[i].a] = ifc.GetAddress(0);

        // remember the n3-n4 channel so we can slow it down later
        if (links[i].a == 3 && links[i].b == 4)
        {
            degradedChannel = dev.Get(0)->GetChannel();
        }
    }

    Ipv4GlobalRoutingHelper::PopulateRoutingTables();

    std::vector<Ptr<TcrhForwarder>> apps;
    for (uint32_t i = 0; i < nodes.GetN(); ++i)
    {
        Ptr<TcrhForwarder> a = CreateObject<TcrhForwarder>();
        nodes.Get(i)->AddApplication(a);
        a->SetStartTime(Seconds(0.0));
        a->SetStopTime(Seconds(400.0));
        apps.push_back(a);
    }
    for (const Link& l : links)
    {
        apps[l.a]->AddFibEntry(l.b + 1, addrOf[l.a][l.b]);
        apps[l.b]->AddFibEntry(l.a + 1, addrOf[l.b][l.a]);
    }
    // where the fail-safe should send a packet whose schedule has broken
    Ipv4Address finalDest = addrOf[5][6];
    for (auto& a : apps)
    {
        a->SetFinalDestination(finalDest);
    }

    // ---------------- the scheduled path: the 5-hop route ------------------
    std::vector<uint16_t> path = {3, 4, 5, 6, 7};     // n2, n3, n4, n5, n6
    std::vector<double> predicted(5, normalDelayMs);   // 5 ms per hop

    std::vector<double> slacks = {1.0, 1.1, 1.2, 1.3, 1.5, 1.75, 2.0, 2.5, 3.0};

    double t = 1.0;
    // ---- phase 1: healthy network. Any deviation here is a FALSE POSITIVE.
    for (double s : slacks)
    {
        for (uint32_t k = 0; k < packetsPerPoint; ++k)
        {
            Simulator::Schedule(Seconds(t),
                                &TcrhForwarder::SendWithSchedule,
                                apps[0], path, predicted, s, false, payload);
            t += 0.05;
        }
    }

    // ---- slow the n3-n4 link down. The link is still UP, so a link-state
    //      check sees nothing wrong. Only a deadline can catch this.
    double switchTime = t + 1.0;
    Simulator::Schedule(Seconds(switchTime), [degradedChannel, degradedDelayMs]() {
        std::ostringstream v;
        v << degradedDelayMs << "ms";
        degradedChannel->SetAttribute("Delay", StringValue(v.str()));
        std::cout << "\n  [t=" << Simulator::Now().GetSeconds()
                  << "s] link n3-n4 slowed to " << degradedDelayMs
                  << " ms (still up, still forwarding)\n";
    });

    t = switchTime + 1.0;
    // ---- phase 2: degraded network. A deviation here is a CORRECT DETECTION.
    for (double s : slacks)
    {
        for (uint32_t k = 0; k < packetsPerPoint; ++k)
        {
            Simulator::Schedule(Seconds(t),
                                &TcrhForwarder::SendWithSchedule,
                                apps[0], path, predicted, s, true, payload);
            t += 0.05;
        }
    }

    Simulator::Stop(Seconds(t + 2.0));
    Simulator::Run();

    // ---------------------------------------------------------------- results
    std::cout << "\n=== PART C: does the deadline catch a slow link? ===\n\n";

    std::map<double, std::pair<uint32_t, uint32_t>> falsePos; // flagged, total
    std::map<double, std::pair<uint32_t, uint32_t>> detected;
    std::map<double, uint32_t> deliveredHealthy, deliveredDegraded;

    for (auto& kv : g_records)
    {
        Record& r = kv.second;
        auto& tgt = r.degradedPhase ? detected[r.slack] : falsePos[r.slack];
        tgt.second++;
        if (r.deviated)
        {
            tgt.first++;
        }
        if (r.delivered)
        {
            (r.degradedPhase ? deliveredDegraded[r.slack] : deliveredHealthy[r.slack])++;
        }
    }

    std::cout << "  " << std::setw(7) << "slack" << std::setw(20)
              << "false positives" << std::setw(18) << "detections"
              << std::setw(14) << "delivered" << "\n";
    std::cout << "  " << std::setw(7) << "S" << std::setw(20) << "(healthy link)"
              << std::setw(18) << "(slow link)" << std::setw(14) << "(degraded)"
              << "\n";

    std::ofstream sw;
    if (!sweepCsv.empty())
    {
        sw.open(sweepCsv);
        sw << "slack,false_positive_pct,detection_pct,delivered_pct\n";
    }

    for (double s : slacks)
    {
        double fp = falsePos[s].second
                        ? 100.0 * falsePos[s].first / falsePos[s].second : 0;
        double dt = detected[s].second
                        ? 100.0 * detected[s].first / detected[s].second : 0;
        double dl = detected[s].second
                        ? 100.0 * deliveredDegraded[s] / detected[s].second : 0;

        std::cout << "  " << std::setw(7) << std::fixed << std::setprecision(2) << s
                  << std::setw(18) << std::setprecision(1) << fp << " %"
                  << std::setw(16) << dt << " %" << std::setw(12) << dl << " %\n";

        if (sw.is_open())
        {
            sw << s << "," << fp << "," << dt << "," << dl << "\n";
        }
    }
    if (sw.is_open())
    {
        sw.close();
        std::cout << "\n  wrote " << sweepCsv << "\n";
    }

    // pick the operating point the same way the Python study did
    double best = slacks[0];
    double bestJ = -1e9;
    for (double s : slacks)
    {
        double fp = falsePos[s].second
                        ? 100.0 * falsePos[s].first / falsePos[s].second : 0;
        double dt = detected[s].second
                        ? 100.0 * detected[s].first / detected[s].second : 0;
        if (dt - fp > bestJ)
        {
            bestJ = dt - fp;
            best = s;
        }
    }
    std::cout << "\n  Best operating point (max detections minus false positives): S = "
              << std::setprecision(2) << best << "\n";

    Simulator::Destroy();
    return 0;
}