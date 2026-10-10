/*
 * bottleneck-experiment.cc
 * ------------------------
 * A basic ns-3 experiment: TCP flows competing over a shared bottleneck link.
 *
 * This is the standard "dumbbell" topology used to teach congestion control.
 * It is deliberately simple, because its purpose is to demonstrate that we can
 * drive ns-3 correctly, not to produce a novel result.
 *
 *   n0 ---\                                        /--- n3   (sinks)
 *          \                                      /
 *           r0 ==================================  r1
 *          /        BOTTLENECK (variable)         \
 *   n1 ---/         50-packet FIFO queue           \--- n4
 *
 *   access links: 100 Mbps, 2 ms        bottleneck: variable, 20 ms
 *
 * What we measure, using FlowMonitor:
 *   - per-flow goodput
 *   - total goodput vs the bottleneck's nominal capacity
 *   - packets dropped at the bottleneck queue
 *   - mean ONE-WAY delay of the data packets (FlowMonitor delaySum / rxPackets;
 *     this is not a round-trip time)
 *
 * v0.9 (2026-10-10, ChronoRoute Phase 1, bug #19): the per-flow column that
 * said "mean RTT" and the CSV column mean_delay_ms are now labelled honestly
 * as one-way delay (mean_one_way_delay_ms). The numbers did not change.
 *
 * What we expect to see (the physics of the thing):
 *   - total goodput tracks bottleneck capacity, never exceeds it
 *   - TCP's congestion control keeps the link busy but not overloaded
 *   - drops appear once offered load exceeds capacity
 *
 * Build:
 *   cp bottleneck-experiment.cc ~/ns-3-dev/scratch/
 *   cd ~/ns-3-dev && ./ns3 build
 *
 * Run one point:
 *   ./ns3 run "scratch/bottleneck-experiment --bottleneck=5Mbps"
 *
 * Run with animation output:
 *   ./ns3 run "scratch/bottleneck-experiment --bottleneck=5Mbps --anim=1"
 */
#define HAS_NETANIM 1
#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/traffic-control-module.h"

#ifdef HAS_NETANIM
#include "ns3/netanim-module.h"
#endif

#include <fstream>
#include <iomanip>
#include <iostream>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("BottleneckExperiment");

