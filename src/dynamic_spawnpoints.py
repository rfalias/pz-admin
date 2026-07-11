"""Parses/writes the DynamicSpawnPoints mod's plain event-spawns file:
one line per spawn, `id|name|x|y|z|createdBy|enabled` (see the mod's
DynamicSpawnPointsShared.lua loadEventSpawnsFromFile/saveEventSpawnsToFile).
`enabled` is a 1/0 flag added after createdBy; older lines written before
that field existed have no trailing enabled value and are treated as
enabled, matching the mod's own fallback."""
import re
from pathlib import Path

LINE_RE = re.compile(r"^(-?\d+)\|([^|]*)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|([^|]*)\|(-?\d+)$")
LEGACY_LINE_RE = re.compile(r"^(-?\d+)\|([^|]*)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(.*)$")


def parse_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        m = LINE_RE.match(line)
        if m:
            id_, name, x, y, z, created_by, enabled = m.groups()
            enabled = enabled == "1"
        else:
            m = LEGACY_LINE_RE.match(line)
            if not m:
                continue
            id_, name, x, y, z, created_by = m.groups()
            enabled = True
        entries.append(
            {
                "id": int(id_),
                "name": name,
                "x": int(x),
                "y": int(y),
                "z": int(z),
                "created_by": created_by,
                "enabled": enabled,
            }
        )
    return entries


def write_file(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for e in entries:
        # Mirrors the mod's own sanitization on save - `|`/newlines can't
        # survive in a pipe-delimited line.
        safe_name = re.sub(r"[|\r\n]", " ", str(e.get("name") or ""))
        created_by = re.sub(r"[|\r\n]", " ", str(e.get("created_by") or ""))
        enabled = 1 if e.get("enabled", True) else 0
        lines.append(
            f"{int(e['id'])}|{safe_name}|{int(e['x'])}|{int(e['y'])}|{int(e['z'])}|{created_by}|{enabled}"
        )
    text = "\n".join(lines)
    path.write_text(text + "\n" if lines else "")


def next_id(entries: list[dict]) -> int:
    return max((e["id"] for e in entries), default=0) + 1
