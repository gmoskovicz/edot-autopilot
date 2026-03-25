--[[
================================================================
FILE:        game_server.lua
DESCRIPTION: Multiplayer game server event handler
             Manages player matchmaking, in-game economy
             transactions, and achievement unlock events.

RUNTIME:     LuaJIT 2.1 (embedded in game engine)
ENGINE:      Custom game server (C++ + Lua scripting)
REDIS:       Session state and player data
SCHEDULE:    Persistent daemon, event-driven
================================================================
--]]

local json   = require("cjson")
local redis  = require("resty.redis")

-- ---- Configuration ------------------------------------------
local CFG = {
    server_id    = "GS-EAST-04",
    region       = "us-east-1",
    max_players  = 1000,
    redis_host   = "10.0.10.5",
    redis_port   = 6379,
    redis_db     = 2,
}

-- ---- Redis helper -------------------------------------------
local function get_redis()
    local r = redis:new()
    r:set_timeout(200)  -- 200ms
    local ok, err = r:connect(CFG.redis_host, CFG.redis_port)
    if not ok then
        error("Redis connect failed: " .. (err or "unknown"))
    end
    r:select(CFG.redis_db)
    return r
end

-- ================================================================
-- matchmaker.create_session — allocate a game session for players
-- ================================================================
local matchmaker = {}

function matchmaker.create_session(player_ids, map_name, game_mode)
    local session_id = "MATCH-" .. string.format("%08X", math.random(0, 0xFFFFFFFF))

    -- Verify all players are online (Redis HGET)
    local r = get_redis()
    local valid_players = {}
    for _, pid in ipairs(player_ids) do
        local status, _ = r:hget("player:" .. pid, "status")
        if status == "online" or status == false then
            table.insert(valid_players, pid)
        end
    end
    r:close()

    -- Allocate dedicated game server
    local server_ip = "10.2." .. math.random(1, 10) .. "." .. math.random(100, 200)
    local server_port = 27000 + math.random(0, 999)

    -- Persist session record in Redis
    local r2 = get_redis()
    r2:hmset("session:" .. session_id,
        "map",          map_name,
        "mode",         game_mode,
        "player_count", #player_ids,
        "server_ip",    server_ip,
        "server_port",  server_port,
        "created_at",   os.time(),
        "status",       "active"
    )
    r2:expire("session:" .. session_id, 7200)  -- 2h TTL
    r2:close()

    print(string.format("[MATCH] %s  map=%s  mode=%s  players=%d  server=%s:%d",
        session_id, map_name, game_mode, #player_ids, server_ip, server_port))

    return session_id
end

-- ================================================================
-- economy.process_purchase — handle in-game item purchase
-- ================================================================
local economy = {}

function economy.process_purchase(player_id, item_id, coins, currency)
    local tx_id = "TX-" .. string.format("%010X", math.random(0, 0xFFFFFFFF))

    local r = get_redis()

    -- Debit player's coin balance
    if coins > 0 then
        local current_coins, _ = r:hget("player:" .. player_id, "gold_coins")
        current_coins = tonumber(current_coins) or 0
        if current_coins < coins then
            r:close()
            error("Insufficient coins: have=" .. current_coins .. " need=" .. coins)
        end
        r:hset("player:" .. player_id, "gold_coins", current_coins - coins)
    end

    -- Grant item to player inventory
    r:sadd("inventory:" .. player_id, item_id)

    -- Record transaction
    r:hmset("txn:" .. tx_id,
        "player_id",  player_id,
        "item_id",    item_id,
        "coins",      coins,
        "currency",   currency,
        "timestamp",  os.time()
    )
    r:expire("txn:" .. tx_id, 86400 * 30)  -- 30-day audit retention

    r:close()

    print(string.format("[PURCHASE] %s  player=%s  item=%s  cost=%d %s",
        tx_id, player_id, item_id, coins, currency))

    return tx_id
end

-- ================================================================
-- achievements.unlock — award achievement to player
-- ================================================================
local achievements = {}

function achievements.unlock(player_id, achievement_id, xp_reward, is_rare)
    -- Check if already unlocked
    local r = get_redis()
    local already_unlocked = r:sismember("achievements:" .. player_id, achievement_id)

    if already_unlocked == 1 then
        r:close()
        return false  -- already have it
    end

    -- Grant achievement and XP
    r:sadd("achievements:" .. player_id, achievement_id)
    local current_xp = tonumber(r:hget("player:" .. player_id, "xp") or "0") or 0
    r:hset("player:" .. player_id, "xp", current_xp + xp_reward)

    r:close()

    local rarity = is_rare and " [RARE]" or ""
    print(string.format("[ACHIEVEMENT] player=%s  %s  xp=+%d%s",
        player_id, achievement_id, xp_reward, rarity))

    return true
end

-- ================================================================
-- MAIN — process events from stdin (JSON, one per line)
-- ================================================================
math.randomseed(os.time())

local events_processed = 0
local errors = 0

print("=== Game Server Event Processor starting ===")
print("Server: " .. CFG.server_id .. " | Region: " .. CFG.region)
print("")

for line in io.lines() do
    if line ~= "" then
        local ok, event = pcall(json.decode, line)
        if not ok then
            io.stderr:write("JSON parse error: " .. line .. "\n")
            errors = errors + 1
        else
            local status, err = pcall(function()
                local etype = event.type
                if etype == "match_create" then
                    matchmaker.create_session(event.player_ids, event.map, event.mode)
                elseif etype == "purchase" then
                    economy.process_purchase(event.player_id, event.item,
                                             event.coins or 0, event.currency or "gold")
                elseif etype == "achievement" then
                    achievements.unlock(event.player_id, event.achievement,
                                        event.xp_reward or 0, event.rare or false)
                else
                    io.stderr:write("Unknown event type: " .. tostring(etype) .. "\n")
                end
            end)

            if not status then
                io.stderr:write("Event error: " .. tostring(err) .. "\n")
                errors = errors + 1
            end

            events_processed = events_processed + 1
        end
    end
end

print("\n=== Summary ===")
print("Events processed: " .. events_processed)
print("Errors:           " .. errors)
