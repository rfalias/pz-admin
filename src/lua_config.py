import re
from pathlib import Path

_ASSIGN_RE = re.compile(r"^(\w+)\s*=\s*(.*)$")
_HEADER_RE = re.compile(r"^(\w+)\s*=\s*\{$")
_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")


def _infer_value(raw: str) -> tuple[str, str]:
    raw = raw.strip()
    if raw.endswith(","):
        raw = raw[:-1].strip()
    if raw.lower() in ("true", "false"):
        return raw.lower(), "bool"
    if _NUMBER_RE.match(raw):
        return raw, "number"
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1], "string"
    return raw, "raw"


def _parse_block(lines: list[str], i: int) -> tuple[list[dict], int]:
    items: list[dict] = []
    pending_comments: list[str] = []
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped == "":
            i += 1
            continue
        if stripped in ("}", "},"):
            return items, i + 1
        if stripped.startswith("--"):
            pending_comments.append(stripped[2:].strip())
            i += 1
            continue
        match = _ASSIGN_RE.match(stripped)
        if not match:
            i += 1
            continue
        key, rest = match.groups()
        rest = rest.strip()
        if rest == "{":
            children, i = _parse_block(lines, i + 1)
            items.append(
                {
                    "key": key,
                    "type": "table",
                    "children": children,
                    "comment": " ".join(pending_comments),
                }
            )
        elif rest in ("{}", "{},"):
            items.append(
                {
                    "key": key,
                    "type": "table",
                    "children": [],
                    "comment": " ".join(pending_comments),
                }
            )
            i += 1
        else:
            value, vtype = _infer_value(rest)
            items.append(
                {
                    "key": key,
                    "type": vtype,
                    "value": value,
                    "comment": " ".join(pending_comments),
                }
            )
            i += 1
        pending_comments = []
    return items, i


def parse_sandbox(path: Path) -> tuple[list[dict], str]:
    """Parse a PZ '<server>_SandboxVars.lua' file into a nested list of entries."""
    var_name = "SandboxVars"
    if not path.exists():
        return [], var_name

    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        match = _HEADER_RE.match(line.strip())
        if match:
            var_name = match.group(1)
            items, _ = _parse_block(lines, i + 1)
            return items, var_name
    return [], var_name


# Curated display categories for the vanilla SandboxVars.lua leaf settings
# (the ones sitting outside any mod's own named table). There's no shipped
# vanilla equivalent of the `page = X` metadata mods put in their own
# sandbox-options.txt, so this is a hand-built taxonomy from the keys' own
# names/comments. Order here is the display order. Any key not listed here
# falls into the trailing "Other" category so a future game update that adds
# new sandbox keys never makes them disappear.
LEAF_CATEGORIES: list[tuple[str, list[str]]] = [
    ("World & Time", [
        "DayLength", "StartYear", "StartMonth", "StartDay", "StartTime",
        "DayNightCycle", "ClimateCycle", "FogCycle", "Temperature", "Rain",
        "TimeSinceApo", "EndRegen", "NightDarkness", "NightLength",
        "MaxFogIntensity", "MaxRainFxIntensity", "EnableSnowOnGround",
    ]),
    ("Zombies (Population & Behavior)", [
        "Zombies", "Distribution", "ZombieVoronoiNoise", "ZombieRespawn",
        "ZombieMigrate", "HoursForCorpseRemoval", "DecayingCorpseHealthImpact",
        "ZombieHealthImpact", "AttackBlockMovements", "ZombieAttractionMultiplier",
        "MultiHitZombies", "RearVulnerability", "SirenEffectsZombies",
        "MaximumRatIndex", "DaysUntilMaximumRatIndex", "MaggotSpawn",
    ]),
    ("Utilities & Buildings", [
        "WaterShut", "ElecShut", "AlarmDecay", "WaterShutModifier",
        "ElecShutModifier", "AlarmDecayModifier", "Alarm", "LockedHouses",
        "GeneratorFuelConsumption", "GeneratorSpawning", "AllowExteriorGenerator",
        "EnableTaintedWaterText", "LightBulbLifespan", "GeneratorTileRange",
        "GeneratorVerticalPowerRange",
    ]),
    ("Loot & Item Spawns", [
        "FoodLootNew", "LiteratureLootNew", "SkillBookLoot", "RecipeResourceLoot",
        "MedicalLootNew", "SurvivalGearsLootNew", "CannedFoodLootNew",
        "WeaponLootNew", "RangedWeaponLootNew", "AmmoLootNew", "MechanicsLootNew",
        "OtherLootNew", "ClothingLootNew", "ContainerLootNew", "KeyLootNew",
        "MediaLootNew", "MementoLootNew", "CookwareLootNew", "MaterialLootNew",
        "FarmingLootNew", "ToolLootNew", "RollsMultiplier", "LootItemRemovalList",
        "RemoveStoryLoot", "RemoveZombieLoot", "ZombiePopLootEffect",
        "InsaneLootFactor", "ExtremeLootFactor", "RareLootFactor",
        "NormalLootFactor", "CommonLootFactor", "AbundantLootFactor",
        "SeenHoursPreventLootRespawn", "HoursForLootRespawn",
        "MaxItemsForLootRespawn", "ConstructionPreventsLootRespawn",
        "WorldItemRemovalList", "HoursForWorldItemRemoval",
        "ItemRemovalListBlacklistToggle", "MaximumLootedBuildingRooms",
        "MaximumLooted", "DaysUntilMaximumLooted", "RuralLooted",
        "MaximumDiminishedLoot", "DaysUntilMaximumDiminishedLoot",
    ]),
    ("World Generation & Exploration", [
        "ErosionSpeed", "ErosionDays", "NatureAbundance", "AnnotatedMapChance",
        "SurvivorHouseChance", "VehicleStoryChance", "ZoneStoryChance",
        "ClayLakeChance", "ClayRiverChance",
    ]),
    ("Farming, Fishing & Foraging", [
        "Farming", "CompostTime", "PlantResilience", "PlantAbundance",
        "FishAbundance", "KillInsideCrops", "PlantGrowingSeasons",
        "PlaceDirtAboveground", "FarmingSpeedNew", "FarmingAmountNew",
    ]),
    ("Character & Survival Stats", [
        "StatsDecrease", "StarterKit", "Nutrition", "FoodRotSpeed", "FridgeFactor",
        "CharacterFreePoints", "ConstructionBonusPoints", "BoneFracture",
        "InjurySeverity", "BloodLevel", "ClothingDegradation",
        "DaysForRottenFoodRemoval", "AllClothesUnlocked", "MetaKnowledge",
        "SeeNotLearntRecipe", "EnablePoisoning", "LevelForMediaXPCutoff",
        "LevelForDismantleXPCutoff", "BloodSplatLifespanDays", "LiteratureCooldown",
        "NegativeTraitsPenalty", "MinutesPerPage", "MuscleStrainFactor",
        "DiscomfortFactor", "WoundInfectionFactor", "NoBlackClothes", "EasyClimbing",
    ]),
    ("Fire", ["FireSpread", "MaximumFireFuelHours"]),
    ("Vehicles", [
        "EnableVehicles", "CarSpawnRate", "VehicleEasyUse", "InitialGas",
        "FuelStationGasInfinite", "FuelStationGasMin", "FuelStationGasMax",
        "FuelStationGasEmptyChance", "LockedCar", "CarGasConsumption",
        "CarGeneralCondition", "CarDamageOnImpact", "DamageToPlayerFromHitByACar",
        "TrafficJam", "CarAlarm", "PlayerDamageFromCrash", "SirenShutoffHours",
        "ChanceHasGas", "RecentlySurvivorVehicles",
    ]),
    ("Animals", [
        "AnimalStatsModifier", "AnimalMetaStatsModifier", "AnimalPregnancyTime",
        "AnimalAgeModifier", "AnimalMilkIncModifier", "AnimalWoolIncModifier",
        "AnimalRanchChance", "AnimalGrassRegrowTime", "AnimalMetaPredator",
        "AnimalMatingSeason", "AnimalEggHatch", "AnimalSoundAttractZombies",
        "AnimalTrackChance", "AnimalPathChance",
    ]),
    ("Meta Events", ["Helicopter", "MetaEvent", "SleepingEvent"]),
    ("Firearms & Combat", [
        "FirearmUseDamageChance", "FirearmNoiseMultiplier", "FirearmJamMultiplier",
        "FirearmMoodleMultiplier", "FirearmWeatherMultiplier", "FirearmHeadGearEffect",
    ]),
]


