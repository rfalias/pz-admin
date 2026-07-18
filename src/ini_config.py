from pathlib import Path


def _move_after(entries: list[dict], anchor_key: str, move_key: str) -> None:
    """Reposition the move_key entry directly after anchor_key, if both are present."""
    move_idx = next((i for i, e in enumerate(entries) if e["key"] == move_key), None)
    anchor_present = any(e["key"] == anchor_key for e in entries)
    if move_idx is None or not anchor_present:
        return
    item = entries.pop(move_idx)
    anchor_idx = next(i for i, e in enumerate(entries) if e["key"] == anchor_key)
    entries.insert(anchor_idx + 1, item)


def parse_ini(path: Path) -> list[dict]:
    """Parse a PZ server .ini file (key=value, '#' comments) into an ordered list of entries."""
    entries = []
    if not path.exists():
        return entries

    pending_comments: list[str] = []
    for raw_line in path.read_text().splitlines():
        stripped = raw_line.strip()
        if stripped == "":
            pending_comments = []
            continue
        if stripped.startswith("#"):
            pending_comments.append(stripped.lstrip("#").strip())
            continue
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            key = key.strip()
            is_bool = value.strip().lower() in ("true", "false")
            entries.append(
                {
                    "key": key,
                    "value": value,
                    "comment": " ".join(pending_comments),
                    "is_bool": is_bool,
                }
            )
            pending_comments = []

    # Mods and WorkshopItems are defined far apart in the stock ini but must be
    # kept in sync with each other, so surface them side by side.
    _move_after(entries, "Mods", "WorkshopItems")
    return entries


# Curated display categories for Server.ini keys. This is a hand-built
# taxonomy (there's no shipped vanilla equivalent of the `page = X` metadata
# mods put in their sandbox-options.txt) - order here is the display order.
# Any key not listed here falls into the trailing "Other" category so a
# future game update that adds new ini keys never makes them disappear.
CATEGORIES: list[tuple[str, list[str]]] = [
    ("General & Chat", [
        "PauseEmpty", "GlobalChat", "ChatStreams", "DisplayUserName",
        "ShowFirstAndLastName", "UsernameDisguises", "HideDisguisedUserName",
        "SwitchZombiesOwnershipEachUpdate", "MouseOverToSeeDisplayName",
        "HidePlayersBehindYou", "MultiplayerStatisticsPeriod",
        "DisableScoreboard", "HideAdminsInPlayerList", "SteamScoreboard",
        "Seed", "ChatMessageCharacterLimit", "ChatMessageSlowModeTime",
        "MapRemotePlayerVisibility",
    ]),
    ("Whitelist & Accounts", [
        "Open", "ServerWelcomeMessage", "MaxAccountsPerUser",
        "AllowNonAsciiUsername", "DropOffWhiteListAfterDeath", "Password",
    ]),
    ("PVP & Safety", [
        "PVP", "PVPLogToolChat", "PVPLogToolFile", "SafetySystem",
        "ShowSafety", "SafetyToggleTimer", "SafetyCooldownTimer",
        "SafetyDisconnectDelay", "PVPMeleeWhileHitReaction",
        "PVPMeleeDamageModifier", "PVPFirearmDamageModifier", "War",
        "WarStartDelay", "WarDuration", "WarSafehouseHitPoints",
        "PlayerBumpPlayer", "CarEngineAttractionModifier",
        "UsePhysicsHitReaction",
    ]),
    ("Spawning & Characters", [
        "SpawnPoint", "SpawnItems", "PlayerRespawnWithSelf",
        "PlayerRespawnWithOther", "AnnounceDeath", "AnnounceAnimalDeath",
        "RemovePlayerCorpsesOnCorpseRemoval", "BloodSplatLifespanDays",
        "SleepAllowed", "SleepNeeded", "KnockedDownAllowed",
        "SneakModeHideFromOtherPlayers", "UltraSpeedDoesnotAffectToAnimals",
        "AllowCoop",
    ]),
    ("Safehouses", [
        "PlayerSafehouse", "AdminSafehouse", "SafehouseAllowTrepass",
        "SafehouseAllowFire", "SafehouseAllowLoot", "SafehouseAllowRespawn",
        "SafehouseDaySurvivedToClaim", "SafeHouseRemovalTime",
        "SafehouseAllowNonResidential", "SafehouseDisableDisguises",
        "MaxSafezoneSize", "SafehousePreventsLootRespawn",
        "DisableSafehouseWhenOwnerConnected", "AllowDestructionBySledgehammer",
        "SledgehammerOnlyInSafehouse",
    ]),
    ("Factions", [
        "Faction", "FactionDaySurvivedToCreate", "FactionPlayersRequiredForTag",
    ]),
    ("Map & World", [
        "Map", "DoLuaChecksum", "SaveWorldEveryMinutes", "NoFire",
        "TrashDeleteAll", "ItemNumbersLimitPerContainer", "FastForwardMultiplier",
    ]),
    ("Mods & Workshop", ["Mods", "WorkshopItems"]),
    ("Server Browser & Steam", [
        "Public", "PublicName", "PublicDescription", "MaxPlayers",
        "PingLimit", "SteamVAC", "DenyLoginOnOverloadedServer",
    ]),
    ("Network & Connection", [
        "DefaultPort", "UDPPort", "ResetID", "ServerPlayerID", "RCONPort",
        "RCONPassword", "UPnP", "SpeedLimit", "LoginQueueEnabled",
        "LoginQueueConnectTimeout", "server_browser_announced_ip",
        "MaxPacketsPerSecond",
    ]),
    ("Voice Chat", ["VoiceEnable", "VoiceMinDistance", "VoiceMaxDistance", "Voice3D"]),
    ("Discord Integration", [
        "DiscordEnable", "DiscordToken", "DiscordChatChannel",
        "DiscordLogChannel", "DiscordCommandChannel", "WebhookAddress",
    ]),
    ("Radio & Moderation", [
        "DisableRadioStaff", "DisableRadioAdmin", "DisableRadioGM",
        "DisableRadioOverseer", "DisableRadioModerator", "DisableRadioInvisible",
        "ClientCommandFilter", "ClientActionLogs", "PerkLogs",
        "BadWordListFile", "GoodWordListFile", "BadWordPolicy",
        "BadWordReplacement", "BanKickGlobalSound",
    ]),
    ("Backups", ["BackupsCount", "BackupsOnStart", "BackupsOnVersionChange", "BackupsPeriod"]),
    ("Vehicles", ["DisableVehicleTowing", "DisableTrailerTowing", "DisableBurntTowing"]),
    ("Anti-Cheat", [
        "AntiCheatSafety", "AntiCheatMovement", "AntiCheatHit",
        "AntiCheatPacket", "AntiCheatPermission", "AntiCheatXP",
        "AntiCheatSafeHouse", "AntiCheatPlayer", "AntiCheatChecksum",
        "AntiCheatItem",
    ]),
]


