--[[
ChronoRoute T-CRH dissector for Wireshark / tshark 4.4+ (Lua 5.4)
=================================================================

T-CRH is the IPv6 Routing Header with Routing Type 253 that ChronoRoute uses to
carry a ground-computed path plus a cumulative arrival deadline for every hop.
The NORMATIVE wire format and processing rules are in spec/tcrh-v1.md; the
golden vectors in spec/golden/tcrh_vectors.json are the test oracle. If this
file and the spec ever disagree, this file is wrong.

  routing-header offset   field
  0  Next Header          (decoded by Wireshark's IPv6 dissector: ipv6.routing.nxt)
  1  Hdr Ext Len          (ipv6.routing.len)
  2  Routing Type = 253   (ipv6.routing.type)
  3  Segments Left        (ipv6.routing.segleft)
  4  Flags                DEV 0x01, GREEDY 0x02, SAT 0x04, UNIT 0x30, reserved 0xC8
  5  Num Hops             h, number of entries actually present (1..255)
  6  Dev Hop              hop index of the node that first set DEV
  7  Reserved
  8  Epoch_Base (4 B)     ingress time stamp, in deadline units, GPS time mod 2^32
  12 entries, 3 B each    SID (2 B) + Delta (1 B), stored in REVERSE path order
     zero padding to a multiple of 8 bytes

Install: copy this file into your personal Lua plugin folder (see README.md), or
load it for one run with   tshark -X lua_script:tools/wireshark/tcrh.lua ...

Every field is under "tcrh.*"; tools/wireshark/README.md lists them all.

Lua 5.4 note: Wireshark loads plugins like require(), so everything here is
`local`. Nothing is added to the global table (a test checks that).
]]

-- If the dissector is already registered (the plugin is installed AND the same
-- file is also passed with -X lua_script), a second Proto("tcrh", ...) would
-- raise an error and abort the Lua start-up. Stop quietly instead; stdout is
-- left alone because tshark may be printing fields there.
-- (Dissector.get returns nil for an unknown name in 4.6; older versions raise
-- an error instead, hence the pcall.)
local already_ok, already = pcall(Dissector.get, "tcrh")
if already_ok and already ~= nil then
    io.stderr:write("tcrh.lua: a T-CRH dissector is already registered; not loading a second copy\n")
    return
end

local SPEC_VERSION = "tcrh-v1 (spec 1.0.1)"

-- ------------------------------------------------------------------ constants
-- These mirror sim/chronoroute/proto/tcrh.py and timebase.py.

local ROUTING_TYPE_TCRH = 253
local FIXED_BYTES = 12          -- NH, HEL, Type, SL, Flags, NumHops, DevHop, Rsvd, Epoch_Base
local ENTRY_BYTES = 3           -- SID (2) + Delta (1)

local FLAG_DEV = 0x01
local FLAG_GREEDY = 0x02
local FLAG_SAT = 0x04
local FLAG_RESERVED_MASK = 0xC8

-- unit code -> deadline unit in nanoseconds (spec section 3)
local UNIT_NS = { [0] = 1000000, [1] = 100000, [2] = 250000, [3] = 125000 }
local UNIT_NAMES = { [0] = "1 ms", [1] = "0.1 ms", [2] = "0.25 ms", [3] = "0.125 ms" }

local MASK32 = 0xFFFFFFFF
local HALF32 = 0x80000000

-- GPS time = UTC + 18 s, and the GPS epoch (1980-01-06) is 315964800 s after
-- the Unix epoch. A pcap timestamp is Unix-epoch time, so
--   t_gps_ns = t_pcap_ns + UNIX_TO_GPS_NS.
-- This is exactly what sim/chronoroute/trace/pcap.py undoes when it writes
-- timestamps, so the margin of a Python pcap is exact.
local UNIX_TO_GPS_NS = (18 - 315964800) * 1000000000

-- Capture-timestamp interpretations for the margin field (a preference)
local TIMEBASE_OFF, TIMEBASE_UTC, TIMEBASE_OFFSET = 0, 1, 2

-- |margin| above this means the capture clock is not the ChronoRoute clock
-- (the largest legal plan, 255 hops x 255 units of 1 ms, is 65 s long).
local PLAUSIBLE_MARGIN_NS = 120 * 1000000000

-- -------------------------------------------------------------- the protocol

local tcrh = Proto("tcrh", "ChronoRoute T-CRH (IPv6 Routing Type 253)")

local VALID_NAMES = { [0] = "No (malformed, see expert info)", [1] = "Yes" }
local YES_NO = { [0] = "No", [1] = "Yes" }
-- How many bytes of the routing header come BEFORE the bytes Wireshark gives us
local INPUT_NAMES = { [0] = "whole routing header", [4] = "starts at Flags (after the 4 common bytes)" }

local F = {
    -- summary (generated)
    valid = ProtoField.uint8("tcrh.valid", "Header valid (spec 6 step 1)", base.DEC, VALID_NAMES),
    reason = ProtoField.string("tcrh.reason", "Malformed because"),
    input_offset = ProtoField.uint8("tcrh.input_offset", "Dissector input", base.DEC, INPUT_NAMES),
    -- wire fields
    flags = ProtoField.uint8("tcrh.flags", "Flags", base.HEX),
    dev = ProtoField.bool("tcrh.flags.dev", "DEV (deadline missed or next link down)", 8, nil, FLAG_DEV),
    greedy = ProtoField.bool("tcrh.flags.greedy", "GREEDY (geographic fallback forwarding)", 8, nil, FLAG_GREEDY),
    sat = ProtoField.bool("tcrh.flags.sat", "SAT (a Delta was clamped to 255 at encode time)", 8, nil, FLAG_SAT),
    unit = ProtoField.uint8("tcrh.flags.unit", "UNIT (deadline unit code)", base.DEC, UNIT_NAMES, 0x30),
    flags_reserved = ProtoField.uint8("tcrh.flags.reserved", "Reserved flag bits", base.HEX, nil, FLAG_RESERVED_MASK),
    num_hops = ProtoField.uint8("tcrh.num_hops", "Num Hops", base.DEC),
    dev_hop = ProtoField.uint8("tcrh.dev_hop", "Dev Hop", base.DEC),
    reserved = ProtoField.uint8("tcrh.reserved", "Reserved", base.HEX),
    epoch_base = ProtoField.uint32("tcrh.epoch_base", "Epoch_Base (units, GPS time mod 2^32)", base.DEC),
    -- derived from the flags (generated)
    unit_ns = ProtoField.uint32("tcrh.unit_ns", "Deadline unit (ns)", base.DEC),
    unit_ms = ProtoField.double("tcrh.unit_ms", "Deadline unit (ms)"),
    epoch_base_ms = ProtoField.double("tcrh.epoch_base_ms", "Epoch_Base (ms, mod 2^32 units)"),
    -- the entries
    entries = ProtoField.none("tcrh.entries", "Entries"),
    entry = ProtoField.none("tcrh.entry", "Entry"),
    entry_index = ProtoField.uint8("tcrh.entry.index", "Index i (wire order)", base.DEC),
    entry_hop = ProtoField.uint8("tcrh.entry.hop", "Hop k = Num Hops - i", base.DEC),
    sid = ProtoField.uint16("tcrh.sid", "SID", base.DEC),
    delta = ProtoField.uint8("tcrh.delta", "Delta (units)", base.DEC),
    delta_ms = ProtoField.double("tcrh.delta_ms", "Delta (ms)"),
    deadline = ProtoField.uint32("tcrh.deadline", "Cumulative deadline D_k (units mod 2^32)", base.DEC),
    deadline_ms = ProtoField.double("tcrh.deadline_ms", "Cumulative deadline D_k (ms)"),
    padding = ProtoField.bytes("tcrh.padding", "Padding"),
    -- where the packet is now (generated)
    current_hop = ProtoField.uint8("tcrh.current_hop", "Current hop k = Num Hops - SL (0 = not yet sent by the ingress)", base.DEC),
    current_sid = ProtoField.uint16("tcrh.current_sid", "Current SID = SID[SL]", base.DEC),
    current_deadline = ProtoField.uint32("tcrh.current_deadline", "Deadline at the current SID (units)", base.DEC),
    current_deadline_ms = ProtoField.double("tcrh.current_deadline_ms", "Deadline at the current SID (ms)"),
    final_sid = ProtoField.uint16("tcrh.final_sid", "Final endpoint = SID[0]", base.DEC),
    -- timing at capture (generated; needs the timebase preference)
    capture_clock = ProtoField.uint32("tcrh.capture_clock", "Unit clock at capture time", base.DEC),
    margin = ProtoField.int32("tcrh.margin", "Margin = deadline - capture clock (units)", base.DEC),
    margin_ms = ProtoField.double("tcrh.margin_ms", "Margin (ms, whole units)"),
    late = ProtoField.uint8("tcrh.late", "Past the current deadline at capture time", base.DEC, YES_NO),
    -- a copy inside an ICMPv6 error message (generated)
    quoted = ProtoField.uint8("tcrh.quoted", "Quoted inside an ICMPv6 error message", base.DEC, YES_NO),
}
tcrh.fields = {
    F.valid, F.reason, F.input_offset,
    F.flags, F.dev, F.greedy, F.sat, F.unit, F.flags_reserved,
    F.num_hops, F.dev_hop, F.reserved, F.epoch_base,
    F.unit_ns, F.unit_ms, F.epoch_base_ms,
    F.entries, F.entry, F.entry_index, F.entry_hop, F.sid, F.delta, F.delta_ms,
    F.deadline, F.deadline_ms, F.padding,
    F.current_hop, F.current_sid, F.current_deadline, F.current_deadline_ms, F.final_sid,
    F.capture_clock, F.margin, F.margin_ms, F.late, F.quoted,
}

-- Expert infos. The malformed ones mirror the reasons of spec section 6 step 1
-- (and of the golden vectors' expect_reason), so a test can compare them 1:1.
local E = {
    truncated = ProtoExpert.new("tcrh.malformed.truncated",
        "T-CRH truncated", expert.group.MALFORMED, expert.severity.ERROR),
    wrong_type = ProtoExpert.new("tcrh.malformed.wrong_type",
        "Routing Type is not 253", expert.group.MALFORMED, expert.severity.ERROR),
    numhops_zero = ProtoExpert.new("tcrh.malformed.numhops_zero",
        "Num Hops is 0", expert.group.MALFORMED, expert.severity.ERROR),
    sl_gt_numhops = ProtoExpert.new("tcrh.malformed.sl_gt_numhops",
        "Segments Left > Num Hops", expert.group.MALFORMED, expert.severity.ERROR),
    length_mismatch = ProtoExpert.new("tcrh.malformed.length_mismatch",
        "Hdr Ext Len too small for Num Hops", expert.group.MALFORMED, expert.severity.ERROR),
    dev = ProtoExpert.new("tcrh.dev",
        "DEV set: the planned schedule was missed", expert.group.SEQUENCE, expert.severity.NOTE),
    greedy = ProtoExpert.new("tcrh.greedy",
        "GREEDY set: geographic fallback forwarding", expert.group.SEQUENCE, expert.severity.NOTE),
    sat = ProtoExpert.new("tcrh.sat",
        "SAT set: a Delta was clamped to 255", expert.group.PROTOCOL, expert.severity.NOTE),
    late = ProtoExpert.new("tcrh.late_at_capture",
        "Past the current SID's deadline at capture time", expert.group.SEQUENCE, expert.severity.WARN),
    reserved_nonzero = ProtoExpert.new("tcrh.reserved_nonzero",
        "Reserved bits are not zero (accepted, passed on unchanged)", expert.group.PROTOCOL, expert.severity.NOTE),
    padding_nonzero = ProtoExpert.new("tcrh.padding_nonzero",
        "Padding is not zero (accepted, passed on unchanged)", expert.group.PROTOCOL, expert.severity.NOTE),
    dev_hop_odd = ProtoExpert.new("tcrh.dev_hop_inconsistent",
        "Dev Hop does not match the flags", expert.group.PROTOCOL, expert.severity.WARN),
    segleft_unknown = ProtoExpert.new("tcrh.segleft_unknown",
        "Segments Left not found", expert.group.UNDECODED, expert.severity.WARN),
    timebase = ProtoExpert.new("tcrh.timebase_mismatch",
        "Implausible margin: capture clock is not the ChronoRoute clock", expert.group.PROTOCOL,
        expert.severity.NOTE),
    quoted = ProtoExpert.new("tcrh.quoted_in_icmpv6",
        "T-CRH quoted inside an ICMPv6 error: a copy of an earlier packet, no deadline verdict",
        expert.group.SEQUENCE, expert.severity.NOTE),
}
tcrh.experts = {
    E.truncated, E.wrong_type, E.numhops_zero, E.sl_gt_numhops, E.length_mismatch,
    E.dev, E.greedy, E.sat, E.late, E.reserved_nonzero, E.padding_nonzero,
    E.dev_hop_odd, E.segleft_unknown, E.timebase, E.quoted,
}

-- Preferences: how to turn a capture timestamp into the node's unit clock.
local TIMEBASE_ENUM = {
    { 1, "off", TIMEBASE_OFF },
    { 2, "utc", TIMEBASE_UTC },
    { 3, "offset", TIMEBASE_OFFSET },
}
tcrh.prefs.timebase = Pref.enum("Capture timestamps",
    TIMEBASE_UTC,
    "How to read capture timestamps for the margin field. "
    .. "utc: timestamps are Unix-epoch UTC (ChronoRoute Python pcaps); GPS = UTC + 18 s. "
    .. "offset: GPS ns = timestamp ns + the offset below (e.g. ns-3 simulation time + t0_gps). "
    .. "off: do not compute margins.",
    TIMEBASE_ENUM, false)
tcrh.prefs.offset_ns = Pref.string("GPS offset (ns)", "0",
    "Used when 'Capture timestamps' is offset: GPS time in ns = capture timestamp in ns + this "
    .. "integer (it may be negative). For an ns-3 pcap whose timestamps are simulation time, "
    .. "use the run's t0_gps_ns.")

-- Fields of the IPv6 dissector that we read. They must be created at load time.
local f_segleft = Field.new("ipv6.routing.segleft")
local f_hdr_ext_len = Field.new("ipv6.routing.len")
local f_time = Field.new("frame.time_epoch")
local f_icmpv6_type = Field.new("icmpv6.type")

-- ---------------------------------------------------------------- arithmetic

-- Signed 32-bit serial difference a - b in [-2^31, 2^31) (spec section 4).
-- Lua 5.4 integers are 64-bit, so this is exact.
local function serial_diff(a, b)
    return ((a - b + HALF32) & MASK32) - HALF32
end

local function pad8(n)
    return ((n + 7) // 8) * 8
end

-- Units -> milliseconds as a double. units * ns is below 2^53, so the product is
-- exact and the one division is correctly rounded.
local function units_to_ms(units, unit_ns)
    return units * unit_ns / 1000000
end

local function fmt_ms(x)
    -- shortest readable form: 100.6 not 100.60000000000001
    local s = string.format("%.6f", x)
    s = s:gsub("0+$", ""):gsub("%.$", "")
    return s
end

-- The capture time in GPS nanoseconds, or nil when margins are switched off or
-- the offset preference is not an integer. frame.time_epoch is an NSTime with
-- integer seconds and nanoseconds (pinfo.abs_ts is a double and loses ns).
local function capture_gps_ns()
    local mode = tcrh.prefs.timebase
    if mode == TIMEBASE_OFF then return nil end
    local fi = f_time()
    if fi == nil then return nil end
    local t = fi.value
    local t_ns = t.secs * 1000000000 + t.nsecs
    if mode == TIMEBASE_UTC then
        return t_ns + UNIX_TO_GPS_NS
    end
    local off = math.tointeger(tonumber(tcrh.prefs.offset_ns))
    if off == nil then return nil end
    return t_ns + off
end

-- --------------------------------------------------------- locating our bytes

-- Wireshark 4.6 hands a routing-type sub-dissector the bytes AFTER the 4 common
-- bytes (measured by tools/wireshark/tests and sim/tests/test_wireshark_dissector.py:
-- the tvb starts at Flags). Older or newer versions might pass the whole header,
-- so work out which case we are in instead of assuming. The common fields that
-- Wireshark decoded for THIS header sit just before our bytes; a frame can carry
-- several routing headers (encapsulation), so they are matched by byte offset.
local function locate(tvb)
    local start = tvb:offset()
    local sl, hel
    local whole = false
    for _, fi in ipairs({ f_segleft() }) do
        if fi.offset == start - 1 then
            sl = fi.value
            for _, h in ipairs({ f_hdr_ext_len() }) do
                if h.offset == start - 3 then hel = h.value end
            end
            if hel == nil then
                -- Wireshark sized our tvb from Hdr Ext Len: (HEL + 1) * 8 - 4 bytes
                hel = (tvb:reported_len() + 4) // 8 - 1
            end
            return 4, sl, hel
        end
        if fi.offset == start + 3 then
            whole = true                                -- Segments Left is our byte 3
            break
        end
    end
    -- Whole header: either Wireshark's own field says so, or (no field found)
    -- the bytes look like one. Otherwise assume Flags-first with SL unknown,
    -- which the dissector reports instead of guessing.
    if tvb:len() >= 4 and (whole or tvb(2, 1):uint() == ROUTING_TYPE_TCRH) then
        return 0, tvb(3, 1):uint(), tvb(1, 1):uint()
    end
    return 4, nil, nil
end

-- ------------------------------------------------- quoted in an ICMPv6 error

-- An ICMPv6 error message (Parameter Problem, Time Exceeded, ...) carries back
-- as much of the packet that caused it as fits, and Wireshark dissects that
-- copy too, so our dissector also runs on the quoted T-CRH. That header is a
-- snapshot of an OLD packet at the node that rejected it, travelling in a new
-- packet: its Segments Left and deadlines say nothing about the capture time,
-- so a margin or a "late" verdict on it would be wrong (and would inflate the
-- counts of check_pcap.sh). Two independent ways to recognise it:
--   * pinfo.in_error_pkt, which Wireshark sets while it dissects the payload
--     of an ICMP error (measured on tshark 4.6.4);
--   * an ICMPv6 error type (0..127) decoded EARLIER in this frame, i.e. at a
--     smaller byte offset than our header (an ICMPv6 message that itself
--     travels behind a T-CRH is decoded after us, so it does not count).
local function quoted_in_icmpv6_error(tvb, pinfo)
    local ok, flag = pcall(function() return pinfo.in_error_pkt end)
    if ok and flag then return true end
    local start = tvb:offset()
    for _, fi in ipairs({ f_icmpv6_type() }) do
        if fi.offset < start and fi.value < 128 then return true end
    end
    return false
end

-- -------------------------------------------------------------- validation

-- Spec section 6 step 1, in the spec's order; the first failing check decides.
-- Returns nil when the header is valid, else (reason, expert, text).
-- `have` is the number of routing-header bytes we can read (captured).
local function validate(get, have, shift, sl, hel)
    if have < 8 then
        return "truncated", E.truncated, string.format("fewer than 8 bytes (%d)", have)
    end
    if shift == 0 and get(2, 1):uint() ~= ROUTING_TYPE_TCRH then
        return "wrong_type", E.wrong_type, string.format("Routing Type %d", get(2, 1):uint())
    end
    local nhops = get(5, 1):uint()
    if nhops == 0 then
        return "numhops_zero", E.numhops_zero, "Num Hops is 0 (a T-CRH carries 1..255 entries)"
    end
    if sl ~= nil and sl > nhops then
        return "sl_gt_numhops", E.sl_gt_numhops,
            string.format("Segments Left %d > Num Hops %d", sl, nhops)
    end
    local total = (hel + 1) * 8
    local need = pad8(FIXED_BYTES + ENTRY_BYTES * nhops)
    if total < need then
        return "length_mismatch", E.length_mismatch,
            string.format("Hdr Ext Len %d gives %d bytes, %d hops need %d", hel, total, nhops, need)
    end
    if have < total then
        return "truncated", E.truncated,
            string.format("Hdr Ext Len announces %d bytes, only %d captured", total, have)
    end
    return nil
end

-- ----------------------------------------------------------------- dissector

function tcrh.dissector(tvb, pinfo, tree)
    local shift, sl, hel = locate(tvb)
    -- get(o, n): the n bytes at ROUTING-HEADER offset o, or nil if not in our input
    local function get(o, n)
        local p = o - shift
        if p < 0 or p + n > tvb:len() then return nil end
        return tvb(p, n)
    end
    local have = tvb:len() + shift
    if hel == nil then hel = (tvb:reported_len() + shift) // 8 - 1 end

    local t = tree:add(tcrh, tvb())
    t:add(F.input_offset, shift):set_generated()
    local quoted = quoted_in_icmpv6_error(tvb, pinfo)
    t:add(F.quoted, quoted and 1 or 0):set_generated()
    if quoted then
        t:add_proto_expert_info(E.quoted)
    end

    local reason, bad_expert, bad_text = validate(get, have, shift, sl, hel)
    t:add(F.valid, reason == nil and 1 or 0):set_generated()
    if reason ~= nil then
        t:add(F.reason, reason):set_generated()
        t:add_proto_expert_info(bad_expert, bad_expert == E.truncated and ("T-CRH truncated: " .. bad_text) or bad_text)
    end
    if sl == nil then
        t:add_proto_expert_info(E.segleft_unknown, "Segments Left not found: current SID and deadline unknown")
    end

    -- Fixed part: show whatever bytes exist, even for a malformed header.
    local flags_r, nh_r, dh_r, rs_r, ep_r = get(4, 1), get(5, 1), get(6, 1), get(7, 1), get(8, 4)
    local flags, nhops, dev_hop, epoch
    if flags_r ~= nil then
        flags = flags_r:uint()
        local fi = t:add(F.flags, flags_r)
        fi:add(F.dev, flags_r)
        fi:add(F.greedy, flags_r)
        fi:add(F.sat, flags_r)
        fi:add(F.unit, flags_r)
        fi:add(F.flags_reserved, flags_r)
        if flags & FLAG_RESERVED_MASK ~= 0 then
            fi:add_proto_expert_info(E.reserved_nonzero,
                string.format("Reserved flag bits 0x%02x are not zero (accepted, passed on unchanged)",
                    flags & FLAG_RESERVED_MASK))
        end
    end
    if nh_r ~= nil then
        nhops = nh_r:uint()
        t:add(F.num_hops, nh_r)
    end
    if dh_r ~= nil then
        dev_hop = dh_r:uint()
        t:add(F.dev_hop, dh_r)
    end
    if rs_r ~= nil then
        local ri = t:add(F.reserved, rs_r)
        if rs_r:uint() ~= 0 then
            ri:add_proto_expert_info(E.reserved_nonzero, "Reserved byte is not zero (accepted, passed on unchanged)")
        end
    end
    local unit_ns
    if flags ~= nil then
        local uc = (flags >> 4) & 3
        unit_ns = UNIT_NS[uc]
        t:add(F.unit_ns, unit_ns):set_generated()
        t:add(F.unit_ms, units_to_ms(1, unit_ns)):set_generated()
    end
    if ep_r ~= nil then
        epoch = ep_r:uint()
        t:add(F.epoch_base, ep_r)
        t:add(F.epoch_base_ms, ep_r, units_to_ms(epoch, unit_ns)):set_generated()
    end

    -- State flags: worth an expert note each (they are what a reader looks for).
    -- Not for a quoted copy: the packet it shows was already counted when it
    -- was captured itself, and a second note would double the expert counts.
    if flags ~= nil and not quoted then
        if flags & FLAG_DEV ~= 0 then
            local who = (dev_hop == 0) and "the ingress (its first link was down)"
                or string.format("hop %d (late, or its next link was down)", dev_hop or -1)
            t:add_proto_expert_info(E.dev, "DEV set by " .. who .. ": the planned schedule was missed")
        end
        if flags & FLAG_GREEDY ~= 0 then
            t:add_proto_expert_info(E.greedy, "GREEDY set: forwarded by the geographic fallback towards SID[0]")
        end
        if flags & FLAG_SAT ~= 0 then
            t:add_proto_expert_info(E.sat, "SAT set: a Delta was clamped to 255, some deadline is earlier than its budget")
        end
        if dev_hop ~= nil and reason == nil then
            if flags & FLAG_DEV == 0 and dev_hop ~= 0 then
                t:add_proto_expert_info(E.dev_hop_odd, string.format("Dev Hop is %d while DEV is clear (spec 2: 0)", dev_hop))
            elseif dev_hop > nhops then
                t:add_proto_expert_info(E.dev_hop_odd, string.format("Dev Hop %d > Num Hops %d", dev_hop, nhops))
            end
        end
    end

    local summary
    if reason == nil then
        -- Entries, wire order: SID[0] is the final endpoint, SID[h-1] the first hop.
        -- Entry i belongs to hop k = h - i, and D_k = Epoch_Base + sum(Delta[i..h-1]).
        local sids, deadlines = {}, {}
        local run = epoch
        for i = nhops - 1, 0, -1 do
            run = (run + get(FIXED_BYTES + ENTRY_BYTES * i + 2, 1):uint()) & MASK32
            deadlines[i] = run
        end
        local et = t:add(F.entries, get(FIXED_BYTES, ENTRY_BYTES * nhops))
        et:set_text(string.format("Entries: %d (wire order: SID[0] = final endpoint first)", nhops))
        for i = 0, nhops - 1 do
            local o = FIXED_BYTES + ENTRY_BYTES * i
            local sid_r, d_r = get(o, 2), get(o + 2, 1)
            local sid, delta, k = sid_r:uint(), d_r:uint(), nhops - i
            sids[i] = sid
            local e = et:add(F.entry, get(o, ENTRY_BYTES))
            e:set_text(string.format("[%d] hop %d: SID %d, +%d units, arrive by %d (%s ms)%s",
                i, k, sid, delta, deadlines[i], fmt_ms(units_to_ms(deadlines[i], unit_ns)),
                (sl == i) and "  <== current" or ""))
            e:add(F.entry_index, i):set_generated()
            e:add(F.entry_hop, k):set_generated()
            e:add(F.sid, sid_r)
            e:add(F.delta, d_r)
            e:add(F.delta_ms, d_r, units_to_ms(delta, unit_ns)):set_generated()
            e:add(F.deadline, d_r, deadlines[i]):set_generated()
            e:add(F.deadline_ms, d_r, units_to_ms(deadlines[i], unit_ns)):set_generated()
        end
        local used = FIXED_BYTES + ENTRY_BYTES * nhops
        local total = (hel + 1) * 8
        if total > used then
            local pr = get(used, total - used)
            t:add(F.padding, pr)
            for j = 0, pr:len() - 1 do
                if pr(j, 1):uint() ~= 0 then
                    t:add_proto_expert_info(E.padding_nonzero)
                    break
                end
            end
        end
        t:add(F.final_sid, get(FIXED_BYTES, 2)):set_generated()

        if sl ~= nil then
            local k = nhops - sl
            t:add(F.current_hop, k):set_generated()
            if sl < nhops then
                -- the node in the Destination Address checks D_k on arrival
                local dk = deadlines[sl]
                local o = FIXED_BYTES + ENTRY_BYTES * sl
                t:add(F.current_sid, get(o, 2)):set_generated()
                t:add(F.current_deadline, get(o + 2, 1), dk):set_generated()
                t:add(F.current_deadline_ms, get(o + 2, 1), units_to_ms(dk, unit_ns)):set_generated()
                -- no timing verdict on a quoted copy (see quoted_in_icmpv6_error)
                local tg = (not quoted) and capture_gps_ns() or nil
                if tg ~= nil then
                    local now_u = (tg // unit_ns) & MASK32           -- clock_u = floor(t / u) mod 2^32
                    local m = serial_diff(dk, now_u)                 -- margin in units
                    -- "late" exactly as spec 6 step 2 says. It equals m < 0 except
                    -- at the half-range boundary (2^31 units), which is far outside
                    -- the plausible range below anyway.
                    local late = serial_diff(now_u, dk) > 0
                    t:add(F.capture_clock, now_u):set_generated()
                    t:add(F.margin, m):set_generated()
                    local mi = t:add(F.margin_ms, units_to_ms(m, unit_ns))
                    mi:set_generated()
                    if math.abs(m) * unit_ns > PLAUSIBLE_MARGIN_NS then
                        -- A whole path lasts well under a minute (255 x 255 units at
                        -- 1 ms is 65 s). A margin this large means the capture clock
                        -- is not the ChronoRoute GPS clock, so "late" would be noise.
                        mi:add_proto_expert_info(E.timebase, string.format(
                            "Margin of %s ms is implausible: the capture timestamps are probably not "
                            .. "on the ChronoRoute clock (set the tcrh.timebase preference)",
                            fmt_ms(units_to_ms(m, unit_ns))))
                    else
                        t:add(F.late, late and 1 or 0):set_generated()
                        if late then
                            mi:add_proto_expert_info(E.late, string.format(
                                "Past the deadline of SID %d at capture time by %d units (%s ms)",
                                sids[sl], -m, fmt_ms(units_to_ms(-m, unit_ns))))
                        end
                    end
                end
                summary = string.format("SL %d/%d, hop %d -> SID %d by %d", sl, nhops, k, sids[sl], dk)
            else
                summary = string.format("SL %d/%d, at the ingress, first hop SID %d", sl, nhops, sids[nhops - 1])
            end
        else
            summary = string.format("%d hops", nhops)
        end
    else
        summary = "MALFORMED: " .. reason
    end

    local state = ""
    if flags ~= nil then
        if flags & FLAG_DEV ~= 0 then state = state .. " DEV" end
        if flags & FLAG_GREEDY ~= 0 then state = state .. " GREEDY" end
        if flags & FLAG_SAT ~= 0 then state = state .. " SAT" end
    end
    if quoted then
        -- the frame is an ICMPv6 error: its Info column belongs to ICMPv6
        t:set_text(string.format("ChronoRoute T-CRH (quoted in an ICMPv6 error, no deadline verdict), %s%s",
            summary, state))
        return tvb:len()
    end
    t:set_text(string.format("ChronoRoute T-CRH, %s%s", summary, state))
    -- The transport dissector after us rewrites the Info column, so put our text
    -- there (replacing the IPv6 dissector's generic "IPv6 routing") and fence
    -- it: later dissectors then only add after it.
    pinfo.cols.info:set(string.format("[T-CRH %s%s] ", summary, state))
    pinfo.cols.info:fence()
    return tvb:len()
end

DissectorTable.get("ipv6.routing.type"):add(ROUTING_TYPE_TCRH, tcrh)
