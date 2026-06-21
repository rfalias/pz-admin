"""
Best-effort decoder for the binary `data` blob in players.db's networkPlayers
table (Project Zomboid's serialized IsoPlayer character data).

This format is undocumented and proprietary to the game's Java code, reverse
engineered by inspecting real save bytes. It is NOT guaranteed correct and
WILL likely need updates after game version changes.

Design notes for future maintenance:
- Each `extract_*` function is independent and defensive (returns None/[]/{}
  on any parse failure) so a format change in one area can't break the rest
  of the page.
- Sequential, offset-based parsing is only used for the identity block, which
  is anchored to the fixed field name "fitnessMod" (written for every
  character) rather than to absolute byte offsets, so it survives names of
  different lengths.
- Perks/XP/traits are NOT parsed sequentially (the variable-length inventory
  section between them and the identity block makes fixed offsets unusable).
  Instead they're found via a blob-wide scan for known field-name strings.
  Extend KNOWN_PERKS / KNOWN_TRAITS below as new ones are discovered.
"""
import struct

KNOWN_PERKS = [
    "Fitness", "Strength", "Sprinting", "Lightfooted", "Nimble", "Sneak",
    "Axe", "Blunt", "SmallBlunt", "LongBlunt", "SmallBlade", "LongBlade",
    "Spear", "Maintenance", "Woodwork", "Cooking", "Farming", "Doctor",
    "Electricity", "MetalWelding", "Mechanics", "Tailoring", "Aiming",
    "Reloading", "Fishing", "Trapping", "PlantScavenging",
]

# Not exhaustive - extend as more are confirmed against real saves.
KNOWN_TRAITS = [
    "axeman", "stout", "strong", "weak", "athletic", "unfit", "fit",
    "cowardly", "brave", "hardofhearing", "keenhearing", "shortsighted",
    "eagleeyed", "slowhealer", "fasthealer", "highthirst", "lowthirst",
    "speedy", "speeddemon", "resilient", "disorganized", "organized",
    "outdoorsman", "fastreader", "slowreader", "fastlearner", "slowlearner",
    "inconspicuous", "conspicuous", "lucky", "unlucky", "graceful",
    "clumsy", "weakstomach", "irongut", "nightowl", "smoker", "wakeful",
    "sleepyhead", "asthmatic", "underweight", "overweight", "obese",
    "thin", "dextrous", "itchy", "hemophobic",
]


def _read_str(data: bytes, p: int) -> tuple[str, int]:
    n = struct.unpack(">H", data[p:p + 2])[0]
    p += 2
    return data[p:p + n].decode("utf-8", errors="replace"), p + n


def _read_i32(data: bytes, p: int) -> tuple[int, int]:
    return struct.unpack(">i", data[p:p + 4])[0], p + 4


def extract_identity(data: bytes) -> dict | None:
    """Forename/surname/nickname/profession + profession-starting perk levels.

    Anchored on the "fitnessMod" field name + its known 1-byte flag + 8-byte
    double, which is written for every character regardless of name length.
    """
    try:
        anchor = data.index(b"fitnessMod") + len(b"fitnessMod")
        p = anchor + 1 + 8  # skip flag byte + double value
        p += 1 + 4  # skip a flag byte + an unreliable length-ish int32
        forename, p = _read_str(data, p)
        surname, p = _read_str(data, p)
        nickname, p = _read_str(data, p)
        p += 4  # skip flag int32
        profession, p = _read_str(data, p)
        p += 4  # skip a zero int32
        count, p = _read_i32(data, p)
        if not (0 <= count <= 32):
            return None
        starting_perks = {}
        for _ in range(count):
            name, p = _read_str(data, p)
            value, p = _read_i32(data, p)
            starting_perks[name] = value
        voice = None
        try:
            voice, _ = _read_str(data, p)
        except Exception:
            pass
        return {
            "forename": forename or None,
            "surname": surname or None,
            "nickname": nickname or None,
            "profession": profession or None,
            "starting_perks": starting_perks,
            "voice": voice,
        }
    except Exception:
        return None


def _scan_named_values(data: bytes, names: list[str], value_fmt: str, value_size: int, is_valid) -> dict:
    """Scan the whole blob for [u16 len][name][fixed-size value] and keep the
    max valid value seen per name (skills/XP only ever increase, so max is
    the best guess at the "current" value when multiple snapshots exist).

    `is_valid` filters candidates *before* the max comparison, so a
    differently-typed field that happens to share a name (e.g. the XP float
    block reinterpreted as an int32 level) can't crowd out the real value.
    """
    found: dict[str, float] = {}
    for name in names:
        name_bytes = name.encode("utf-8")
        prefix = struct.pack(">H", len(name_bytes)) + name_bytes
        start = 0
        while True:
            idx = data.find(prefix, start)
            if idx == -1:
                break
            value_pos = idx + len(prefix)
            chunk = data[value_pos:value_pos + value_size]
            if len(chunk) == value_size:
                try:
                    value = struct.unpack(value_fmt, chunk)[0]
                    if is_valid(value) and (name not in found or value > found[name]):
                        found[name] = value
                except struct.error:
                    pass
            start = idx + 1
    return found


def extract_perk_levels(data: bytes) -> dict:
    """Best-effort current perk levels (int32), via KNOWN_PERKS scan."""
    try:
        levels = _scan_named_values(data, KNOWN_PERKS, ">i", 4, lambda v: 0 < v <= 10)
        return {k: int(v) for k, v in levels.items()}
    except Exception:
        return {}


def extract_perk_xp(data: bytes) -> dict:
    """Best-effort current perk XP (float32), via KNOWN_PERKS scan."""
    try:
        xp = _scan_named_values(data, KNOWN_PERKS, ">f", 4, lambda v: 0 <= v < 10_000_000)
        return {k: round(v, 1) for k, v in xp.items()}
    except Exception:
        return {}


def extract_traits(data: bytes) -> list[str]:
    """Best-effort trait list, matched against the curated KNOWN_TRAITS list.

    Trait IDs are observed written as "base:<id>" (lowercase), same convention
    as profession (e.g. "base:lumberjack"). Also checks bare/capitalized forms
    in case other mod namespaces or formats are encountered.
    """
    found = []
    try:
        for trait in KNOWN_TRAITS:
            variants = (trait, trait.capitalize(), f"base:{trait}")
            for variant in variants:
                name_bytes = variant.encode("utf-8")
                prefix = struct.pack(">H", len(name_bytes)) + name_bytes
                if prefix in data:
                    found.append(trait)
                    break
    except Exception:
        return []
    return found


def parse_character(data: bytes) -> dict:
    """Combine all best-effort extractors into one dict. Never raises."""
    identity = extract_identity(data) or {}
    return {
        **identity,
        "perk_levels": extract_perk_levels(data),
        "perk_xp": extract_perk_xp(data),
        "traits": extract_traits(data),
    }