def categorize(entries: list[dict]) -> list[dict]:
    """Group entries into display categories for server.html.

    Purely a rendering concern: entries keep their original dicts, just
    bucketed. Any key not covered by CATEGORIES lands in a trailing "Other"
    category so new ini keys from a future game update stay visible instead
    of silently vanishing from the page.
    """
    by_key = {e["key"]: e for e in entries}
    used: set[str] = set()
    groups = []
    for name, keys in CATEGORIES:
        group_entries = [by_key[k] for k in keys if k in by_key]
        used.update(k for k in keys if k in by_key)
        if group_entries:
            groups.append({"name": name, "entries": group_entries})
    leftover = [e for e in entries if e["key"] not in used]
    if leftover:
        groups.append({"name": "Other", "entries": leftover})
    return groups


def get_value(entries: list[dict], key: str, default: str = "") -> str:
    entry = next((e for e in entries if e["key"] == key), None)
    return entry["value"] if entry else default


def split_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(";") if v.strip()]


def validate_mods(entries: list[dict]) -> str | None:
    """Warn when a Mods entry doesn't have a matching WorkshopItems id."""
    mods = next((e for e in entries if e["key"] == "Mods"), None)
    workshop = next((e for e in entries if e["key"] == "WorkshopItems"), None)
    if mods is None or workshop is None:
        return None

    mod_ids = split_list(mods["value"])
    workshop_ids = split_list(workshop["value"])
    missing = len(mod_ids) - len(workshop_ids)
    if missing > 0:
        return (
            f"Mods has {len(mod_ids)} entr{'y' if len(mod_ids) == 1 else 'ies'} but "
            f"WorkshopItems only has {len(workshop_ids)} — add the missing Workshop ID"
            f"{'' if missing == 1 else 's'} so every mod can be downloaded."
        )
    return None


def write_ini(path: Path, entries: list[dict]) -> None:
    lines = []
    for entry in entries:
        if entry["comment"]:
            lines.append(f"# {entry['comment']}")
        lines.append(f"{entry['key']}={entry['value']}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip("\n") + "\n")


def diff_entries(old_entries: list[dict], new_entries: list[dict]) -> list[str]:
    """Return one 'key: old -> new' string per changed value, for audit logging."""
    old_values = {e["key"]: e["value"] for e in old_entries}
    diffs = []
    for entry in new_entries:
        old_value = old_values.get(entry["key"], "")
        if entry["value"] != old_value:
            diffs.append(f"{entry['key']}: {old_value!r} -> {entry['value']!r}")
    return diffs


def apply_form(entries: list[dict], form: dict, managed_keys: set[str] | None = None) -> None:
    """Apply submitted form values onto entries.

    `managed_keys` restricts which entries this form submission is allowed to
    touch. Checkboxes only POST when checked, so an absent boolean key is
    normally treated as "unchecked" - but that's only safe for entries the
    form actually has a field for. Without `managed_keys`, a partial form
    (e.g. the Mods page submitting just Mods/WorkshopItems) would silently
    flip every other boolean setting in the ini to false.
    """
    for entry in entries:
        key = entry["key"]
        if managed_keys is not None and key not in managed_keys:
            continue
        if entry["is_bool"]:
            entry["value"] = "true" if key in form else "false"
        elif key in form:
            entry["value"] = form[key]
