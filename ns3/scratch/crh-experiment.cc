/*
 * crh-experiment.cc
 * -----------------
 * An implementation of the IPv6 Compact Routing Header, CRH-16, as defined in
 * RFC 9631 (August 2024), on top of ns-3.
 *
 * WHY THIS PROTOCOL
 * -----------------
 * CRH-16 is the standard protocol my ChronoRoute project extends. ChronoRoute
 * adds a per-hop time deadline to each segment; everything else -- the header
 * layout, the segment identifier list, the Segments Left index, the
 * forwarding-table lookup -- is RFC 9631 exactly as written. So implementing
 * CRH-16 correctly is the foundation the whole project stands on, and it is
 * what this assessment demonstrates.
 *
 * WHAT CRH DOES
 * -------------
 * Normal IP forwarding lets each router decide the next hop. Source routing
 * inverts that: the SOURCE writes the whole path into the packet, and routers
 * just follow it. CRH is the compact way to do this in IPv6 -- each hop costs
 * 2 bytes instead of the 16 bytes SRv6 spends on a full IPv6 address.
 *
 * HEADER FORMAT (RFC 9631 Section 3)
 * ----------------------------------
 *    0               1               2               3
 *    0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
 *   +---------------+---------------+---------------+---------------+
 *   |  Next Header  |  Hdr Ext Len  | Routing Type  | Segments Left |
 *   +---------------+---------------+---------------+---------------+
 *   |                       SID[0] | SID[1] | ...                   |
 *   +---------------------------------------------------------------+
 *                   (zero-padded to a 64-bit boundary)
 *
 *   Routing Type = 5 for CRH-16 (6 for CRH-32).
 *   Each SID is 16 bits and identifies an entry in that router's CRH-FIB.
 *   SIDs are stored in REVERSE order, so SID[0] is the LAST hop.
 *   The CRH MUST end on a 64-bit boundary, zero-padded if necessary.
 *
 * FORWARDING ALGORITHM (RFC 9631 Section 5)
 * -----------------------------------------
 *   1. if Segments Left == 0, this packet is for me -- deliver it
 *   2. compute L, the minimum CRH length; if L > Hdr Ext Len, discard
 *   3. decrement Segments Left
 *   4. current SID = SID[Segments Left]           <-- decrement THEN index
 *   5. look up the current SID in the CRH-FIB
 *   6. if not found, discard; otherwise forward to that interface
 *
 * Build:  copy to ~/ns-3-dev/scratch/ and run ./ns3 build
 * Run:    ./ns3 run "scratch/crh-experiment"
 *
 * v0.9 (2026-10-10, ChronoRoute Phase 1):
 *   - bug #20: the path trace now records the node that RECEIVED the packet
 *     (it used to record, at the sender, the node the SID was meant to reach,
 *     so the path check compared the intended path with itself). --miswire=1
 *     plants a wrong CRH-FIB entry to show that the check can now fail.
 *   - latency is reported exactly instead of floored to whole milliseconds.
 *   - the header's TypeId is ns3::CrhExperimentHeader, because the chronoroute
 *     contrib module now owns ns3::CrhHeader.
 *   - default outputs are crh_sizes_v09.csv and crh_paths_v09.csv, so the
 *     Assessment 7 CSVs are never overwritten.
 */

#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"

#include <iomanip>
#include <iostream>
#include <map>
#include <sstream>
#include <vector>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("CrhExperiment");

// ===========================================================================
//  PART 1 -- The CRH-16 header (RFC 9631)
// ===========================================================================

/** Routing Type value assigned by IANA to CRH-16 (RFC 9631). */
static const uint8_t CRH16_ROUTING_TYPE = 5;
/** Routing Type value assigned to CRH-32, for the size comparison. */
static const uint8_t CRH32_ROUTING_TYPE = 6;

class CrhHeader : public Header
{
  public:
    CrhHeader()
        : m_nextHeader(17), // 17 = UDP
          m_segmentsLeft(0)
    {
    }

