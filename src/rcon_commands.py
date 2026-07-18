"""
Declarative catalog of Project Zomboid RCON commands, used to drive the
Remote Control tab's form UI. The command keyword used here is the RCON
command name itself (no leading slash - that's only used by the in-game
chat command equivalent, which sometimes has a different name, e.g. the
"kick" RCON command corresponds to the "/kickuser" chat command).

Each param has a "type" controlling how it's rendered and how its value is
folded into the final command string (see static/remote.js):
- "text": free text. quoted=True wraps the value in double quotes.
- "number": numeric input, unquoted.
- "bool_flag": yes/no dropdown, emits a bare "-true"/"-false" token.
- "flag_bool": checkbox, emits a bare flag token (e.g. "-ip") if checked.
- "flag_text": text input tied to a flag name, emits `flag "value"` if non-empty.
- "select": dropdown from a fixed `options` list, unquoted.
- "coords": three number inputs (x, y, z), joined as "x,y,z" with no spaces.
- "item": text input with a searchable datalist of known PZ items (see
  items_index.py / /shops/items-index.json), same lookup used by the Shops
  stock editor. Selecting a suggestion resolves to its module.item id before
  the command is built; typing an exact id directly (e.g. for an item not
  yet in the index) still works unquoted, same as "text".

A param is omitted entirely from the built command if it's not required and
left blank - PZ commands generally treat a missing optional arg as "use the
issuer" or "use the default", not an empty string.
"""

ACCESS_LEVELS = ["admin", "moderator", "overseer", "gm", "observer", "user"]
LOG_TYPES = [
    "general", "network", "multiplayer", "voice", "packet", "networkfiledebug",
    "lua", "mod", "sound", "zombie", "combat", "objects", "fireplace", "radio",
    "maploading", "clothing", "animation", "asset", "script", "shader", "input",
    "recipe", "actionsystem", "isoregion", "unitests", "fileio", "ownership",
    "death", "damage", "statistic", "vehicle", "checksum",
]
LOG_LEVELS = ["trace", "debug", "general", "warning", "error"]