int
main(int argc, char* argv[])
{
    // ----- parameters, all overridable from the command line -----
    std::string bottleneckRate = "5Mbps";
    std::string bottleneckDelay = "20ms";
    std::string accessRate = "100Mbps";
    std::string accessDelay = "2ms";
    std::string queueSize = "50p"; // 50 packets
    uint32_t nFlows = 2;
    double simTime = 10.0;
    bool enableAnim = false;
    bool verbose = false;
    std::string csvFile = "";

    CommandLine cmd(__FILE__);
    cmd.AddValue("bottleneck", "Bottleneck link data rate", bottleneckRate);
    cmd.AddValue("bottleneckDelay", "Bottleneck one-way delay", bottleneckDelay);
    cmd.AddValue("queue", "Bottleneck queue size, e.g. 50p", queueSize);
    cmd.AddValue("flows", "Number of competing TCP flows", nFlows);
    cmd.AddValue("time", "Simulation duration in seconds", simTime);
    cmd.AddValue("anim", "Write a NetAnim XML trace", enableAnim);
    cmd.AddValue("verbose", "Print per-flow detail", verbose);
    cmd.AddValue("csv", "Append a summary row to this CSV file", csvFile);
    cmd.Parse(argc, argv);

    // TCP configuration. NewReno is the classic, well-understood choice and
    // makes the sawtooth behaviour easy to explain in a viva.
    Config::SetDefault("ns3::TcpL4Protocol::SocketType",
                       TypeIdValue(TcpNewReno::GetTypeId()));
    Config::SetDefault("ns3::TcpSocket::SegmentSize", UintegerValue(1448));

    // ---------------------------------------------------------------- nodes
    // 0..nFlows-1        : senders
    // nFlows             : left router  (r0)
    // nFlows + 1         : right router (r1)
    // nFlows+2 .. 2n+1   : receivers
    NodeContainer senders;
    senders.Create(nFlows);
    NodeContainer routers;
    routers.Create(2);
    NodeContainer receivers;
    receivers.Create(nFlows);

    // ------------------------------------------------------------- channels
    PointToPointHelper access;
    access.SetDeviceAttribute("DataRate", StringValue(accessRate));
    access.SetChannelAttribute("Delay", StringValue(accessDelay));

    PointToPointHelper bottleneck;
    bottleneck.SetDeviceAttribute("DataRate", StringValue(bottleneckRate));
    bottleneck.SetChannelAttribute("Delay", StringValue(bottleneckDelay));

    NetDeviceContainer bottleneckDevs =
        bottleneck.Install(routers.Get(0), routers.Get(1));

    std::vector<NetDeviceContainer> senderDevs;
    std::vector<NetDeviceContainer> receiverDevs;
    for (uint32_t i = 0; i < nFlows; ++i)
    {
        senderDevs.push_back(access.Install(senders.Get(i), routers.Get(0)));
        receiverDevs.push_back(access.Install(routers.Get(1), receivers.Get(i)));
    }

    // ------------------------------------------------------- protocol stack
    InternetStackHelper stack;
    stack.Install(senders);
    stack.Install(routers);
    stack.Install(receivers);

    // ---------------------------------------------------------- addressing
    Ipv4AddressHelper addr;
    addr.SetBase("10.1.0.0", "255.255.255.0");
    addr.Assign(bottleneckDevs);

    std::vector<Ipv4InterfaceContainer> receiverIfs;
    for (uint32_t i = 0; i < nFlows; ++i)
    {
        std::ostringstream sn;
        sn << "10.2." << (i + 1) << ".0";
        addr.SetBase(sn.str().c_str(), "255.255.255.0");
        addr.Assign(senderDevs[i]);

        std::ostringstream rn;
        rn << "10.3." << (i + 1) << ".0";
        addr.SetBase(rn.str().c_str(), "255.255.255.0");
        receiverIfs.push_back(addr.Assign(receiverDevs[i]));
    }

    // Replace the bottleneck's queue discipline with a plain FIFO of known
    // size, so that "the queue filled up and dropped packets" is unambiguous.
    //
    // ORDER MATTERS: Ipv4AddressHelper::Assign is what installs ns-3's default
    // queue disc, so this must come AFTER addressing. Do it before, and there
    // is nothing to Uninstall, and you get an assertion failure at send time:
    //   "No root queue disc installed on device"
    TrafficControlHelper tch;
    tch.SetRootQueueDisc("ns3::FifoQueueDisc", "MaxSize", StringValue(queueSize));
    tch.Uninstall(bottleneckDevs);
    QueueDiscContainer bottleneckQdiscs = tch.Install(bottleneckDevs);

    Ipv4GlobalRoutingHelper::PopulateRoutingTables();

    // -------------------------------------------------------- applications
    uint16_t port = 9000;
    ApplicationContainer sinkApps;
    ApplicationContainer sourceApps;

    for (uint32_t i = 0; i < nFlows; ++i)
    {
        // receiver: soak up everything sent to it
        PacketSinkHelper sink("ns3::TcpSocketFactory",
                              InetSocketAddress(Ipv4Address::GetAny(), port + i));
        sinkApps.Add(sink.Install(receivers.Get(i)));

        // sender: BulkSend pushes as fast as TCP allows, which is what we want
        // for a saturation experiment. MaxBytes 0 means "send forever".
        Address dest(InetSocketAddress(receiverIfs[i].GetAddress(1), port + i));
        BulkSendHelper source("ns3::TcpSocketFactory", dest);
        source.SetAttribute("MaxBytes", UintegerValue(0));
        source.SetAttribute("SendSize", UintegerValue(1448));
        sourceApps.Add(source.Install(senders.Get(i)));
    }

    sinkApps.Start(Seconds(0.0));
    sinkApps.Stop(Seconds(simTime));
    // stagger the starts slightly so the flows do not synchronise perfectly
    for (uint32_t i = 0; i < sourceApps.GetN(); ++i)
    {
        sourceApps.Get(i)->SetStartTime(Seconds(1.0 + 0.1 * i));
        sourceApps.Get(i)->SetStopTime(Seconds(simTime));
    }

    // ------------------------------------------------------- measurement
    FlowMonitorHelper fmHelper;
    Ptr<FlowMonitor> monitor = fmHelper.InstallAll();

#ifdef HAS_NETANIM
    // NetAnim needs fixed screen coordinates for every node, otherwise it has
    // nothing to draw. These are layout only; they do not affect the physics.
    AnimationInterface* anim = nullptr;
    if (enableAnim)
    {
        anim = new AnimationInterface("bottleneck-anim.xml");
        for (uint32_t i = 0; i < nFlows; ++i)
        {
            double y = 10.0 + 20.0 * i;
            anim->SetConstantPosition(senders.Get(i), 10.0, y);
            anim->SetConstantPosition(receivers.Get(i), 80.0, y);
            anim->UpdateNodeDescription(senders.Get(i), "TX" + std::to_string(i));
            anim->UpdateNodeDescription(receivers.Get(i), "RX" + std::to_string(i));
            anim->UpdateNodeColor(senders.Get(i), 0, 200, 0);
            anim->UpdateNodeColor(receivers.Get(i), 0, 0, 200);
        }
        double midY = 10.0 + 10.0 * (nFlows - 1);
        anim->SetConstantPosition(routers.Get(0), 35.0, midY);
        anim->SetConstantPosition(routers.Get(1), 55.0, midY);
        anim->UpdateNodeDescription(routers.Get(0), "R0");
        anim->UpdateNodeDescription(routers.Get(1), "R1");
        anim->UpdateNodeColor(routers.Get(0), 200, 0, 0);
        anim->UpdateNodeColor(routers.Get(1), 200, 0, 0);
        anim->EnablePacketMetadata(true);
    }
#endif

    // ------------------------------------------------------------- run it
    Simulator::Stop(Seconds(simTime));
    Simulator::Run();

    // ---------------------------------------------------------- results
    monitor->CheckForLostPackets();
    Ptr<Ipv4FlowClassifier> classifier =
        DynamicCast<Ipv4FlowClassifier>(fmHelper.GetClassifier());
    FlowMonitor::FlowStatsContainer stats = monitor->GetFlowStats();

    double totalGoodputMbps = 0.0;
    uint64_t totalRxBytes = 0;
    uint32_t dataFlows = 0;
    std::vector<double> perFlowGoodput;
    // FlowMonitor's delaySum adds up, per received packet, the time from the
    // packet leaving the sender's IP layer to it reaching the receiver's IP
    // layer: a ONE-WAY delay (propagation + transmission + queueing). It is
    // not a round-trip time, so nothing below is labelled RTT (bug #19: the
    // per-flow column used to say "mean RTT").
    double delaySumMs = 0.0;
    uint64_t delayPkts = 0;

    std::cout << "\n=== Bottleneck experiment ===\n";
    std::cout << "bottleneck : " << bottleneckRate << ", " << bottleneckDelay
              << ", queue " << queueSize << "\n";
    std::cout << "flows      : " << nFlows << "   duration: " << simTime
              << " s\n\n";

    if (verbose)
    {
        std::cout << std::left << std::setw(24) << "flow" << std::right
                  << std::setw(10) << "tx pkts" << std::setw(10) << "rx pkts"
                  << std::setw(12) << "goodput" << std::setw(16) << "1-way delay"
                  << "\n";
    }

    for (auto it = stats.begin(); it != stats.end(); ++it)
    {
        Ipv4FlowClassifier::FiveTuple t = classifier->FindFlow(it->first);

        // Count ONLY the forward data direction. The reverse direction carries
        // pure ACKs; including it inflates goodput above the link capacity,
        // which is how I first got a nonsensical 101% utilisation.
        if (t.destinationPort < port || t.destinationPort >= port + nFlows)
        {
            continue;
        }
        dataFlows++;

        double duration = (it->second.timeLastRxPacket.GetSeconds() -
                           it->second.timeFirstTxPacket.GetSeconds());
        double goodput = duration > 0
                             ? it->second.rxBytes * 8.0 / duration / 1e6
                             : 0.0;
        totalGoodputMbps += goodput;
        totalRxBytes += it->second.rxBytes;
        perFlowGoodput.push_back(goodput);
        delaySumMs += it->second.delaySum.GetSeconds() * 1000.0;
        delayPkts += it->second.rxPackets;

        if (verbose)
        {
            std::ostringstream label;
            label << t.sourceAddress << " -> " << t.destinationAddress;
            double delay = it->second.rxPackets > 0
                               ? it->second.delaySum.GetSeconds() /
                                     it->second.rxPackets * 1000.0
                               : 0.0;
            std::cout << std::left << std::setw(24) << label.str() << std::right
                      << std::setw(10) << it->second.txPackets << std::setw(10)
                      << it->second.rxPackets << std::setw(9) << std::fixed
                      << std::setprecision(2) << goodput << " Mb"
                      << std::setw(14) << std::setprecision(1) << delay << " ms"
                      << "\n";
        }
    }

    // drops recorded by the bottleneck queue discipline itself
    uint32_t qDrops = 0;
    for (uint32_t i = 0; i < bottleneckQdiscs.GetN(); ++i)
    {
        qDrops += bottleneckQdiscs.Get(i)->GetStats().nTotalDroppedPackets;
    }

    // Jain's fairness index: 1.0 means every flow got an equal share,
    // 1/n means one flow took everything. A plain FIFO is known to be unfair,
    // so this number is worth reporting.
    double fairness = 0.0;
    if (!perFlowGoodput.empty())
    {
        double sum = 0.0;
        double sumSq = 0.0;
        for (double g : perFlowGoodput)
        {
            sum += g;
            sumSq += g * g;
        }
        fairness = sumSq > 0 ? (sum * sum) / (perFlowGoodput.size() * sumSq) : 0.0;
    }

    // what the link could theoretically carry
    DataRate nominal(bottleneckRate);
    double nominalMbps = nominal.GetBitRate() / 1e6;
    double utilisation = nominalMbps > 0 ? totalGoodputMbps / nominalMbps * 100.0
                                         : 0.0;

    std::cout << "\n";
    std::cout << "  data flows        : " << dataFlows << "\n";
    std::cout << "  total goodput     : " << std::fixed << std::setprecision(3)
              << totalGoodputMbps << " Mbps\n";
    std::cout << "  nominal capacity  : " << nominalMbps << " Mbps\n";
    std::cout << "  link utilisation  : " << std::setprecision(1) << utilisation
              << " %\n";
    std::cout << "  bytes delivered   : " << totalRxBytes << "\n";
    std::cout << "  queue drops       : " << qDrops << "\n";
    double meanDelayMs = delayPkts > 0 ? delaySumMs / delayPkts : 0.0;
    std::cout << "  Jain fairness     : " << std::setprecision(3) << fairness
              << "  (1.0 = perfectly equal shares)\n";
    std::cout << "  mean one-way delay: " << std::setprecision(1) << meanDelayMs
              << " ms  (link delay is " << bottleneckDelay << ")\n\n";

    if (!csvFile.empty())
    {
        // The delay column is named for what it is, a one-way delay (it was
        // the ambiguous "mean_delay_ms" next to a "mean RTT" label, bug #19).
        const std::string csvHeader = "bottleneck_mbps,flows,queue,goodput_mbps,utilisation_pct,"
                                      "queue_drops,fairness,mean_one_way_delay_ms,rx_bytes";

        // write a header only if the file is new
        std::ifstream probe(csvFile);
        bool needHeader = !probe.good() || probe.peek() == std::ifstream::traits_type::eof();
        std::string existingHeader;
        if (!needHeader)
        {
            std::getline(probe, existingHeader);
        }
        probe.close();

        // never append rows under a different header (for example an old CSV
        // that still has mean_delay_ms): the columns would silently disagree
        if (!needHeader && existingHeader != csvHeader)
        {
            std::cerr << "  " << csvFile << " has a different header:\n    " << existingHeader
                      << "\n  write to a new file instead (for example *_v09.csv)\n";
            Simulator::Destroy();
            return 1;
        }

        std::ofstream out(csvFile, std::ios::app);
        if (needHeader)
        {
            out << csvHeader << "\n";
        }
        out << nominalMbps << "," << nFlows << "," << queueSize << ","
            << totalGoodputMbps << "," << utilisation << "," << qDrops << ","
            << fairness << "," << meanDelayMs << "," << totalRxBytes << "\n";
        out.close();
        std::cout << "  appended a row to " << csvFile << "\n\n";
    }

    Simulator::Destroy();
    return 0;
}