    static TypeId GetTypeId()
    {
        // Not "ns3::CrhHeader": the chronoroute contrib module (Phase 1)
        // registers that name, and ns-3 links every scratch program against
        // every module, so two classes with one TypeId name abort at start-up
        // ("Trying to allocate twice the same uid").
        static TypeId tid = TypeId("ns3::CrhExperimentHeader")
                                .SetParent<Header>()
                                .SetGroupName("Internet")
                                .AddConstructor<CrhHeader>();
        return tid;
    }

    TypeId GetInstanceTypeId() const override
    {
        return GetTypeId();
    }

    /**
     * Load the path.
     *
     * Pass the segments in FORWARD order (the order the packet will visit
     * them). We store them reversed, because RFC 9631 says SIDs are listed in
     * reverse order so that Segments Left can be used directly as an index.
     */
    void SetPath(const std::vector<uint16_t>& forwardOrderSids)
    {
        m_sids.assign(forwardOrderSids.rbegin(), forwardOrderSids.rend());
        m_segmentsLeft = m_sids.size();
    }

    uint8_t GetSegmentsLeft() const
    {
        return m_segmentsLeft;
    }

    void SetSegmentsLeft(uint8_t sl)
    {
        m_segmentsLeft = sl;
    }

    /** The SID that Segments Left currently points at. */
    uint16_t GetCurrentSid() const
    {
        NS_ASSERT_MSG(m_segmentsLeft < m_sids.size(),
                      "Segments Left out of range for the SID list");
        return m_sids[m_segmentsLeft];
    }

    uint32_t GetNumSids() const
    {
        return m_sids.size();
    }

    /**
     * Hdr Ext Len, in 8-octet units NOT counting the first 8 octets
     * (RFC 8200). This is the value that actually goes on the wire.
     */
    uint8_t GetHdrExtLen() const
    {
        return static_cast<uint8_t>(GetSerializedSize() / 8) - 1;
    }

    /**
     * L, the minimum CRH length (RFC 9631 Section 5.1), expressed in the same
     * units as Hdr Ext Len. A CRH must be long enough to hold Segments Left
     * SIDs. If it is not, the packet is malformed and must be discarded --
     * this is the check that stops a truncated header from indexing off the
     * end of the list.
     */
    uint8_t GetMinimumLength() const
    {
        uint32_t bytes = 4 + m_segmentsLeft * 2; // 4 fixed bytes + SL SIDs
        uint32_t padded = ((bytes + 7) / 8) * 8;
        return static_cast<uint8_t>(padded / 8) - 1;
    }

    /**
     * Size on the wire. RFC 9631: "the CRH MUST end on a 64-bit boundary",
     * so the SID list is zero-padded up to a multiple of 8 bytes.
     */
    uint32_t GetSerializedSize() const override
    {
        uint32_t bytes = 4 + m_sids.size() * 2;
        return ((bytes + 7) / 8) * 8; // round up to a multiple of 8
    }

    void Serialize(Buffer::Iterator start) const override
    {
        uint32_t total = GetSerializedSize();

        start.WriteU8(m_nextHeader);
        start.WriteU8(static_cast<uint8_t>(total / 8) - 1); // Hdr Ext Len
        start.WriteU8(CRH16_ROUTING_TYPE);                  // Routing Type = 5
        start.WriteU8(m_segmentsLeft);

        for (uint16_t sid : m_sids)
        {
            start.WriteHtonU16(sid);
        }

        // zero padding to the 64-bit boundary
        uint32_t written = 4 + m_sids.size() * 2;
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

        NS_ASSERT_MSG(routingType == CRH16_ROUTING_TYPE,
                      "Not a CRH-16 header (routing type " << +routingType << ")");

        uint32_t total = (hdrExtLen + 1) * 8;
        uint32_t sidBytes = total - 4;

        // Read every SID-sized slot, padding included.
        //
        // This looks wasteful but it is what the RFC requires. A router
        // receiving a CRH has NO way to tell a real SID from a zero pad byte:
        // the header carries no SID count. It never needs to know, because it
        // only ever reads SID[Segments Left], which is always inside the real
        // SIDs. That is exactly why RFC 9631 Section 5.1 makes you check the
        // minimum length first -- that check, not a count field, is what stops
        // a malformed header from indexing into the padding.
        m_sids.clear();
        for (uint32_t i = 0; i < sidBytes / 2; ++i)
        {
            m_sids.push_back(start.ReadNtohU16());
        }

        return total;
    }

