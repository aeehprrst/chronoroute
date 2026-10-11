-- Test helper (not a plugin): loads the Lua file named by the environment
-- variable CR_LUA_UNDER_TEST inside a STRICT environment and reports, on
-- stderr, every global it writes ("LEAK <name>") and every undefined global it
-- reads ("UNDEFINED <name>"), at load time and while it dissects packets.
--
-- Why not just compare _G before and after? Wireshark 4.6 runs each script in
-- its own environment, so a global set by one script never appears in another
-- script's _G (measured): such a comparison could not see a leak at all.
-- Here the file's _ENV is a proxy table, so every global access passes through
-- the two functions below.
--
-- Usage (what sim/tests/test_wireshark_dissector.py does):
--   CR_LUA_UNDER_TEST=tools/wireshark/tcrh.lua \
--     tshark -r x.pcap -X lua_script:tools/wireshark/tests/strict_load.lua -V
local path = os.getenv("CR_LUA_UNDER_TEST")
if path == nil or path == "" then
    io.stderr:write("strict_load.lua: set CR_LUA_UNDER_TEST to the file to load\n")
    return
end

local real_globals = _G
local env = setmetatable({}, {
    __index = function(_, name)
        local value = real_globals[name]
        if value == nil then
            io.stderr:write("UNDEFINED ", tostring(name), "\n")
        end
        return value
    end,
    __newindex = function(t, name, value)
        io.stderr:write("LEAK ", tostring(name), "\n")
        rawset(t, name, value)
    end,
})

-- Wireshark replaces loadfile() with its own version that ignores the
-- environment argument (measured: a leak went unnoticed), so read the text and
-- use load(), which honours it.
local fh, open_err = io.open(path, "r")
if fh == nil then
    io.stderr:write("strict_load.lua: cannot open ", path, ": ", tostring(open_err), "\n")
    return
end
local text = fh:read("a")
fh:close()
local chunk, err = load(text, "@" .. path, "t", env)
if chunk == nil then
    io.stderr:write("strict_load.lua: cannot load ", path, ": ", tostring(err), "\n")
    return
end
chunk()
io.stderr:write("STRICT_LOADED ", path, "\n")
