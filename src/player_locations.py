import json
from pathlib import Path

# The mod's writer switched from one-JSON-object-per-line to this compact
# CSV form (~60% smaller, verified with a round-trip encode/decode test):
#   x,y,z,lastUpdated,action_code[,extra...]
# k (killed_zombie) carries one extra field (totalKills); p (picked_up)
# carries two (item, itemId). kill_tally.txt is unaffected -- it's a single
# overwritten line, not an accumulating log, so the byte-savings concern
# doesn't apply there.
_ACTION_CODES = {"t": "tick", "d": "died", "k": "killed_zombie", "p": "picked_up"}
_CODES_BY_ACTION = {v: k for k, v in _ACTION_CODES.items()}


def _history_path(username: str, base_dir: Path) -> Path:
    return base_dir / username / "location_history.txt"


def _parse_json_line(line: str) -> dict | None:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _parse_csv_line(line: str) -> dict | None:
    parts = line.split(",")
    if len(parts) < 5:
        return None
    action = _ACTION_CODES.get(parts[4])
    if action is None:
        return None
    try:
        entry = {
            "x": float(parts[0]),
            "y": float(parts[1]),
            "z": float(parts[2]),
            "lastUpdated": int(float(parts[3])),
            "action": action,
        }
    except ValueError:
        return None
    if action == "killed_zombie" and len(parts) > 5:
        try:
            entry["totalKills"] = int(parts[5])
        except ValueError:
            pass
    elif action == "picked_up" and len(parts) > 6:
        entry["item"] = parts[5]
        entry["itemId"] = parts[6]
    return entry


def _parse_lines(lines: list[str]) -> list[dict]:
    """Handles both the old JSON-per-line format and the new compact CSV
    one -- this is an accumulating log, not a snapshot, so lines written
    before the mod upgrade stay JSON forever unless a partial clear
    happens to rewrite (and thereby upgrade) them. Malformed lines of
    either kind are skipped rather than failing the whole read."""
    entries = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        entry = _parse_json_line(line) if line.startswith("{") else _parse_csv_line(line)
        if entry is None:
            continue
        if "x" not in entry or "y" not in entry or "lastUpdated" not in entry:
            continue
        entries.append(entry)
    return entries


def _format_csv_line(e: dict) -> str:
    """Serializes back into the compact writer format -- used when
    clear_location_history rewrites a kept subset, which also upgrades any
    old JSON-format lines it happens to keep."""
    code = _CODES_BY_ACTION.get(e.get("action", "tick"), "t")
    parts = [
        f"{e['x']:.2f}",
        f"{e['y']:.2f}",
        f"{e.get('z', 0.0):.2f}",
        str(int(e["lastUpdated"])),
        code,
    ]
    if code == "k" and e.get("totalKills") is not None:
        parts.append(str(e["totalKills"]))
    elif code == "p" and e.get("item") is not None:
        parts.append(str(e["item"]))
        parts.append(str(e.get("itemId", "")))
    return ",".join(parts)


def read_location_history(username: str, base_dir: Path) -> list[dict]:
    """Return this player's breadcrumb history, oldest first. Malformed lines
    are skipped rather than failing the whole read."""
    path = _history_path(username, base_dir)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    entries = _parse_lines(lines)
    entries.sort(key=lambda e: e["lastUpdated"])
    return entries


def read_kill_tally(username: str, base_dir: Path) -> dict | None:
    """Reads this player's kill_tally.txt -- a single JSON object,
    overwritten (not appended) each time the mod updates it."""
    path = base_dir / username / "kill_tally.txt"
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for raw_line in reversed(lines):
        line = raw_line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def all_kill_tallies(base_dir: Path) -> dict[str, dict]:
    """Returns {username_lower: {username, kills, lastUpdated}} for every
    player directory under base_dir that has a kill_tally.txt -- used for
    the players table and the zombie-kill leaderboard."""
    if not base_dir.exists():
        return {}
    result = {}
    for entry in base_dir.iterdir():
        if not entry.is_dir():
            continue
        tally = read_kill_tally(entry.name, base_dir)
        if tally and "kills" in tally:
            result[entry.name.lower()] = tally
    return result


def latest_location(username: str, base_dir: Path) -> dict | None:
    """Cheap read of just the last breadcrumb entry, for list-page use."""
    path = _history_path(username, base_dir)
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for raw_line in reversed(lines):
        entries = _parse_lines([raw_line])
        if entries:
            return entries[0]
    return None


def filter_by_timeframe(
    entries: list[dict], start_epoch: float | None, end_epoch: float | None
) -> list[dict]:
    if start_epoch is None and end_epoch is None:
        return entries
    result = []
    for e in entries:
        ts = e.get("lastUpdated")
        if ts is None:
            continue
        if start_epoch is not None and ts < start_epoch:
            continue
        if end_epoch is not None and ts > end_epoch:
            continue
        result.append(e)
    return result


def clear_location_history(
    username: str,
    base_dir: Path,
    start_epoch: float | None = None,
    end_epoch: float | None = None,
) -> int:
    """Delete this player's breadcrumb history. With no bounds, deletes the
    whole file. With bounds, rewrites the file keeping only entries outside
    the [start_epoch, end_epoch] range. Returns the number of entries removed."""
    path = _history_path(username, base_dir)
    if not path.exists():
        return 0

    if start_epoch is None and end_epoch is None:
        entries = read_location_history(username, base_dir)
        path.unlink()
        return len(entries)

    entries = read_location_history(username, base_dir)
    to_remove = filter_by_timeframe(entries, start_epoch, end_epoch)
    if not to_remove:
        return 0
    remove_keys = {(e["x"], e["y"], e["lastUpdated"]) for e in to_remove}
    kept = [e for e in entries if (e["x"], e["y"], e["lastUpdated"]) not in remove_keys]

    if not kept:
        path.unlink()
    else:
        path.write_text(
            "\n".join(_format_csv_line(e) for e in kept) + "\n",
            encoding="utf-8",
        )
    return len(to_remove)