def categorize_leaves(items: list[dict]) -> list[dict]:
    """Group top-level (non-table) sandbox settings into display categories.

    Purely a rendering concern for sandbox.html: items keep their original
    dicts, just bucketed. Any key not covered by LEAF_CATEGORIES lands in a
    trailing "Other" category so new sandbox keys from a future game update
    stay visible instead of silently vanishing from the page.
    """
    by_key = {i["key"]: i for i in items}
    used: set[str] = set()
    groups = []
    for name, keys in LEAF_CATEGORIES:
        group_items = [by_key[k] for k in keys if k in by_key]
        used.update(k for k in keys if k in by_key)
        if group_items:
            groups.append({"name": name, "settings": group_items})
    leftover = [i for i in items if i["key"] not in used]
    if leftover:
        groups.append({"name": "Other", "settings": leftover})
    return groups


def _format_value(item: dict) -> str:
    if item["type"] == "string":
        return f'"{item["value"]}"'
    return item["value"]


def _render_block(items: list[dict], indent: int) -> list[str]:
    pad = "    " * indent
    out = []
    for item in items:
        if item.get("comment"):
            out.append(f"{pad}-- {item['comment']}")
        if item["type"] == "table":
            out.append(f"{pad}{item['key']} = {{")
            out.extend(_render_block(item["children"], indent + 1))
            out.append(f"{pad}}},")
        else:
            out.append(f"{pad}{item['key']} = {_format_value(item)},")
    return out


def render_sandbox(items: list[dict], var_name: str = "SandboxVars") -> str:
    lines = [f"{var_name} = {{"]
    lines.extend(_render_block(items, 1))
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_sandbox(path: Path, items: list[dict], var_name: str = "SandboxVars") -> None:
    path.write_text(render_sandbox(items, var_name))


def diff_items(old_items: list[dict], new_items: list[dict], prefix: str = "") -> list[str]:
    """Return one 'dotted.path: old -> new' string per changed leaf value, for audit logging."""
    old_by_key = {i["key"]: i for i in old_items}
    diffs = []
    for item in new_items:
        path = f"{prefix}{item['key']}"
        old = old_by_key.get(item["key"])
        if item["type"] == "table":
            old_children = old["children"] if old and old.get("type") == "table" else []
            diffs.extend(diff_items(old_children, item["children"], prefix=f"{path}."))
        else:
            old_value = old["value"] if old and "value" in old else None
            if old_value != item["value"]:
                diffs.append(f"{path}: {old_value!r} -> {item['value']!r}")
    return diffs


def apply_form(items: list[dict], form: dict, prefix: str = "") -> None:
    for item in items:
        path = f"{prefix}{item['key']}"
        if item["type"] == "table":
            apply_form(item["children"], form, prefix=f"{path}.")
        elif item["type"] == "bool":
            item["value"] = "true" if path in form else "false"
        elif path in form:
            item["value"] = form[path]