    void Print(std::ostream& os) const override
    {
        os << "CRH-16 (type=" << +CRH16_ROUTING_TYPE
           << " segsLeft=" << +m_segmentsLeft << " sids=[";
        for (size_t i = 0; i < m_sids.size(); ++i)
        {
            os << (i ? " " : "") << m_sids[i];
        }
        os << "] " << GetSerializedSize() << "B)";
    }

    /** Hex dump of the encoded bytes, for the RFC-compliance check. */
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

  private:
    uint8_t m_nextHeader;
    uint8_t m_segmentsLeft;
    std::vector<uint16_t> m_sids; // stored in REVERSE path order
};

// ---- size helpers, for the overhead comparison ----
static uint32_t
Crh16Size(uint32_t nSids)
{
    return ((4 + nSids * 2) + 7) / 8 * 8;
}

static uint32_t
Crh32Size(uint32_t nSids)
{
    return ((4 + nSids * 4) + 7) / 8 * 8;
}

static uint32_t
SrhSize(uint32_t nSids)
{
    // RFC 8754 SRH: 8-byte fixed part + a full 128-bit address per segment
    return ((8 + nSids * 16) + 7) / 8 * 8;
}

// ===========================================================================
//  PART 2 -- Global trace state (so we can prove the path was followed)
// ===========================================================================

struct PacketTrace
{
    std::vector<uint32_t> hops;   // node ids actually visited
    std::vector<uint8_t> segsSeen; // Segments Left observed at each hop
    Time sent;
    Time received;
    bool delivered = false;
    uint32_t headerBytes = 0;
};

static std::map<uint32_t, PacketTrace> g_traces; // packet id -> trace
static uint32_t g_dropped = 0;

// ===========================================================================
//  PART 3 -- The CRH forwarder application
// ===========================================================================

/**
 * Runs on every node. Receives UDP datagrams whose payload begins with a CRH,
 * applies the RFC 9631 forwarding algorithm, and either delivers the packet or
 * passes it to the next hop.
 *
 * NOTE ON SCOPE: a production implementation would live inside the IPv6 stack
 * and be triggered by the extension-header chain. Hooking ns-3's
 * Ipv6L3Protocol is a large piece of work, so, as is normal for a research
 * prototype, the header is carried in a UDP payload and processed by this
 * application. The header bytes and the forwarding algorithm are exactly as
 * the RFC specifies; only the place the code runs differs.
 */