COMMANDS = [
    {
        "name": "additem", "description": "Give an item to a player (yourself if no username given).",
        "params": [
            {"name": "username", "label": "Username", "type": "text", "quoted": True},
            {"name": "item", "label": "Item", "type": "item", "required": True, "placeholder": "Base.Axe"},
            {"name": "count", "label": "Count", "type": "number"},
        ],
    },
    {
        "name": "addkey", "description": "Give a key to a player (yourself if no username given).",
        "params": [
            {"name": "username", "label": "Username", "type": "text", "quoted": True},
            {"name": "keyId", "label": "Key ID", "type": "text", "required": True, "quoted": True},
            {"name": "name", "label": "Key name", "type": "text", "quoted": True},
        ],
    },
    {
        "name": "addsteamid", "description": "Add a SteamID to the server's allowed list.",
        "params": [{"name": "steamid", "label": "SteamID", "type": "text", "required": True, "quoted": True}],
    },
    {
        "name": "addtosafehouse", "description": "Add a player to a safehouse.",
        "params": [
            {"name": "title", "label": "Safehouse title", "type": "text", "required": True, "quoted": True},
            {"name": "username", "label": "Username", "type": "text", "required": True, "quoted": True},
        ],
    },
    {
        "name": "adduser", "description": "Add a new user to a whitelisted server.",
        "params": [
            {"name": "username", "label": "Username", "type": "text", "required": True, "quoted": True},
            {"name": "password", "label": "Password", "type": "text", "required": True, "quoted": True},
        ],
    },
    {
        "name": "addvehicle", "description": "Spawn a vehicle at a player or coordinates.",
        "params": [
            {"name": "script", "label": "Vehicle script", "type": "text", "required": True, "quoted": True, "placeholder": "Base.VanAmbulance"},
            {"name": "target", "label": "Username or x,y,z", "type": "text", "required": True, "quoted": True},
        ],
    },
    {
        "name": "addxp", "description": "Give XP to a player.",
        "params": [
            {"name": "username", "label": "Username", "type": "text", "required": True, "quoted": True},
            {"name": "perkxp", "label": "Perk=XP", "type": "text", "required": True, "placeholder": "Woodwork=2"},
            {"name": "value", "label": "Apply XP multiplier", "type": "bool_flag"},
        ],
    },
    {"name": "alarm", "description": "Sound a building alarm at the admin's position.", "params": []},
    {
        "name": "banid", "description": "Ban a SteamID.",
        "params": [{"name": "steamid", "label": "SteamID", "type": "text", "required": True}],
        "destructive": True,
    },
    {
        "name": "banip", "description": "Ban an IP address.",
        "params": [{"name": "ip", "label": "IP address", "type": "text", "required": True}],
        "destructive": True,
    },
    {
        "name": "banuser", "description": "Ban a user, optionally also banning their IP.",
        "params": [
            {"name": "username", "label": "Username", "type": "text", "required": True, "quoted": True},
            {"name": "ip", "label": "Also ban IP", "type": "flag_bool", "flag": "-ip"},
            {"name": "reason", "label": "Reason", "type": "flag_text", "flag": "-r", "quoted": True},
        ],
        "destructive": True,
    },
    {
        "name": "changeoption", "description": "Change a server option.",
        "params": [
            {"name": "optionName", "label": "Option name", "type": "text", "required": True},
            {"name": "newValue", "label": "New value", "type": "text", "required": True, "quoted": True},
        ],
    },
    {"name": "checkModsNeedUpdate", "description": "Check whether any mod needs an update (writes to log).", "params": []},
    {"name": "chopper", "description": "Place a helicopter event on a random player.", "params": []},
    {
        "name": "createhorde", "description": "Spawn a zombie horde near a player (or yourself).",
        "params": [
            {"name": "count", "label": "Count", "type": "number", "required": True},
            {"name": "username", "label": "Username", "type": "text", "quoted": True},
        ],
    },
    {"name": "createhorde2", "description": "Spawn a zombie horde (variant).", "params": []},
    {
        "name": "godmod", "description": "Make a player invincible (yourself if no username given).",
        "params": [
            {"name": "username", "label": "Username", "type": "text", "quoted": True},
            {"name": "value", "label": "Enabled", "type": "bool_flag", "required": True},
        ],
    },
    {
        "name": "godmodplayer", "description": "Make a specific player invincible.",
        "params": [
            {"name": "username", "label": "Username", "type": "text", "required": True, "quoted": True},
            {"name": "value", "label": "Enabled", "type": "bool_flag", "required": True},
        ],
    },
    {"name": "gunshot", "description": "Place a gunshot sound on a random player.", "params": []},
    {
        "name": "help", "description": "List all commands, or show help for one command.",
        "params": [{"name": "command", "label": "Command", "type": "text", "quoted": True}],
    },
    {
        "name": "invisible", "description": "Make a player invisible to zombies (yourself if no username given).",
        "params": [
            {"name": "username", "label": "Username", "type": "text", "quoted": True},
            {"name": "value", "label": "Enabled", "type": "bool_flag", "required": True},
        ],
    },
    {
        "name": "invisibleplayer", "description": "Make a specific player invisible to zombies.",
        "params": [
            {"name": "username", "label": "Username", "type": "text", "required": True, "quoted": True},
            {"name": "value", "label": "Enabled", "type": "bool_flag", "required": True},
        ],
    },
    {
        "name": "kick", "description": "Kick a user, optionally with a reason.",
        "params": [
            {"name": "username", "label": "Username", "type": "text", "required": True, "quoted": True},
            {"name": "reason", "label": "Reason", "type": "flag_text", "flag": "-r", "quoted": True},
        ],
        "destructive": True,
    },
    {
        "name": "kickfromsafehouse", "description": "Remove a player from a safehouse.",
        "params": [
            {"name": "title", "label": "Safehouse title", "type": "text", "required": True, "quoted": True},
            {"name": "username", "label": "Username", "type": "text", "required": True, "quoted": True},
        ],
    },
    {
        "name": "lightning", "description": "Trigger lightning near a player (yourself if no username given).",
        "params": [{"name": "username", "label": "Username", "type": "text", "quoted": True}],
    },
    {
        "name": "log", "description": "Set the server's log level for a log type.",
        "params": [
            {"name": "type", "label": "Type", "type": "select", "required": True, "options": LOG_TYPES, "quoted": True},
            {"name": "level", "label": "Level", "type": "select", "required": True, "options": LOG_LEVELS, "quoted": True},
        ],
    },
    {
        "name": "noclip", "description": "Toggle a player passing through walls (yourself if no username given).",
        "params": [
            {"name": "username", "label": "Username", "type": "text", "quoted": True},
            {"name": "value", "label": "Enabled", "type": "bool_flag"},
        ],
    },
    {"name": "players", "description": "List all connected players.", "params": []},
    {"name": "quit", "description": "Save and quit the server.", "params": [], "destructive": True},
    {"name": "releasesafehouse", "description": "Release a safehouse you own.", "params": []},
    {"name": "reloadalllua", "description": "Reload all Lua scripts on the server.", "params": []},
    {
        "name": "reloadlua", "description": "Reload a single Lua script.",
        "params": [{"name": "filename", "label": "Filename", "type": "text", "required": True, "quoted": True}],
    },
    {"name": "reloadoptions", "description": "Reload server options (ServerOptions.ini) and send to clients.", "params": []},
    {
        "name": "removeitem", "description": "Remove items from yourself.",
        "params": [
            {"name": "item", "label": "Item", "type": "item", "required": True, "placeholder": "Base.Axe"},
            {"name": "count", "label": "Count (0 = all)", "type": "number"},
        ],
    },
    {
        "name": "removemapsymbolsforuser", "description": "Remove all shared map symbols for a user.",
        "params": [{"name": "username", "label": "Username", "type": "text", "required": True, "quoted": True}],
    },
    {
        "name": "removesteamid", "description": "Remove a SteamID from the allowed list.",
        "params": [{"name": "steamid", "label": "SteamID", "type": "text", "required": True, "quoted": True}],
    },
    {
        "name": "removeuserfromwhitelist", "description": "Remove a user from the whitelist.",
        "params": [{"name": "username", "label": "Username", "type": "text", "required": True, "quoted": True}],
        "destructive": True,
    },
    {"name": "removezombies", "description": "Remove zombies from the server.", "params": []},
    {"name": "save", "description": "Save the current world.", "params": []},
    {
        "name": "servermsg", "description": "Broadcast a message to all connected players.",
        "params": [{"name": "message", "label": "Message", "type": "text", "required": True, "quoted": True}],
    },
    {
        "name": "setaccesslevel", "description": "Set a player's access level.",
        "params": [
            {"name": "username", "label": "Username", "type": "text", "required": True, "quoted": True},
            {"name": "accesslevel", "label": "Access level", "type": "select", "required": True, "options": ACCESS_LEVELS, "quoted": True},
        ],
    },
    {
        "name": "setpassword", "description": "Change a user's password.",
        "params": [
            {"name": "username", "label": "Username", "type": "text", "required": True, "quoted": True},
            {"name": "newpassword", "label": "New password", "type": "text", "required": True, "quoted": True},
        ],
    },
    {"name": "showoptions", "description": "Show the current server options and values.", "params": []},
    {
        "name": "startrain", "description": "Start rain on the server.",
        "params": [{"name": "intensity", "label": "Intensity (1-100)", "type": "number"}],
    },
    {
        "name": "startstorm", "description": "Start a storm on the server.",
        "params": [{"name": "duration", "label": "Duration (game hours)", "type": "number"}],
    },
    {"name": "stoprain", "description": "Stop rain on the server.", "params": []},
    {"name": "stopweather", "description": "Stop all weather on the server.", "params": []},
    {
        "name": "stats", "description": "Set/clear server statistic reporting.",
        "params": [
            {"name": "mode", "label": "Mode", "type": "select", "required": True, "options": ["none", "file", "console", "all"]},
            {"name": "period", "label": "Period", "type": "number"},
        ],
    },
    {
        "name": "teleport", "description": "Teleport to a player, or one player to another.",
        "params": [
            {"name": "player1", "label": "Player", "type": "text", "required": True, "quoted": True},
            {"name": "player2", "label": "To player", "type": "text", "quoted": True},
        ],
    },
    {
        "name": "teleportplayer", "description": "Teleport one player to another.",
        "params": [
            {"name": "player1", "label": "Player", "type": "text", "required": True, "quoted": True},
            {"name": "player2", "label": "To player", "type": "text", "required": True, "quoted": True},
        ],
    },
    {
        "name": "teleportto", "description": "Teleport to coordinates.",
        "params": [{"name": "coords", "label": "Coordinates", "type": "coords", "required": True}],
    },
    {
        "name": "thunder", "description": "Trigger thunder near a player (yourself if no username given).",
        "params": [{"name": "username", "label": "Username", "type": "text", "quoted": True}],
    },
    {
        "name": "unbanid", "description": "Unban a SteamID.",
        "params": [{"name": "steamid", "label": "SteamID", "type": "text", "required": True}],
    },
    {
        "name": "unbanip", "description": "Unban an IP address.",
        "params": [{"name": "ip", "label": "IP address", "type": "text", "required": True}],
    },
    {
        "name": "unbanuser", "description": "Unban a player.",
        "params": [{"name": "username", "label": "Username", "type": "text", "required": True, "quoted": True}],
    },
    {
        "name": "voiceban", "description": "Block or unblock voice chat from a user.",
        "params": [
            {"name": "username", "label": "Username", "type": "text", "required": True, "quoted": True},
            {"name": "value", "label": "Blocked", "type": "bool_flag", "required": True},
        ],
    },
    {
        "name": "worldgen", "description": "Control the full world generator.",
        "params": [{"name": "action", "label": "Action", "type": "select", "required": True, "options": ["start", "recheck", "stop", "status"]}],
        "destructive": True,
    },
]
