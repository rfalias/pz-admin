"""Parses/writes the EventManager mod's trigger-zone and spawn-point files
(see the mod's EventManagerShared.lua loadTriggerZonesFromFile/
saveTriggerZonesToFile/loadSpawnPointsFromFile/saveSpawnPointsToFile):

Trigger zones: `id|name|x|y|z|radius|cooldownSec|outfitName|femaleChance|sprinterChance|createdBy`
  A zone is an area that can trigger a zombie spawn; outfit/femaleChance/
  sprinterChance are shared across every spawn point attached to it.

Spawn points: `id|zoneId|x|y|z|zombieCount|jitterRadius|createdBy`
  A spawn point has no independent existence outside its parent zone -
  removing a zone cascade-deletes its spawn points (mirrored by
  remove_zone_cascade below, matching EventManagerServer.AdminRemoveTriggerZone).

Validation limits mirror EventManagerServer.lua's own handlers exactly, so
a save here can't produce a zone/point the mod itself would have rejected.
"""
import re
from pathlib import Path

ZONE_RE = re.compile(
    r"^(-?\d+)\|([^|]*)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|([^|]*)\|(-?\d+)\|(-?\d+)\|(.*)$"
)
POINT_RE = re.compile(r"^(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(.*)$")

MIN_ZONE_RADIUS = 1
MAX_ZONE_RADIUS = 50
MIN_ZONE_COOLDOWN_SEC = 5
MAX_SPAWN_POINTS_PER_ZONE = 6
MAX_ZOMBIES_PER_SPAWN_POINT = 50

_SANITIZE_RE = re.compile(r"[|\r\n]")


def _sanitize(value) -> str:
    return _SANITIZE_RE.sub(" ", str(value or ""))


def read_zones(path: Path) -> list[dict]:
    if not path.exists():
        return []
    zones = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        m = ZONE_RE.match(line)
        if not m:
            continue
        id_, name, x, y, z, radius, cooldown_sec, outfit_name, female_chance, sprinter_chance, created_by = m.groups()
        zones.append(
            {
                "id": int(id_),
                "name": name,
                "x": int(x),
                "y": int(y),
                "z": int(z),
                "radius": int(radius),
                "cooldown_sec": int(cooldown_sec),
                "outfit_name": outfit_name,
                "female_chance": int(female_chance),
                "sprinter_chance": int(sprinter_chance),
                "created_by": created_by,
            }
        )
    return zones


def write_zones(path: Path, zones: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for z in zones:
        lines.append(
            "|".join(
                [
                    str(int(z["id"])),
                    _sanitize(z["name"]),
                    str(int(z["x"])),
                    str(int(z["y"])),
                    str(int(z["z"])),
                    str(int(z["radius"])),
                    str(int(z["cooldown_sec"])),
                    _sanitize(z.get("outfit_name") or ""),
                    str(int(z.get("female_chance") or 0)),
                    str(int(z.get("sprinter_chance") or 0)),
                    _sanitize(z.get("created_by") or ""),
                ]
            )
        )
    text = "\n".join(lines)
    path.write_text(text + "\n" if lines else "")


def read_spawn_points(path: Path) -> list[dict]:
    if not path.exists():
        return []
    points = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        m = POINT_RE.match(line)
        if not m:
            continue
        id_, zone_id, x, y, z, zombie_count, jitter_radius, created_by = m.groups()
        points.append(
            {
                "id": int(id_),
                "zone_id": int(zone_id),
                "x": int(x),
                "y": int(y),
                "z": int(z),
                "zombie_count": int(zombie_count),
                "jitter_radius": int(jitter_radius),
                "created_by": created_by,
            }
        )
    return points


def write_spawn_points(path: Path, points: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for p in points:
        lines.append(
            "|".join(
                [
                    str(int(p["id"])),
                    str(int(p["zone_id"])),
                    str(int(p["x"])),
                    str(int(p["y"])),
                    str(int(p["z"])),
                    str(int(p["zombie_count"])),
                    str(int(p["jitter_radius"])),
                    _sanitize(p.get("created_by") or ""),
                ]
            )
        )
    text = "\n".join(lines)
    path.write_text(text + "\n" if lines else "")


def zones_with_points(zones: list[dict], points: list[dict]) -> list[dict]:
    """Zones enriched with their own nested `spawn_points` list, for display/editing."""
    by_zone: dict[int, list[dict]] = {}
    for p in points:
        by_zone.setdefault(p["zone_id"], []).append(p)
    return [{**z, "spawn_points": by_zone.get(z["id"], [])} for z in zones]


def next_id(entries: list[dict]) -> int:
    return max((e["id"] for e in entries), default=0) + 1