class CrhForwarder : public Application
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::CrhForwarder")
                                .SetParent<Application>()
                                .SetGroupName("Applications")
                                .AddConstructor<CrhForwarder>();
        return tid;
    }

    CrhForwarder()
        : m_socket(nullptr),
          m_port(7777)
    {
    }

    /** Install one CRH-FIB entry: SID -> the interface to send out of. */
    void AddFibEntry(uint16_t sid, Ipv4Address nextHop)
    {
        m_fib[sid] = nextHop;
    }

    void SetPort(uint16_t port)
    {
        m_port = port;
    }

    /** Source-node helper: build a CRH and inject the packet. */
    void SendWithPath(uint32_t packetId,
                      const std::vector<uint16_t>& forwardPath,
                      uint32_t payloadBytes)
    {
        CrhHeader crh;
        crh.SetPath(forwardPath);

        PacketTrace tr;
        tr.sent = Simulator::Now();
        tr.headerBytes = crh.GetSerializedSize();
        tr.hops.push_back(GetNode()->GetId());
        tr.segsSeen.push_back(crh.GetSegmentsLeft());
        g_traces[packetId] = tr;

        Ptr<Packet> p = Create<Packet>(payloadBytes);
        // the packet id travels in its own tiny header so we can follow it
        IdTag tag;
        tag.id = packetId;
        p->AddByteTag(tag);
        p->AddHeader(crh);

        // The source is itself a CRH-configured node, so it performs the first
        // lookup exactly like any router (RFC 9631 Appendix A.1).
        ProcessAndForward(p, packetId, false);
    }

    /** A tiny byte tag carrying our packet id through the simulation. */
    class IdTag : public Tag
    {
      public:
        uint32_t id = 0;

        static TypeId GetTypeId()
        {
            static TypeId tid = TypeId("ns3::IdTag")
                                    .SetParent<Tag>()
                                    .SetGroupName("Applications")
                                    .AddConstructor<IdTag>();
            return tid;
        }

        TypeId GetInstanceTypeId() const override
        {
            return GetTypeId();
        }

        uint32_t GetSerializedSize() const override
        {
            return 4;
        }

        void Serialize(TagBuffer i) const override
        {
            i.WriteU32(id);
        }

        void Deserialize(TagBuffer i) override
        {
            id = i.ReadU32();
        }

        void Print(std::ostream& os) const override
        {
            os << "id=" << id;
        }
    };

  protected:
    void StartApplication() override
    {
        if (!m_socket)
        {
            m_socket = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
            m_socket->Bind(InetSocketAddress(Ipv4Address::GetAny(), m_port));
            m_socket->SetRecvCallback(MakeCallback(&CrhForwarder::HandleRead, this));
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
            ProcessAndForward(packet, pid, true);
        }
    }

    /**
     * The RFC 9631 Section 5 forwarding algorithm, step for step.
     *
     * justArrived is true when the packet has just been received from the
     * network (HandleRead) and false at the source, which SendWithPath has
     * already recorded.
     */
    void ProcessAndForward(Ptr<Packet> packet, uint32_t pid, bool justArrived)
    {
        CrhHeader crh;
        packet->RemoveHeader(crh);

        uint32_t me = GetNode()->GetId();
        PacketTrace& tr = g_traces[pid];

        // Record where the packet ACTUALLY is: this node, the one that received
        // it, with the Segments Left it arrived with. (Bug #20: the first
        // version recorded, at the sender, the node the chosen SID was SUPPOSED
        // to reach, so the path check compared the intended path with itself
        // and could never fail. Run with --miswire=1 to see it fail now.)
        if (justArrived)
        {
            tr.hops.push_back(me);
            tr.segsSeen.push_back(crh.GetSegmentsLeft());
        }

        // --- STEP 1: Segments Left == 0 means the packet has arrived ---
        if (crh.GetSegmentsLeft() == 0)
        {
            tr.delivered = true;
            tr.received = Simulator::Now();
            return;
        }

        // --- STEP 2: validate the header length (RFC 9631 Section 5.1) ---
        if (crh.GetMinimumLength() > crh.GetHdrExtLen())
        {
            // A real router would send ICMPv6 Parameter Problem, Code 6.
            g_dropped++;
            return;
        }

        // --- STEP 3: decrement Segments Left ---
        crh.SetSegmentsLeft(crh.GetSegmentsLeft() - 1);

        // --- STEP 4: the current SID is the one Segments Left now points at ---
        uint16_t sid = crh.GetCurrentSid();

        // --- STEP 5: look the SID up in this node's CRH-FIB ---
        auto entry = m_fib.find(sid);
        if (entry == m_fib.end())
        {
            // A real router would send ICMPv6 Parameter Problem, Code 0.
            g_dropped++;
            return;
        }

        // --- STEP 6: forward out of the interface the FIB gave us ---
        packet->AddHeader(crh);

        Ptr<Socket> tx = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
        tx->Connect(InetSocketAddress(entry->second, m_port));
        tx->Send(packet);
        tx->Close();
        // (where it lands is recorded by the receiving node, see above)
    }

    Ptr<Socket> m_socket;
    uint16_t m_port;
    std::map<uint16_t, Ipv4Address> m_fib;
};

// ===========================================================================
//  PART 4 -- Self-test: does our encoding match RFC 9631 exactly?
// ===========================================================================

