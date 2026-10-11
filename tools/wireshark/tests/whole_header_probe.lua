-- Test helper (not a plugin): hands the WHOLE payload of UDP port 50254 to the
-- tcrh dissector, i.e. a buffer that starts at Next Header (routing-header
-- byte 0) instead of at Flags. Wireshark 4.6's own dispatch always passes the
-- bytes from Flags on, so without this probe tcrh.lua's "whole header" branch
-- (written in case another Wireshark version does pass byte 0) would never run.
--
-- Load it AFTER tcrh.lua:
--   tshark -X lua_script:tools/wireshark/tcrh.lua \
--          -X lua_script:tools/wireshark/tests/whole_header_probe.lua -r x.pcap
local tcrh = Dissector.get("tcrh")
if tcrh == nil then
    io.stderr:write("whole_header_probe.lua: load tcrh.lua first\n")
    return
end

local probe = Proto("tcrh_whole_probe", "T-CRH whole-header test probe")

function probe.dissector(tvb, pinfo, tree)
    return tcrh:call(tvb, pinfo, tree)
end

DissectorTable.get("udp.port"):add(50254, probe)
