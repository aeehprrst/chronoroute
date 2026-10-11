"""
Trace outputs of ChronoRoute runs.

    pcap   pcap files with IPv6 + T-CRH (or CRH) + transport packets, readable by
           Wireshark / tshark with tools/wireshark/tcrh.lua (plan phase P6)

Sub-modules are imported explicitly (`from chronoroute.trace import pcap`), so
importing this package stays cheap.
"""