static bool
RunHeaderSelfTest()
{
    std::cout << "\n=== PART A: CRH-16 header conformance self-test ===\n\n";
    bool ok = true;

    // A 3-segment path: visit SID 2, then 3, then 7.
    CrhHeader h;
    h.SetPath({2, 3, 7});

    // Expected bytes, worked out by hand from RFC 9631:
    //   Next Header  = 17 (UDP)            -> 0x11
    //   Hdr Ext Len  = 1  (16 bytes total) -> 0x01
    //   Routing Type = 5  (CRH-16)         -> 0x05
    //   Segments Left= 3                   -> 0x03
    //   SIDs reversed: 7, 3, 2             -> 0007 0003 0002
    //   4 + 3*2 = 10 bytes, which must pad up to 16 (the next 64-bit boundary)
    //   so six padding bytes follow        -> 0000 0000 0000
    const std::string expected = "11010503000700030002000000000000";

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

    // 64-bit boundary rule
    std::cout << "\n  64-bit boundary rule (RFC 9631 Section 3):\n";
    for (uint32_t n = 1; n <= 8; ++n)
    {
        CrhHeader t;
        std::vector<uint16_t> path(n, 1);
        t.SetPath(path);
        uint32_t sz = t.GetSerializedSize();
        bool aligned = (sz % 8 == 0);
        std::cout << "    " << n << " SIDs -> " << sz << " bytes"
                  << (aligned ? "  (8-byte aligned)" : "  *** NOT ALIGNED ***")
                  << "\n";
        if (!aligned)
        {
            ok = false;
        }
    }

    // round trip through serialize/deserialize
    std::cout << "\n  serialize / deserialize round trip:\n";
    Ptr<Packet> p = Create<Packet>(100);
    CrhHeader out;
    out.SetPath({4, 9, 2, 6});
    p->AddHeader(out);

    CrhHeader back;
    p->RemoveHeader(back);

    std::cout << "    sent    : segsLeft=" << +out.GetSegmentsLeft()
              << " size=" << out.GetSerializedSize() << "B\n";
    std::cout << "    received: segsLeft=" << +back.GetSegmentsLeft()
              << " size=" << back.GetSerializedSize() << "B\n";

    // Compare the things a router actually uses: Segments Left, the size, and
    // the SID sequence produced by walking Segments Left down to zero.
    bool sameSequence = true;
    CrhHeader a = out;
    CrhHeader b = back;
    std::ostringstream seqA;
    std::ostringstream seqB;
    while (a.GetSegmentsLeft() > 0 && b.GetSegmentsLeft() > 0)
    {
        a.SetSegmentsLeft(a.GetSegmentsLeft() - 1);
        b.SetSegmentsLeft(b.GetSegmentsLeft() - 1);
        seqA << a.GetCurrentSid() << " ";
        seqB << b.GetCurrentSid() << " ";
        if (a.GetCurrentSid() != b.GetCurrentSid())
        {
            sameSequence = false;
        }
    }
    std::cout << "    SID sequence sent    : " << seqA.str() << "\n";
    std::cout << "    SID sequence received: " << seqB.str() << "\n";

    if (back.GetSegmentsLeft() != out.GetSegmentsLeft() ||
        back.GetSerializedSize() != out.GetSerializedSize() || !sameSequence)
    {
        std::cout << "    *** round trip FAILED ***\n";
        ok = false;
    }
    else
    {
        std::cout << "    round trip: PASS\n";
    }

    // the minimum-length check (RFC 9631 Section 5.1)
    std::cout << "\n  minimum-length check on a malformed header:\n";
    CrhHeader bad;
    bad.SetPath({2, 3}); // only 2 SIDs, so the header is 8 bytes
    std::cout << "    honest header : 2 SIDs, segsLeft=2, HdrExtLen="
              << +bad.GetHdrExtLen() << ", minimum required="
              << +bad.GetMinimumLength() << "  -> accepted\n";
    bad.SetSegmentsLeft(6); // claim 6 segments in a header that cannot hold them
    bool rejected = bad.GetMinimumLength() > bad.GetHdrExtLen();
    std::cout << "    forged header : segsLeft forged to 6, HdrExtLen="
              << +bad.GetHdrExtLen() << ", minimum required="
              << +bad.GetMinimumLength() << "  -> "
              << (rejected ? "REJECTED (correct)" : "accepted *** WRONG ***") << "\n";
    std::cout << "    This is the check that stops a forged Segments Left from\n"
                 "    indexing past the end of the SID list. A real router would\n"
                 "    also send ICMPv6 Parameter Problem, Code 6.\n";
    if (!rejected)
    {
        ok = false;
    }

    // the index rule: decrement first, then index
    std::cout << "\n  Segments Left as an index (decrement, then read):\n";
    CrhHeader w;
    w.SetPath({2, 3, 7}); // forward order
    std::cout << "    path 2 -> 3 -> 7, stored reversed as [7 3 2]\n";
    while (w.GetSegmentsLeft() > 0)
    {
        w.SetSegmentsLeft(w.GetSegmentsLeft() - 1);
        std::cout << "    segsLeft now " << +w.GetSegmentsLeft()
                  << " -> current SID = " << w.GetCurrentSid() << "\n";
    }

    return ok;
}

