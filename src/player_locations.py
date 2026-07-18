import json
from pathlib import Path


def _history_path(username: str, base_dir: Path) -> Path:
    return base_dir / username / "location_history.txt"


def _parse_lines(lines: list[str]) -> list[dict]:
    entries = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "x" not in entry or "y" not in entry or "lastUpdated" not in entry:
            continue
        entries.append(entry)
    return entries


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
            "\n".join(json.dumps(e, separators=(",", ":")) for e in kept) + "\n",
            encoding="utf-8",
        )
    return len(to_remove)
