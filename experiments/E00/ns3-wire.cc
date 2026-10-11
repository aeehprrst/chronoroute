// SPDX-License-Identifier: GPL-2.0-only
// E0 stdin-independent batch adapter to the installed ns-3 ChronoRoute library.
#include "ns3/tcrh-header.h"
#include "ns3/crh-header.h"
#include "ns3/tcrh-process.h"
#include "ns3/packet.h"
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

std::vector<std::string> Split(const std::string& text, char separator)
{
    std::vector<std::string> out;
    std::istringstream in(text);
    for (std::string s; std::getline(in, s, separator);) out.push_back(s);
    return out;
}
template <typename T> std::vector<T> Numbers(const std::string& text)
{
    std::vector<T> out;
    for (const auto& s : Split(text, ',')) out.push_back(static_cast<T>(std::stoull(s)));
    return out;
}
std::vector<uint8_t> Unhex(const std::string& text)
{
    std::vector<uint8_t> out;
    if (text.size() % 2) throw std::runtime_error("odd hex");
    for (size_t i = 0; i < text.size(); i += 2)
        out.push_back(static_cast<uint8_t>(std::stoul(text.substr(i, 2), nullptr, 16)));
    return out;
}
std::string Hex(const std::vector<uint8_t>& bytes)
{
    std::string out;
    const char* digits = "0123456789abcdef";
    for (uint8_t b : bytes) { out += digits[b >> 4]; out += digits[b & 15]; }
    return out;
}
template <typename T> void Optional(const std::optional<T>& value)
{
    if (value) std::cout << +*value; else std::cout << "null";
}
int main(int argc, char** argv)
{
    if (argc != 2) return 2;
    std::ifstream in(argv[1]);
    if (!in) return 2;
    for (std::string line; std::getline(in, line);)
    {
        auto f = Split(line, '\t');
        if (f.size() < 3) return 2;
        std::cout << "{\"id\":" << f[1];
        if (f[0] == "CE")
        {
            ns3::CrhHeader h;
            h.SetPath(Numbers<uint32_t>(f[4]), std::stoul(f[2]));
            h.SetNextHeader(std::stoul(f[3]));
            std::cout << ",\"hex\":\"" << Hex(h.ToBytes()) << "\"";
        }
        else if (f[0] == "CP")
        {
            auto b = Unhex(f[2]);
            auto r = ns3::CrhProcessAtNode(b.data(), b.size());
            std::cout << ",\"action\":\"" << r.action << "\",\"hex\":";
            if (r.outBytes) std::cout << "\"" << Hex(*r.outBytes) << "\""; else std::cout << "null";
            std::cout << ",\"next_sid\":"; Optional(r.nextSid);
            std::cout << ",\"icmp_code\":"; Optional(r.icmpCode);
            std::cout << ",\"icmp_pointer\":"; Optional(r.icmpPointer);
            std::cout << ",\"reason\":";
            if (r.reason) std::cout << "\"" << r.reason << "\""; else std::cout << "null";
        }
        else if (f[0] == "B" || f[0] == "E")
        {
            auto sids = Numbers<uint16_t>(f[6]);
            ns3::TcrhHeader h;
            if (f[0] == "B")
                h = ns3::TcrhHeader::Build(sids, Numbers<uint64_t>(f[7]), std::stoull(f[4]),
                                         std::stoul(f[2]), std::stoul(f[3]));
            else
            {
                bool sat = false;
                auto deltas = f[8] == "budgets"
                    ? ns3::TcrhHeader::EncodeDeltas(Numbers<uint64_t>(f[7]), std::stoul(f[2]), &sat)
                    : Numbers<uint8_t>(f[7]);
                h.SetPath(sids, deltas, std::stoul(f[4]), std::stoul(f[2]),
                          std::stoul(f[5]) | (sat ? 4 : 0));
                h.SetNextHeader(std::stoul(f[3]));
            }
            auto p = ns3::Create<ns3::Packet>();
            p->AddHeader(h);
            std::vector<uint8_t> b(p->GetSize());
            p->CopyData(b.data(), b.size());
            std::cout << ",\"hex\":\"" << Hex(b) << "\"";
        }
        else if (f[0] == "I")
        {
            auto r = ns3::tcrh::IngressSend(Unhex(f[2]));
            if (!r.ok) return 3;
            std::cout << ",\"hex\":\"" << Hex(r.outBytes) << "\",\"first_sid\":" << r.firstSid;
        }
        else
        {
            ns3::tcrh::Policy policy;
            if (!ns3::tcrh::PolicyFromName(f[4], &policy)) return 2;
            auto r = f[0] == "L" ? ns3::tcrh::LinkDownFallback(Unhex(f[2]))
                : ns3::tcrh::ProcessAtNode(Unhex(f[2]), std::stoul(f[3]), policy);
            std::cout << ",\"action\":\"" << ns3::tcrh::ActionName(r.action) << "\",\"hex\":";
            if (r.outBytes) std::cout << "\"" << Hex(*r.outBytes) << "\""; else std::cout << "null";
            std::cout << ",\"next_sid\":"; Optional(r.nextSid);
            std::cout << ",\"late\":" << (r.late ? "true" : "false");
            std::cout << ",\"hop_index\":"; Optional(r.hopIndex);
            std::cout << ",\"deadline_u\":"; Optional(r.deadlineU);
            std::cout << ",\"icmp_code\":"; Optional(r.icmpCode);
            std::cout << ",\"icmp_pointer\":"; Optional(r.icmpPointer);
            std::cout << ",\"reason\":";
            if (r.reason) std::cout << "\"" << r.reason << "\""; else std::cout << "null";
        }
        std::cout << "}\n";
    }
}