// ===========================================================================
//  PART 5 -- Header size comparison
// ===========================================================================

static void
RunSizeComparison(const std::string& csvFile)
{
    std::cout << "\n=== PART B: header size vs SRv6 ===\n\n";
    std::cout << "  " << std::setw(6) << "SIDs" << std::setw(10) << "CRH-16"
              << std::setw(10) << "CRH-32" << std::setw(12) << "SRv6 SRH"
              << std::setw(16) << "CRH-16 saving" << "\n";

    std::ofstream out;
    if (!csvFile.empty())
    {
        out.open(csvFile);
        out << "sids,crh16_bytes,crh32_bytes,srh_bytes\n";
    }

    for (uint32_t n = 1; n <= 20; ++n)
    {
        uint32_t c16 = Crh16Size(n);
        uint32_t c32 = Crh32Size(n);
        uint32_t srh = SrhSize(n);

        if (n <= 12 || n == 15 || n == 20)
        {
            std::cout << "  " << std::setw(6) << n << std::setw(9) << c16 << "B"
                      << std::setw(9) << c32 << "B" << std::setw(11) << srh << "B"
                      << std::setw(15) << std::fixed << std::setprecision(1)
                      << (double)srh / c16 << "x\n";
        }
        if (out.is_open())
        {
            out << n << "," << c16 << "," << c32 << "," << srh << "\n";
        }
    }
    if (out.is_open())
    {
        out.close();
        std::cout << "\n  wrote " << csvFile << "\n";
    }
}

// ===========================================================================
//  PART 6 -- The network experiment
// ===========================================================================

int
main(int argc, char* argv[])
{
    uint32_t payloadBytes = 100;
    // v0.9 outputs get their own names so the Assessment 7 CSVs stay untouched
    std::string sizeCsv = "crh_sizes_v09.csv";
    std::string pathCsv = "crh_paths_v09.csv";
    bool quiet = false;
    bool miswire = false;

    CommandLine cmd(__FILE__);
    cmd.AddValue("payload", "Payload size in bytes", payloadBytes);
    cmd.AddValue("sizeCsv", "Where to write the size comparison", sizeCsv);
    cmd.AddValue("pathCsv", "Where to write the path results", pathCsv);
    cmd.AddValue("quiet", "Suppress the self-test output", quiet);
    cmd.AddValue("miswire",
                 "Regression check for bug #20: give n1 a WRONG CRH-FIB entry for SID 7 "
                 "(n5 instead of n6). The path check must then FAIL.",
                 miswire);
    cmd.Parse(argc, argv);

    if (!quiet)
    {
        bool ok = RunHeaderSelfTest();
        if (!ok)
        {
            std::cout << "\nSELF-TEST FAILED -- stopping.\n";
            return 1;
        }
        RunSizeComparison(sizeCsv);
    }

    // -------------------------------------------------------------------
    //  Topology. There is a short way and a long way from n0 to n6:
    //
    //         n1 ------------- (2 hops, what normal IP routing picks)
    //        /  \
    //      n0    n6
    //        \  /
    //   n2-n3-n4-n5   (5 hops, only reachable if the SOURCE demands it)
    //
    //  Links: n0-n1, n1-n6           short path
    //         n0-n2, n2-n3, n3-n4, n4-n5, n5-n6   long path
    // -------------------------------------------------------------------
    std::cout << "\n=== PART C: forwarding a packet along a source-chosen path ===\n\n";

    NodeContainer nodes;
    nodes.Create(7);

    PointToPointHelper p2p;
    p2p.SetDeviceAttribute("DataRate", StringValue("10Mbps"));
    p2p.SetChannelAttribute("Delay", StringValue("5ms"));

    struct Link
    {
        uint32_t a;
        uint32_t b;
    };

    std::vector<Link> links = {
        {0, 1}, {1, 6},                          // the short path
        {0, 2}, {2, 3}, {3, 4}, {4, 5}, {5, 6},  // the long path
    };

    InternetStackHelper stack;
    stack.Install(nodes);

    Ipv4AddressHelper addr;
    // addrOf[a][b] = the address of node b on the link between a and b
    std::map<uint32_t, std::map<uint32_t, Ipv4Address>> addrOf;

    for (size_t i = 0; i < links.size(); ++i)
    {
        NetDeviceContainer dev = p2p.Install(nodes.Get(links[i].a), nodes.Get(links[i].b));

        std::ostringstream base;
        base << "10.1." << (i + 1) << ".0";
        addr.SetBase(base.str().c_str(), "255.255.255.0");
        Ipv4InterfaceContainer ifc = addr.Assign(dev);

        addrOf[links[i].a][links[i].b] = ifc.GetAddress(1); // b's address
        addrOf[links[i].b][links[i].a] = ifc.GetAddress(0); // a's address
    }

    Ipv4GlobalRoutingHelper::PopulateRoutingTables();

    // -------------------------------------------------------------------
    //  Install a CRH forwarder on every node and fill in its CRH-FIB.
    //
    //  SID convention: SID = node id + 1. The RFC is clear that a SID is
    //  just an index into a FIB and carries no address meaning, so any
    //  numbering works as long as each node's FIB agrees.
    // -------------------------------------------------------------------
    std::vector<Ptr<CrhForwarder>> apps;
    for (uint32_t i = 0; i < nodes.GetN(); ++i)
    {
        Ptr<CrhForwarder> app = CreateObject<CrhForwarder>();
        nodes.Get(i)->AddApplication(app);
        app->SetStartTime(Seconds(0.0));
        app->SetStopTime(Seconds(10.0));
        apps.push_back(app);
    }

    // Each node learns, for every direct neighbour, which interface reaches it.
    for (const Link& l : links)
    {
        apps[l.a]->AddFibEntry(l.b + 1, addrOf[l.a][l.b]);
        apps[l.b]->AddFibEntry(l.a + 1, addrOf[l.b][l.a]);
    }

    // A deliberately wrong FIB entry, to prove the path check can fail: n1 now
    // resolves SID 7 (n6) to n5's address on the n5-n6 link. IP routing takes
    // the packet n1 -> n6 -> n5, and n5 receives it with Segments Left = 0, so
    // it is "delivered" -- at the wrong node.
    if (miswire)
    {
        apps[1]->AddFibEntry(7, addrOf[6][5]);
        std::cout << "  [--miswire] n1's CRH-FIB maps SID 7 to n5 (" << addrOf[6][5]
                  << ") instead of n6\n\n";
    }

    // -------------------------------------------------------------------
    //  Two packets, same source and destination, different chosen paths.
    // -------------------------------------------------------------------
    std::vector<uint16_t> shortPath = {2, 7};             // n1, n6
    std::vector<uint16_t> longPath = {3, 4, 5, 6, 7};     // n2, n3, n4, n5, n6

    // An impossible path: n1 and n4 are not neighbours, so when the packet
    // reaches n1 the SID for n4 will not be in n1's CRH-FIB and the packet
    // must be discarded (RFC 9631 Section 5, ICMPv6 Parameter Problem Code 0).
    std::vector<uint16_t> brokenPath = {2, 5, 7};         // n1, n4, n6

    Simulator::Schedule(Seconds(1.0),
                        &CrhForwarder::SendWithPath,
                        apps[0],
                        1,
                        shortPath,
                        payloadBytes);

    Simulator::Schedule(Seconds(2.0),
                        &CrhForwarder::SendWithPath,
                        apps[0],
                        2,
                        longPath,
                        payloadBytes);

    Simulator::Schedule(Seconds(3.0),
                        &CrhForwarder::SendWithPath,
                        apps[0],
                        3,
                        brokenPath,
                        payloadBytes);

    Simulator::Stop(Seconds(5.0));
    Simulator::Run();

    // -------------------------------------------------------------------
    //  Results
    // -------------------------------------------------------------------
    std::vector<std::pair<std::string, std::vector<uint32_t>>> expected = {
        {"short (n0->n1->n6)", {0, 1, 6}},
        {"long  (n0->n2->n3->n4->n5->n6)", {0, 2, 3, 4, 5, 6}},
        {"broken (n0->n1->n4, n1 and n4 are not neighbours)", {0, 1}},
    };

    std::ofstream pout;
    if (!pathCsv.empty())
    {
        pout.open(pathCsv);
        pout << "packet,intended_hops,actual_hops,delivered,latency_ms,header_bytes\n";
    }

    bool allOk = true;
    for (uint32_t pid = 1; pid <= 3; ++pid)
    {
        PacketTrace& tr = g_traces[pid];
        auto& exp = expected[pid - 1];

        std::cout << "  Packet " << pid << " -- " << exp.first << "\n";

        std::ostringstream actual;
        for (size_t i = 0; i < tr.hops.size(); ++i)
        {
            actual << (i ? " -> n" : "n") << tr.hops[i];
        }
        std::cout << "    intended : ";
        for (size_t i = 0; i < exp.second.size(); ++i)
        {
            std::cout << (i ? " -> n" : "n") << exp.second[i];
        }
        std::cout << "\n    actual   : " << actual.str() << "\n";

        std::cout << "    segsLeft : ";
        for (size_t i = 0; i < tr.segsSeen.size(); ++i)
        {
            std::cout << (i ? " -> " : "") << +tr.segsSeen[i];
        }
        std::cout << "\n";

        bool expectDrop = (pid == 3);
        bool match = (tr.hops == exp.second);
        // exact (ns resolution), not GetMilliSeconds(), which floors to whole ms
        double latency =
            tr.delivered ? (tr.received - tr.sent).GetNanoSeconds() / 1e6 : -1;

        std::cout << "    header   : " << tr.headerBytes << " bytes\n";
        std::cout << "    delivered: " << (tr.delivered ? "yes" : "no");
        if (tr.delivered)
        {
            std::cout << "   latency: " << latency << " ms";
        }
        if (expectDrop)
        {
            bool correct = match && !tr.delivered;
            std::cout << "\n    expected   : discarded at n1 (SID not in its CRH-FIB)\n";
            std::cout << "    result     : " << (correct ? "PASS" : "FAIL") << "\n\n";
            if (!correct)
            {
                allOk = false;
            }
        }
        else
        {
            std::cout << "\n    path match: " << (match ? "PASS" : "FAIL") << "\n\n";
            if (!match || !tr.delivered)
            {
                allOk = false;
            }
        }

        if (pout.is_open())
        {
            pout << pid << "," << exp.second.size() << "," << tr.hops.size() << ","
                 << (tr.delivered ? 1 : 0) << "," << latency << "," << tr.headerBytes
                 << "\n";
        }
    }

    if (pout.is_open())
    {
        pout.close();
        std::cout << "  wrote " << pathCsv << "\n";
    }

    std::cout << "  packets discarded by CRH checks: " << g_dropped << "\n";
    std::cout << "\n  OVERALL: " << (allOk ? "PASS" : "FAIL") << "\n\n";

    Simulator::Destroy();
    return allOk ? 0 : 1;
}